"""Tests for the ``gnome-shortcut`` backend of :mod:`klyrshift.switcher`.

GNOME is replaced by a fake that answers ``gsettings get`` like the real
command and applies a pressed input-source shortcut the way GNOME Shell does:
holding the modifiers and tapping the key *k* times activates the *k*-th most
recently used source.
"""

from __future__ import annotations

import subprocess

import pytest

from klyrshift import switcher as switcher_module
from klyrshift.switcher import (
    LayoutSwitcher,
    _parse_gvariant_list,
    key_sender_for,
    parse_accelerator,
)


class FakeGnome:
    """Answers ``gsettings`` and reacts to the input-source shortcut."""

    def __init__(
        self,
        sources: list[str],
        mru: list[str] | None = None,
        shortcut: str = "['<Super>space', 'XF86Keyboard']",
        applies: bool = True,
    ) -> None:
        self.sources = sources
        self.mru = list(mru) if mru is not None else []
        self.shortcut = shortcut
        self.applies = applies
        self.presses: list[tuple[list[str], int]] = []
        self.commands: list[list[str]] = []

    @staticmethod
    def _render(ids: list[str]) -> str:
        if not ids:
            return "@a(ss) []\n"
        return "[" + ", ".join(f"('xkb', '{layout}')" for layout in ids) + "]\n"

    def run(self, command: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        key = command[-1]
        if key == "sources":
            out = self._render(self.sources)
        elif key == "mru-sources":
            out = self._render(self.mru)
        elif key == "switch-input-source":
            out = self.shortcut + "\n"
        else:
            return subprocess.CompletedProcess(command, 1, "", "no such key")
        return subprocess.CompletedProcess(command, 0, out, "")

    def press(self, keys: list[str], taps: int) -> bool:
        self.presses.append((keys, taps))
        if self.applies:
            order = self.mru + [s for s in self.sources if s not in self.mru]
            chosen = order[taps % len(order)]
            self.mru = [chosen] + [s for s in order if s != chosen]
        return True


@pytest.fixture
def gnome(monkeypatch: pytest.MonkeyPatch) -> FakeGnome:
    fake = FakeGnome(["us", "ru"])
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", fake.run)
    monkeypatch.setattr(switcher_module, "GNOME_POLL_INTERVAL", 0.0)
    return fake


def _switcher(fake: FakeGnome, method: str = "gnome-shortcut") -> LayoutSwitcher:
    return LayoutSwitcher(
        ["us", "ru"],
        method,
        session_type="wayland",
        key_sender=fake.press,
        desktop="ubuntu:GNOME",
    )


# --- parsing ----------------------------------------------------------------


def test_parse_gvariant_list() -> None:
    assert _parse_gvariant_list("[('xkb', 'us'), ('xkb', 'ru')]\n") == [
        ("xkb", "us"),
        ("xkb", "ru"),
    ]
    assert _parse_gvariant_list("@a(ss) []\n") == []
    assert _parse_gvariant_list("['<Super>space']") == ["<Super>space"]
    assert _parse_gvariant_list("not a list") == []
    assert _parse_gvariant_list("('xkb', 'us')") == []


@pytest.mark.parametrize(
    ("accelerator", "keys"),
    [
        ("<Super>space", ["KEY_LEFTMETA", "KEY_SPACE"]),
        ("<Shift><Alt>z", ["KEY_LEFTSHIFT", "KEY_LEFTALT", "KEY_Z"]),
        ("<Primary>1", ["KEY_LEFTCTRL", "KEY_1"]),
        ("<Control>Tab", ["KEY_LEFTCTRL", "KEY_TAB"]),
    ],
)
def test_parse_accelerator(accelerator: str, keys: list[str]) -> None:
    assert parse_accelerator(accelerator) == keys


@pytest.mark.parametrize(
    "accelerator",
    ["", "<Super>", "<Hyper>space", "<Super", "<Super>\u00c4", "<Super>a-b", "XF86Keyboard"],
)
def test_parse_accelerator_rejects(accelerator: str) -> None:
    assert parse_accelerator(accelerator) is None


def test_key_sender_only_for_uinput() -> None:
    class Injector:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def tap_combo(self, key_names: list[str], taps: int = 1) -> bool:
            return True

    uinput = Injector("uinput")
    assert key_sender_for(uinput) == uinput.tap_combo
    assert key_sender_for(Injector("wtype")) is None
    assert key_sender_for(object()) is None


# --- backend resolution -----------------------------------------------------


def test_auto_picks_gnome_without_g3kb(monkeypatch: pytest.MonkeyPatch, gnome: FakeGnome) -> None:
    monkeypatch.setattr(
        switcher_module,
        "_which",
        lambda name: None if name == "g3kb-switch" else "/usr/bin/" + name,
    )
    assert _switcher(gnome, "auto").backend == "gnome-shortcut"


def test_auto_still_prefers_g3kb(gnome: FakeGnome) -> None:
    assert _switcher(gnome, "auto").backend == "g3kb-switch"


def test_auto_ignores_gnome_on_other_desktops(
    monkeypatch: pytest.MonkeyPatch, gnome: FakeGnome
) -> None:
    monkeypatch.setattr(
        switcher_module,
        "_which",
        lambda name: None if name == "g3kb-switch" else "/usr/bin/" + name,
    )
    switcher = LayoutSwitcher(
        ["us", "ru"], "auto", session_type="wayland", key_sender=gnome.press, desktop="KDE"
    )
    assert switcher.backend == "none"


def test_gnome_needs_a_key_sender(gnome: FakeGnome) -> None:
    switcher = LayoutSwitcher(["us", "ru"], "gnome-shortcut", session_type="wayland")
    assert switcher.backend == "none"


def test_gnome_needs_gsettings(monkeypatch: pytest.MonkeyPatch, gnome: FakeGnome) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: None)
    assert _switcher(gnome).backend == "none"


def test_gnome_needs_a_pressable_shortcut(gnome: FakeGnome) -> None:
    gnome.shortcut = "['XF86Keyboard']"
    assert _switcher(gnome).backend == "none"
    gnome.shortcut = "@as []"
    assert _switcher(gnome).backend == "none"


# --- query and switch -------------------------------------------------------


def test_current_layout_is_first_mru_entry(gnome: FakeGnome) -> None:
    gnome.mru = ["ru", "us"]
    assert _switcher(gnome).get_current_layout(force=True) == "ru"


def test_current_layout_before_first_switch(gnome: FakeGnome) -> None:
    gnome.mru = []
    assert _switcher(gnome).get_current_layout(force=True) == "us"


def test_switch_presses_shortcut_once_for_two_layouts(gnome: FakeGnome) -> None:
    switcher = _switcher(gnome)
    assert switcher.switch_to("ru") is True
    assert gnome.presses == [(["KEY_LEFTMETA", "KEY_SPACE"], 1)]
    assert switcher.get_current_layout(force=True) == "ru"
    assert switcher.switch_to("us") is True
    assert gnome.presses[-1] == (["KEY_LEFTMETA", "KEY_SPACE"], 1)


def test_switch_to_active_layout_presses_nothing(gnome: FakeGnome) -> None:
    gnome.mru = ["ru", "us"]
    assert _switcher(gnome).switch_to("ru") is True
    assert gnome.presses == []


def test_switch_taps_to_the_mru_position(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGnome(["us", "ru", "ua"], mru=["us", "ru", "ua"])
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", fake.run)
    monkeypatch.setattr(switcher_module, "GNOME_POLL_INTERVAL", 0.0)
    switcher = LayoutSwitcher(
        ["us", "ru", "ua"],
        "gnome-shortcut",
        session_type="wayland",
        key_sender=fake.press,
        desktop="GNOME",
    )
    assert switcher.switch_to("ua") is True
    assert fake.presses == [(["KEY_LEFTMETA", "KEY_SPACE"], 2)]
    assert fake.mru[0] == "ua"


def test_switch_fails_when_gnome_does_not_apply(
    monkeypatch: pytest.MonkeyPatch, gnome: FakeGnome
) -> None:
    monkeypatch.setattr(switcher_module, "GNOME_SWITCH_TIMEOUT", 0.0)
    gnome.applies = False
    assert _switcher(gnome).switch_to("ru") is False


def test_switch_fails_when_the_key_cannot_be_pressed(gnome: FakeGnome) -> None:
    switcher = LayoutSwitcher(
        ["us", "ru"],
        "gnome-shortcut",
        session_type="wayland",
        key_sender=lambda keys, taps: False,
        desktop="GNOME",
    )
    assert switcher.switch_to("ru") is False


def test_switch_to_a_layout_gnome_does_not_have(gnome: FakeGnome) -> None:
    gnome.sources = ["us"]
    assert _switcher(gnome).switch_to("ru") is False


# --- start_switch -----------------------------------------------------------


def test_start_switch_returns_before_gnome_applies(gnome: FakeGnome) -> None:
    """The shortcut is pressed at once; waiting for GNOME is deferred."""
    switcher = _switcher(gnome)
    calls_before = len(gnome.commands)
    finish = switcher.start_switch("ru")
    assert gnome.presses == [(["KEY_LEFTMETA", "KEY_SPACE"], 1)]
    # Only the MRU lookup ran: no polling happened yet.
    polled = [c for c in gnome.commands[calls_before:] if c[-1] == "mru-sources"]
    assert len(polled) == 1
    assert finish() is True
    assert switcher.get_current_layout() == "ru"


def test_start_switch_reports_failure(monkeypatch: pytest.MonkeyPatch, gnome: FakeGnome) -> None:
    monkeypatch.setattr(switcher_module, "GNOME_SWITCH_TIMEOUT", 0.0)
    gnome.applies = False
    assert _switcher(gnome).start_switch("ru")() is False
    gnome.sources = ["us"]
    assert _switcher(gnome).start_switch("ru")() is False


def test_start_switch_is_synchronous_for_other_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """g3kb-switch/setxkbmap switch inside start_switch and keep the settle pause."""
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def run(command: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", run)
    monkeypatch.setattr(switcher_module.time, "sleep", sleeps.append)
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    finish = switcher.start_switch("ru")
    assert calls == [["g3kb-switch", "-s", "ru"]]
    assert sleeps == [switcher_module.SWITCH_SETTLE]
    assert finish() is True
    assert calls == [["g3kb-switch", "-s", "ru"]]
