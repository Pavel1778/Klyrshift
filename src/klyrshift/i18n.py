"""Interface localisation (i18n).

The user interface used to hard-code Russian strings. They now live in a
catalogue so the language can be switched without editing code, which is what
the roadmap's Stage 4 asks for.

Design choices:

* **Source language is Russian.** Every string in the code stays readable and
  Russian is the fallback: a missing translation shows the original text rather
  than a placeholder or a key. A translator therefore only has to add the
  languages they care about.
* **Catalogue format is JSON**, not ``.po``/``.mo``. The project ships no
  gettext toolchain in CI and the strings are plain sentences, so a flat
  ``{source: translation}`` map is enough and keeps the build reproducible. It is
  read from the package data (``data/locales/<lang>.json``) and, for a source
  checkout, from ``locales/`` at the repository root.
* **Plural handling is explicit.** Russian has three plural forms; a catalogue
  entry may be a list of forms selected by :func:`plural_form`. A plain string
  is used for every count.

The module has no GTK dependency, so the CLI, the daemon and ``doctor`` can use
it too.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# Languages with a shipped catalogue. Russian is the source language and needs
# no file; it is listed so ``--lang ru`` is accepted explicitly.
SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("ru", "en")
DEFAULT_LOCALE: Final[str] = "ru"

# Set by :func:`set_locale`; ``None`` means "detect from the environment".
_active_locale: str | None = None
# ``{locale: {source: translation}}``, filled lazily and cached.
_catalogues: dict[str, dict[str, Any]] = {}


def _locale_data_dirs() -> list[Any]:
    """Return the places a catalogue may live, package data first.

    The package-data path is a ``Traversable`` (it may be inside a zip), while
    the source-checkout path is a plain directory resolved from ``__file__``.
    """
    candidates: list[Any] = [resources.files("klyrshift") / "data" / "locales"]
    repo_locales = Path(__file__).resolve().parent.parent.parent / "locales"
    candidates.append(repo_locales)
    return candidates


def _load_catalogue(locale: str) -> dict[str, Any]:
    """Read ``<locale>.json`` returning an empty mapping when absent."""
    if locale in _catalogues:
        return _catalogues[locale]
    catalogue: dict[str, Any] = {}
    for directory in _locale_data_dirs():
        try:
            text = (directory / f"{locale}.json").read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, NotADirectoryError):
            continue
        except (TypeError, AttributeError):  # pragma: no cover - odd resource paths
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("Catalogue %s is not valid JSON", locale, exc_info=True)
            continue
        if isinstance(data, dict):
            catalogue = {str(k): v for k, v in data.items()}
            break
    _catalogues[locale] = catalogue
    return catalogue


def _detect_locale() -> str:
    """Return the locale to use, from the environment.

    Honours ``LANGUAGE``, ``LC_ALL``, ``LC_MESSAGES`` and ``LANG`` in that
    order, strips any encoding/territory suffix (``ru_RU.UTF-8`` -> ``ru``), and
    falls back to :data:`DEFAULT_LOCALE` for anything unsupported.
    """
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "").strip()
        if not value:
            continue
        # ``LANGUAGE`` may hold a colon-separated priority list.
        for part in value.split(":"):
            language = part.split(".")[0].split("@")[0].split("_")[0].lower()
            if language in SUPPORTED_LOCALES:
                return language
    return DEFAULT_LOCALE


def get_locale() -> str:
    """Return the active locale (an explicit choice, else the environment)."""
    if _active_locale is not None:
        return _active_locale
    return _detect_locale()


def set_locale(locale: str | None) -> str:
    """Set the active locale and return it.

    An empty or unsupported value resets to environment detection. Passing
    ``"auto"`` (the config default) also resets.
    """
    global _active_locale
    cleaned = (locale or "").strip().lower()
    if not cleaned or cleaned == "auto" or cleaned not in SUPPORTED_LOCALES:
        _active_locale = None
    else:
        _active_locale = cleaned
    return get_locale()


def plural_form(count: int, locale: str | None = None) -> int:
    """Return the plural form index for ``count`` in ``locale``.

    Russian (and Ukrainian) use three forms: 1, 2-4, then 5+. English uses two:
    1 and everything else.
    """
    language = (locale or get_locale()).lower()
    if language == "ru" or language == "uk":
        if count % 10 == 1 and count % 100 != 11:
            return 0
        if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
            return 1
        return 2
    return 0 if count == 1 else 1


def tr(source: str, *args: object, count: int | None = None, **kwargs: object) -> str:
    """Translate ``source`` into the active locale.

    Args:
        source: The Russian source string, used verbatim when no translation
            exists. It may contain ``str.format`` placeholders.
        *args: Positional values for ``str.format``.
        count: When given, selects a plural form from a list-valued entry.
        **kwargs: Keyword values for ``str.format``.

    Returns:
        The translated (and formatted) string. A missing translation, an
        unsupported locale or a formatting error all fall back to the source,
        so a broken catalogue can never crash the UI.
    """
    locale = get_locale()
    catalogue = _load_catalogue(locale) if locale != DEFAULT_LOCALE else {}
    entry = catalogue.get(source)

    if isinstance(entry, list):
        index = plural_form(count if count is not None else 0, locale)
        text = entry[index] if index < len(entry) else source
    elif isinstance(entry, str):
        text = entry
    else:
        text = source

    if not args and not kwargs:
        return text
    try:
        return text.format(*args, **kwargs)
    except (KeyError, IndexError, ValueError):
        logger.warning("Bad format for %r in locale %s", source, locale, exc_info=True)
        return source


# Alias kept short for the many call sites in the GUI modules.
_ = tr


class LazyLabels(Mapping[str, str]):
    """A read-only mapping whose values are translated on lookup.

    Module-level label dicts (``THEME_LABELS``, ``MODE_LABELS``) are built at
    import time, before the user's locale is known. Translating their values
    eagerly would freeze whichever locale happened to be active first, so the
    mapping stores the Russian source and translates in ``__getitem__`` instead.
    ``[]``, ``.get()``, ``in`` and iteration all keep working.
    """

    __slots__ = ("_source",)

    def __init__(self, source: Mapping[str, str]) -> None:
        self._source = dict(source)

    def __getitem__(self, key: str) -> str:
        return tr(self._source[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._source)

    def __len__(self) -> int:
        return len(self._source)

    def __repr__(self) -> str:
        return f"LazyLabels({self._source!r})"
