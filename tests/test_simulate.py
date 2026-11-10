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


def test_live_fix_does_not_leave_a_stale_boundary() -> None:
    """A live-buffer hotkey fix must clear the remembered boundary.

    The toggle/T9/punctuation hotkeys act on the word in the live buffer when
    one exists; that fix retypes no boundary, so the remembered boundary must
    become empty. Otherwise the *next* reach-back fix deletes one character too
    many and eats the separator before the word (``abc привет`` -> ``abcghbdtn ``).
    """
    result = run_scenario(
        "mode manual, config hotkey_toggle_layout_last_word=CTRL+SHIFT+T, "
        "type abc, space, type ghbdtn, ctrl+shift+t, ctrl+shift+t"
    )
    # Step 2 converts the live word in place (no boundary); step 3 flips it back.
    # The space after ``abc`` must survive both.
    assert result.screen == "abc ghbdtn"


def test_boundary_separators_are_never_lost() -> None:
    """A fix consumes and retypes its boundary, so separators are invariant.

    This sweeps a batch of scripted sequences (auto/manual/hybrid, with
    reach-back hotkeys and idle flushes between words) and asserts the final
    screen keeps every Space/Enter that was typed. It is the broad guard for the
    whole reach-back family: a stale or mis-counted boundary shows up as a
    missing separator.
    """
    scenarios = [
        "type abc, space, type ghbdtn, space",
        "mode manual, type abc, space, type ghbdtn, space, dblshift",
        "config hotkey_toggle_layout_last_word=CTRL+SHIFT+T, "
        "type abc, space, type ghbdtn, space, ctrl+shift+t",
        "mode manual, config hotkey_toggle_layout_last_word=CTRL+SHIFT+T, "
        "type abc, space, type ghbdtn, ctrl+shift+t, ctrl+shift+t",
        "type abc, enter, type ghbdtn, enter",
        "mode manual, type abc, enter, type ghbdtn, enter, dblshift",
        "config typo_mode=manual, type langauge, space, ctrl+shift+f",
        "mode manual, type abc, space, type abc, space, type abc, space",
    ]
    for scenario in scenarios:
        result = run_scenario(scenario)
        expected_separators = scenario.count(", space") + scenario.count(", enter")
        got = result.screen.count(" ") + result.screen.count("\n")
        assert got >= expected_separators, (scenario, result.screen)


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


def test_config_chunk_without_an_equals_raises() -> None:
    with pytest.raises(ScenarioError):
        run_scenario("config justaword, type ghbdtn, space")


def test_empty_config_chunk_is_ignored() -> None:
    """A trailing/duplicate ``;`` must not be treated as a bad chunk."""
    result = run_scenario("config mode=auto;, type ghbdtn, space")
    assert result.screen == "привет "


def test_a_scenario_error_from_apply_config_is_not_double_wrapped() -> None:
    """A ``ScenarioError`` raised while applying is re-raised unchanged.

    The simulator wraps arbitrary config failures in ``ScenarioError``; a
    ``ScenarioError`` that already came from the config layer must pass through,
    not be nested inside another one.
    """
    from klyrshift.simulate import _apply_config, _Driver

    driver = _Driver(Config(stop_words=[]), "us")

    def boom(_cfg: Config) -> None:
        raise ScenarioError("already a scenario error")

    driver.daemon.config.validate = lambda: None  # type: ignore[method-assign]
    driver.daemon.apply_config = boom  # type: ignore[method-assign, assignment]
    with pytest.raises(ScenarioError) as excinfo:
        _apply_config(driver.daemon, "mode=auto")
    assert str(excinfo.value) == "already a scenario error"


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


@pytest.mark.parametrize("mode", ["auto", "hybrid"])
@pytest.mark.parametrize(
    "boundary,char,extra",
    [
        ("space", " ", ""),
        ("enter", "\n", ""),
        ("tab", "\t", "config on_tab=true, "),
        ("dot", ".", "config on_punctuation=true, "),
        ("comma", ",", "config on_punctuation=true, "),
    ],
)
def test_boundary_never_eats_a_character(mode: str, boundary: str, char: str, extra: str) -> None:
    """Every boundary leaves the *whole* corrected word plus the boundary.

    This is the anti-corruption invariant: the deletion counts back from the
    caret, so a boundary left out of the count eats the word's last character
    (`ghbdtn` + Enter -> `gпривет`). The screen must be exactly ``привет`` +
    the boundary, for every boundary type and every correcting mode.
    """
    result = run_scenario(f"mode {mode}, {extra}type ghbdtn, {boundary}")
    assert result.replacements, (mode, boundary)
    assert result.screen == "привет" + char, (mode, boundary, result.screen)


# --- the config step refreshes every derived cache --------------------------


def test_config_override_refreshes_the_exception_set() -> None:
    """``config exceptions_apps=...`` must take effect immediately.

    The exception set is cached on the daemon at construction. The simulator's
    ``config`` step used to write the field and leave the cache stale, so the
    override was silently ignored and an excepted app was still corrected.
    """
    result = run_scenario("config exceptions_apps=[myapp], app myapp, type ghbdtn, space")
    assert result.screen == "ghbdtn "
    assert result.replacements == []


def test_config_override_refreshes_the_parsed_hotkeys() -> None:
    """A hotkey overridden through ``config`` must be re-parsed, not ignored."""
    result = run_scenario(
        "config hotkey_toggle_layout_last_word=CTRL+SHIFT+Y, type ghbdtn, ctrl+shift+y"
    )
    assert result.screen == "привет"
    assert result.layout == "ru"


def test_config_override_refreshes_the_detector_tuning() -> None:
    """``min_word_length`` reaches the detector, not only the config object."""
    assert run_scenario("config min_word_length=7, type ghbdtn, space").screen == "ghbdtn "
    assert run_scenario("config min_word_length=3, type ghbdtn, space").screen == "привет "


# --- the working mode must not poison the learned vocabulary ----------------


def test_manual_mode_does_not_learn_a_word_it_never_judged() -> None:
    """A word silenced by manual mode must not be promoted by learning.

    Typing a wrong-layout word three times in manual mode used to promote it
    (the flush counted as a "keep"), so after the user switched to auto the
    word was never corrected again. Manual mode means "only when I ask": the
    word was never evaluated, so it must not become learned vocabulary.
    """
    result = run_scenario(
        "mode manual, type ghbdtn, space, type ghbdtn, space, type ghbdtn, space, "
        "mode auto, type ghbdtn, space"
    )
    assert result.learned == []
    assert result.screen == "ghbdtn ghbdtn ghbdtn привет "


def test_quiet_hours_do_not_learn_a_word_they_silenced() -> None:
    result = run_scenario(
        "config quiet_hours_enabled=true, config quiet_hours_start=00:00, "
        "config quiet_hours_end=23:59, type ghbdtn, space, type ghbdtn, space, "
        "type ghbdtn, space"
    )
    assert result.learned == []


def test_an_excepted_app_does_not_learn_a_word_it_silenced() -> None:
    result = run_scenario(
        "config exceptions_apps=[myapp], app myapp, type ghbdtn, space, "
        "type ghbdtn, space, type ghbdtn, space"
    )
    assert result.learned == []


def test_auto_mode_still_learns_a_word_the_user_keeps() -> None:
    """The fix must not disable learning: an evaluated, kept word still promotes."""
    result = run_scenario("type vercel, space, type vercel, space, type vercel, space")
    assert result.learned == ["vercel"]


# --- the application-undo model is faithful -------------------------------


def test_ctrl_z_after_later_typing_does_not_resurrect_the_pre_fix_state() -> None:
    """A real editor's Ctrl+Z reverts the *last* edit, not the daemon's fix.

    The simulator used to keep only one snapshot (before each replacement), so
    a Ctrl+Z after the user typed something new jumped the screen back to a
    state the user had already moved past -- resurrecting the pre-fix text and
    then, through the ``no-lost-characters`` invariant, reporting a lost
    separator the daemon never lost. Here the last edit is the Space, so the
    application's undo removes it; the daemon's earlier fix (``дом``) stays on
    screen and the user's typing is not jumped past.
    """
    result = run_scenario("type ljv, dblshift, type hello, wait, space, ctrl z")
    assert result.screen == "домhello"
    assert result.undone_separators == 1


def test_user_undo_of_a_separator_is_credited_to_the_screen() -> None:
    """A separator the user's own Ctrl+Z removed is not a daemon defect.

    The QA engine's ``no-lost-characters`` invariant must credit it back, or a
    scenario that ends with Ctrl+Z is reported as a confirmed bug even though
    the daemon lost nothing.
    """
    result = run_scenario("type ghbdtn, space, type ghbdtn, space, ctrl z")
    assert result.undone_separators == 1


# --- an invalid config override is a scenario error -------------------------


@pytest.mark.parametrize(
    "override",
    [
        "mode=bogus",
        "min_word_length=abc",
        "typo_max_distance=5",
        "confidence_threshold=5.0",
        "backend=telepathy",
    ],
)
def test_invalid_config_value_raises_a_scenario_error(override: str) -> None:
    """A bad config value must surface as a ``ScenarioError``, not a traceback.

    The value is written onto the config and validated. A raw ``ValueError``
    escaping the simulator bypasses the CLI's error handling and prints a
    traceback instead of the one-line scenario error the user expects.
    """
    with pytest.raises(ScenarioError):
        run_scenario(f"config {override}, type ghbdtn, space")


def test_invalid_config_value_leaves_the_daemon_usable() -> None:
    """A rejected override must not corrupt the daemon for the rest of the run.

    The scenario stops at the bad step, but the check documents that the error
    is raised before any state is committed.
    """
    with pytest.raises(ScenarioError):
        run_scenario("config mode=bogus, type ghbdtn, space")


def test_a_non_valueerror_from_a_config_override_is_still_a_scenario_error() -> None:
    """The guard is by *class*, not by value.

    A bad override can fail with something other than ``ValueError``: a typo'd
    ``~user`` in a path makes ``Path.expanduser()`` raise ``RuntimeError``. That
    must surface as a ``ScenarioError`` too, or the next novel invalid input
    prints a traceback again.
    """
    with pytest.raises(ScenarioError) as excinfo:
        run_scenario("config dictionary_custom_path=~nosuchuser_xyz/dict.txt, type ghbdtn, space")
    assert "RuntimeError" in str(excinfo.value)


# --- the undo stack is bounded ----------------------------------------------


def test_undo_stack_is_bounded_for_a_long_typing_run() -> None:
    """A long scenario must not grow the undo stack without bound.

    One snapshot is taken per edit (so Ctrl+Z can revert the most recent one),
    and each snapshot copies the whole screen: a 500-keystroke run kept 501
    copies, O(n^2) memory. A real application's undo history is bounded, so the
    simulator caps it too; only the most recent edits need to be restorable.
    """
    from klyrshift.simulate import _Driver, _run_step

    driver = _Driver(Config(stop_words=[]), "us")
    _run_step(driver, "type " + "abcdefghij" * 60)  # 600 characters
    assert len(driver.injector.undo_stack) <= 100


def test_ctrl_z_still_undoes_the_last_edit_after_the_cap() -> None:
    """Capping the history must not break the common Ctrl+Z case."""
    result = run_scenario("type ghbdtn, space, type ghbdtn, space, ctrl z")
    assert result.screen == "привет привет"
    assert result.undone_separators == 1


# --- undo at the history cap (user-visible behaviour) -----------------------


def _drive_long_run(edits: int) -> object:
    """Return a driver after ``edits`` single-character edits."""
    from klyrshift.simulate import _Driver, _run_step

    driver = _Driver(Config(stop_words=[]), "us")
    _run_step(driver, "type " + "abcdefghij" * (edits // 10) + "abc"[: edits % 10])
    return driver


def test_ctrl_z_past_the_cap_still_undoes_the_most_recent_edit() -> None:
    """Past the cap, Ctrl+Z must undo the *newest* edit, not silently no-op.

    The cap drops the *oldest* snapshots, so the most recent edit is always
    restorable. The failure mode to guard against is a cap that drops from the
    wrong end (or clears the stack), which would make Ctrl+Z do nothing or jump
    to a stale point.
    """
    driver = _drive_long_run(150)
    assert len(driver.injector.undo_stack) == 100
    before = "".join(driver.screen)
    from klyrshift.simulate import _run_step

    _run_step(driver, "ctrl z")
    after = "".join(driver.screen)
    assert after == before[:-1], "Ctrl+Z past the cap did not remove the last character"


def test_ctrl_z_never_deletes_below_empty() -> None:
    """Repeated Ctrl+Z on a short screen drains it to empty and stops."""
    from klyrshift.simulate import _Driver, _run_step

    driver = _Driver(Config(stop_words=[]), "us")
    _run_step(driver, "type abc")
    for _ in range(120):
        _run_step(driver, "ctrl z")
    assert "".join(driver.screen) == ""
    assert driver.injector.undo_stack == []


def test_undo_does_not_roll_back_the_session_vocabulary() -> None:
    """A screen undo must not revert learning: the two are independent.

    The undo snapshot restores the *screen*; the learned vocabulary is a
    separate, forward-only signal. Rolling the vocabulary back with the screen
    would make a promoted word "un-learn" on a Ctrl+Z, which is not what the
    user asked for.
    """
    result = run_scenario("type vercel, space, type vercel, space, type vercel, space, ctrl z")
    assert result.learned == ["vercel"]


def test_a_scenario_with_more_undos_than_the_cap_still_passes() -> None:
    """A long scenario that out-undoes the cap must not become a QA failure.

    The cap is an internal bound, not a limit on how many Ctrl+Z a scenario may
    contain; the run must complete and render a sane screen.
    """
    from klyrshift.simulate import _Driver, _run_step

    driver = _Driver(Config(stop_words=[]), "us")
    _run_step(driver, "type ghbdtn")
    for _ in range(150):
        _run_step(driver, "ctrl z")
    assert "".join(driver.screen) == ""
