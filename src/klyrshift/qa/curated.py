"""The curated scenario library, loaded from bundled JSON data.

The scenarios live in ``data/qa/scenarios.json`` (package data) rather than as
Python literals: they contain user-visible text, and keeping that out of the
source avoids the i18n guard (which flags every Cyrillic literal in a ``.py``
file) and keeps the corpus data, not code.

The library is the *ground truth* the engine starts from: the generator expands
around it, and the regression store records the bugs found against it. Because
it is JSON, it can be exported, diffed and edited without touching the engine.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Final

from .scenario import Scenario, ScenarioFormatError

DATA_NAME: Final[str] = "scenarios.json"


@lru_cache(maxsize=1)
def load_curated() -> tuple[Scenario, ...]:
    """Load and validate the bundled curated scenarios (cached).

    Raises:
        ScenarioFormatError: If the bundled file is missing or malformed. A
            broken corpus is a build error, not something to skip silently.
    """
    try:
        text = (resources.files("klyrshift") / "data" / "qa" / DATA_NAME).read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ScenarioFormatError(f"cannot read the bundled QA corpus: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioFormatError(f"the bundled QA corpus is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ScenarioFormatError("the bundled QA corpus must be a JSON array")
    scenarios = [Scenario.from_dict(item) for item in data]
    return tuple(sorted(scenarios, key=lambda s: s.id))


class _CuratedView:
    """A lazily-loaded, list-like view of the curated corpus.

    ``CURATED`` reads as a list but loads the JSON on first use, so importing
    this module stays cheap and a missing file is a lazy error.
    """

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(load_curated())

    def __len__(self) -> int:
        return len(load_curated())

    def __getitem__(self, index: int) -> Scenario:
        return load_curated()[index]

    def __bool__(self) -> bool:
        return bool(load_curated())


CURATED: Final[_CuratedView] = _CuratedView()


__all__: Final[list[str]] = ["CURATED", "load_curated"]
