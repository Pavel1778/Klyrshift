"""Headless behavioural simulator for the daemon.

The daemon reads a keyboard, talks to the compositor and injects synthetic key
events, so it can only be exercised end to end on a real desktop -- which is
exactly what an automated agent does not have. This module replaces the three
operating-system boundaries (the keyboard, the layout switcher and the text
injector) with in-process fakes and drives the *real* daemon logic with a small
scenario language. It is what makes Klyrshift testable without a keyboard:

    python -m klyrshift.simulate 'type ghbdtn, space'
    python -m klyrshift.simulate 'mode manual, type langauge, space'
    klyrshift simulate --json 'type ghbdtn, space, ctrl z, type ghbdtn, space'

The scenario is a comma-separated list of steps:

* ``type <text>`` -- press the physical keys that produce ``text`` on a US
  keyboard (``ghbdtn`` -> the six keys ``g h b d t n``); the active layout
  decides the glyphs on screen.
* ``key <NAME>`` / ``press <NAME>`` -- a single named key (``space``,
  ``enter``, ``tab``, ``backspace``, ``esc``, ``left``, ``f12`` ...).
* ``space`` / ``enter`` / ``tab`` / ``backspace`` -- shorthands.
* ``shift+<key>`` / ``ctrl+<key>`` / ``alt+<key>`` / ``super+<key>`` -- a chord,
  matched against the daemon's hotkey engine.
* ``dblshift`` / ``dblctrl`` / ``dblalt`` -- a double tap of a modifier.
* ``layout <name>`` -- make ``name`` the active layout.
* ``mode <auto|manual|hybrid>`` -- set the working mode before the rest runs.
* ``config key=value; key=value`` -- override configuration fields.
* ``wait`` -- force the idle-timeout flush (``type hello, wait``).

The simulator renders the "screen" by applying each injected replacement to the
text it has accumulated, so the output is what the user would actually see --
which is the property a unit test asserting a raw ``(backspace, text, layout)``
tuple cannot check.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final, cast

from .config import Config
from .daemon import _US_KEY_NAMES, KlyrshiftDaemon
from .detector import LanguageDetector
from .injector import TextInjector
from .switcher import LayoutSwitcher

# The physical key that produces each canonical US character, and whether it
# needs Shift. Derived from the daemon's own table so the two can never drift.
_CHAR_TO_KEY: Final[dict[str, tuple[str, bool]]] = {}
for _name, (_plain, _shifted) in _US_KEY_NAMES.items():
    _CHAR_TO_KEY.setdefault(_plain, (_name, False))
    _CHAR_TO_KEY.setdefault(_shifted, (_name, True))

# Named keys a scenario may address directly (lower-case, no ``KEY_`` prefix).
_NAMED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "space",
        "enter",
        "kpenter",
        "tab",
        "backspace",
        "esc",
        "escape",
        "delete",
        "insert",
        "home",
        "end",
        "pageup",
        "pagedown",
        "up",
        "down",
        "left",
        "right",
        "leftctrl",
        "rightctrl",
        "leftalt",
        "rightalt",
        "leftshift",
        "rightshift",
        "leftmeta",
        "rightmeta",
    }
    | {f"f{n}" for n in range(1, 25)}
)

# Modifier family -> (left key name, right key name).
_MODIFIER_KEYS: Final[dict[str, tuple[str, str]]] = {
    "shift": ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"),
    "ctrl": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"),
    "alt": ("KEY_LEFTALT", "KEY_RIGHTALT"),
    "super": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
}


class ScenarioError(ValueError):
    """A scenario could not be parsed."""


@dataclass
class SimEvent:
    """One recorded event: an input step or an injected replacement."""

    kind: str
    detail: str


@dataclass
class SimulationResult:
    """The outcome of a scenario run.

    Attributes:
        screen: The text the user would see after every replacement.
        replacements: ``(backspace_count, new_text, layout)`` per injection.
        events: An ordered log of inputs and injections.
        mode: The working mode at the end of the run.
        layout: The active layout at the end of the run.
        suppressed: Words the user rejected with Ctrl+Z this session.
        learned: Words promoted into the detector's vocabulary this session.
        stats: The learning counters (metadata only, never a word).
    """

    screen: str = ""
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    events: list[SimEvent] = field(default_factory=list)
    mode: str = "auto"
    layout: str = "us"
    suppressed: list[str] = field(default_factory=list)
    learned: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "screen": self.screen,
            "replacements": [
                {"backspaces": n, "text": text, "layout": layout}
                for n, text, layout in self.replacements
            ],
            "events": [{"kind": e.kind, "detail": e.detail} for e in self.events],
            "mode": self.mode,
            "layout": self.layout,
            "suppressed": self.suppressed,
            "learned": self.learned,
            "stats": self.stats,
        }


class _SimSwitcher:
    """A layout switcher that only remembers the active layout."""

    backend = "simulate"

    def __init__(self, current: str, layouts: list[str]) -> None:
        self.current = current
        self.layouts = layouts
        self.switches: list[str] = []
        self.session_type = "simulate"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        self.switches.append(layout)
        return True

    def describe(self) -> str:
        return f"backend=simulate layout={self.current}"


class _SimInjector:
    """An injector that applies replacements to an in-memory screen buffer.

    This is the difference from a plain recording fake: the daemon's decisions
    depend on what is on screen (``_last_flushed_word``, the undo history), so
    the simulator keeps the screen in step exactly as a real compositor would.
    """

    backend = "simulate"

    def __init__(self, result: SimulationResult, screen: list[str]) -> None:
        self._result = result
        self._screen = screen
        # A snapshot of the screen before each replacement, so the simulator can
        # emulate the *application's* own undo when the user presses Ctrl+Z (the
        # daemon only observes that chord; the app restores the text).
        self.undo_stack: list[list[str]] = []

    def can_type(self, char: str, layout: str) -> bool:
        # Mirrors the literal backends (``wtype``/``xdotool``), which can type
        # any character: the simulator must not refuse a fix for a backend
        # limitation it is not modelling.
        return bool(char)

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.undo_stack.append(list(self._screen))
        screen = "".join(self._screen)
        kept = screen[: len(screen) - backspace_count] if backspace_count else screen
        self._screen[:] = list(kept + new)
        self._result.replacements.append((backspace_count, new, layout))
        self._result.events.append(SimEvent("replace", f"-{backspace_count} +{new!r} @{layout}"))
        return True

    def app_undo(self) -> bool:
        """Emulate the application undoing its last edit (the daemon's rewrite)."""
        if not self.undo_stack:
            return False
        self._screen[:] = self.undo_stack.pop()
        self._result.events.append(SimEvent("app-undo", "restored the pre-fix text"))
        return True

    def describe(self) -> str:
        return "backend=simulate"


@dataclass
class _Event:
    """Minimal evdev-event stand-in (``type``/``code``/``value``)."""

    type: int
    code: int
    value: int


class _Driver:
    """Wires a real daemon to the in-memory fakes and records the run."""

    def __init__(self, config: Config, start_layout: str) -> None:
        self.result = SimulationResult(mode=config.mode, layout=start_layout)
        self.screen: list[str] = []
        self.switcher = _SimSwitcher(start_layout, list(config.layouts))
        self.injector = _SimInjector(self.result, self.screen)
        detector = LanguageDetector(
            converter=None,
            stop_words=config.stop_words,
            min_word_length=config.min_word_length,
            confidence_threshold=config.confidence_threshold,
        )
        self.daemon = KlyrshiftDaemon(
            config,
            detector=detector,
            # The daemon types these parameters as the concrete backend classes;
            # the simulator's fakes implement the same duck-typed surface, so
            # the casts are the price of keeping the daemon's public typing
            # strict for real callers.
            switcher=cast(LayoutSwitcher, self.switcher),
            injector=cast(TextInjector, self.injector),
        )

    # --- event plumbing ---------------------------------------------------
    def _send(self, events: list[tuple[int, int]], kind: str, detail: str) -> None:
        import evdev

        for code, value in events:
            self.daemon._handle_event(_Event(evdev.ecodes.EV_KEY, code, value))
        # Record one entry per logical step: the press (value 1), not its
        # matching release, so the event log reads like the scenario.
        if any(value == 1 for _code, value in events):
            self.result.events.append(SimEvent(kind, detail))

    def tap(self, key_name: str, kind: str, detail: str) -> None:
        self._send(self._codes(key_name, 1), kind, detail)
        self._send(self._codes(key_name, 0), kind, detail)

    def hold(self, key_name: str, value: int, kind: str, detail: str) -> None:
        self._send(self._codes(key_name, value), kind, detail)

    @staticmethod
    def _codes(key_name: str, value: int) -> list[tuple[int, int]]:
        import evdev

        code = getattr(evdev.ecodes, key_name, None)
        if code is None:
            raise ScenarioError(f"unknown key {key_name!r}")
        return [(int(code), value)]

    def type_text(self, text: str) -> None:
        for char in text:
            pair = _CHAR_TO_KEY.get(char)
            if pair is None:
                raise ScenarioError(f"no physical key produces {char!r}")
            key_name, needs_shift = pair
            if needs_shift:
                self.hold("KEY_LEFTSHIFT", 1, "type", char)
            self._append_typed(key_name, char)
            self.tap(key_name, "type", char)
            if needs_shift:
                self.hold("KEY_LEFTSHIFT", 0, "type", char)

    def _append_typed(self, key_name: str, fallback: str) -> None:
        """Append the glyph the active layout renders for ``key_name``.

        Appended *before* the key event so a boundary flush (which deletes and
        retypes the word) sees the character already on screen, exactly as the
        compositor would have shown it.
        """
        rendered = self._render(key_name, fallback)
        if rendered:
            self.screen.append(rendered)

    def _render(self, key_name: str, fallback: str) -> str:
        import evdev

        code = getattr(evdev.ecodes, key_name, None)
        if code is None:
            return fallback
        rendered = self.daemon._key_to_char(int(code))
        return rendered if rendered is not None else fallback

    def boundary(self, key_name: str, char: str, *, consume: bool) -> None:
        """Press a word-boundary key, mirroring how the daemon treats it.

        A Space is consumed and retyped by the replacement, so it is on screen
        *before* the flush. Enter/Tab are left in place after the corrected word,
        so they are appended afterwards (the daemon does not delete them).
        """
        if consume:
            self.screen.append(char)
            self.tap(key_name, "boundary", key_name)
        else:
            self.tap(key_name, "boundary", key_name)
            self.screen.append(char)

    def backspace(self) -> None:
        """Delete the last on-screen character, then press Backspace."""
        if self.screen:
            self.screen.pop()
        self.tap("KEY_BACKSPACE", "backspace", "backspace")

    def chord(self, modifiers: list[str], key: str) -> None:
        label = f"{'+'.join(modifiers)}+{key}"
        for mod in modifiers:
            self.hold(_MODIFIER_KEYS[mod][0], 1, "chord", label)
        if key in _MODIFIER_KEYS:
            self.tap(_MODIFIER_KEYS[key][0], "chord", label)
        else:
            self.tap(_key_name_for(key), "chord", label)
        for mod in reversed(modifiers):
            self.hold(_MODIFIER_KEYS[mod][0], 0, "chord", label)
        # The daemon never grabs the keyboard, so a bare Ctrl+Z also reaches the
        # application, which undoes its own last edit (the daemon's rewrite).
        # Emulate that here, or the screen would not match the daemon's model.
        if key.lower() == "z" and modifiers == ["ctrl"]:
            self.injector.app_undo()

    def wait(self) -> None:
        """Force the idle flush by backdating the last keystroke."""
        with self.daemon._lock:
            if self.daemon.buffer:
                self.daemon.last_key_time = time.time() - 3600.0
        self.daemon._flush_if_idle()


def _key_name_for(token: str) -> str:
    """Map a scenario key token to an evdev key name."""
    lowered = token.strip().lower()
    if lowered in _MODIFIER_KEYS:
        return _MODIFIER_KEYS[lowered][0]
    if lowered.startswith("key_"):
        return lowered.upper()
    if lowered in _NAMED_KEYS:
        return f"KEY_{lowered.upper()}"
    if len(lowered) == 1 and lowered.isalpha():
        return f"KEY_{lowered.upper()}"
    raise ScenarioError(f"unknown key {token!r}")


def _coerce(raw: str) -> Any:
    """Coerce a scenario value to bool/int/float/list/str.

    ``true``/``false`` are booleans, but a bare ``off``/``on`` is *not* coerced
    to a boolean: those are also valid values for the mode fields
    (``typo_mode = "off"``), so a string field keeps the word.
    """
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("'\"") for part in inner.split(",")]
    lowered = raw.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _apply_config(daemon: KlyrshiftDaemon, assignments: str) -> None:
    """Apply ``key=value; key=value`` overrides to the daemon's config."""
    for chunk in assignments.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ScenarioError(f"config override must be key=value, got {chunk!r}")
        key, raw = (part.strip() for part in chunk.split("=", 1))
        if not hasattr(daemon.config, key):
            raise ScenarioError(f"unknown config field {key!r}")
        setattr(daemon.config, key, _coerce(raw))
    daemon.config.validate()


def _run_step(driver: _Driver, step: str) -> None:
    """Execute one scenario step."""
    head, _, rest = step.partition(" ")
    command = head.lower()
    rest = rest.strip()

    if command == "type":
        driver.type_text(rest)
    elif command == "config":
        _apply_config(driver.daemon, rest)
    elif command == "layout":
        if not rest:
            raise ScenarioError("layout needs a name")
        driver.switcher.switch_to(rest.lower())
    elif command == "mode":
        driver.daemon.config.mode = rest.lower()
        driver.daemon.config.validate()
    elif command in ("wait", "idle"):
        driver.wait()
    elif command in ("key", "press"):
        driver.tap(_key_name_for(rest), "key", rest)
    elif command == "space":
        driver.boundary("KEY_SPACE", " ", consume=driver.daemon.config.on_space)
    elif command in ("enter", "tab"):
        key = f"KEY_{command.upper()}"
        enabled = (
            driver.daemon.config.on_enter if command == "enter" else driver.daemon.config.on_tab
        )
        driver.boundary(key, "\n" if command == "enter" else "\t", consume=not enabled)
    elif command == "backspace":
        driver.backspace()
    elif command in ("esc", "escape"):
        driver.tap("KEY_ESC", command, command)
    elif command in ("dblshift", "dblctrl", "dblalt"):
        down = _MODIFIER_KEYS[command[3:]][0]
        driver.tap(down, command, command)
        driver.tap(down, command, command)
    elif command in _MODIFIER_KEYS and rest:
        # Space-separated chord: ``ctrl z``, ``shift f12``.
        driver.chord([command], rest)
    elif "+" in command:
        parts = command.split("+")
        key, modifiers = parts[-1], parts[:-1]
        for mod in modifiers:
            if mod not in _MODIFIER_KEYS:
                raise ScenarioError(f"unknown modifier {mod!r} in {step!r}")
        driver.chord(modifiers, key)
    else:
        driver.tap(_key_name_for(command), "key", command)


def run_scenario(
    scenario: str,
    *,
    config: Config | None = None,
    start_layout: str = "us",
) -> SimulationResult:
    """Run ``scenario`` through a real daemon wired to in-memory fakes.

    Args:
        scenario: A comma-separated list of steps (see the module docstring).
        config: Optional base configuration; ``mode``/``config`` steps override
            it. When omitted a config with an empty stop-word list is used so a
            scenario is self-contained.
        start_layout: The layout active before the first step.

    Returns:
        A :class:`SimulationResult` with the screen text, the injections and the
        learning state.
    """
    driver = _Driver(config if config is not None else Config(stop_words=[]), start_layout)
    for raw_step in scenario.split(","):
        step = raw_step.strip()
        if step:
            _run_step(driver, step)

    result = driver.result
    result.screen = "".join(driver.screen)
    result.mode = driver.daemon.config.mode
    result.layout = driver.switcher.current
    result.suppressed = sorted(driver.daemon.learning.suppressed_words())
    result.learned = driver.daemon.learning.learned_words()
    stats = driver.daemon.learning.stats
    result.stats = {
        "observed": stats.observed,
        "kept": stats.kept,
        "corrected": stats.corrected,
        "rejected": stats.rejected,
        "promoted": stats.promoted,
    }
    return result


__all__ = [
    "ScenarioError",
    "SimEvent",
    "SimulationResult",
    "run_scenario",
]


def _main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m klyrshift.simulate``."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="python -m klyrshift.simulate",
        description="Run a keystroke scenario through the real daemon headlessly.",
    )
    parser.add_argument("scenario", help="comma-separated steps, e.g. 'type ghbdtn, space'")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--layout", default="us", help="active layout before the first step")
    args = parser.parse_args(argv)

    try:
        result = run_scenario(args.scenario, start_layout=args.layout)
    except ScenarioError as exc:
        print(f"scenario error: {exc}")
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"screen: {result.screen!r}")
        print(f"mode: {result.mode}  layout: {result.layout}")
        for n, text, layout in result.replacements:
            print(f"  replace -{n} +{text!r} @{layout}")
        if result.suppressed:
            print(f"suppressed: {', '.join(result.suppressed)}")
        if result.learned:
            print(f"learned: {', '.join(result.learned)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
