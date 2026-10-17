"""Integration tests for ``install.sh`` autostart handling.

The installer is the only component that *decides* whether the daemon starts at
login, and it had no way to opt out: ``--no-autostart`` did not exist, so a user
who did not want a login service could not say so. These tests run the real
``install.sh`` in a sandbox whose system binaries are stub scripts on ``PATH``
(``systemctl``, ``apt-get``, ``notify-send``, ...). The installer logic is
executed for real; only the outside world is simulated, which is what a
container without systemd requires.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"

# Every external program install.sh may call. Stubs record their argv so the
# test can assert what the installer asked the system to do.
_STUBS = (
    "sudo",
    "apt-get",
    "apt-cache",
    "gnome-shell",
    "systemctl",
    "notify-send",
    "modprobe",
    "udevadm",
    "update-desktop-database",
    "gtk-update-icon-cache",
    "pip",
)


def _write_stub(path: Path, log: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s %s\\n" "$(basename "$0")" "$*" >> "{log}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(home, systemctl_log)`` with a stubbed PATH and a fake venv.

    The venv is pre-created so the installer skips ``python -m venv`` and
    ``pip install -e .`` (slow, and needs the network); the stubs it would then
    call are present and harmless.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True)
    home.mkdir(parents=True)

    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    for name in _STUBS:
        _write_stub(bin_dir / name, log)

    venv_bin = home / ".local" / "share" / "lingvix" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    _write_stub(venv_bin / "python", log)
    _write_stub(venv_bin / "pip", log)
    _write_stub(venv_bin / "lingvix", log)

    return home, log


def _run_installer(sandbox: tuple[Path, Path], *args: str) -> subprocess.CompletedProcess[str]:
    home, _ = sandbox
    bin_dir = home.parent / "stub-bin"
    env = {
        **os.environ,
        "HOME": str(home),
        # Stubs first so they shadow any real binary; the rest of PATH stays so
        # coreutils (sed, chmod, install, ...) still work.
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "SUDO_USER": "",
        "USER": "tester",
    }
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--yes", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _autostart_entry(home: Path) -> Path:
    return home / ".config" / "autostart" / "lingvix.desktop"


def _systemctl_calls(log: Path) -> list[str]:
    """Return the ``systemctl`` argv (minus the leading ``--user``) in order."""
    calls = [
        line.split(" ", 1)[1]
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.startswith("systemctl ")
    ]
    return [c[len("--user ") :] if c.startswith("--user ") else c for c in calls]


def test_default_install_writes_autostart_and_enables_the_unit(
    sandbox: tuple[Path, Path],
) -> None:
    """The documented zero-config path: entry written, unit enabled at login."""
    home, log = sandbox
    result = _run_installer(sandbox)
    assert result.returncode == 0, result.stderr

    assert _autostart_entry(home).is_file()
    calls = _systemctl_calls(log)
    assert any(c.startswith("enable") and "lingvix.service" in c for c in calls), calls


def test_no_autostart_skips_the_entry_and_does_not_enable_the_unit(
    sandbox: tuple[Path, Path],
) -> None:
    """``--no-autostart`` must not start the daemon at login, but still run it."""
    home, log = sandbox
    result = _run_installer(sandbox, "--no-autostart")
    assert result.returncode == 0, result.stderr

    assert not _autostart_entry(home).exists()
    calls = _systemctl_calls(log)
    assert not any(c.startswith("enable") for c in calls), calls
    assert any(c.startswith("disable") and "lingvix.service" in c for c in calls), calls
    # The session itself must still work: the daemon is started, just not enabled.
    assert any(c.startswith("start") and "lingvix.service" in c for c in calls), calls


def test_no_autostart_removes_an_entry_left_by_an_earlier_install(
    sandbox: tuple[Path, Path],
) -> None:
    """Re-installing with the opt-out must undo a previous default install.

    Without this, a user who installed once (entry written) and then reinstalled
    with ``--no-autostart`` would still be started at every login.
    """
    home, _ = sandbox
    assert _run_installer(sandbox).returncode == 0
    assert _autostart_entry(home).is_file()

    assert _run_installer(sandbox, "--no-autostart").returncode == 0
    assert not _autostart_entry(home).exists()


def test_help_documents_the_opt_out(sandbox: tuple[Path, Path]) -> None:
    home, _ = sandbox
    bin_dir = home.parent / "stub-bin"
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert "--no-autostart" in result.stdout
