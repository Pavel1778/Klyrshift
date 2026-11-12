"""Every declared setting and knob must have an effect.

A configuration key or a dataclass field that nothing reads is a trap: the GUI
shows a switch, the docs describe it, the user toggles it, and nothing changes.
The audit in ``docs/SPECIFICATION_AUDIT.md`` found several of these; these tests
pin that each now reaches real code, so a future refactor cannot quietly orphan
one again.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pytest

from klyrshift import daemon as daemon_module, logging_setup
from klyrshift.config import Config
from klyrshift.daemon import KlyrshiftDaemon
from klyrshift.detector import LanguageDetector
from klyrshift.qa.analyzer import reproduces
from klyrshift.qa.runner import RunConfig


class _Switcher:
    def __init__(self, current: str = "us") -> None:
        self.current = current

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


class _Injector:
    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        return True

    def describe(self) -> str:
        return "backend=fake"


def _daemon(config: Config) -> KlyrshiftDaemon:
    return KlyrshiftDaemon(
        config,
        detector=LanguageDetector(converter=None, stop_words=config.stop_words),
        switcher=_Switcher(),
        injector=_Injector(),
    )


# --- log_rotation_mb reaches the rotating handler ---------------------------


def test_log_rotation_mb_sets_the_handler_size(tmp_path: Path) -> None:
    """The GUI "Ротация, МБ" spin must change the handler's byte cap."""
    logging_setup.setup_logging("INFO", log_dir=tmp_path, rotation_mb=7)
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 7 * 1024 * 1024
    logging.getLogger().handlers.clear()


def test_log_rotation_default_keeps_five_megabytes(tmp_path: Path) -> None:
    logging_setup.setup_logging("INFO", log_dir=tmp_path)
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 5 * 1024 * 1024
    logging.getLogger().handlers.clear()


def test_log_rotation_is_clamped_to_at_least_one_megabyte(tmp_path: Path) -> None:
    """A nonsensical value must not produce a zero-byte cap (which would spin)."""
    logging_setup.setup_logging("INFO", log_dir=tmp_path, rotation_mb=0)
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 1024 * 1024
    logging.getLogger().handlers.clear()


# --- sound_on_fix and notify_on_error reach the daemon ----------------------


def test_sound_on_fix_plays_a_sound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon_module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )
    daemon = _daemon(Config(sound_on_fix=True))
    daemon._announce_fix()
    assert calls, "sound_on_fix did not invoke the sound player"
    assert calls[0][0] == daemon_module.SOUND_PLAYER


def test_sound_on_fix_off_plays_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon_module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )
    daemon = _daemon(Config(sound_on_fix=False, notify_on_fix=False))
    daemon._announce_fix()
    assert calls == []


def test_a_missing_sound_player_is_survived(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no canberra-gtk-play")

    monkeypatch.setattr(daemon_module.subprocess, "run", _boom)
    _daemon(Config(sound_on_fix=True))._announce_fix()  # must not raise


def test_notify_on_error_shows_a_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon_module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )
    _daemon(Config(notify_on_error=True))._notify_error()
    assert calls, "notify_on_error did not invoke notify-send"
    assert calls[0][0] == "notify-send"


def test_notify_on_error_off_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon_module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )
    _daemon(Config(notify_on_error=False))._notify_error()
    assert calls == []


def test_an_event_failure_notifies_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error notification is wired into the real event-failure path."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon_module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )
    daemon = _daemon(Config(notify_on_error=True))

    def _boom(event: object) -> None:
        raise RuntimeError("bad event")

    monkeypatch.setattr(daemon, "_handle_event_inner", _boom)
    daemon._handle_event(object())
    assert any(argv[0] == "notify-send" for argv in calls)


# --- RunConfig.repeats reaches the analyser ---------------------------------


def test_run_config_repeats_is_read() -> None:
    """The documented knob must be a real field, not a docstring-only promise."""
    config = RunConfig(repeats=3)
    assert config.repeats == 3


def test_reproduces_honours_the_run_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """``reproduces`` runs the scenario exactly the requested number of times."""
    from klyrshift.qa import analyzer

    runs: list[int] = []

    class _Execution:
        passed = False
        outcome = "failed"
        violations: ClassVar[list[object]] = []
        result = None

    def _fake_execute(scenario: object) -> _Execution:
        runs.append(1)
        return _Execution()

    monkeypatch.setattr(analyzer, "execute", _fake_execute)

    class _Scenario:
        steps: ClassVar[list[str]] = []

    assert reproduces(_Scenario(), runs=4) is True
    assert len(runs) == 4


# --- every declared setting has a reader ------------------------------------


# Fields a GUI switch or a documentation page may bind by name, but that are
# intentionally inert. Each entry states *why* so the list cannot grow silently:
# a reader that adds a name here without a reason is the very trap this test
# exists to catch.
_INERT_FIELDS = {
    # Kept for forward compatibility: the daemon never grabs the keyboard, so it
    # cannot swallow a chord (see docs/ARCHITECTURE.md and UNDO_CONTRACT.md).
    "hotkey_swallow",
}


def _config_fields() -> list[str]:
    return list(Config.__dataclass_fields__)


def test_every_config_field_is_read_somewhere() -> None:
    """A Config field that nothing reads is an unused specification.

    The signal is an *attribute* read (``config.x``) somewhere outside
    ``config.py``. A GUI binding or a help topic that merely names the field as
    a string does not count: that is exactly how ``notify_on_error``,
    ``sound_on_fix`` and ``log_rotation_mb`` looked "used" while nothing read
    them. A field with no attribute read is dead unless it is listed as
    intentionally inert.
    """
    import re

    package = Path(__file__).resolve().parent.parent / "src" / "klyrshift"
    blobs = [p.read_text(encoding="utf-8") for p in package.rglob("*.py") if p.name != "config.py"]
    dead: list[str] = []
    for field in _config_fields():
        if field in _INERT_FIELDS:
            continue
        pattern = re.compile(r"\." + re.escape(field) + r"\b")
        if not any(pattern.search(text) for text in blobs):
            dead.append(field)
    assert dead == [], "Config fields no code reads (unused specification): " + ", ".join(dead)


def test_inert_fields_are_documented_as_inert() -> None:
    """An intentionally inert field must be explained, not merely excluded."""
    for field in _INERT_FIELDS:
        assert field in _config_fields(), f"{field} is not a Config field"
    architecture = (Path(__file__).resolve().parent.parent / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )
    for field in _INERT_FIELDS:
        assert field in architecture, f"{field} is inert but not documented in ARCHITECTURE.md"
