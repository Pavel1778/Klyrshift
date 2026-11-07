"""Reporting: a JSON document and a human-readable Markdown summary.

Both are built from a :class:`~klyrshift.qa.runner.RunSummary`, so they report
only *measured* data: how many scenarios ran, how many passed, the failures, the
new bugs, the repeats and the time spent. No coverage percentage is invented --
the report lists the functional areas the corpus actually exercised, computed
from the categories of the scenarios that ran.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final


@dataclass
class RunSummary:
    """The measured outcome of one QA run.

    Attributes:
        total: Scenarios attempted.
        passed: Scenarios with no violation.
        failed: Scenarios with at least one violation.
        harness_errors: Scenarios the simulator rejected (a broken scenario).
        skipped: Scenarios filtered out before running.
        violations: ``invariant name -> count`` across the run.
        new_bugs: Ids of confirmed bugs not seen before this run.
        repeat_bugs: Ids of confirmed bugs already in the store.
        minimal: ``id -> minimal step list`` for the confirmed bugs.
        categories: The functional areas the run touched.
        duration_s: Wall-clock seconds the run took.
        failures: Per-scenario failure detail (from the analyzer).
    """

    total: int = 0
    passed: int = 0
    failed: int = 0
    harness_errors: int = 0
    skipped: int = 0
    violations: dict[str, int] = field(default_factory=dict)
    new_bugs: list[str] = field(default_factory=list)
    repeat_bugs: list[str] = field(default_factory=list)
    minimal: dict[str, list[str]] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "harness_errors": self.harness_errors,
            "skipped": self.skipped,
            "violations": dict(sorted(self.violations.items())),
            "new_bugs": list(self.new_bugs),
            "repeat_bugs": list(self.repeat_bugs),
            "minimal": {k: list(v) for k, v in sorted(self.minimal.items())},
            "categories": list(self.categories),
            "duration_s": round(self.duration_s, 3),
            "failures": list(self.failures),
        }


def to_json(summary: RunSummary) -> str:
    """Return the summary as pretty-printed JSON."""
    return json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def to_markdown(summary: RunSummary) -> str:
    """Return the summary as a Markdown report (measured data only)."""
    lines: list[str] = []
    lines.append("# Klyrshift QA report")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Scenarios run | {summary.total} |")
    lines.append(f"| Passed | {summary.passed} |")
    lines.append(f"| Failed | {summary.failed} |")
    lines.append(f"| Harness errors | {summary.harness_errors} |")
    lines.append(f"| Skipped | {summary.skipped} |")
    lines.append(f"| New bugs | {len(summary.new_bugs)} |")
    lines.append(f"| Repeat bugs | {len(summary.repeat_bugs)} |")
    lines.append(f"| Duration (s) | {summary.duration_s:.2f} |")
    lines.append("")
    lines.append(
        "Areas exercised: " + (", ".join(summary.categories) if summary.categories else "none")
    )
    lines.append("")
    if summary.violations:
        lines.append("## Invariant violations")
        lines.append("")
        lines.append("| Invariant | Count |")
        lines.append("|---|---|")
        for name, count in sorted(summary.violations.items()):
            lines.append(f"| `{name}` | {count} |")
        lines.append("")
    if summary.new_bugs:
        lines.append("## New bugs")
        lines.append("")
        for bug_id in summary.new_bugs:
            lines.append(f"- `{bug_id}`")
        lines.append("")
    if summary.repeat_bugs:
        lines.append("## Repeat bugs")
        lines.append("")
        for bug_id in summary.repeat_bugs:
            lines.append(f"- `{bug_id}`")
        lines.append("")
    if summary.failures:
        lines.append("## Failures")
        lines.append("")
        for failure in summary.failures:
            scenario_id = failure.get("scenario", "?")
            classification = failure.get("classification", "?")
            lines.append(f"### `{scenario_id}` — {classification}")
            lines.append("")
            lines.append(f"- Invariants: {', '.join(failure.get('invariants', [])) or 'none'}")
            lines.append(f"- Expected: `{failure.get('expected', '')}`")
            lines.append(f"- Actual: `{failure.get('actual', '')}`")
            minimal = failure.get("minimal_steps", [])
            if minimal:
                lines.append(f"- Minimal: `{', '.join(minimal)}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_reports(summary: RunSummary, directory: Path) -> tuple[Path, Path]:
    """Write ``qa-report.json`` and ``qa-report.md`` under ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "qa-report.json"
    md_path = directory / "qa-report.md"
    json_path.write_text(to_json(summary), encoding="utf-8")
    md_path.write_text(to_markdown(summary), encoding="utf-8")
    return json_path, md_path


__all__: Final[list[str]] = [
    "RunSummary",
    "to_json",
    "to_markdown",
    "write_reports",
]
