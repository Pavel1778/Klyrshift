"""The scenario model and its JSON format.

A *scenario* is data, never code: a list of steps in the fixed DSL of
:mod:`klyrshift.simulate`, plus the configuration to start from, the invariants
to check and a human-readable expectation. Nothing in a scenario is ever
executed as a command -- the executor only ever feeds the steps to the
simulator's own parser.

The format is JSON so a scenario can be stored, diffed and replayed:

    {
      "id": "layout/basic-space",
      "title": "A wrong-layout word is fixed on Space",
      "category": "layout",
      "difficulty": "basic",
      "tags": ["layout", "boundary"],
      "steps": ["type ghbdtn", "space"],
      "config": {},
      "layout": "us",
      "expect": {"screen": "привет "},
      "invariants": ["no-lost-characters", "layout-switched"],
      "seed": 0,
      "notes": "The flagship case."
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

# The difficulty ladder, ordered from the simplest to the most intricate.
DIFFICULTIES: Final[tuple[str, ...]] = ("basic", "intermediate", "advanced")

# The functional areas a scenario can belong to. Kept as a closed set so a
# report can group by category without inventing names.
CATEGORIES: Final[tuple[str, ...]] = (
    "layout",
    "typo",
    "punctuation",
    "boundary",
    "modes",
    "undo",
    "learning",
    "per-app",
    "guards",
    "snippets",
    "robustness",
)


class ScenarioFormatError(ValueError):
    """A scenario file or mapping is not a valid scenario."""


@dataclass
class Scenario:
    """One reproducible keystroke scenario.

    Attributes:
        id: A unique, stable identifier (``category/name`` by convention).
        title: A one-line human description.
        steps: The simulator steps, in order.
        category: One of :data:`CATEGORIES` (used to group a report).
        difficulty: One of :data:`DIFFICULTIES`.
        tags: Free-form labels for filtering.
        config: Configuration overrides applied before the steps, as the
            simulator's ``config key=value`` step would (a mapping of field
            name to value).
        layout: The layout active before the first step.
        expect: Optional expectations; the only recognised key is ``screen``,
            the exact text the user should see at the end.
        invariants: Names from :mod:`klyrshift.qa.invariants` to check.
        seed: The RNG seed a generator used, for reproducibility (``0`` for a
            hand-written scenario).
        notes: Optional longer explanation.
        origin: Where the scenario came from -- ``manual``, ``generated`` or
            ``regression``.
    """

    id: str
    steps: list[str]
    title: str = ""
    category: str = "layout"
    difficulty: str = "basic"
    tags: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    layout: str = "us"
    expect: dict[str, Any] = field(default_factory=dict)
    invariants: list[str] = field(default_factory=list)
    seed: int = 0
    notes: str = ""
    origin: str = "manual"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Normalise and check the fields in place, raising on a bad value."""
        self.id = str(self.id).strip()
        if not self.id:
            raise ScenarioFormatError("a scenario needs a non-empty id")
        self.steps = [str(step).strip() for step in self.steps if str(step).strip()]
        if not self.steps:
            raise ScenarioFormatError(f"scenario {self.id!r} has no steps")
        self.category = str(self.category).strip().lower()
        if self.category not in CATEGORIES:
            raise ScenarioFormatError(
                f"scenario {self.id!r} has unknown category {self.category!r}"
            )
        self.difficulty = str(self.difficulty).strip().lower()
        if self.difficulty not in DIFFICULTIES:
            raise ScenarioFormatError(
                f"scenario {self.id!r} has unknown difficulty {self.difficulty!r}"
            )
        self.tags = sorted({str(tag).strip() for tag in self.tags if str(tag).strip()})
        if not isinstance(self.config, dict):
            raise ScenarioFormatError(f"scenario {self.id!r} config must be a mapping")
        if not isinstance(self.expect, dict):
            raise ScenarioFormatError(f"scenario {self.id!r} expect must be a mapping")
        unknown = set(self.expect) - {"screen"}
        if unknown:
            raise ScenarioFormatError(
                f"scenario {self.id!r} has unknown expectation keys: {sorted(unknown)}"
            )
        self.layout = str(self.layout).strip() or "us"
        self.seed = int(self.seed)
        self.origin = str(self.origin).strip() or "manual"

    # --- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping (stable key order)."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "difficulty": self.difficulty,
            "tags": list(self.tags),
            "steps": list(self.steps),
            "config": dict(self.config),
            "layout": self.layout,
            "expect": dict(self.expect),
            "invariants": list(self.invariants),
            "seed": self.seed,
            "notes": self.notes,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: object) -> Scenario:
        """Build a scenario from an untrusted mapping."""
        if not isinstance(data, dict):
            raise ScenarioFormatError(f"a scenario must be a mapping, got {type(data).__name__}")
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise ScenarioFormatError(f"unknown scenario keys: {sorted(unknown)}")
        try:
            return cls(**data)
        except TypeError as exc:
            raise ScenarioFormatError(str(exc)) from exc

    def to_json(self) -> str:
        """Return the scenario as pretty-printed JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Scenario:
        """Parse a scenario from JSON text."""
        try:
            data: object = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScenarioFormatError(f"scenario is not valid JSON: {exc}") from exc
        return cls.from_dict(data)


def load_scenarios(path: Path) -> list[Scenario]:
    """Load a scenario *file* (one object or a list) or a directory of files.

    A directory is read recursively; every ``*.json`` file is loaded, and the
    results are returned sorted by id so a run is deterministic.
    """
    scenarios: list[Scenario] = []
    if path.is_dir():
        for child in sorted(path.rglob("*.json")):
            scenarios.extend(_load_one(child))
    else:
        scenarios.extend(_load_one(path))
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.id in seen:
            raise ScenarioFormatError(f"duplicate scenario id {scenario.id!r}")
        seen.add(scenario.id)
    return sorted(scenarios, key=lambda s: s.id)


def _load_one(path: Path) -> list[Scenario]:
    text = path.read_text(encoding="utf-8")
    try:
        data: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioFormatError(f"{path} is not valid JSON: {exc}") from exc
    if isinstance(data, list):
        return [Scenario.from_dict(item) for item in data]
    return [Scenario.from_dict(data)]


def save_scenarios(scenarios: list[Scenario], path: Path) -> None:
    """Write ``scenarios`` to ``path`` as a JSON array (stable order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [scenario.to_dict() for scenario in scenarios], ensure_ascii=False, indent=2, sort_keys=True
    )
    path.write_text(payload + "\n", encoding="utf-8")


__all__ = [
    "CATEGORIES",
    "DIFFICULTIES",
    "Scenario",
    "ScenarioFormatError",
    "load_scenarios",
    "save_scenarios",
]
