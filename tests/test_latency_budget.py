"""The CI latency budget must actually fail the build when a budget is crossed.

``scripts/measure_latency.py`` is the guard against an order-of-magnitude
detector regression (a corpus reloaded per word, an accidental O(n^2)). A guard
that cannot fail is worse than none, so the exit-code logic is exercised here
directly; the measured numbers themselves are checked by the ``latency-budget``
CI job, not by pytest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "measure_latency.py"


def _load_module() -> object:
    """Import ``scripts/measure_latency.py`` without it being a package."""
    name = "measure_latency"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.fixture(scope="module")
def latency() -> object:
    return _load_module()


def test_no_budget_always_passes(latency: object) -> None:
    assert latency._check_budgets(999.0, 999.0, None, None) == 0


def test_within_budget_passes(latency: object) -> None:
    assert latency._check_budgets(0.01, 4.0, 0.5, 64.0) == 0


def test_slowest_direction_can_fail(latency: object) -> None:
    assert latency._check_budgets(0.6, 4.0, 0.5, 64.0) == 1


def test_memory_can_fail(latency: object) -> None:
    assert latency._check_budgets(0.01, 65.0, 0.5, 64.0) == 1


def test_boundary_is_inclusive(latency: object) -> None:
    """A value exactly on the budget passes; only exceeding it fails."""
    assert latency._check_budgets(0.5, 64.0, 0.5, 64.0) == 0
