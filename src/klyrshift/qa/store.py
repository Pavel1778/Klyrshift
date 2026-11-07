"""The regression store: every confirmed failure, with its reproduction.

A store entry records one confirmed bug: the original scenario, the minimal
reproduction, the violated invariant and a status. The store is a JSON file so
it can be committed and reviewed; it is *appended to*, never rewritten from
scratch, so a regression entry survives a code fix and is re-checked.

The store never weakens a test: it records facts (this scenario failed on this
commit) and a status a human sets. It cannot delete an entry; a fixed entry is
marked ``fixed`` and re-checked, not removed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .analyzer import FailureReport
from .scenario import Scenario, ScenarioFormatError

# The status a regression entry can carry.
OPEN: Final[str] = "open"
FIXED: Final[str] = "fixed"

DEFAULT_STORE_PATH: Final[str] = "qa/regressions.json"


@dataclass
class RegressionEntry:
    """One confirmed bug and its reproduction.

    Attributes:
        scenario: The full scenario that failed.
        minimal: The shortest steps that still fail.
        minimal_screen: The screen the minimal scenario produces.
        invariants: The violated invariant names.
        status: ``open`` or ``fixed``.
        found_at: An ISO date the bug was first seen.
        note: A short human explanation.
    """

    scenario: Scenario
    minimal: list[str] = field(default_factory=list)
    minimal_screen: str = ""
    invariants: list[str] = field(default_factory=list)
    status: str = OPEN
    found_at: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "id": self.scenario.id,
            "scenario": self.scenario.to_dict(),
            "minimal": list(self.minimal),
            "minimal_screen": self.minimal_screen,
            "invariants": list(self.invariants),
            "status": self.status,
            "found_at": self.found_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: object) -> RegressionEntry:
        """Build an entry from an untrusted mapping."""
        if not isinstance(data, dict):
            raise ScenarioFormatError("a regression entry must be a mapping")
        scenario = Scenario.from_dict(data.get("scenario", {}))
        return cls(
            scenario=scenario,
            minimal=[str(step) for step in data.get("minimal", [])],
            minimal_screen=str(data.get("minimal_screen", "")),
            invariants=[str(name) for name in data.get("invariants", [])],
            status=str(data.get("status", OPEN)),
            found_at=str(data.get("found_at", "")),
            note=str(data.get("note", "")),
        )


class RegressionStore:
    """A JSON-backed collection of :class:`RegressionEntry`, keyed by id."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(DEFAULT_STORE_PATH)
        self._entries: dict[str, RegressionEntry] = {}
        self.load()

    def load(self) -> None:
        """Read the store, tolerating a missing or corrupt file."""
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        for item in data:
            try:
                entry = RegressionEntry.from_dict(item)
            except ScenarioFormatError:
                continue
            self._entries[entry.scenario.id] = entry

    def save(self) -> None:
        """Write the store atomically, sorted by id."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [self._entries[key].to_dict() for key in sorted(self._entries)],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def record(
        self, report: FailureReport, *, found_at: str = "", note: str = ""
    ) -> RegressionEntry:
        """Add or update an entry from a failure report (never deletes)."""
        scenario_id = report.scenario.id
        entry = RegressionEntry(
            scenario=report.scenario,
            minimal=list(report.minimal),
            minimal_screen=report.minimal_screen,
            invariants=list(report.invariants),
            status=OPEN,
            found_at=found_at,
            note=note or report.detail,
        )
        # A bug already recorded keeps its original date and note.
        existing = self._entries.get(scenario_id)
        if existing is not None:
            entry.found_at = existing.found_at or found_at
            entry.note = existing.note or entry.note
        self._entries[scenario_id] = entry
        self.save()
        return entry

    def mark_fixed(self, scenario_id: str) -> bool:
        """Mark an entry fixed; return ``False`` when it is not present."""
        entry = self._entries.get(scenario_id)
        if entry is None:
            return False
        entry.status = FIXED
        self.save()
        return True

    def open_entries(self) -> list[RegressionEntry]:
        """Return the entries still marked open, sorted by id."""
        return [e for e in self.sorted() if e.status == OPEN]

    def sorted(self) -> list[RegressionEntry]:
        """Return every entry, sorted by id."""
        return [self._entries[key] for key in sorted(self._entries)]

    def __len__(self) -> int:
        return len(self._entries)


__all__: Final[list[str]] = [
    "DEFAULT_STORE_PATH",
    "FIXED",
    "OPEN",
    "RegressionEntry",
    "RegressionStore",
]
