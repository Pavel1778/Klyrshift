"""Keyboard layout switching.

Three backends are supported:

* ``g3kb-switch`` talks to GNOME Shell over D-Bus and works on both Wayland and
  X11 sessions. It is the preferred backend when installed, but it is not in
  the Debian/Ubuntu archives and its Shell extension tracks GNOME releases.
* ``gnome-shortcut`` needs nothing beyond GNOME itself. The active layout is the
  first entry of ``org.gnome.desktop.input-sources mru-sources``, and switching
  presses the input-source shortcut (``switch-input-source``, ``<Super>space``
  by default) on the daemon's virtual keyboard: holding the modifiers and
  tapping the key *k* times selects the *k*-th most recently used layout.
* ``setxkbmap`` is the X11 fallback and is unavailable under a pure Wayland
  session.

The active layout is cached for a short period to avoid spawning a process for
every key press.
"""

from __future__ import annotations

import ast
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Final

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT: Final[float] = 2.0
CACHE_TTL: Final[float] = 1.0
BACKEND_G3KB: Final[str] = "g3kb-switch"
BACKEND_SETXKBMAP: Final[str] = "setxkbmap"
BACKEND_GNOME: Final[str] = "gnome-shortcut"
BACKEND_NONE: Final[str] = "none"

GSETTINGS: Final[str] = "gsettings"
INPUT_SOURCES_SCHEMA: Final[str] = "org.gnome.desktop.input-sources"
KEYBINDINGS_SCHEMA: Final[str] = "org.gnome.desktop.wm.keybindings"
SWITCH_INPUT_SOURCE_KEY: Final[str] = "switch-input-source"
# How long to wait for GNOME to report the new layout after the shortcut. It
# normally takes ~100 ms; past this the switch is reported as failed.
GNOME_SWITCH_TIMEOUT: Final[float] = 1.0
GNOME_POLL_INTERVAL: Final[float] = 0.01
# Pause after a synchronous switch before typing, to let the compositor settle.
SWITCH_SETTLE: Final[float] = 0.05
# GTK accelerator modifiers -> evdev key names.
_ACCEL_MODIFIERS: Final[dict[str, str]] = {
    "super": "KEY_LEFTMETA",
    "shift": "KEY_LEFTSHIFT",
    "control": "KEY_LEFTCTRL",
    "ctrl": "KEY_LEFTCTRL",
    "primary": "KEY_LEFTCTRL",
    "alt": "KEY_LEFTALT",
}

KeySender = Callable[[list[str], int], bool]
"""Press ``key_names`` (modifiers first) tapping the last one ``taps`` times."""


def _run(command: list[str], timeout: float = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run ``command`` safely and return the completed process.

    Args:
        command: Argument vector, executed without a shell.
        timeout: Maximum runtime in seconds.

    Returns:
        The completed process; ``returncode`` is ``-1`` when the command could
        not be executed or timed out.
    """
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Command %s failed: %s", command, exc)
        return subprocess.CompletedProcess(command, -1, "", str(exc))


def _which(program: str) -> str | None:
    """Return the resolved path of ``program`` if available."""
    return shutil.which(program)


def _parse_gvariant_list(text: str) -> list[object]:
    """Parse the ``gsettings get`` rendering of a GVariant array.

    ``gsettings`` prints arrays as Python-compatible literals, with a type
    annotation in front of an empty one (``@a(ss) []``).
    """
    text = text.strip()
    if text.startswith("@"):
        text = text.partition(" ")[2]
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return list(value) if isinstance(value, list) else []


def key_sender_for(injector: object) -> KeySender | None:
    """Return the injector's key-chord method when it can press keys.

    Only the ``uinput`` backend owns a virtual keyboard that can hold a
    modifier, so only it can drive the ``gnome-shortcut`` switcher.
    """
    if getattr(injector, "backend", None) != "uinput":
        return None
    tap_combo = getattr(injector, "tap_combo", None)
    return tap_combo if callable(tap_combo) else None


def parse_accelerator(accelerator: str) -> list[str] | None:
    """Translate a GTK accelerator such as ``<Super>space`` into evdev keys.

    Returns the modifier key names followed by the main key name, or ``None``
    when the accelerator uses something this backend cannot press.
    """
    keys: list[str] = []
    rest = accelerator.strip()
    while rest.startswith("<"):
        name, sep, rest = rest[1:].partition(">")
        if not sep:
            return None
        modifier = _ACCEL_MODIFIERS.get(name.lower())
        if modifier is None:
            return None
        keys.append(modifier)
    if not rest or not rest.isascii() or not rest.isalnum():
        return None
    key = f"KEY_{rest.upper()}"
    try:
        from evdev import ecodes
    except ImportError:
        return None
    # GTK key names that are not evdev keys (``XF86Keyboard``) cannot be pressed.
    if not isinstance(getattr(ecodes, key, None), int):
        return None
    keys.append(key)
    return keys


class LayoutSwitcher:
    """Read and change the active keyboard layout.

    Args:
        layouts: Ordered list of layout identifiers as configured by the user.
            The order must match the order in which the layouts are registered
            in the desktop environment, because ``g3kb-switch`` addresses them
            by index.
        switch_method: One of ``"auto"``, ``"g3kb-switch"``,
            ``"gnome-shortcut"`` or ``"setxkbmap"``.
        session_type: Override for ``XDG_SESSION_TYPE`` (used in tests).
        key_sender: Presses a key chord on the daemon's virtual keyboard
            (:meth:`TextInjector.tap_combo`). Required by ``gnome-shortcut``;
            without it that backend is unavailable.
        desktop: Override for ``XDG_CURRENT_DESKTOP`` (used in tests).
    """

    def __init__(
        self,
        layouts: list[str] | None = None,
        switch_method: str = "auto",
        session_type: str | None = None,
        key_sender: KeySender | None = None,
        desktop: str | None = None,
    ) -> None:
        self.layouts = [layout.lower() for layout in (layouts or ["us", "ru"])]
        self.session_type = (session_type or os.environ.get("XDG_SESSION_TYPE", "")).lower()
        self.desktop = (desktop or os.environ.get("XDG_CURRENT_DESKTOP", "")).lower()
        self._key_sender = key_sender
        self._shortcut: list[str] | None = None
        self._requested_method = switch_method
        self._backend = self._resolve_backend(switch_method)
        self._cache_value: str | None = None
        self._cache_time: float = 0.0

    def _resolve_backend(self, switch_method: str) -> str:
        """Choose a concrete backend honouring availability and the request."""
        if switch_method == BACKEND_G3KB:
            return BACKEND_G3KB if _which(BACKEND_G3KB) else BACKEND_NONE
        if switch_method == BACKEND_SETXKBMAP:
            return BACKEND_SETXKBMAP if _which(BACKEND_SETXKBMAP) else BACKEND_NONE
        if switch_method == BACKEND_GNOME:
            return BACKEND_GNOME if self._gnome_available() else BACKEND_NONE
        # auto
        if _which(BACKEND_G3KB):
            return BACKEND_G3KB
        if "gnome" in self.desktop and self._gnome_available():
            return BACKEND_GNOME
        if self.session_type != "wayland" and _which(BACKEND_SETXKBMAP):
            return BACKEND_SETXKBMAP
        return BACKEND_NONE

    def _gnome_available(self) -> bool:
        """Return whether the ``gnome-shortcut`` backend can work here."""
        if self._key_sender is None or not _which(GSETTINGS):
            return False
        self._shortcut = self._read_shortcut()
        return self._shortcut is not None

    def _read_shortcut(self) -> list[str] | None:
        """Return the first input-source shortcut this backend can press."""
        result = _run([GSETTINGS, "get", KEYBINDINGS_SCHEMA, SWITCH_INPUT_SOURCE_KEY])
        if result.returncode != 0:
            return None
        for accelerator in _parse_gvariant_list(result.stdout):
            if isinstance(accelerator, str):
                keys = parse_accelerator(accelerator)
                if keys is not None:
                    return keys
        return None

    @property
    def backend(self) -> str:
        """Return the name of the active backend."""
        return self._backend

    def _index_to_layout(self, value: str) -> str | None:
        """Translate a backend value (index or name) into a layout id."""
        value = value.strip()
        if not value:
            return None
        if value.isdigit():
            index = int(value)
            if 0 <= index < len(self.layouts):
                return self.layouts[index]
            return None
        lowered = value.lower()
        for layout in self.layouts:
            if lowered == layout or lowered.startswith(layout):
                return layout
        return None

    def _query_g3kb(self) -> str | None:
        """Query the current layout through ``g3kb-switch``."""
        result = _run([BACKEND_G3KB, "-p"])
        if result.returncode != 0:
            return None
        return self._index_to_layout(result.stdout.strip())

    def _gnome_sources(self, key: str) -> list[str]:
        """Return the XKB layout ids stored under ``key`` of the input sources."""
        result = _run([GSETTINGS, "get", INPUT_SOURCES_SCHEMA, key])
        if result.returncode != 0:
            return []
        ids: list[str] = []
        for entry in _parse_gvariant_list(result.stdout):
            if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[1], str):
                ids.append(entry[1])
        return ids

    def _gnome_order(self) -> list[str]:
        """Return GNOME's input sources, most recently used first.

        ``mru-sources`` is empty until the user switches for the first time;
        GNOME then starts on the first configured source.
        """
        sources = self._gnome_sources("sources")
        order = [source for source in self._gnome_sources("mru-sources") if source in sources]
        return order + [source for source in sources if source not in order]

    def _query_gnome(self) -> str | None:
        """Query the current layout from GNOME's most-recently-used list."""
        order = self._gnome_order()
        return self._index_to_layout(order[0]) if order else None

    def _query_setxkbmap(self) -> str | None:
        """Query the current layout through ``setxkbmap -query``."""
        result = _run([BACKEND_SETXKBMAP, "-query"])
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line.lower().startswith("layout:"):
                value = line.split(":", 1)[1].strip()
                first = value.split(",")[0].strip()
                return self._index_to_layout(first)
        return None

    def get_current_layout(self, *, force: bool = False) -> str:
        """Return the currently active layout.

        Args:
            force: When true, bypass the cache and query the backend again.

        Returns:
            A layout identifier, or the first configured layout when the layout
            cannot be determined.
        """
        now = time.monotonic()
        if not force and self._cache_value is not None and now - self._cache_time < CACHE_TTL:
            return self._cache_value

        value: str | None = None
        if self._backend == BACKEND_G3KB:
            value = self._query_g3kb()
        elif self._backend == BACKEND_GNOME:
            value = self._query_gnome()
        elif self._backend == BACKEND_SETXKBMAP:
            value = self._query_setxkbmap()

        if value is None:
            value = self.layouts[0] if self.layouts else "us"
        self._cache_value = value
        self._cache_time = now
        return value

    def _g3kb_set(self, target: str) -> subprocess.CompletedProcess[str]:
        """Invoke ``g3kb-switch -s`` with ``target`` (name or index)."""
        argv = [BACKEND_G3KB, "-s", target]
        # Log the exact argv at DEBUG so a failing switch can be reproduced.
        logger.debug("Switching layout: %s", argv)
        return _run(argv)

    def switch_to(self, layout: str) -> bool:
        """Switch to ``layout``.

        Args:
            layout: The target layout identifier.

        Returns:
            ``True`` when the switch command succeeded, ``False`` otherwise.
        """
        layout = layout.lower()
        if layout not in self.layouts:
            logger.warning("Layout %s is not configured", layout)
            return False

        success = False
        if self._backend == BACKEND_G3KB:
            success = self._switch_g3kb(layout)
        elif self._backend == BACKEND_GNOME:
            waiter = self._press_gnome_shortcut(layout)
            success = waiter is not None and waiter()
        elif self._backend == BACKEND_SETXKBMAP:
            logger.debug("Switching layout: %s", [BACKEND_SETXKBMAP, layout])
            result = _run([BACKEND_SETXKBMAP, layout])
            success = result.returncode == 0
        else:
            logger.warning("No layout backend available; cannot switch to %s", layout)
            return False

        if success:
            self._cache_value = layout
            self._cache_time = time.monotonic()
        else:
            logger.error("Failed to switch layout to %s via %s", layout, self._backend)
        return success

    def start_switch(self, layout: str) -> Callable[[], bool]:
        """Begin switching to ``layout`` and return a callable that finishes it.

        The caller can do layout-independent work (deleting the mistyped text)
        between the two halves. With ``gnome-shortcut`` the shortcut is pressed
        here and the returned callable waits until GNOME reports the new
        layout, so that wait overlaps the deletion. Every other backend
        switches synchronously here and pauses for the compositor, exactly as
        :meth:`switch_to` followed by the usual settle delay, and the returned
        callable only reports the result.
        """
        if self._backend != BACKEND_GNOME or layout.lower() not in self.layouts:
            success = self.switch_to(layout)
            time.sleep(SWITCH_SETTLE)
            return lambda: success
        target = layout.lower()
        waiter = self._press_gnome_shortcut(target)
        if waiter is None:
            logger.error("Failed to switch layout to %s via %s", target, self._backend)
            return lambda: False

        def finish() -> bool:
            success = waiter()
            if success:
                self._cache_value = target
                self._cache_time = time.monotonic()
            else:
                logger.error("Failed to switch layout to %s via %s", target, self._backend)
            return success

        return finish

    def _press_gnome_shortcut(self, layout: str) -> Callable[[], bool] | None:
        """Press the input-source shortcut so that ``layout`` becomes active.

        Returns a callable that waits for GNOME to report the switch, or
        ``None`` when the shortcut could not be pressed. Holding the modifiers
        and tapping the key *k* times selects the *k*-th most recently used
        source, so *k* is the target's position in ``mru-sources``.
        """
        order = self._gnome_order()
        taps = next(
            (
                index
                for index, source in enumerate(order)
                if self._index_to_layout(source) == layout
            ),
            None,
        )
        if taps is None:
            logger.warning("Layout %s is not among the GNOME input sources", layout)
            return None
        if taps == 0:
            return lambda: True
        if self._key_sender is None or self._shortcut is None:
            return None
        logger.debug("Switching layout: %s x%d", self._shortcut, taps)
        if not self._key_sender(self._shortcut, taps):
            return None

        def wait() -> bool:
            deadline = time.monotonic() + GNOME_SWITCH_TIMEOUT
            while True:
                if self._query_gnome() == layout:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(GNOME_POLL_INTERVAL)

        return wait

    def _switch_g3kb(self, layout: str) -> bool:
        """Switch to ``layout`` through ``g3kb-switch``.

        ``g3kb-switch -s`` accepts either the layout name (for example ``ru``)
        or its numeric group index. The name is tried first and the index is
        used as a fallback, because some builds match the D-Bus layout id
        exactly while others only resolve the index. A zero exit status is
        authoritative: ``g3kb-switch`` prints diagnostics to stderr on a
        non-fatal path, so stderr is deliberately not inspected.
        """
        result = self._g3kb_set(layout)
        if result.returncode == 0:
            return True
        logger.debug(
            "g3kb-switch -s %s failed (rc=%s): %s",
            layout,
            result.returncode,
            (result.stderr or "").strip(),
        )
        index = str(self.layouts.index(layout))
        fallback = self._g3kb_set(index)
        return fallback.returncode == 0

    def describe(self) -> str:
        """Return a human readable description of the switcher state."""
        return f"backend={self._backend} session={self.session_type or 'unknown'}"
