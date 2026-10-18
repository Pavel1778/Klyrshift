"""Ctrl+Z (and the undo hotkey) must not lead to a word being re-corrected.

The daemon never grabs the keyboard, so it cannot swallow ``Ctrl+Z``: the
application performs its own undo, which reverts the daemon's rewrite and
restores the text the user had typed. The daemon observes the chord and records
the word as rejected, so the next flush does not fix it again -- otherwise the
word "keeps changing back" no matter how often the user undoes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from klyrshift.config import Config  # noqa: E402
from klyrshift.daemon import KlyrshiftDaemon  # noqa: E402
from klyrshift.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeSwitcher:
    current: str = "us"
    backend: str = "fake"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    backend: str = "fake"

    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True


@pytest.fixture(autouse=True)
def _hermetic_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def set_layout(daemon: KlyrshiftDaemon, layout: str) -> None:
    """Point the fake switcher at ``layout`` (the user switching back)."""
    switcher = daemon.switcher
    assert isinstance(switcher, FakeSwitcher)
    switcher.current = layout


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def make_daemon(**kwargs: object) -> KlyrshiftDaemon:
    options: dict[str, object] = {"analysis_timeout": 0.8, "stop_words": []}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=None, stop_words=config.stop_words, min_word_length=config.min_word_length
    )
    return KlyrshiftDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


def type_word(daemon: KlyrshiftDaemon, text: str) -> None:
    for char in text:
        name = "KEY_" + char.upper()
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))


def press_ctrl_z(daemon: KlyrshiftDaemon, *, shift: bool = False) -> None:
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    if shift:
        daemon._handle_event(make_event("KEY_LEFTSHIFT", 1))
    daemon._handle_event(make_event("KEY_Z", 1))
    daemon._handle_event(make_event("KEY_Z", 0))
    if shift:
        daemon._handle_event(make_event("KEY_LEFTSHIFT", 0))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))


def _injector(daemon: KlyrshiftDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


def test_ctrl_z_suppresses_the_recently_fixed_word() -> None:
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]

    press_ctrl_z(daemon)
    assert daemon.learning.is_suppressed("ghbdtn") is True
    assert daemon.learning.stats.rejected == 1


def test_the_word_is_not_fixed_again_after_ctrl_z() -> None:
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    press_ctrl_z(daemon)

    before = len(_injector(daemon).replacements)
    set_layout(daemon, "us")
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert len(_injector(daemon).replacements) == before


def test_explicit_hotkey_still_fixes_a_rejected_word() -> None:
    """The user asked for it, so the manual hotkey overrides the rejection."""
    daemon = make_daemon(hotkey_fix_last_word="CTRL+F12")
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    press_ctrl_z(daemon)

    before = len(_injector(daemon).replacements)
    set_layout(daemon, "us")
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_F12", 1))
    assert len(_injector(daemon).replacements) == before + 1


def test_ctrl_shift_z_is_not_a_rejection() -> None:
    """Ctrl+Shift+Z is the usual redo; it must not suppress the word."""
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    press_ctrl_z(daemon, shift=True)
    assert daemon.learning.stats.rejected == 0


def test_undo_hotkey_suppresses_the_restored_word() -> None:
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert daemon._undo_last_fix() is True
    assert daemon.learning.is_suppressed("ghbdtn") is True

    before = len(_injector(daemon).replacements)
    set_layout(daemon, "us")
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert len(_injector(daemon).replacements) == before


def test_ctrl_z_without_a_recent_fix_suppresses_nothing() -> None:
    """An unrelated Ctrl+Z must not suppress a word the daemon never touched."""
    daemon = make_daemon()
    type_word(daemon, "vercel")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == []
    press_ctrl_z(daemon)
    assert daemon.learning.stats.rejected == 0


def test_ctrl_chord_key_does_not_leak_into_the_buffer() -> None:
    """The ``c`` of ``Ctrl+C`` must not become a stray word to correct."""
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_C", 1))
    daemon._handle_event(make_event("KEY_C", 0))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))
    assert daemon.buffer == ""
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == []
