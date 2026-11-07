"""Orchestration: the entry point that ties the pieces together.

:func:`run` executes a scenario corpus, analyses the failures, records the
confirmed bugs and builds a report. It is the single place that knows the order:
execute -> analyse -> record -> summarise. Everything it calls is pure enough to
be tested alone.

A run is deterministic by default: the same corpus and the same seed produce the
same report, with no network and no API key. LLM-assisted generation is a
separate, optional input to :func:`~klyrshift.qa.generator.generate`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .analyzer import CONFIRMED_BUG, analyse
from .executor import OUTCOME_HARNESS_ERROR, execute
from .generator import GeneratorConfig, LLMProvider, generate
from .report import RunSummary
from .scenario import Scenario
from .store import RegressionStore


@dataclass
class RunConfig:
    """Knobs for a QA run.

    Attributes:
        seed: RNG seed for generated scenarios.
        generated: How many generated scenarios to add to the corpus.
        focus: Restrict generation to these categories.
        changed_files: Source files a change touched (focuses generation).
        minimise: Whether to minimise a confirmed failure.
        record: Whether to write confirmed bugs to the regression store.
        store_path: Where the regression store lives.
        repeats: How many times a failing scenario must reproduce to count as a
            confirmed bug (rather than flaky). Two is the minimum.
    """

    seed: int = 0
    generated: int = 0
    focus: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    minimise: bool = True
    record: bool = True
    store_path: Path | None = None
    repeats: int = 2


def build_corpus(
    base: Sequence[Scenario],
    config: RunConfig,
    *,
    llm: LLMProvider | None = None,
) -> list[Scenario]:
    """Return the corpus to run: ``base`` plus any generated scenarios."""
    corpus = list(base)
    if config.generated > 0 or llm is not None:
        report = generate(
            GeneratorConfig(
                seed=config.seed,
                count=max(config.generated, 0),
                focus=list(config.focus),
                changed_files=list(config.changed_files),
            ),
            llm=llm,
            known=corpus,
        )
        corpus.extend(report.scenarios)
    return corpus


def run(
    scenarios: Sequence[Scenario],
    config: RunConfig | None = None,
    *,
    store: RegressionStore | None = None,
) -> RunSummary:
    """Run ``scenarios``, analyse failures, record bugs and summarise.

    Args:
        scenarios: The corpus to run.
        config: The run knobs.
        store: A regression store to record into; a default one is created when
            ``config.record`` is set and none is given.

    Returns:
        A :class:`RunSummary` with the measured outcome.
    """
    cfg = config or RunConfig()
    regression = store
    if regression is None and cfg.record:
        regression = RegressionStore(cfg.store_path)

    known_ids = {entry.scenario.id for entry in regression.sorted()} if regression else set()

    summary = RunSummary()
    started = time.monotonic()
    for scenario in scenarios:
        summary.total += 1
        execution = execute(scenario)
        if execution.outcome == OUTCOME_HARNESS_ERROR:
            summary.harness_errors += 1
            summary.failures.append(
                {
                    "scenario": scenario.id,
                    "classification": "harness-error",
                    "invariants": [],
                    "expected": str(scenario.expect.get("screen", "")),
                    "actual": "",
                    "minimal_steps": list(scenario.steps),
                    "detail": execution.error,
                }
            )
            continue
        if execution.passed:
            summary.passed += 1
            continue

        summary.failed += 1
        for violation in execution.violations:
            summary.violations[violation.name] = summary.violations.get(violation.name, 0) + 1

        failure = analyse(scenario, execution, minimise=cfg.minimise)
        summary.failures.append(failure.to_dict())
        if failure.classification != CONFIRMED_BUG:
            continue
        if failure.scenario.id in known_ids:
            summary.repeat_bugs.append(failure.scenario.id)
        else:
            summary.new_bugs.append(failure.scenario.id)
        summary.minimal[failure.scenario.id] = list(failure.minimal)
        if regression is not None:
            regression.record(failure, found_at=time.strftime("%Y-%m-%d"))

    summary.duration_s = time.monotonic() - started
    summary.categories = sorted({scenario.category for scenario in scenarios})
    return summary


def rerun_regressions(store: RegressionStore, config: RunConfig | None = None) -> RunSummary:
    """Re-run every open regression entry to see whether it still fails.

    An entry that now passes is marked fixed; one that still fails stays open.
    """
    cfg = config or RunConfig(record=False)
    open_entries = store.open_entries()
    summary = RunSummary(total=len(open_entries))
    for entry in open_entries:
        execution = execute(entry.scenario)
        if execution.passed:
            store.mark_fixed(entry.scenario.id)
            summary.passed += 1
        else:
            summary.failed += 1
            for violation in execution.violations:
                summary.violations[violation.name] = summary.violations.get(violation.name, 0) + 1
            summary.repeat_bugs.append(entry.scenario.id)
        summary.categories = sorted({e.scenario.category for e in open_entries})
    del cfg  # reserved for future per-run knobs
    return summary


__all__: Final[list[str]] = [
    "RunConfig",
    "build_corpus",
    "rerun_regressions",
    "run",
]
