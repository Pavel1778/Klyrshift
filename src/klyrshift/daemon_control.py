"""Control a Klyrshift daemon however it was launched.

A daemon can be started two ways: as a ``systemd --user`` service, or as a plain
detached process from ``klyrshift start``. The GUI must see and control both;
otherwise a daemon started from a terminal is invisible to the big toggle and
cannot be stopped from the app. This module presents one interface over the two:
it prefers the systemd unit when it is enabled, and falls back to the PID lock
file that *every* daemon writes (the systemd unit writes it too, because it runs
the same ``klyrshift start --foreground`` command).

The lock file is the single source of truth for "is a daemon alive": it is
created under ``XDG_CACHE_HOME`` and released on exit, and it works without
systemd at all (containers, minimal installs, manual runs).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from .config import cache_dir
from .daemon import HISTORY_FILE_NAME
from .i18n import _

logger = logging.getLogger(__name__)

LOCK_FILE_NAME: Final[str] = "daemon.lock"
SERVICE: Final[str] = "klyrshift.service"
START_TIMEOUT: Final[float] = 5.0
STOP_GRACE: Final[float] = 3.0
POLL_INTERVAL: Final[float] = 0.1
SYSTEMCTL_TIMEOUT: Final[float] = 5.0
# When ``systemctl`` times out (a hung or missing user D-Bus) every probe would
# otherwise pay the full timeout again. After one failure the module stops
# calling systemctl for a short while and falls back to the PID lock file, which
# is enough to report daemon state without a multi-second stall per refresh.
SYSTEMCTL_BACKOFF: Final[float] = 10.0
_systemctl_backoff_until: float = 0.0

# Why the most recent :func:`start` failed, for the GUI to show the user. It is
# a human-readable one-liner (no typed text) and is reset at the top of every
# ``start`` so a stale message is never shown after a later success.
_last_start_error: str | None = None


def last_error() -> str | None:
    """Return the reason the last :func:`start` failed, or ``None``."""
    return _last_start_error


def _set_start_error(message: str | None) -> None:
    """Record the reason a start attempt failed (or clear it on success)."""
    global _last_start_error
    _last_start_error = message


def lock_path() -> Path:
    """Return the path of the daemon PID lock file."""
    return cache_dir() / LOCK_FILE_NAME


def pid_alive(pid: int) -> bool:
    """Return ``True`` when a process with ``pid`` exists and has not exited.

    A *zombie* process (exited but not yet reaped by its parent) still answers
    ``os.kill(pid, 0)``, so the signal probe alone reports a dead daemon as
    alive. That is the "toggle works every other time" failure: the GUI spawns
    the daemon as a child, the daemon exits, the GUI has not reaped it yet, and
    the ON/OFF button keeps reading the stale state. We therefore also consult
    ``/proc`` and treat a zombie as gone.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # A live process owned by another user: we cannot inspect it, assume alive.
        return True
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """Return ``True`` when ``pid`` is a zombie (exited, not yet reaped)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    # Format: ``pid (comm) state ...``; ``comm`` may contain spaces and
    # parentheses, so split after the last ')'.
    close = stat.rfind(")")
    if close == -1:
        return False
    fields = stat[close + 1 :].split()
    return bool(fields) and fields[0] == "Z"


def read_pid() -> int | None:
    """Return the PID in the lock file when that process is still alive.

    A lock file left behind by a crashed daemon is removed (best effort) so a
    later ``start`` does not trip over it. The unlink only happens when the file
    still names the dead pid, so a fresh daemon that has just rewritten the lock
    is never affected.
    """
    try:
        raw = lock_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    pid = int(raw)
    if pid_alive(pid):
        return pid
    try:
        if lock_path().read_text(encoding="utf-8").strip() == raw:
            lock_path().unlink()
    except OSError:
        logger.debug("Could not remove stale lock file", exc_info=True)
    return None


def systemctl_available() -> bool:
    """Return ``True`` when ``systemctl`` is on PATH."""
    return shutil.which("systemctl") is not None


def _systemctl(
    args: list[str], timeout: float = SYSTEMCTL_TIMEOUT
) -> subprocess.CompletedProcess[str] | None:
    """Run ``systemctl --user <args>`` returning ``None`` on any failure.

    A timeout (a hung user D-Bus) starts a short backoff during which systemctl
    is not called at all: the PID lock file still answers "is a daemon running",
    and this keeps a stalled systemctl from freezing every refresh in a caller.
    """
    global _systemctl_backoff_until
    if not systemctl_available():
        return None
    if time.monotonic() < _systemctl_backoff_until:
        return None
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _systemctl_backoff_until = time.monotonic() + SYSTEMCTL_BACKOFF
        logger.debug("systemctl %s failed: %s", args, exc)
        return None


def systemd_active() -> bool:
    """Return ``True`` when the systemd user unit is active."""
    result = _systemctl(["is-active", SERVICE])
    return result is not None and result.stdout.strip() == "active"


# Where ``systemctl --user enable --global`` records the enablement. The unit's
# ``WantedBy=default.target`` creates ``default.target.wants/<service>``; the
# other targets are listed so a future ``WantedBy`` change does not silently
# break the probe.
GLOBAL_USER_UNIT_DIR: Final[Path] = Path("/etc/systemd/user")
GLOBAL_UNIT_TARGETS: Final[tuple[str, ...]] = (
    "default.target.wants",
    "graphical-session.target.wants",
    "multi-user.target.wants",
)


def globally_enabled() -> bool:
    """Return ``True`` when the unit is enabled globally in ``/etc/systemd/user``."""
    return any(
        (GLOBAL_USER_UNIT_DIR / target / SERVICE).is_symlink() for target in GLOBAL_UNIT_TARGETS
    )


def _mask_path() -> Path:
    """Return the per-user unit override path (``~/.config/systemd/user/<svc>``)."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "systemd" / "user" / SERVICE


def masked() -> bool:
    """Return ``True`` when the user masked the unit (symlink to ``/dev/null``)."""
    path = _mask_path()
    try:
        return path.is_symlink() and os.readlink(path) == os.devnull
    except OSError:
        return False


def systemd_enabled() -> bool:
    """Return ``True`` when the systemd user unit starts at login.

    ``is-enabled`` only answers for the *current* user manager. The ``.deb``
    enables the unit **globally** (``/etc/systemd/user``), which a manager that
    has not reloaded yet -- or a probe without a running user manager -- reports
    as ``disabled``. That made the GUI switch read "off" for a daemon that does
    start at login. The global wants symlink is therefore checked directly.
    """
    if masked():
        return False
    result = _systemctl(["is-enabled", SERVICE])
    if result is not None and result.stdout.strip() == "enabled":
        return True
    return globally_enabled()


def is_running() -> bool:
    """Return ``True`` when a daemon is running, however it was started."""
    return read_pid() is not None or systemd_active()


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` every :data:`POLL_INTERVAL` until it holds or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(POLL_INTERVAL)
    return predicate()


def spawn_detached(dry_run: bool = False) -> bool:
    """Start a detached daemon process, logging any failure.

    Prefers the installed ``klyrshift`` launcher over ``sys.executable -m``
    because the launcher sets ``PYTHONPATH`` for the packaged layout; spawning
    ``python3 -m klyrshift`` directly would fail to import the package in a
    ``.deb`` install when the GUI was not itself started through the launcher.

    Returns:
        ``True`` when the process was spawned (not when the daemon is healthy:
        the caller still polls the lock file), ``False`` when ``Popen`` failed.
    """
    launcher = shutil.which("klyrshift")
    command = (
        [launcher, "start", "--foreground"]
        if launcher
        else [sys.executable, "-m", "klyrshift", "start", "--foreground"]
    )
    if dry_run:
        command.append("--dry-run")
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        logger.error("Could not spawn the daemon", exc_info=True)
        return False
    return True


def start(dry_run: bool = False) -> bool:
    """Start the daemon and return whether it came up.

    Prefers the systemd unit when it is enabled so the service keeps its
    restart-on-failure semantics; otherwise spawns a detached process. Either
    way the daemon writes the PID lock file, which is what the GUI polls.

    On failure :func:`last_error` carries a human-readable reason (the systemd
    error, a spawn error, or "daemon exited immediately") for the GUI to show
    instead of a generic message.
    """
    _set_start_error(None)
    if is_running():
        return True
    if systemd_enabled():
        result = _systemctl(["start", SERVICE])
        if result is not None and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            _set_start_error(detail[0] if detail else _("systemd не смог запустить сервис"))
            logger.warning("systemctl start failed: %s", detail)
        if _wait_until(lambda: read_pid() is not None or systemd_active(), START_TIMEOUT):
            return True
        if _last_start_error is None:
            _set_start_error(
                _("сервис не стал активным (проверьте journalctl --user -u klyrshift)")
            )
    if not spawn_detached(dry_run=dry_run):
        # Keep an earlier systemd reason if there is one: it is more specific
        # than "could not spawn" and points the user at the real failure.
        if _last_start_error is None:
            _set_start_error(_("не удалось запустить процесс демона"))
        return False
    if not _wait_until(lambda: read_pid() is not None, START_TIMEOUT):
        if _last_start_error is None:
            _set_start_error(_("демон не записал PID (проверьте ~/.local/state/klyrshift/)"))
        return False
    # The lock appears before the daemon checks for devices, so confirm it is
    # still alive a moment later; otherwise a daemon that died instantly (no
    # keyboard devices) would be reported as a successful start.
    time.sleep(0.3)
    if read_pid() is None:
        _set_start_error(_("демон завершился сразу после старта (нет доступа к клавиатуре?)"))
        return False
    # The fallback spawn succeeded after a failed systemd start: drop the
    # now-irrelevant systemd reason so it is not shown as a live error.
    _set_start_error(None)
    return True


def _kill_pid(pid: int, sig: int) -> bool:
    """Send ``sig`` to ``pid``; return ``True`` when it was delivered or gone."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except OSError:
        logger.debug("kill(%d, %s) failed", pid, sig, exc_info=True)
        return False
    return True


def stop() -> bool:
    """Stop the daemon, however it was started.

    The systemd unit is stopped *first* when it is the manager: it carries
    ``Restart=always``, so a process killed out from under systemd is respawned
    a few seconds later. A plain detached daemon (no systemd) is signalled
    directly, and SIGTERM is escalated to SIGKILL when it is ignored.
    """
    # Stop the unit first when it is the manager: systemd would otherwise
    # restart a process killed out from under it (``Restart=always``).
    if systemd_active():
        _systemctl(["stop", SERVICE])
    pid = read_pid()
    if pid is not None:
        _kill_pid(pid, signal.SIGTERM)
        if not _wait_until(lambda: not pid_alive(pid), STOP_GRACE):
            logger.warning("Daemon %d ignored SIGTERM; escalating to SIGKILL", pid)
            _kill_pid(pid, signal.SIGKILL)
            _wait_until(lambda: not pid_alive(pid), STOP_GRACE)
    return not is_running()


def kill() -> bool:
    """Force-stop the daemon with SIGKILL, without a graceful attempt.

    Stops the systemd unit first (when active) so ``Restart=always`` cannot
    resurrect the process, then SIGKILLs the lock-file PID. Used by
    ``klyrshift kill`` for a daemon wedged in a subprocess that ignores SIGTERM.
    """
    if systemd_active():
        _systemctl(["stop", SERVICE])
    pid = read_pid()
    if pid is not None:
        _kill_pid(pid, signal.SIGKILL)
        _wait_until(lambda: not pid_alive(pid), STOP_GRACE)
    return not is_running()


def restart() -> bool:
    """Restart the daemon (used after a configuration change)."""
    if not is_running():
        return start()
    was_service = systemd_enabled()
    stop()
    if was_service:
        _systemctl(["start", SERVICE])
        return _wait_until(lambda: read_pid() is not None or systemd_active(), START_TIMEOUT)
    spawn_detached()
    return _wait_until(lambda: read_pid() is not None, START_TIMEOUT)


def reload_config() -> bool:
    """Ask the daemon to reload its configuration.

    Prefers ``SIGHUP`` to the running process (works for a manual or service
    daemon alike); falls back to ``systemctl reload-or-restart``.
    """
    pid = read_pid()
    if pid is not None:
        return _kill_pid(pid, signal.SIGHUP)
    result = _systemctl(["reload-or-restart", SERVICE])
    return result is not None and result.returncode == 0


def undo_last_fix() -> bool:
    """Ask the running daemon to undo its most recent correction.

    Returns ``False`` when no daemon is running. This is the reliable undo path
    the GUI button uses: it does not depend on the application's own undo
    history, which groups a correction differently from one app to the next.
    """
    pid = read_pid()
    if pid is None:
        return False
    return _kill_pid(pid, signal.SIGUSR1)


def request_history() -> bool:
    """Ask the running daemon to rewrite its metadata-only history snapshot.

    The daemon already writes ``history.json`` whenever its history changes, so
    the GUI no longer needs this; it remains for a manual refresh. Returns
    ``False`` when no daemon is running.
    """
    pid = read_pid()
    if pid is None:
        return False
    if not hasattr(signal, "SIGUSR2"):  # pragma: no cover - POSIX always has it
        return False
    return _kill_pid(pid, signal.SIGUSR2)


def read_history() -> list[dict[str, object]]:
    """Return the daemon's recent corrections as metadata-only dicts.

    Reads the snapshot the daemon wrote on :func:`request_history`. The file
    contains word *lengths*, layouts and timestamps only; the typed text is
    never present. A missing or malformed file yields an empty list.
    """
    path = cache_dir() / HISTORY_FILE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    history = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def autostart_path() -> Path:
    """Return the XDG autostart entry path (``~/.config/autostart/<svc>.desktop``)."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{SERVICE.removesuffix('.service')}.desktop"


def _xdg_autostart_enabled() -> bool:
    """Return ``True`` when the XDG autostart entry exists and is not hidden."""
    path = autostart_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    # A desktop file can stay on disk but be switched off with ``Hidden=true``
    # (or ``X-GNOME-Autostart-enabled=false``), which every autostart
    # implementation honours. Treat those as disabled rather than present.
    hidden = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Hidden=") and stripped.split("=", 1)[1].strip().lower() == "true":
            hidden = True
        if (
            stripped.startswith("X-GNOME-Autostart-enabled=")
            and stripped.split("=", 1)[1].strip().lower() == "false"
        ):
            hidden = True
    return not hidden


def _write_xdg_autostart(enabled: bool) -> bool:
    """Enable or disable the XDG autostart entry, returning whether it changed.

    The entry is the installer's fallback path (``install.sh`` writes it when
    the systemd user unit is not used). Disabling must actually remove or
    neutralise it, otherwise ``autostart_enabled`` keeps reporting ``True`` and
    the GUI switch snaps back on -- the "autostart cannot be turned off" bug.
    """
    path = autostart_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        except OSError as exc:
            logger.debug("Could not remove the autostart entry %s: %s", path, exc)
            return False
        return True
    # Re-enabling: un-hide an entry that is already there, or recreate it from
    # the packaged template (the systemd-less install path).
    if not path.exists():
        return _create_xdg_autostart(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not read the autostart entry %s: %s", path, exc)
        return False
    fixed = re.sub(r"(?m)^\s*Hidden\s*=\s*true\s*$", "Hidden=false", text)
    fixed = re.sub(
        r"(?m)^\s*X-GNOME-Autostart-enabled\s*=\s*false\s*$",
        "X-GNOME-Autostart-enabled=true",
        fixed,
    )
    if fixed != text:
        try:
            path.write_text(fixed, encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not rewrite the autostart entry %s: %s", path, exc)
            return False
    return True


def _create_xdg_autostart(path: Path) -> bool:
    """Render the packaged autostart template into ``path``."""
    try:
        from importlib import resources

        template = (
            resources.files("klyrshift")
            / "data"
            / f"{SERVICE.removesuffix('.service')}-autostart.desktop"
        )
        text = template.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as exc:
        logger.debug("No packaged autostart template: %s", exc)
        return False
    launcher = shutil.which("klyrshift") or str(Path(sys.executable).with_name("klyrshift"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("@BIN@", launcher), encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not write the autostart entry %s: %s", path, exc)
        return False
    return True


def enable_autostart() -> bool:
    """Enable the daemon at login (systemd unit or XDG autostart entry).

    Both install paths are covered: the ``.deb`` uses the global systemd unit,
    ``install.sh`` writes the XDG autostart entry. Whichever path the install
    used, enabling re-establishes it so the switch reflects the request.
    """
    # A mask set by a previous disable wins over the unit and the wants symlink,
    # so lift it first; otherwise "enable" would silently do nothing.
    if masked():
        _systemctl(["unmask", SERVICE])
    result = _systemctl(["enable", SERVICE])
    if result is not None and result.returncode == 0:
        return True
    # ``enable`` fails for a globally enabled unit the user may not touch
    # (the symlink lives in /etc and belongs to root). Unmasking is enough in
    # that case: the global wants symlink is still there.
    if globally_enabled():
        return True
    return _write_xdg_autostart(True)


def disable_autostart() -> bool:
    """Disable the daemon at login on **both** paths.

    Disabling only the systemd unit used to leave the XDG autostart entry in
    place, so the daemon still started at login and the GUI switch flipped back
    on. The ``.deb`` also enables the unit *globally* (``/etc/systemd/user``),
    which an unprivileged user cannot ``disable`` -- so the unit is masked as
    well, which every user may do and which overrides the global enablement.
    """
    result = _systemctl(["disable", SERVICE])
    unit_ok = result is None or result.returncode == 0
    # A globally enabled unit survives a per-user disable. Masking is the only
    # way for an unprivileged user to opt out, and it is also what makes
    # ``autostart_enabled`` report ``False`` afterwards.
    if globally_enabled():
        masked_result = _systemctl(["mask", SERVICE])
        unit_ok = masked_result is not None and masked_result.returncode == 0
    entry_ok = _write_xdg_autostart(False)
    return unit_ok and entry_ok


def autostart_enabled() -> bool:
    """Return ``True`` when the daemon will start at login.

    Either the systemd unit is enabled (per-user or globally) or an active XDG
    autostart entry exists, so the GUI reflects both install paths.
    """
    return systemd_enabled() or _xdg_autostart_enabled()
