"""The suggestion hybrid mode offers instead of an automatic fix.

Hybrid mode declines a low-confidence conversion. That decision is only useful
if the user can still apply it: these tests cover the two ways to accept the
offer (the tray entry and the dedicated hotkey), that the offer is dropped once
it is stale, and -- most important -- that neither the offer nor its
acceptance ever puts the typed word into a log line or a subprocess argv.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests.test_modes_hotkeys import (
    _injector,
    make_daemon,
    press,
    tap,
)


def _withhold(monkeypatch: pytest.MonkeyPatch, daemon: Any, target: str = "ru") -> None:
    """Make the detector offer ``target`` with a below-threshold confidence."""
    monkeypatch.setattr(
        daemon.detector, "target_layout_with_confidence", lambda *a, **k: (target, 1.0)
    )


def test_withheld_suggestion_is_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0)
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    assert _injector(daemon).replacements == []
    assert daemon._pending_suggestion == ("ghbdtn", "ru", 1.0)


def test_accepting_the_suggestion_applies_it(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0)
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    assert daemon._accept_suggestion() is True
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    # The offer is consumed: a second press must not retype the word.
    assert daemon._pending_suggestion is None
    assert daemon._accept_suggestion() is False


def test_a_new_word_drops_the_previous_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale offer must never be applied to text the user moved past."""
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0)
    offers = {"ghbdtn": "ru"}

    def detect(buffer: str, *a: object, **k: object) -> tuple[str, float] | tuple[None, None]:
        target = offers.get(buffer)
        return (target, 1.0) if target else (None, None)

    monkeypatch.setattr(daemon.detector, "target_layout_with_confidence", detect)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert daemon._pending_suggestion == ("ghbdtn", "ru", 1.0)

    # A word the detector offers nothing for must clear the old offer, not
    # leave it applyable to the new text.
    press(daemon, "hello")
    tap(daemon, "KEY_SPACE")

    assert daemon._pending_suggestion is None
    assert daemon._accept_suggestion() is False
    assert _injector(daemon).replacements == []


def test_accepting_without_an_offer_is_a_no_op() -> None:
    daemon = make_daemon(mode="hybrid")
    assert daemon._accept_suggestion() is False
    assert _injector(daemon).replacements == []


def test_double_shift_applies_the_withheld_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix hotkey reaches back to the flushed word and applies the offer."""
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0, hotkey_fix_last_word="PAUSE")
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert daemon._pending_suggestion is not None

    tap(daemon, "KEY_PAUSE")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_auto_mode_never_offers_a_suggestion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto applies the conversion; there is nothing left to offer."""
    daemon = make_daemon(mode="auto", hybrid_confidence=3.0)
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    assert _injector(daemon).replacements == [(7, "привет ", "ru")]
    assert daemon._pending_suggestion is None


def test_offer_is_dropped_when_the_layout_already_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applying the offer after a manual layout switch would retype in place."""
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0)
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    daemon.switcher.switch_to("ru")
    assert daemon._accept_suggestion() is False
    assert _injector(daemon).replacements == []
    assert daemon._pending_suggestion is None


def test_dedicated_hotkey_accepts_the_suggestion(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0, hotkey_accept_suggestion="PAUSE")
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    tap(daemon, "KEY_PAUSE")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_suggestion_notification_never_carries_the_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body is a fixed label: argv is world-readable via ``ps``."""
    recorded: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        recorded.append([str(a) for a in args])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0, suggest_on_withhold=True)
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    assert recorded, "the withhold should have notified"
    assert all("ghbdtn" not in " ".join(argv) for argv in recorded)


def test_suggestion_is_not_notified_unless_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0, suggest_on_withhold=False)
    monkeypatch.setattr(daemon, "_notify_suggestion", lambda: calls.append(1))
    _withhold(monkeypatch, daemon)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")

    assert calls == []
    assert daemon._pending_suggestion is not None


def test_withholding_never_logs_the_word(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The DEBUG line used to ``%r`` the buffer, leaking the typing to the log."""
    import logging

    daemon = make_daemon(mode="hybrid", hybrid_confidence=3.0)
    _withhold(monkeypatch, daemon)
    with caplog.at_level(logging.DEBUG):
        press(daemon, "ghbdtn")
        tap(daemon, "KEY_SPACE")

    assert caplog.records, "the withhold should have logged something"
    assert all("ghbdtn" not in record.getMessage() for record in caplog.records)
