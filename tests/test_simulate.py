"""Headless behavioural tests through the keystroke simulator.

``klyrshift.simulate`` drives the real daemon with in-memory fakes, so these
tests assert what the *user would see* (the rendered screen), not just the raw
``(backspace, text, layout)`` tuples the other daemon tests check. They are the
regression net for the two reports this change fixes:

* manual mode must not correct anything without an explicit command;
* ``Ctrl+Z`` must stop a correction from coming back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from klyrshift.config import Config  # noqa: E402
from klyrshift.simulate import ScenarioError, run_scenario  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


# --- auto mode --------------------------------------------------------------


def test_auto_mode_converts_a_wrong_layout_word() -> None:
    result = run_scenario("type ghbdtn, space")
    assert result.screen == "привет "
    assert result.layout == "ru"
    assert result.replacements == [(7, "привет ", "ru")]


def test_auto_mode_leaves_a_correct_word() -> None:
    result = run_scenario("type hello, space")
    assert result.screen == "hello "
    assert result.replacements == []


def test_enter_boundary_keeps_the_newline_after_the_word() -> None:
    """The Enter that ended the word is consumed and retyped, not eaten.

    The deletion counts characters back from the caret, and the Enter sits
    between the caret and the word; leaving it out would strand it in front of
    the correction *and* drop the first character of the word
    (``ghbdtn`` + Enter -> ``gпривет``).
    """
    result = run_scenario("type ghbdtn, enter")
    assert result.screen == "привет\n"
    assert result.replacements == [(7, "привет\n", "ru")]


def test_tab_boundary_keeps_the_tab() -> None:
    result = run_scenario("config on_tab=true, type ghbdtn, tab")
    assert result.screen == "привет\t"
    assert result.replacements == [(7, "привет\t", "ru")]


def test_punctuation_boundary_keeps_the_punctuation() -> None:
    result = run_scenario("config on_punctuation=true, type ghbdtn, dot")
    assert result.screen == "привет."
    assert result.replacements == [(7, "привет.", "ru")]


def test_punctuation_boundary_not_enabled_is_buffered() -> None:
    result = run_scenario("type ghbdtn, dot, space")
    # The dot is part of the buffer, so the whole token converts as one word
    # (``.`` maps to ``ю`` under ``ru``): one fix, not two.
    assert result.replacements == [(8, "приветю ", "ru")]


def test_idle_flush_converts_a_word_without_a_separator() -> None:
    result = run_scenario("type ghbdtn, wait")
    assert result.screen == "привет"
    assert result.replacements == [(6, "привет", "ru")]


def test_backspace_edits_the_buffer() -> None:
    result = run_scenario("type ghbdtnx, backspace, space")
    assert result.screen == "привет "
    assert result.replacements == [(7, "привет ", "ru")]


# --- manual mode: nothing happens without a command -------------------------


def test_manual_mode_never_auto_corrects_a_layout_word() -> None:
    result = run_scenario("mode manual, type ghbdtn, space")
    assert result.screen == "ghbdtn "
    assert result.replacements == []


def test_manual_mode_never_auto_corrects_a_typo() -> None:
    """The reported bug: T9 on + manual mode used to rewrite every word."""
    result = run_scenario("mode manual, config typo_mode=auto, type langauge, space")
    assert result.screen == "langauge "
    assert result.replacements == []


def test_manual_mode_never_auto_corrects_punctuation() -> None:
    # ``ntrcn`` is the physical keys for ``текст`` in the Russian layout; the
    # two ``-`` keys follow, so the on-screen word is ``текст--``.
    result = run_scenario(
        "mode manual, config punctuation_mode=auto, layout ru, type ntrcn, type --, space"
    )
    assert result.replacements == []
    assert result.screen == "текст-- "


def test_manual_mode_fixes_on_the_explicit_hotkey() -> None:
    """Double Shift is the user asking, so manual mode still obeys it."""
    result = run_scenario("mode manual, type ghbdtn, dblshift")
    assert result.screen == "привет"
    assert result.replacements == [(6, "привет", "ru")]


def test_double_shift_after_space_keeps_the_space() -> None:
    """A reach-back fix after a boundary must not eat a character.

    The Space that flushed the word is still on screen, so the deletion has to
    cover it and the replacement retype it -- otherwise the fix deletes one
    character too many (``gпривет``).
    """
    result = run_scenario("mode manual, type ghbdtn, space, dblshift")
    assert result.screen == "привет "
    assert result.replacements == [(7, "привет ", "ru")]


def test_double_shift_after_enter_keeps_the_newline() -> None:
    result = run_scenario("mode manual, type ghbdtn, enter, dblshift")
    assert result.screen == "привет\n"


def test_toggle_layout_after_space_keeps_the_space() -> None:
    result = run_scenario(
        "config hotkey_toggle_layout_last_word=CTRL+SHIFT+T, type ghbdtn, space, ctrl+shift+t"
    )
    assert result.screen == "ghbdtn "
    assert result.replacements == [(7, "привет ", "ru"), (7, "ghbdtn ", "us")]


def test_typo_hotkey_after_space_keeps_the_space() -> None:
    result = run_scenario("config typo_mode=manual, type langauge, space, ctrl+shift+f")
    assert result.screen == "language "


def test_manual_mode_typo_hotkey_still_works() -> None:
    result = run_scenario("mode manual, config typo_mode=auto, type langauge, ctrl+shift+f")
    assert result.screen == "language"


# --- learning: Ctrl+Z rejects and never re-fires ----------------------------


def test_ctrl_z_stops_the_word_from_being_corrected_again() -> None:
    result = run_scenario("type ghbdtn, space, ctrl z, type ghbdtn, space")
    # The first fix is undone by the application, and the re-typed word is left
    # alone: only one replacement ever happened.
    assert result.replacements == [(7, "привет ", "ru")]
    assert result.screen == "ghbdtn привет "
    assert "ghbdtn" in result.suppressed


def test_ctrl_z_rejects_the_newest_fix_not_the_first() -> None:
    """The stale-undo bug: a later fix was never suppressed."""
    result = run_scenario("type ghbdtn, space, ctrl z, layout ru, type hello, space, ctrl z")
    assert set(result.suppressed) == {"ghbdtn", "руддщ"}


def test_rejected_word_survives_a_layout_change() -> None:
    result = run_scenario("type ghbdtn, space, ctrl z, layout ru, type ghbdtn, space")
    # Even with the other layout active, the rejected word is not touched.
    assert len(result.replacements) == 1


def test_ctrl_z_suppresses_a_punctuation_fix_too() -> None:
    """A rejected punctuation fix must not be re-applied either.

    The punctuation pass rewrites a token such as ``текст--``; that token is not
    a plain word, so the rejection used to be dropped and the fix came back.
    """
    scenario = (
        "config punctuation_mode=auto, layout ru, type ntrcn, type --, space, "
        "ctrl z, type ntrcn, type --, space"
    )
    result = run_scenario(scenario)
    assert len(result.replacements) == 1
    assert result.screen == "текст-- текст-- "
    assert "текст--" in result.suppressed


def test_explicit_hotkey_still_fixes_a_rejected_word() -> None:
    """A rejected word is left alone automatically, but the hotkey still wins."""
    auto_only = run_scenario("type ghbdtn, space, ctrl z, layout us, type ghbdtn, space")
    with_hotkey = run_scenario("type ghbdtn, space, ctrl z, layout us, type ghbdtn, dblshift")
    # The rejected word is not fixed again automatically, but the deliberate
    # double Shift does convert it -- one more replacement than the auto-only run.
    assert len(with_hotkey.replacements) == len(auto_only.replacements) + 1
    assert with_hotkey.screen == "ghbdtn привет"


def test_learning_counters_track_the_session() -> None:
    result = run_scenario("type ghbdtn, space, ctrl z")
    assert result.stats["corrected"] == 1
    assert result.stats["rejected"] == 1


# --- result serialisation ---------------------------------------------------


def test_result_is_json_serialisable() -> None:
    result = run_scenario("type ghbdtn, space")
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "привет" in payload


def test_events_read_like_the_scenario() -> None:
    result = run_scenario("type gh, space")
    kinds = [event.kind for event in result.events]
    assert kinds.count("type") == 2
    assert "boundary" in kinds


# --- scenario errors --------------------------------------------------------


def test_unknown_key_raises() -> None:
    with pytest.raises(ScenarioError):
        run_scenario("key definitely-not-a-key")


def test_unknown_config_field_raises() -> None:
    with pytest.raises(ScenarioError):
        run_scenario("config not_a_field=1")


def test_untypable_character_raises() -> None:
    with pytest.raises(ScenarioError):
        run_scenario("type ghbdtn😀")


def test_config_override_changes_behaviour() -> None:
    base = Config(stop_words=[])
    result = run_scenario("type ghbdtn, space", config=base)
    assert result.screen == "привет "
    # Now pin the mode to manual through the config object itself.
    manual = Config(stop_words=[], mode="manual")
    result = run_scenario("type ghbdtn, space", config=manual)
    assert result.screen == "ghbdtn "


def test_off_is_a_mode_value_not_a_boolean() -> None:
    """``typo_mode=off`` must stay the string ``"off"``, not become ``False``.

    ``off``/``on`` are tempting boolean words, but they are also mode values, so
    coercing them to a bool made ``config typo_mode=off`` fail validation.
    """
    from klyrshift.simulate import _coerce

    assert _coerce("off") == "off"
    assert _coerce("auto") == "auto"
    assert _coerce("true") is True
    assert _coerce("false") is False
    assert _coerce("5") == 5
    assert _coerce("[a, b]") == ["a", "b"]


def test_mode_matrix_manual_is_silent_auto_is_not() -> None:
    """One place that pins the whole mode x per-feature-mode contract."""
    words = {
        "layout": "type ghbdtn, space",
        "typo": "config typo_mode=auto, type langauge, space",
        "punct": "config punctuation_mode=auto, layout ru, type ntrcn, type --, space",
    }
    for mode in ("auto", "hybrid"):
        for scenario in words.values():
            assert run_scenario(f"mode {mode}, {scenario}").replacements, (mode, scenario)
    for scenario in words.values():
        assert run_scenario(f"mode manual, {scenario}").replacements == []
