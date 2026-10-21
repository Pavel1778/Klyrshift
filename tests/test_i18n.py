"""Interface localisation: the catalogue, the fallback and the CLI switch.

The UI used to hard-code Russian strings. Stage 4 moved them into a catalogue so
the language can be switched without editing code. These tests pin the contract
that makes that safe:

* every user-facing Russian literal in the source has a catalogue entry, so a
  string added later cannot silently stay untranslated;
* a missing entry falls back to the Russian source rather than a key or a
  placeholder;
* the plural rules pick the right form for Russian and English;
* ``--lang`` on the command line really changes what the CLI prints, including
  ``--help``, which is built before the flag is parsed.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import pytest

from klyrshift import i18n
from klyrshift.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src" / "klyrshift"
CATALOGUE = SOURCE_ROOT / "data" / "locales" / "en.json"

CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")

# Cyrillic literals that are data, not user-facing text: the vowel set the
# detector uses to guess a script. Everything else must be translatable.
NON_TEXT_LITERALS = frozenset({"aeiouyаеёиоуыэюяіїє"})


def _catalogue() -> dict[str, object]:
    data: dict[str, object] = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def _source_literals() -> frozenset[str]:
    """Return every Cyrillic string literal in the source, minus docstrings.

    Both wrapping styles are covered because the check looks at the literals
    themselves: an inline ``_("...")``, a module constant printed as
    ``_(MSG_FOO)``, and a value translated where it is rendered (a tour step's
    ``title``, a ``LazyLabels`` entry). A string is either wrapped somewhere or
    it is a gap -- the check does not care which call site does the work.

    Cached: the scan parses every source file, and the orphan check calls it
    once per catalogue key, which without the cache is quadratic (~5 minutes).
    """
    literals: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings or node.value in NON_TEXT_LITERALS:
                continue
            if CYRILLIC.search(node.value):
                literals.add(node.value)
    return frozenset(literals)


@pytest.fixture(autouse=True)
def _reset_locale() -> Iterator[None]:
    """Every test starts and ends with environment-based detection."""
    i18n.set_locale("")
    yield
    i18n.set_locale("")


def test_every_source_string_has_a_translation() -> None:
    """A new Russian literal without an English entry fails the build."""
    catalogue = _catalogue()
    missing = sorted(literal for literal in _source_literals() if literal not in catalogue)
    assert missing == []


def test_catalogue_has_no_orphan_entries() -> None:
    """Every catalogue key must still exist in the source."""
    unused = sorted(key for key in _catalogue() if key not in _source_literals())
    assert unused == []


def test_catalogue_is_valid_json_with_string_or_list_values() -> None:
    for key, value in _catalogue().items():
        assert isinstance(key, str) and key
        assert isinstance(value, (str, list))
        if isinstance(value, list):
            assert value and all(isinstance(form, str) for form in value)


def test_missing_translation_falls_back_to_the_source() -> None:
    i18n.set_locale("en")
    assert i18n.tr("Строка, которой нет в каталоге.") == "Строка, которой нет в каталоге."


def test_russian_needs_no_catalogue() -> None:
    i18n.set_locale("ru")
    assert i18n.tr("Klyrshift не запущен.") == "Klyrshift не запущен."


def test_translation_is_applied_for_english() -> None:
    i18n.set_locale("en")
    assert i18n.tr("Klyrshift не запущен.") == "Klyrshift is not running."


def test_formatting_uses_the_translation() -> None:
    i18n.set_locale("en")
    assert i18n.tr("Раскладки: {0}", "us, ru") == "Layouts: us, ru"


def test_bad_format_falls_back_instead_of_raising() -> None:
    """A catalogue typo must never crash the UI."""
    i18n.set_locale("en")
    assert i18n.tr("Раскладки: {0}", "us") == "Layouts: us"
    # A missing positional argument makes ``str.format`` raise; the source text
    # is returned instead so a bad catalogue cannot break a page.
    assert i18n.tr("{0} (раскладки: {1})", 1) == "{0} (раскладки: {1})"


def test_plural_forms_russian_and_english() -> None:
    assert [i18n.plural_form(n, "ru") for n in (1, 2, 5, 11, 21, 22)] == [0, 1, 2, 2, 0, 1]
    assert [i18n.plural_form(n, "en") for n in (1, 2, 5)] == [0, 1, 1]


def test_plural_entry_selects_the_form() -> None:
    """A list-valued entry picks its form from the count and the locale."""
    entry = "{0} word"
    two_forms = ["{0} word", "{0} words"]
    three_forms = ["{0} слово", "{0} слова", "{0} слов"]
    original = i18n._catalogues.get("en")
    try:
        i18n.set_locale("en")
        i18n._catalogues["en"] = {entry: two_forms}
        assert i18n.tr(entry, 1, count=1) == "1 word"
        assert i18n.tr(entry, 5, count=5) == "5 words"
        # Russian keeps three forms; English only ever selects the first two.
        i18n._catalogues["en"] = {entry: three_forms}
        assert i18n.tr(entry, 2, count=2) == "2 слова"
    finally:
        if original is None:
            i18n._catalogues.pop("en", None)
        else:
            i18n._catalogues["en"] = original


def test_set_locale_rejects_unknown_values() -> None:
    assert i18n.set_locale("en") == "en"
    assert i18n.set_locale("klingon") == i18n._detect_locale()
    assert i18n.set_locale("auto") == i18n._detect_locale()


def test_locale_detection_strips_territory_and_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    i18n.set_locale("")
    assert i18n.get_locale() == "en"


def test_unsupported_environment_locale_falls_back_to_russian(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    i18n.set_locale("")
    assert i18n.get_locale() == i18n.DEFAULT_LOCALE


def test_every_shipped_locale_is_detected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shipped catalogue must be reachable by ``LANG`` alone."""
    for locale in i18n.SUPPORTED_LOCALES:
        monkeypatch.setenv("LANG", f"{locale}_XX.UTF-8")
        monkeypatch.delenv("LANGUAGE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)
        i18n.set_locale("")
        assert i18n.get_locale() == locale


def test_parser_help_is_translated_by_the_flag() -> None:
    """``--help`` is built before ``--lang`` is parsed, so it must still switch."""
    i18n.set_locale("en")
    english = build_parser().format_help()
    i18n.set_locale("ru")
    russian = build_parser().format_help()
    assert "start the daemon" in english
    assert "запустить демон" in russian


def test_cli_prints_english_with_lang_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "en", "hotkeys"]) == 0
    out = capsys.readouterr().out
    assert "Fix the last word" in out
    assert "Исправление последнего слова" not in out


def test_cli_prints_russian_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hotkeys"]) == 0
    out = capsys.readouterr().out
    assert "Исправление последнего слова" in out


def test_lang_equals_form_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang=en", "hotkeys"]) == 0
    assert "Fix the last word" in capsys.readouterr().out


def test_lazy_labels_translate_on_lookup() -> None:
    labels = i18n.LazyLabels({"a": "Светлая"})
    i18n.set_locale("en")
    assert labels["a"] == "Light"
    i18n.set_locale("ru")
    assert labels["a"] == "Светлая"
    assert list(labels) == ["a"] and len(labels) == 1


def test_every_supported_locale_has_a_native_name() -> None:
    """The interface-language selector lists each language in its own script."""
    for locale in i18n.SUPPORTED_LOCALES:
        assert i18n.locale_name(locale) != locale, locale
    assert i18n.locale_name("klingon") == "klingon"


def test_partial_catalogue_falls_back_to_english() -> None:
    """A locale with a partial catalogue shows English, never Cyrillic."""
    i18n.set_locale("de")
    # Translated in de.json.
    assert i18n.tr("Настройки") == "Einstellungen"
    # Absent from de.json, present in en.json (a CLI hotkey label).
    assert i18n.tr("Исправление последнего слова") == "Fix the last word"


def test_fallback_stops_at_english_and_never_loops() -> None:
    """``en`` and ``ru`` have empty fallback chains."""
    assert i18n.LOCALE_FALLBACKS["en"] == ()
    assert i18n.LOCALE_FALLBACKS["ru"] == ()
    for locale in i18n.SUPPORTED_LOCALES:
        assert locale not in i18n.LOCALE_FALLBACKS[locale]


def test_missing_in_both_locale_and_english_keeps_the_source() -> None:
    i18n.set_locale("uk")
    assert i18n.tr("Строка, которой нет нигде.") == "Строка, которой нет нигде."


def test_french_treats_zero_as_singular() -> None:
    """French says "0 mot", so zero selects form 0, unlike German or English."""
    assert [i18n.plural_form(n, "fr") for n in (0, 1, 2)] == [0, 0, 1]
    assert [i18n.plural_form(n, "de") for n in (0, 1, 2)] == [1, 0, 1]
    assert [i18n.plural_form(n, "en") for n in (0, 1, 2)] == [1, 0, 1]


def test_ukrainian_uses_three_plural_forms() -> None:
    assert [i18n.plural_form(n, "uk") for n in (1, 2, 5, 11, 21, 22)] == [0, 1, 2, 2, 0, 1]


def test_supported_locales_is_the_registry_config_and_gui_read() -> None:
    """Adding a catalogue is the only edit needed to offer a language."""
    from klyrshift import config

    assert ("auto", *i18n.SUPPORTED_LOCALES) == config.VALID_UI_LOCALES

    # The GUI module imports GTK at module level, so read it as text: the
    # selector must derive its order from the registry rather than restate it.
    gui = Path(__file__).resolve().parent.parent / "src" / "klyrshift" / "gui" / "settings_page.py"
    text = gui.read_text(encoding="utf-8")
    assert 'UI_LOCALE_ORDER = ("auto", *i18n.SUPPORTED_LOCALES)' in text


def test_language_help_lists_every_shipped_locale() -> None:
    """A stale "ru or en" hint must not survive a language being added."""
    i18n.set_locale("ru")
    help_text = build_parser().format_help()
    for locale in i18n.SUPPORTED_LOCALES:
        assert locale in help_text
    assert "ru или en" not in help_text
