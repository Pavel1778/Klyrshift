"""Independent correctness checks over a simulation result.

An invariant is a *pure function* of the scenario, the typed input and the
:class:`~klyrshift.simulate.SimulationResult`. It never looks at the daemon's
internals and never mutates anything, so a failure it reports is a statement
about the observable screen, not about an implementation detail.

The checks are deliberately independent of the simulator's own assertions: the
simulator says "here is the screen", an invariant says "that screen is wrong,
and here is why". A check returns a *witness* -- the exact text that shows the
violation -- so a failure report can point at it.

The typed counts in :class:`InvariantContext` are computed from the *steps*, not
from the simulator, so they are an independent oracle: the simulator drives the
daemon, the counts describe what the user actually pressed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from ..converter import LayoutConverter
from .scenario import Scenario

_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_LATIN = re.compile(r"[A-Za-z]")

# The named punctuation steps and the character each produces.
_PUNCT_STEPS: Final[dict[str, str]] = {"dot": ".", "comma": ","}


@dataclass
class InvariantContext:
    """Everything an invariant may look at, and nothing else.

    Attributes:
        scenario: The scenario that ran.
        screen: The final on-screen text.
        replacements: ``(backspace_count, new_text, layout)`` per injection.
        mode: The working mode at the end of the run.
        layout: The active layout at the end of the run.
        suppressed: Words the user rejected with ``Ctrl+Z``.
        typed_separators: How many Space/Enter/Tab characters the user pressed.
        typed_punctuation: How many ``.``/``,`` characters the user pressed.
        typed_chars: How many printable characters the user pressed.
        final_separators: How many separators the screen shows.
        steps: The scenario steps, in order.
    """

    scenario: Scenario
    screen: str
    replacements: list[tuple[int, str, str]]
    mode: str
    layout: str
    suppressed: list[str]
    typed_separators: int
    typed_punctuation: int
    typed_chars: int
    final_separators: int
    steps: list[str]


@dataclass
class InvariantViolation:
    """One failed invariant: which one, why, and the witness text."""

    name: str
    reason: str
    witness: str = ""


Checker = Callable[[InvariantContext], InvariantViolation | None]

_REGISTRY: dict[str, Checker] = {}


def invariant(name: str) -> Callable[[Checker], Checker]:
    """Register ``check`` under ``name``."""

    def register(check: Checker) -> Checker:
        if name in _REGISTRY:
            raise ValueError(f"invariant {name!r} is already registered")
        _REGISTRY[name] = check
        return check

    return register


def registered() -> list[str]:
    """Return every registered invariant name, sorted."""
    return sorted(_REGISTRY)


def check(name: str, context: InvariantContext) -> InvariantViolation | None:
    """Run one invariant by name; raise ``KeyError`` for an unknown name."""
    return _REGISTRY[name](context)


def run_invariants(context: InvariantContext) -> list[InvariantViolation]:
    """Run every invariant the scenario names, in order, and collect failures."""
    violations: list[InvariantViolation] = []
    for name in context.scenario.invariants:
        violation = check(name, context)
        if violation is not None:
            violations.append(violation)
    return violations


# --------------------------------------------------------------------------
# Invariants. Each is a pure function of the context.
# --------------------------------------------------------------------------


@invariant("no-lost-characters")
def _no_lost_characters(context: InvariantContext) -> InvariantViolation | None:
    """No separator the user pressed may disappear from the screen.

    A fix consumes and retypes exactly the boundary it triggered on, so the
    number of Space/Enter/Tab characters on screen never drops below the number
    pressed. A lost separator is the signature of a deletion/insertion count
    that is off by one.
    """
    if context.final_separators < context.typed_separators:
        return InvariantViolation(
            "no-lost-characters",
            f"pressed {context.typed_separators} separator(s), screen shows "
            f"{context.final_separators}",
            witness=context.screen,
        )
    return None


@invariant("space-preserved")
def _space_preserved(context: InvariantContext) -> InvariantViolation | None:
    """A Space survives a fix triggered by that Space."""
    if "space" not in context.steps:
        return None
    pressed = count_spaces(context.steps)
    shown = context.screen.count(" ")
    if shown < pressed:
        return InvariantViolation(
            "space-preserved",
            f"pressed {pressed} space(s), screen shows {shown}",
            witness=context.screen,
        )
    return None


@invariant("enter-preserved")
def _enter_preserved(context: InvariantContext) -> InvariantViolation | None:
    """An Enter survives a fix triggered by that Enter."""
    if "enter" not in context.steps:
        return None
    pressed = context.steps.count("enter")
    shown = context.screen.count("\n")
    if shown < pressed:
        return InvariantViolation(
            "enter-preserved",
            f"pressed {pressed} newline(s), screen shows {shown}",
            witness=context.screen,
        )
    return None


@invariant("tab-preserved")
def _tab_preserved(context: InvariantContext) -> InvariantViolation | None:
    """A Tab survives a fix triggered by that Tab."""
    if "tab" not in context.steps:
        return None
    pressed = context.steps.count("tab")
    shown = context.screen.count("\t")
    if shown < pressed:
        return InvariantViolation(
            "tab-preserved",
            f"pressed {pressed} tab(s), screen shows {shown}",
            witness=context.screen,
        )
    return None


@invariant("punctuation-preserved")
def _punctuation_preserved(context: InvariantContext) -> InvariantViolation | None:
    """A punctuation character is not dropped from the screen.

    The punctuation trigger is opt-in; when it is off the character is part of
    the buffer and may be converted as a whole, but a *drop* is always a defect.
    """
    shown = sum(context.screen.count(ch) for ch in ".,")
    if shown < context.typed_punctuation:
        return InvariantViolation(
            "punctuation-preserved",
            f"pressed {context.typed_punctuation} punctuation mark(s), screen shows {shown}",
            witness=context.screen,
        )
    return None


@invariant("manual-mode-silent")
def _manual_mode_silent(context: InvariantContext) -> InvariantViolation | None:
    """In ``manual`` mode nothing is rewritten without an explicit hotkey."""
    if context.mode != "manual":
        return None
    if has_explicit_hotkey(context.steps):
        return None
    if context.replacements:
        return InvariantViolation(
            "manual-mode-silent",
            f"manual mode applied {len(context.replacements)} fix(es) with no hotkey",
            witness=context.screen,
        )
    return None


@invariant("ctrl-z-suppressed")
def _ctrl_z_suppressed(context: InvariantContext) -> InvariantViolation | None:
    """A ``Ctrl+Z`` rejection is recorded.

    The check is structural: after the chord at least one word must be recorded
    as rejected, so the very next flush does not fix it again.
    """
    if "ctrl z" not in context.steps:
        return None
    if not context.suppressed:
        return InvariantViolation(
            "ctrl-z-suppressed",
            "Ctrl+Z was pressed but no word was recorded as rejected",
            witness=context.screen,
        )
    return None


@invariant("no-mixed-script-replacement")
def _no_mixed_script_replacement(context: InvariantContext) -> InvariantViolation | None:
    """No replacement *output* mixes Latin and Cyrillic inside one token.

    The detector never converts a mixed-script token as a unit, so a fix must
    never emit one. This looks at each replacement's ``new_text``, not the whole
    screen: two adjacent words from different scripts typed with no separator
    (``world`` then ``ljv``) are legal input, not a corrupted token.
    """
    for _backspaces, new_text, _layout in context.replacements:
        for token in re.split(r"\s+", new_text):
            if _LATIN.search(token) and _CYRILLIC.search(token):
                return InvariantViolation(
                    "no-mixed-script-replacement",
                    f"a fix emitted the mixed-script token {token!r}",
                    witness=token,
                )
    return None


@invariant("layout-switched")
def _layout_switched(context: InvariantContext) -> InvariantViolation | None:
    """When a layout fix ran and the user did not switch back, the layout is the target.

    The daemon switches to the fix's target layout. A later ``layout`` step by the
    user is a deliberate change, so the check only applies when the scenario
    contains no ``layout`` step.
    """
    if not context.replacements:
        return None
    if any(step.startswith("layout ") for step in context.steps):
        return None
    last_layout = context.replacements[-1][2]
    if context.layout != last_layout:
        return InvariantViolation(
            "layout-switched",
            f"last fix targeted {last_layout!r} but the active layout is {context.layout!r}",
            witness=context.layout,
        )
    return None


@invariant("no-over-deletion")
def _no_over_deletion(context: InvariantContext) -> InvariantViolation | None:
    """A replacement never deletes more characters than were pressed."""
    total_deleted = sum(backspaces for backspaces, _text, _layout in context.replacements)
    total_inserted = sum(len(text) for _n, text, _layout in context.replacements)
    if total_deleted - total_inserted > context.typed_chars:
        return InvariantViolation(
            "no-over-deletion",
            f"replacements deleted {total_deleted} and inserted {total_inserted} "
            f"with only {context.typed_chars} character(s) pressed",
            witness=context.screen,
        )
    return None


@invariant("screen-matches-expectation")
def _screen_matches_expectation(context: InvariantContext) -> InvariantViolation | None:
    """The screen equals the scenario's ``expect.screen`` when one is given."""
    expected = context.scenario.expect.get("screen")
    if expected is None:
        return None
    if context.screen != expected:
        return InvariantViolation(
            "screen-matches-expectation",
            f"expected {expected!r}, got {context.screen!r}",
            witness=context.screen,
        )
    return None


@invariant("layout-is-known")
def _layout_is_known(context: InvariantContext) -> InvariantViolation | None:
    """The final layout is one the converter knows."""
    if context.layout not in LayoutConverter()._forward:
        return InvariantViolation(
            "layout-is-known",
            f"final layout {context.layout!r} is not a known layout",
            witness=context.layout,
        )
    return None


def has_explicit_hotkey(steps: list[str]) -> bool:
    """Return whether the user issued an explicit fix command.

    A double tap, or any chord other than the observed ``Ctrl+Z``, is the user
    asking for a fix, so the manual-mode invariant does not apply.
    """
    for step in steps:
        if step in {"dblshift", "dblctrl", "dblalt"}:
            return True
        if "+" in step and step != "ctrl z" and not step.startswith("ctrl z"):
            return True
    return False


def count_spaces(steps: list[str]) -> int:
    """Count the Space characters the steps press (independent oracle)."""
    total = 0
    for step in steps:
        if step == "space":
            total += 1
        elif step.startswith("type "):
            total += step[len("type ") :].count(" ")
    return total


def typed_separators(steps: list[str]) -> int:
    """Count the Space/Enter/Tab characters the steps press."""
    total = 0
    for step in steps:
        if step in {"space", "enter", "tab"}:
            total += 1
        elif step.startswith("type "):
            total += step[len("type ") :].count(" ")
    return total


def typed_punctuation(steps: list[str]) -> int:
    """Count the ``.``/``,`` characters the steps press (independent oracle)."""
    total = 0
    for step in steps:
        if step in _PUNCT_STEPS:
            total += 1
        elif step.startswith("type "):
            text = step[len("type ") :]
            total += sum(text.count(ch) for ch in ".,")
    return total


def typed_chars(steps: list[str]) -> int:
    """Count the printable characters the steps press."""
    total = 0
    for step in steps:
        if step in {"space", "enter", "tab"} or step in _PUNCT_STEPS:
            total += 1
        elif step.startswith("type "):
            total += len(step[len("type ") :])
    return total


__all__: Final[list[str]] = [
    "Checker",
    "InvariantContext",
    "InvariantViolation",
    "check",
    "count_spaces",
    "has_explicit_hotkey",
    "invariant",
    "registered",
    "run_invariants",
    "typed_chars",
    "typed_punctuation",
    "typed_separators",
]
