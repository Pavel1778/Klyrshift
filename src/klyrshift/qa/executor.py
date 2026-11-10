"""A safe executor: run a scenario through ``klyrshift.simulate``.

The executor never runs a command a scenario (or an LLM) proposes. A scenario
is data; its ``steps`` are handed to the simulator's own parser, which accepts
only the fixed step DSL. The only other thing the executor does is apply the
scenario's ``config`` mapping through the simulator's ``config`` step, which
itself validates every field against :class:`~klyrshift.config.Config`.

The executor produces an :class:`Execution` with the raw
:class:`~klyrshift.simulate.SimulationResult`, the invariant violations and the
outcome. It also classifies a *harness* error (a step the simulator rejects, or
an exception in the daemon) separately from a genuine assertion failure, so a
broken scenario is never reported as a product bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ..simulate import ScenarioError, SimulationResult, run_scenario
from . import invariants as inv
from .invariants import InvariantContext, InvariantViolation
from .scenario import Scenario

# The outcome of one run.
OUTCOME_PASSED: Final[str] = "passed"
OUTCOME_FAILED: Final[str] = "failed"
OUTCOME_HARNESS_ERROR: Final[str] = "harness-error"


@dataclass
class Execution:
    """The result of running one scenario once.

    Attributes:
        scenario: The scenario that ran.
        outcome: ``passed`` / ``failed`` / ``harness-error``.
        result: The simulator result, or ``None`` when the run never completed.
        violations: The invariant violations found (empty on a pass).
        error: A message when the run failed in the harness, not the product.
        steps: The scenario steps, in order (for the report and the minimiser).
    """

    scenario: Scenario
    outcome: str
    result: SimulationResult | None = None
    violations: list[InvariantViolation] = field(default_factory=list)
    error: str = ""
    steps: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return ``True`` only for a clean pass."""
        return self.outcome == OUTCOME_PASSED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "scenario": self.scenario.id,
            "outcome": self.outcome,
            "screen": self.result.screen if self.result else None,
            "replacements": [list(r) for r in (self.result.replacements if self.result else [])],
            "violations": [
                {"name": v.name, "reason": v.reason, "witness": v.witness} for v in self.violations
            ],
            "error": self.error,
            "steps": list(self.steps),
        }


def _config_steps(scenario: Scenario) -> list[str]:
    """Turn a scenario's config mapping into one simulator ``config`` step."""
    if not scenario.config:
        return []
    assignments = "; ".join(
        f"{key}={_render_value(value)}" for key, value in scenario.config.items()
    )
    return [f"config {assignments}"]


def _render_value(value: Any) -> str:
    """Render a config value the way the simulator's ``config`` step parses it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
    return str(value)


def build_script(scenario: Scenario) -> str:
    """Return the full simulator script for ``scenario``.

    The script is the config step (if any), the steps, and nothing else. It is
    a plain string fed to the simulator's parser, so no code is ever evaluated.
    """
    parts = _config_steps(scenario) + list(scenario.steps)
    return ", ".join(parts)


def execute(scenario: Scenario, *, start_layout: str | None = None) -> Execution:
    """Run ``scenario`` once and check its invariants.

    Args:
        scenario: The scenario to run.
        start_layout: Overrides the scenario's ``layout`` when given (the
            minimiser uses it to replay a sub-scenario from the same start).

    Returns:
        An :class:`Execution`. A step the simulator rejects, or an exception in
        the daemon, yields ``OUTCOME_HARNESS_ERROR`` rather than a false bug.
    """
    layout = start_layout if start_layout is not None else scenario.layout
    script = build_script(scenario)
    try:
        result = run_scenario(script, start_layout=layout)
    except ScenarioError as exc:
        return Execution(
            scenario=scenario,
            outcome=OUTCOME_HARNESS_ERROR,
            error=f"scenario rejected by the simulator: {exc}",
            steps=list(scenario.steps),
        )
    except Exception as exc:  # the daemon must survive any input; a crash is a harness error
        return Execution(
            scenario=scenario,
            outcome=OUTCOME_HARNESS_ERROR,
            error=f"unexpected error while running the scenario: {type(exc).__name__}: {exc}",
            steps=list(scenario.steps),
        )

    context = InvariantContext(
        scenario=scenario,
        screen=result.screen,
        replacements=list(result.replacements),
        mode=result.mode,
        layout=result.layout,
        suppressed=list(result.suppressed),
        typed_separators=inv.typed_separators(scenario.steps),
        typed_punctuation=inv.typed_punctuation(scenario.steps),
        typed_chars=inv.typed_chars(scenario.steps),
        final_separators=result.screen.count(" ")
        + result.screen.count("\n")
        + result.screen.count("\t"),
        undone_separators=result.undone_separators,
        steps=list(scenario.steps),
    )
    violations = inv.run_invariants(context)
    outcome = OUTCOME_FAILED if violations else OUTCOME_PASSED
    return Execution(
        scenario=scenario,
        outcome=outcome,
        result=result,
        violations=violations,
        steps=list(scenario.steps),
    )


__all__: Final[list[str]] = [
    "OUTCOME_FAILED",
    "OUTCOME_HARNESS_ERROR",
    "OUTCOME_PASSED",
    "Execution",
    "build_script",
    "execute",
]
