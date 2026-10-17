"""End-to-end backend selection against real executables on ``PATH``.

The rest of the suite monkeypatches ``_which``/``_run``, so it proves the
decision *logic* but never that the code actually finds and drives a backend
binary. These tests write small stub programs that record their argv, put them
on ``PATH`` and run the real classes, so the ``g3kb-switch`` / ``setxkbmap`` /
``wtype`` / ``xdotool`` paths execute as they would on a user's machine.

No display server is required: the stubs replace the desktop tools. What is
*not* covered here -- and cannot be, without a GNOME session -- is whether the
real ``g3kb-switch``/``wtype`` binaries talk to a live compositor.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from klyrshift.injector import TextInjector
from klyrshift.switcher import LayoutSwitcher

STUB = """#!/bin/sh
# Record the invocation, then behave like the tool it stands in for.
printf '%s\\n' "$*" >> "{log}"
{body}
"""


def _make_stub(bin_dir: Path, name: str, log: Path, body: str = "exit 0") -> None:
    path = bin_dir / name
    path.write_text(STUB.format(log=log, body=body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _isolate(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    """Point ``PATH`` at ``bin_dir`` alone so no host tool leaks in."""
    monkeypatch.setenv("PATH", str(bin_dir))
    # shutil.which uses os.environ via os.get_exec_path, which caches nothing,
    # but a stale PATH_FALLBACK would still resolve host binaries.
    monkeypatch.delenv("PATH_FALLBACK", raising=False)


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    _isolate(monkeypatch, bin_dir)
    return bin_dir, log


def test_g3kb_backend_is_found_and_driven(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, log = sandbox
    _make_stub(bin_dir, "g3kb-switch", log, body='case "$1" in -p) echo "1";; esac')
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")

    assert switcher.backend == "g3kb-switch"
    assert switcher.get_current_layout(force=True) == "ru"
    assert switcher.switch_to("us") is True

    calls = log.read_text(encoding="utf-8").splitlines()
    assert "-p" in calls
    assert "-s us" in calls


def test_x11_falls_back_to_setxkbmap_and_switches(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, log = sandbox
    _make_stub(bin_dir, "setxkbmap", log, body='case "$1" in -query) echo "layout: us";; esac')
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="x11")

    assert switcher.backend == "setxkbmap"
    assert switcher.get_current_layout(force=True) == "us"
    assert switcher.switch_to("ru") is True

    calls = log.read_text(encoding="utf-8").splitlines()
    assert "-query" in calls
    assert "ru" in calls


def test_wayland_without_g3kb_has_no_backend(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``setxkbmap`` must not be used on Wayland: it cannot reach the compositor."""
    bin_dir, log = sandbox
    _make_stub(bin_dir, "setxkbmap", log)
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")

    assert switcher.backend == "none"
    assert switcher.switch_to("ru") is False
    assert log.read_text(encoding="utf-8") == ""


def test_g3kb_name_failure_falls_back_to_index(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that rejects the name must still switch, via the group index."""
    bin_dir, log = sandbox
    _make_stub(
        bin_dir,
        "g3kb-switch",
        log,
        body='if [ "$1" = "-s" ] && [ "$2" = "ru" ]; then exit 1; fi\nexit 0',
    )
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")

    assert switcher.switch_to("ru") is True
    calls = log.read_text(encoding="utf-8").splitlines()
    assert "-s ru" in calls
    assert "-s 1" in calls  # index of "ru" in ["us", "ru"]


def test_wtype_backend_types_through_a_real_process(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, log = sandbox
    _make_stub(bin_dir, "wtype", log)
    injector = TextInjector(session_type="wayland")

    assert injector.backend == "wtype"
    assert injector.replace_text(2, "привет", "ru") is True

    calls = log.read_text(encoding="utf-8").splitlines()
    assert sum("BackSpace" in c for c in calls) == 2
    assert any("привет" in c for c in calls)


def test_xdotool_is_the_x11_injection_backend(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, log = sandbox
    _make_stub(bin_dir, "xdotool", log)
    injector = TextInjector(session_type="x11")

    assert injector.backend == "xdotool"
    assert injector.replace_text(1, "hello", "us") is True

    calls = log.read_text(encoding="utf-8").splitlines()
    assert any("BackSpace" in c for c in calls)
    assert any("hello" in c for c in calls)


def test_no_injection_backend_reports_failure(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bin_dir, log = sandbox
    injector = TextInjector(session_type="wayland")

    assert injector.backend == "none"
    assert injector.replace_text(1, "x", "us") is False
    assert log.read_text(encoding="utf-8") == ""


def test_failing_backend_is_reported_not_swallowed(
    sandbox: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero exit must surface as ``False``, so the daemon can recover."""
    bin_dir, log = sandbox
    _make_stub(bin_dir, "wtype", log, body="exit 3")
    injector = TextInjector(session_type="wayland")

    assert injector.backend == "wtype"
    assert injector.replace_text(1, "x", "us") is False


def test_stubs_are_the_only_thing_on_path(sandbox: tuple[Path, Path]) -> None:
    """Guard the isolation itself: a leaky PATH would fake these results."""
    bin_dir, _ = sandbox
    assert os.environ["PATH"] == str(bin_dir)
