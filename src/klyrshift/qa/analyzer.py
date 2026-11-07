"""Failure analysis: classify a failure and minimise its scenario.

Two jobs, both independent of the invariant engine:

* **classify** -- decide whether a failure is a confirmed bug, an unstable
  (flaky) result, a broken test harness, or an unconfirmed suspicion. The
  classification is based on *repetition*: a result that does not reproduce on a
  second run is flaky, not a bug; a scenario the simulator rejects is a harness
  error; a violation whose expectation the scenario itself did not assert is a
  suspicion.
* **minimise** -- shrink a failing scenario to the shortest step list that still
  fails, by delta-debugging: drop steps, then shorten ``type`` steps. Each
  candidate is re-run; only a candidate that fails *the same way* is kept, so
  the minimiser never "fixes" a bug by changing it.

Minimisation replays the scenario through the executor, so it obeys the same
safe-DSL rule: no step is ever executed as code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from .executor import OUTCOME_HARNESS_ERROR, Execution, execute
from .scenario import Scenario

# The failure classes.
CONFIRMED_BUG: Final[str] = "confirmed-bug"
FLAKY: Final[str] = "flaky"
HARNESS_ERROR: Final[str] = "harness-error"
SUSPICION: Final[str] = "suspicion"

# The invariants whose failure is a *structural* statement about the screen
# (a character or a word was lost), as opposed to an expectation the scenario
# author wrote by hand. A structural failure is a confirmed bug even on the
# first run; a mismatch of a hand-written ``expect`` is only a suspicion until
# it reproduces, because the expectation itself may be wrong.
_STRUCTURAL: Final[frozenset[str]] = frozenset(
    {
        "no-lost-characters",
        "space-preserved",
        "enter-preserved",
        "tab-preserved",
        "punctuation-preserved",
        "manual-mode-silent",
        "no-mixed-script-replacement",
        "layout-switched",
        "no-over-deletion",
    }
)


@dataclass
class FailureReport:
    """A classified, minimised failure.

    Attributes:
        scenario: The scenario that failed (the original, full one).
        classification: One of the four classes above.
        invariants: The violated invariant names.
        expected: The scenario's declared expectation, if any.
        actual: The screen the run produced.
        minimal: The shortest steps that still fail, when minimisation ran.
        minimal_screen: The screen the minimal scenario produces.
        detail: A human-readable explanation.
    """

    scenario: Scenario
    classification: str
    invariants: list[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    minimal: list[str] = field(default_factory=list)
    minimal_screen: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "scenario": self.scenario.id,
            "classification": self.classification,
            "invariants": list(self.invariants),
            "expected": self.expected,
            "actual": self.actual,
            "minimal_steps": list(self.minimal),
            "minimal_screen": self.minimal_screen,
            "detail": self.detail,
        }


def classify(execution: Execution) -> str:
    """Return the failure class for a non-passing execution."""
    if execution.outcome == OUTCOME_HARNESS_ERROR:
        return HARNESS_ERROR
    names = {v.name for v in execution.violations}
    if names & _STRUCTURAL:
        return CONFIRMED_BUG
    # Only a hand-written expectation failed; it may itself be wrong.
    return SUSPICION


def reproduces(scenario: Scenario, *, runs: int = 2) -> bool:
    """Return whether the scenario fails the same way on every one of ``runs``."""
    if runs < 2:
        runs = 2
    first: str | None = None
    for _ in range(runs):
        execution = execute(scenario)
        if execution.passed:
            return False
        signature = _signature(execution)
        if first is None:
            first = signature
        elif signature != first:
            return False
    return True


def _signature(execution: Execution) -> str:
    """A stable signature of *how* a run failed (invariant names + screen)."""
    names = ",".join(sorted(v.name for v in execution.violations))
    screen = execution.result.screen if execution.result else ""
    return f"{execution.outcome}|{names}|{screen}"


def analyse(scenario: Scenario, execution: Execution, *, minimise: bool = True) -> FailureReport:
    """Classify ``execution`` and (optionally) minimise the scenario."""
    classification = classify(execution)
    if classification in (CONFIRMED_BUG, SUSPICION) and not reproduces(scenario):
        classification = FLAKY

    report = FailureReport(
        scenario=scenario,
        classification=classification,
        invariants=sorted({v.name for v in execution.violations}),
        expected=str(scenario.expect.get("screen", "")),
        actual=execution.result.screen if execution.result else "",
        detail=execution.error,
    )
    if minimise and classification == CONFIRMED_BUG:
        minimal, minimal_screen = minimise_scenario(scenario)
        report.minimal = minimal
        report.minimal_screen = minimal_screen
    else:
        report.minimal = list(scenario.steps)
        report.minimal_screen = report.actual
    return report


def minimise_scenario(scenario: Scenario) -> tuple[list[str], str]:
    """Shrink ``scenario`` to the shortest step list that fails the same way.

    Delta-debugging: try removing one step at a time (and trimming a ``type``
    step), keeping any change that preserves the failure signature. The
    reference signature is taken from the original run, so the minimiser never
    turns one failure into a different one.

    Returns:
        ``(steps, screen)`` for the minimal failing scenario.
    """
    reference = execute(scenario)
    if reference.passed:
        return list(scenario.steps), reference.result.screen if reference.result else ""
    target = _signature(reference)

    current = list(scenario.steps)
    changed = True
    while changed:
        changed = False
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if not candidate:
                continue
            if _still_fails(scenario, candidate, target):
                current = candidate
                changed = True
                break
        if changed:
            continue
        # No step can be dropped: try shortening a ``type`` step.
        for index, step in enumerate(current):
            if not step.startswith("type ") or len(step) <= len("type x"):
                continue
            text = step[len("type ") :]
            for shorter in (text[:-1], text[1:]):
                if not shorter:
                    continue
                candidate = list(current)
                candidate[index] = f"type {shorter}"
                if _still_fails(scenario, candidate, target):
                    current = candidate
                    changed = True
                    break
            if changed:
                break

    minimal = Scenario(
        id=scenario.id + "#minimal",
        steps=current,
        category=scenario.category,
        difficulty=scenario.difficulty,
        config=dict(scenario.config),
        layout=scenario.layout,
        expect=dict(scenario.expect),
        invariants=list(scenario.invariants),
        origin="regression",
    )
    final = execute(minimal)
    screen = final.result.screen if final.result else ""
    return current, screen


def _still_fails(scenario: Scenario, steps: list[str], target: str) -> bool:
    """Return whether ``steps`` still fail with the reference signature."""
    candidate = Scenario(
        id=scenario.id + "#candidate",
        steps=steps,
        category=scenario.category,
        difficulty=scenario.difficulty,
        config=dict(scenario.config),
        layout=scenario.layout,
        expect=dict(scenario.expect),
        invariants=list(scenario.invariants),
        origin="regression",
    )
    return _signature(execute(candidate)) == target


__all__: Final[list[str]] = [
    "CONFIRMED_BUG",
    "FLAKY",
    "HARNESS_ERROR",
    "SUSPICION",
    "FailureReport",
    "analyse",
    "classify",
    "minimise_scenario",
    "reproduces",
]
