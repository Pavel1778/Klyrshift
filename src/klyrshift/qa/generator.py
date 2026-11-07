"""Deterministic scenario generation, with a pluggable LLM hook.

The generator has two modes and they are independent:

* **Deterministic** (the default, no network, no API key). It builds scenarios
  from a small grammar of steps, seeded by a fixed seed, so the same seed always
  produces the same scenarios. It expands *around* the curated library and a
  list of known bug classes, avoiding duplicates of what already exists.
* **LLM-assisted** (opt-in). An :class:`LLMProvider` proposes extra step
  sequences as *data*; the generator validates every proposal through
  :class:`~klyrshift.qa.scenario.Scenario` and drops anything malformed. A
  provider that fails or is absent is simply skipped -- the deterministic run
  never depends on it.

Nothing an LLM returns is executed: the proposal is a list of step strings,
validated against the simulator's own DSL by the executor.

The generator also maps *changed source files* to the functional areas they
affect, so a run can focus on what a change touched.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

from .curated import CURATED
from .scenario import CATEGORIES, Scenario

# Source-file prefix -> functional areas it can affect. A change under a prefix
# focuses generation on those categories.
_FILE_CATEGORIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("src/klyrshift/daemon.py", ("layout", "boundary", "modes", "undo", "learning")),
    ("src/klyrshift/detector.py", ("layout", "guards")),
    ("src/klyrshift/converter.py", ("layout",)),
    ("src/klyrshift/typo.py", ("typo",)),
    ("src/klyrshift/punctuation.py", ("punctuation",)),
    ("src/klyrshift/learning.py", ("learning",)),
    ("src/klyrshift/injector.py", ("layout", "boundary")),
    ("src/klyrshift/config.py", ("modes", "per-app", "guards")),
    ("src/klyrshift/text_expander.py", ("snippets",)),
    ("src/klyrshift/app_layouts.py", ("per-app",)),
)

# The step alphabet the generator draws from, grouped so a generated scenario is
# plausible rather than random noise.
_WORDS: Final[tuple[str, ...]] = ("ghbdtn", "hello", "ljv", "langauge", "abc", "world")
_BOUNDARIES: Final[tuple[str, ...]] = ("space", "enter", "tab", "dot", "comma")
_HOTKEYS: Final[tuple[str, ...]] = ("dblshift", "ctrl+shift+t", "ctrl+shift+f")
_MODES: Final[tuple[str, ...]] = ("auto", "manual", "hybrid")
# A boundary trigger that is off by default must be enabled in the config first.
_BOUNDARY_CONFIG: Final[dict[str, dict[str, object]]] = {
    "tab": {"on_tab": True},
    "dot": {"on_punctuation": True},
    "comma": {"on_punctuation": True},
}


class LLMProvider(Protocol):
    """A source of extra scenarios. Implementations must be side-effect free."""

    def propose(self, focus: Sequence[str], seed: int) -> list[list[str]]:
        """Return proposed step lists for the given focus areas."""
        ...


@dataclass
class GeneratorConfig:
    """Knobs for a deterministic generation run.

    Attributes:
        seed: The RNG seed; the same seed always yields the same scenarios.
        count: How many scenarios to produce.
        focus: Restrict to these categories (empty means all).
        max_steps: The longest step list a scenario may have.
        changed_files: Source files a change touched, used to focus generation.
    """

    seed: int = 0
    count: int = 40
    focus: list[str] = field(default_factory=list)
    max_steps: int = 6
    changed_files: list[str] = field(default_factory=list)


@dataclass
class GenerationReport:
    """What a generation run produced and why some candidates were dropped."""

    scenarios: list[Scenario] = field(default_factory=list)
    duplicates: int = 0
    invalid: int = 0
    focus: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable summary."""
        return {
            "generated": len(self.scenarios),
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "focus": list(self.focus),
        }


def categories_for_files(files: Iterable[str]) -> list[str]:
    """Return the functional areas a set of changed files can affect."""
    found: set[str] = set()
    for name in files:
        normalised = name.replace("\\", "/")
        for prefix, categories in _FILE_CATEGORIES:
            if normalised.startswith(prefix):
                found.update(categories)
    return sorted(found)


def _signature(scenario: Scenario) -> str:
    """A stable identity for deduplication: steps + config + layout."""
    config = ",".join(f"{k}={v}" for k, v in sorted(scenario.config.items()))
    return f"{'|'.join(scenario.steps)}@@{config}@@{scenario.layout}"


def generate(
    config: GeneratorConfig | None = None,
    *,
    llm: LLMProvider | None = None,
    known: Sequence[Scenario] | None = None,
) -> GenerationReport:
    """Generate scenarios deterministically, plus any an LLM provider offers.

    Args:
        config: The generation knobs.
        llm: An optional provider of extra step lists (validated, never run
            directly).
        known: Scenarios already in the corpus, used for deduplication. Defaults
            to the curated library.

    Returns:
        A :class:`GenerationReport` with the accepted scenarios and counts.
    """
    cfg = config or GeneratorConfig()
    rng = random.Random(cfg.seed)
    focus = _resolve_focus(cfg)
    report = GenerationReport(focus=focus)

    seen: set[str] = set()
    for scenario in list(known if known is not None else CURATED):
        seen.add(_signature(scenario))

    # Deterministic generation: try many candidates, keep the first ``count``
    # that are valid and not duplicates.
    attempts = 0
    max_attempts = cfg.count * 20 + 50
    while len(report.scenarios) < cfg.count and attempts < max_attempts:
        attempts += 1
        steps, config_map = _random_steps(rng, focus, cfg.max_steps)
        category = _category_for(steps, focus)
        candidate = _build(cfg, category, steps, config_map)
        try:
            candidate.validate()
        except Exception:
            report.invalid += 1
            continue
        signature = _signature(candidate)
        if signature in seen:
            report.duplicates += 1
            continue
        seen.add(signature)
        report.scenarios.append(candidate)

    # LLM-assisted generation: optional, validated, deduplicated.
    if llm is not None:
        try:
            proposals = llm.propose(focus, cfg.seed)
        except Exception:
            proposals = []
        for steps in proposals:
            if len(report.scenarios) >= cfg.count:
                break
            if not steps:
                continue
            category = _category_for(list(steps), focus)
            candidate = _build(cfg, category, list(steps), {})
            try:
                candidate.validate()
            except Exception:
                report.invalid += 1
                continue
            signature = _signature(candidate)
            if signature in seen:
                report.duplicates += 1
                continue
            seen.add(signature)
            candidate.origin = "generated"
            report.scenarios.append(candidate)

    return report


def _resolve_focus(cfg: GeneratorConfig) -> list[str]:
    """Combine an explicit focus with the areas the changed files imply."""
    focus = {c for c in cfg.focus if c in CATEGORIES}
    if cfg.changed_files:
        focus.update(categories_for_files(cfg.changed_files))
    return sorted(focus)


def _random_steps(
    rng: random.Random, focus: Sequence[str], max_steps: int
) -> tuple[list[str], dict[str, object]]:
    """Build one plausible step list and the config it needs."""
    steps: list[str] = []
    config_map: dict[str, object] = {}
    # Occasionally pin a mode, which changes what the invariants expect.
    if rng.random() < 0.5:
        mode = rng.choice(_MODES)
        steps.append(f"mode {mode}")
    for _ in range(rng.randint(1, max_steps)):
        steps.append(f"type {rng.choice(_WORDS)}")
        roll = rng.random()
        if roll < 0.55:
            boundary = rng.choice(_BOUNDARIES)
            steps.append(boundary)
            config_map.update(_BOUNDARY_CONFIG.get(boundary, {}))
        elif roll < 0.7:
            steps.append("wait")
        elif roll < 0.85:
            steps.append(rng.choice(_HOTKEYS))
        elif roll < 0.95:
            steps.append("backspace")
        else:
            steps.append("ctrl z")
    return steps, config_map


def _category_for(steps: Sequence[str], focus: Sequence[str]) -> str:
    """Pick the category a step list belongs to, honouring the focus."""
    if "ctrl z" in steps:
        candidate = "learning"
    elif "mode manual" in steps:
        candidate = "modes"
    elif "dot" in steps or "comma" in steps:
        candidate = "boundary"
    elif any(step.startswith("ctrl+shift+f") for step in steps):
        candidate = "typo"
    else:
        candidate = "layout"
    if focus and candidate not in focus and focus[0] in CATEGORIES:
        return focus[0]
    return candidate


def _stable_id(seed: int, steps: Sequence[str], config_map: dict[str, object]) -> str:
    """Return a seed-stable identifier (``hash()`` is process-randomised)."""
    payload = f"{seed}|{'|'.join(steps)}|{sorted(config_map.items())}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]
    return digest


def _build(
    cfg: GeneratorConfig,
    category: str,
    steps: list[str],
    config_map: dict[str, object],
) -> Scenario:
    """Build a generated scenario with a seed-stable id."""
    digest = _stable_id(cfg.seed, steps, config_map)
    return Scenario(
        id=f"gen/{category}/{cfg.seed}-{digest}",
        title=f"Generated {category} scenario (seed {cfg.seed})",
        steps=steps,
        category=category,
        difficulty="intermediate",
        tags=["generated", category],
        config=config_map,
        invariants=[
            "no-lost-characters",
            "no-mixed-script-replacement",
            "layout-is-known",
        ],
        seed=cfg.seed,
        origin="generated",
    )


__all__: Final[list[str]] = [
    "GenerationReport",
    "GeneratorConfig",
    "LLMProvider",
    "categories_for_files",
    "generate",
]
