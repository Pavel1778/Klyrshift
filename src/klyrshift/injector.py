"""Text replacement backends.

Klyrshift rewrites already-typed text by sending the right number of
``Backspace`` key presses followed by the corrected text. Three backends are
supported, tried in order of preference:

* ``uinput`` creates a virtual kernel keyboard and emits real key events. It is
  layout-aware: characters are translated into physical keys using the target
  layout so the compositor produces the intended glyphs.
* ``wtype`` uses the Wayland virtual-keyboard protocol and types literal text.
* ``xdotool`` types literal text under X11.

Backends are selected automatically based on availability unless the user pins
one through the configuration.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any, Final

from .converter import LayoutConverter

logger = logging.getLogger(__name__)

BACKEND_UINPUT: Final[str] = "uinput"
BACKEND_WTYPE: Final[str] = "wtype"
BACKEND_XDOTOOL: Final[str] = "xdotool"
BACKEND_NONE: Final[str] = "none"

COMMAND_TIMEOUT: Final[float] = 10.0
BACKSPACE_DELAY: Final[float] = 0.005
# Delay after a layout switch before typing, to let the compositor settle.
SETTLE_DELAY: Final[float] = 0.05

# Canonical US character -> (evdev key name, requires shift).
_BASE_KEYS: Final[dict[str, str]] = {
    "`": "KEY_GRAVE",
    "1": "KEY_1",
    "2": "KEY_2",
    "3": "KEY_3",
    "4": "KEY_4",
    "5": "KEY_5",
    "6": "KEY_6",
    "7": "KEY_7",
    "8": "KEY_8",
    "9": "KEY_9",
    "0": "KEY_0",
    "-": "KEY_MINUS",
    "=": "KEY_EQUAL",
    "q": "KEY_Q",
    "w": "KEY_W",
    "e": "KEY_E",
    "r": "KEY_R",
    "t": "KEY_T",
    "y": "KEY_Y",
    "u": "KEY_U",
    "i": "KEY_I",
    "o": "KEY_O",
    "p": "KEY_P",
    "[": "KEY_LEFTBRACE",
    "]": "KEY_RIGHTBRACE",
    "\\": "KEY_BACKSLASH",
    "a": "KEY_A",
    "s": "KEY_S",
    "d": "KEY_D",
    "f": "KEY_F",
    "g": "KEY_G",
    "h": "KEY_H",
    "j": "KEY_J",
    "k": "KEY_K",
    "l": "KEY_L",
    ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE",
    "z": "KEY_Z",
    "x": "KEY_X",
    "c": "KEY_C",
    "v": "KEY_V",
    "b": "KEY_B",
    "n": "KEY_N",
    "m": "KEY_M",
    ",": "KEY_COMMA",
    ".": "KEY_DOT",
    "/": "KEY_SLASH",
    " ": "KEY_SPACE",
}

# Canonical shifted character -> matching unshifted character.
_SHIFT_PAIRS: Final[dict[str, str]] = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _SHIFT_PAIRS[_letter.upper()] = _letter


def _run(command: list[str], timeout: float = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run ``command`` without a shell, returning the completed process."""
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


class TextInjector:
    """Replace typed text using the best available backend.

    Args:
        converter: Converter used to translate characters into physical keys
            for the ``uinput`` backend.
        backend: One of ``"auto"``, ``"uinput"``, ``"wtype"`` or ``"xdotool"``.
        session_type: Override for ``XDG_SESSION_TYPE`` (used in tests).
    """

    def __init__(
        self,
        converter: LayoutConverter | None = None,
        backend: str = "auto",
        session_type: str | None = None,
        settle_ms: int = 0,
    ) -> None:
        import os

        self.converter = converter or LayoutConverter()
        self.session_type = (session_type or os.environ.get("XDG_SESSION_TYPE", "")).lower()
        self._requested_backend = backend
        self._backend = self._resolve_backend(backend)
        self._settle_ms = max(0, int(settle_ms))
        # The uinput backend keeps one virtual keyboard open for its lifetime.
        # Creating ``evdev.UInput`` costs ~100 ms (python-evdev polls until the
        # new event node is readable) and the compositor needs a moment to start
        # listening to a new device, so a device per call made every fix pay
        # both, twice.
        self._device: Any | None = None
        self._device_codes: frozenset[int] = frozenset()

    def warm_up(self) -> None:
        """Create the shared virtual keyboard ahead of the first fix.

        The daemon calls this at start-up so the compositor already knows the
        device when the first correction is typed. A failure is not fatal: the
        device is created on first use instead.
        """
        if self._backend != BACKEND_UINPUT:
            return
        try:
            import evdev
        except ImportError:
            return
        try:
            self._acquire_uinput(evdev, set())
        except (OSError, PermissionError, ValueError):
            logger.debug("Could not pre-create the uinput device", exc_info=True)

    def close(self) -> None:
        """Destroy the shared virtual keyboard, if one is open."""
        if self._device is not None:
            device, self._device = self._device, None
            self._device_codes = frozenset()
            with contextlib.suppress(OSError):
                self._close_uinput(device)

    def _uinput_available(self) -> bool:
        """Return ``True`` when a writable ``/dev/uinput`` exists."""
        import os

        return os.access("/dev/uinput", os.W_OK)

    def _resolve_backend(self, backend: str) -> str:
        """Choose a concrete backend honouring availability and the request."""
        if backend == BACKEND_UINPUT:
            return BACKEND_UINPUT if self._uinput_available() else BACKEND_NONE
        if backend == BACKEND_WTYPE:
            return BACKEND_WTYPE if _which(BACKEND_WTYPE) else BACKEND_NONE
        if backend == BACKEND_XDOTOOL:
            return BACKEND_XDOTOOL if _which(BACKEND_XDOTOOL) else BACKEND_NONE
        # auto
        if self._uinput_available():
            return BACKEND_UINPUT
        if _which(BACKEND_WTYPE):
            return BACKEND_WTYPE
        if _which(BACKEND_XDOTOOL):
            return BACKEND_XDOTOOL
        return BACKEND_NONE

    @property
    def backend(self) -> str:
        """Return the name of the active backend."""
        return self._backend

    def can_type(self, char: str, layout: str) -> bool:
        """Return whether ``char`` can be typed in ``layout`` by this backend.

        Used to decide whether a word-boundary character can be safely consumed
        and retyped as part of a replacement. The literal backends (``wtype``,
        ``xdotool``) can type any character; the layout-aware ``uinput`` backend
        can only produce the characters it has a physical key for.
        """
        if not char:
            return False
        if self._backend in (BACKEND_WTYPE, BACKEND_XDOTOOL):
            return True
        if self._backend != BACKEND_UINPUT:
            return False
        return self._char_to_key(char, layout) is not None

    def replace_text(
        self,
        backspace_count: int,
        new: str,
        layout: str,
        before_typing: Callable[[], bool] | None = None,
    ) -> bool:
        """Delete ``backspace_count`` characters and type ``new``.

        The caller passes a *count* rather than the old text: the daemon tracks
        the physical keys that produced the on-screen characters, so the number
        of Backspaces always matches exactly what is displayed, no matter how
        fast the user types. Passing the old string would make the deletion
        depend on the character buffer staying in sync with the screen.

        Args:
            backspace_count: How many Backspace presses to emit.
            new: The corrected text to type.
            layout: The layout that will be active while typing ``new``.
            before_typing: Called after the deletion and before ``new`` is
                typed. The daemon passes the second half of a layout switch
                here (:meth:`LayoutSwitcher.start_switch`), so waiting for the
                compositor to apply the new layout overlaps the deletion. A
                ``False`` result is logged; the text is typed regardless,
                exactly as when a synchronous switch fails.

        Returns:
            ``True`` when the replacement succeeded.
        """
        if self._backend == BACKEND_NONE:
            logger.error("No text injection backend available")
            return False

        # The uinput backend emits the backspaces and the new text as one atomic
        # batch (all events written, then a single ``syn``). That closes the
        # crash window in which the daemon had deleted the old text but not yet
        # typed the replacement, which would leave the user with truncated text.
        if self._backend == BACKEND_UINPUT:
            return self._uinput_batch(backspace_count, new, layout, before_typing)

        if not self._send_backspaces(backspace_count):
            logger.warning("Failed to send backspaces; aborting replacement")
            return False

        time.sleep(SETTLE_DELAY)
        self._run_before_typing(before_typing)
        return self._type_text(new, layout)

    @staticmethod
    def _run_before_typing(before_typing: Callable[[], bool] | None) -> None:
        """Run the pre-typing hook, logging (not failing) a ``False`` result."""
        if before_typing is not None and not before_typing():
            logger.warning("Layout switch did not complete before typing")

    def _send_backspaces(self, count: int) -> bool:
        """Send ``count`` backspace presses."""
        if count <= 0:
            return True
        command = [self._backend, "key", "BackSpace"]
        for _ in range(count):
            result = _run(command)
            if result.returncode != 0:
                return False
            time.sleep(BACKSPACE_DELAY)
        return True

    def _type_text(self, text: str, layout: str) -> bool:
        """Type ``text`` using the active backend."""
        if self._backend == BACKEND_UINPUT:
            return self._type_uinput(text, layout)
        if self._backend == BACKEND_WTYPE:
            result = _run([BACKEND_WTYPE, "-s", "0", "-d", "0", text])
            return result.returncode == 0
        if self._backend == BACKEND_XDOTOOL:
            result = _run([BACKEND_XDOTOOL, "type", "--clearmodifiers", text])
            return result.returncode == 0
        return False

    def _char_to_key(self, char: str, layout: str) -> tuple[str, bool] | None:
        """Resolve ``char`` to a physical key and shift state for ``layout``.

        Args:
            char: A character that should be produced.
            layout: Layout in which the character will be typed.

        Returns:
            A ``(key_name, shift)`` tuple, or ``None`` when the character cannot
            be produced in the given layout.
        """
        reverse = self.converter._reverse.get(layout)
        canonical = char
        if reverse is not None and char in reverse:
            canonical = reverse[char]

        if canonical in _BASE_KEYS:
            return _BASE_KEYS[canonical], False
        base = _SHIFT_PAIRS.get(canonical)
        if base is not None and base in _BASE_KEYS:
            return _BASE_KEYS[base], True
        return None

    def _uinput_tap(self, key_name: str, *, count: int = 1, delay: float = 0.0) -> bool:
        """Tap ``key_name`` ``count`` times through a virtual keyboard."""
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        key_code = getattr(evdev.ecodes, key_name, None)
        if key_code is None:
            logger.error("Unknown key %s", key_name)
            return False

        shift_code = evdev.ecodes.KEY_LEFTSHIFT
        ev_key = evdev.ecodes.EV_KEY
        try:
            device = self._acquire_uinput(evdev, {key_code, shift_code})
            for _ in range(count):
                device.write(ev_key, key_code, 1)
                device.write(ev_key, key_code, 0)
                device.syn()
                if delay:
                    time.sleep(delay)
        except (OSError, PermissionError, ValueError):
            self._uinput_failed()
            return False
        return True

    def tap_combo(self, key_names: list[str], taps: int = 1) -> bool:
        """Press ``key_names`` together (in order) through a virtual keyboard.

        Used for shortcuts such as ``Ctrl+C``. ``key_names`` are evdev names
        (``"KEY_LEFTCTRL"``, ``"KEY_C"``); modifiers are held while the last key
        is tapped ``taps`` times (GNOME's input-source switcher, for example,
        selects the *k*-th layout when Space is tapped *k* times under Super).
        Only the ``uinput`` backend is supported; other backends return
        ``False``.
        """
        if not key_names or taps < 1 or self._backend != BACKEND_UINPUT:
            return False
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False
        resolved: list[int] = []
        for name in key_names:
            code = getattr(evdev.ecodes, name, None)
            if code is None:
                logger.error("Unknown key in combo %s", key_names)
                return False
            resolved.append(int(code))
        code_set = set(resolved)
        ev_key = evdev.ecodes.EV_KEY
        try:
            device = self._acquire_uinput(evdev, code_set)
            for code in resolved[:-1]:
                device.write(ev_key, code, 1)
            for _ in range(taps):
                device.write(ev_key, resolved[-1], 1)
                device.write(ev_key, resolved[-1], 0)
            for code in reversed(resolved[:-1]):
                device.write(ev_key, code, 0)
            device.syn()
        except (OSError, PermissionError, ValueError):
            self._uinput_failed()
            return False
        return True

    def _resolve_uinput_keys(
        self, text: str, layout: str
    ) -> tuple[list[tuple[int, bool]], set[int]] | None:
        """Resolve ``text`` into ``(keycode, shift)`` pairs and a key set.

        Returns ``None`` when a character cannot be produced in ``layout``.

        The second element is the set of *key codes* (plain integers from
        ``evdev.ecodes``) that the virtual keyboard must be able to emit. Key
        codes are never taken from ``uinput.KEY_*``: on Debian 13 those
        constants are ``(event_type, code)`` tuples, and older releases expose
        them under a different module layout altogether.
        """
        import evdev

        codes: set[int] = {int(evdev.ecodes.KEY_LEFTSHIFT), int(evdev.ecodes.KEY_BACKSPACE)}
        resolved: list[tuple[int, bool]] = []
        for char in text:
            key = self._char_to_key(char, layout)
            if key is None:
                # Do not log the character itself; it may be sensitive input.
                logger.warning("Cannot type a character in layout %s via uinput", layout)
                return None
            name, shift = key
            code = getattr(evdev.ecodes, name, None)
            if code is None:
                return None
            codes.add(int(code))
            resolved.append((int(code), shift))
        return resolved, codes

    @staticmethod
    def _open_uinput(evdev: Any, key_codes: set[int]) -> Any:
        """Open a virtual keyboard able to emit ``key_codes``.

        Uses ``evdev.UInput`` (a hard dependency, available in Debian 12 and
        13) rather than ``uinput.UInput``: the ``uinput`` package changed its
        API between releases (``Device``/``emit`` versus ``UInput``/``write``)
        and its ``KEY_*`` constants are tuples, which makes it an unreliable
        dependency here.
        """
        capabilities = {int(evdev.ecodes.EV_KEY): sorted(int(code) for code in key_codes)}
        return evdev.UInput(capabilities, name="klyrshift")

    def _acquire_uinput(self, evdev: Any, key_codes: set[int]) -> Any:
        """Return the shared virtual keyboard, creating it when needed.

        The device is created once with every key the uinput backend can type
        (all of :data:`_BASE_KEYS` plus Shift and Backspace) and reused for
        every later call. A request for a key outside that set (a ``tap_combo``
        with Ctrl, for example) recreates it with the union, so the set only
        grows and the device is rebuilt at most a handful of times.
        """
        wanted = frozenset(int(code) for code in key_codes)
        if self._device is not None and wanted <= self._device_codes:
            return self._device
        codes = wanted | self._device_codes | self._baseline_codes(evdev)
        self.close()
        self._device = self._open_uinput(evdev, set(codes))
        self._device_codes = codes
        return self._device

    @staticmethod
    def _baseline_codes(evdev: Any) -> frozenset[int]:
        """Return the key codes every shared device is created with."""
        names = {*_BASE_KEYS.values(), "KEY_LEFTSHIFT", "KEY_BACKSPACE"}
        codes = (getattr(evdev.ecodes, name, None) for name in names)
        return frozenset(int(code) for code in codes if code is not None)

    def _uinput_failed(self) -> None:
        """Log a failed write and drop the device so the next call rebuilds it."""
        logger.error("Could not write to the uinput device", exc_info=True)
        self.close()

    @staticmethod
    def _close_uinput(device: Any) -> None:
        """Close ``device``, tolerating backends that only implement ``close``."""
        try:
            device.close()
        except AttributeError:
            destroy = getattr(device, "destroy", None)
            if destroy is not None:
                destroy()

    def _type_uinput(self, text: str, layout: str) -> bool:
        """Type ``text`` through a virtual kernel keyboard."""
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        resolved_bundle = self._resolve_uinput_keys(text, layout)
        if resolved_bundle is None:
            return False
        resolved, codes = resolved_bundle
        shift_code = int(evdev.ecodes.KEY_LEFTSHIFT)
        ev_key = evdev.ecodes.EV_KEY

        try:
            device = self._acquire_uinput(evdev, codes)
            for code, shift in resolved:
                if shift:
                    device.write(ev_key, shift_code, 1)
                device.write(ev_key, code, 1)
                device.write(ev_key, code, 0)
                if shift:
                    device.write(ev_key, shift_code, 0)
                device.syn()
        except (OSError, PermissionError, ValueError):
            self._uinput_failed()
            return False
        return True

    def _uinput_batch(
        self,
        backspace_count: int,
        text: str,
        layout: str,
        before_typing: Callable[[], bool] | None = None,
    ) -> bool:
        """Delete ``backspace_count`` chars and type ``text``.

        The backspaces are written and flushed with a single ``syn`` so a crash
        before that point leaves the text untouched instead of half-deleted.
        The replacement characters are then emitted and flushed separately,
        after an optional settle pause (``backspace_settle_ms``). Chromium and
        Electron applications process Backspace asynchronously; typing into the
        same ``syn`` can therefore race the deletion and leave the first
        character behind (the ``рhello`` symptom). A short pause between the two
        flushes gives the compositor time to apply the deletion.
        """
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        resolved_bundle = self._resolve_uinput_keys(text, layout)
        if resolved_bundle is None:
            return False
        resolved, codes = resolved_bundle

        shift_code = int(evdev.ecodes.KEY_LEFTSHIFT)
        backspace_code = int(evdev.ecodes.KEY_BACKSPACE)
        ev_key = evdev.ecodes.EV_KEY

        try:
            device = self._acquire_uinput(evdev, codes)
            for _ in range(backspace_count):
                device.write(ev_key, backspace_code, 1)
                device.write(ev_key, backspace_code, 0)
            device.syn()
        except (OSError, PermissionError, ValueError):
            self._uinput_failed()
            return False

        if self._settle_ms > 0:
            time.sleep(self._settle_ms / 1000.0)
        self._run_before_typing(before_typing)

        try:
            device = self._acquire_uinput(evdev, codes)
            for code, shift in resolved:
                if shift:
                    device.write(ev_key, shift_code, 1)
                device.write(ev_key, code, 1)
                device.write(ev_key, code, 0)
                if shift:
                    device.write(ev_key, shift_code, 0)
            device.syn()
        except (OSError, PermissionError, ValueError):
            self._uinput_failed()
            return False
        return True

    def describe(self) -> str:
        """Return a human readable description of the injector state."""
        return f"backend={self._backend} session={self.session_type or 'unknown'}"
