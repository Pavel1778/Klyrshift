"""Tests for the autonomous QA engine (:mod:`klyrshift.qa`).

The engine is a layer on top of the existing suite: it drives the real daemon
through :mod:`klyrshift.simulate`, checks independent invariants, classifies
failures, minimises them and keeps a regression store. These tests pin the
contract of each piece *and* the end-to-end run, so the engine cannot silently
weaken a check or invent a pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from klyrshift.qa import invariants as inv  # noqa: E402
from klyrshift.qa.analyzer import (  # noqa: E402
    CONFIRMED_BUG,
    HARNESS_ERROR,
    SUSPICION,
    analyse,
    minimise_scenario,
)
from klyrshift.qa.curated import CURATED, load_curated  # noqa: E402
from klyrshift.qa.executor import (  # noqa: E402
    OUTCOME_FAILED,
    OUTCOME_HARNESS_ERROR,
    OUTCOME_PASSED,
    build_script,
    execute,
)
from klyrshift.qa.generator import (  # noqa: E402
    GeneratorConfig,
    categories_for_files,
    generate,
)
from klyrshift.qa.report import to_json, to_markdown  # noqa: E402
from klyrshift.qa.runner import RunConfig, build_corpus, rerun_regressions, run  # noqa: E402
from klyrshift.qa.scenario import (  # noqa: E402
    Scenario,
    ScenarioFormatError,
    load_scenarios,
    save_scenarios,
)
from klyrshift.qa.store import RegressionStore  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


# --- Stage 2: the scenario model -------------------------------------------


def test_scenario_round_trips_through_json() -> None:
    scenario = Scenario(
        id="layout/x",
        steps=["type ghbdtn", "space"],
        title="t",
        category="layout",
        tags=["b", "a"],
        config={"on_tab": True},
        expect={"screen": "ok"},
        invariants=["screen-matches-expectation"],
    )
    again = Scenario.from_json(scenario.to_json())
    assert again == scenario
    assert again.tags == ["a", "b"]  # normalised (sorted)


def test_scenario_rejects_empty_steps() -> None:
    with pytest.raises(ScenarioFormatError):
        Scenario(id="x", steps=[])


def test_scenario_rejects_unknown_category() -> None:
    with pytest.raises(ScenarioFormatError):
        Scenario(id="x", steps=["space"], category="nonsense")


def test_scenario_rejects_unknown_expectation_key() -> None:
    with pytest.raises(ScenarioFormatError):
        Scenario(id="x", steps=["space"], expect={"whenever": "y"})


def test_scenario_rejects_unknown_key_in_mapping() -> None:
    with pytest.raises(ScenarioFormatError):
        Scenario.from_dict({"id": "x", "steps": ["space"], "bogus": 1})


def test_load_and_save_scenarios(tmp_path: Path) -> None:
    scenarios = [Scenario(id="a/x", steps=["space"]), Scenario(id="b/y", steps=["enter"])]
    path = tmp_path / "s.json"
    save_scenarios(scenarios, path)
    loaded = load_scenarios(path)
    assert [s.id for s in loaded] == ["a/x", "b/y"]


def test_load_scenarios_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "dup.json"
    path.write_text(
        json.dumps([{"id": "x", "steps": ["space"]}, {"id": "x", "steps": ["enter"]}]),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioFormatError):
        load_scenarios(path)


# --- Stage 4: the executor --------------------------------------------------


def test_executor_passes_a_correct_scenario() -> None:
    execution = execute(
        Scenario(
            id="x/ok",
            steps=["type ghbdtn", "space"],
            expect={"screen": "\u043f\u0440\u0438\u0432\u0435\u0442 "},
            invariants=["screen-matches-expectation", "no-lost-characters"],
        )
    )
    assert execution.outcome == OUTCOME_PASSED


def test_executor_fails_a_wrong_expectation() -> None:
    execution = execute(
        Scenario(
            id="x/bad",
            steps=["type ghbdtn", "space"],
            expect={"screen": "WRONG"},
            invariants=["screen-matches-expectation"],
        )
    )
    assert execution.outcome == OUTCOME_FAILED
    assert [v.name for v in execution.violations] == ["screen-matches-expectation"]


def test_executor_reports_a_bad_step_as_harness_error() -> None:
    execution = execute(Scenario(id="x/badstep", steps=["frobnicate"], invariants=[]))
    assert execution.outcome == OUTCOME_HARNESS_ERROR
    assert "rejected" in execution.error


def test_build_script_includes_config_first() -> None:
    script = build_script(
        Scenario(id="x", steps=["type ghbdtn"], config={"on_tab": True, "typo_mode": "off"})
    )
    assert script.startswith("config ")
    assert "on_tab=true" in script
    assert script.endswith("type ghbdtn")


def test_build_script_renders_lists_and_dicts() -> None:
    script = build_script(
        Scenario(
            id="x",
            steps=["space"],
            config={"stop_words": ["a", "b"], "app_modes": {"code": "manual"}},
        )
    )
    assert "[a, b]" in script
    assert "{code: manual}" in script


# --- Stage 5: the invariant engine -----------------------------------------


def test_invariant_registry_is_not_empty() -> None:
    names = inv.registered()
    for expected in (
        "no-lost-characters",
        "space-preserved",
        "enter-preserved",
        "tab-preserved",
        "punctuation-preserved",
        "manual-mode-silent",
        "ctrl-z-suppressed",
        "no-mixed-script-replacement",
        "layout-switched",
        "no-over-deletion",
        "screen-matches-expectation",
        "layout-is-known",
    ):
        assert expected in names


def test_no_lost_characters_fires_on_a_missing_separator() -> None:
    scenario = Scenario(id="x", steps=["type ghbdtn", "space"], invariants=["no-lost-characters"])
    context = inv.InvariantContext(
        scenario=scenario,
        screen="\u043f\u0440\u0438\u0432\u0435\u0442",  # no trailing space
        replacements=[(6, "\u043f\u0440\u0438\u0432\u0435\u0442", "ru")],
        mode="auto",
        layout="ru",
        suppressed=[],
        typed_separators=1,
        typed_punctuation=0,
        typed_chars=6,
        final_separators=0,
        steps=scenario.steps,
    )
    violation = inv.check("no-lost-characters", context)
    assert violation is not None
    assert violation.name == "no-lost-characters"


def test_manual_mode_silent_fires_on_an_automatic_fix() -> None:
    scenario = Scenario(id="x", steps=["mode manual", "type ghbdtn", "space"])
    context = inv.InvariantContext(
        scenario=scenario,
        screen="\u043f\u0440\u0438\u0432\u0435\u0442 ",
        replacements=[(7, "\u043f\u0440\u0438\u0432\u0435\u0442 ", "ru")],
        mode="manual",
        layout="ru",
        suppressed=[],
        typed_separators=1,
        typed_punctuation=0,
        typed_chars=6,
        final_separators=1,
        steps=scenario.steps,
    )
    assert inv.check("manual-mode-silent", context) is not None


def test_manual_mode_silent_is_quiet_with_a_hotkey() -> None:
    scenario = Scenario(id="x", steps=["mode manual", "type ghbdtn", "dblshift"])
    context = inv.InvariantContext(
        scenario=scenario,
        screen="\u043f\u0440\u0438\u0432\u0435\u0442",
        replacements=[(6, "\u043f\u0440\u0438\u0432\u0435\u0442", "ru")],
        mode="manual",
        layout="ru",
        suppressed=[],
        typed_separators=0,
        typed_punctuation=0,
        typed_chars=6,
        final_separators=0,
        steps=scenario.steps,
    )
    assert inv.check("manual-mode-silent", context) is None


def test_mixed_script_check_only_looks_at_replacements() -> None:
    # Two adjacent words from different scripts are legal input, not a bug.
    scenario = Scenario(id="x", steps=["type world", "type ljv"])
    context = inv.InvariantContext(
        scenario=scenario,
        screen="world\u0434\u043e\u043c",
        replacements=[],
        mode="auto",
        layout="us",
        suppressed=[],
        typed_separators=0,
        typed_punctuation=0,
        typed_chars=8,
        final_separators=0,
        steps=scenario.steps,
    )
    assert inv.check("no-mixed-script-replacement", context) is None


def test_mixed_script_check_fires_on_a_mixed_replacement() -> None:
    scenario = Scenario(id="x", steps=["type ghbdtn", "space"])
    context = inv.InvariantContext(
        scenario=scenario,
        screen="g\u043f\u0440\u0438\u0432\u0435\u0442",
        replacements=[(6, "g\u043f\u0440\u0438\u0432\u0435\u0442", "ru")],
        mode="auto",
        layout="ru",
        suppressed=[],
        typed_separators=1,
        typed_punctuation=0,
        typed_chars=6,
        final_separators=0,
        steps=scenario.steps,
    )
    assert inv.check("no-mixed-script-replacement", context) is not None


def test_typed_counts_are_an_independent_oracle() -> None:
    steps = ["type ghbdtn", "space", "type abc", "dot", "enter", "tab"]
    # space + enter + tab = three separator keys.
    assert inv.typed_separators(steps) == 3
    assert inv.typed_punctuation(steps) == 1  # the dot step


# --- Stage 6: the analyzer --------------------------------------------------


def test_classify_treats_a_structural_violation_as_a_bug() -> None:
    """A structural violation is a confirmed bug; a wrong expectation is not.

    The classification does not depend on re-running: whether a failure is a bug
    or a suspicion is a property of *which* invariant failed. A screen that lost
    a character is structural; a hand-written ``expect`` mismatch may itself be
    wrong, so it is only a suspicion (and ``analyse`` downgrades a non-repeating
    one to flaky).
    """
    from klyrshift.qa.analyzer import SUSPICION, classify
    from klyrshift.qa.executor import Execution
    from klyrshift.qa.invariants import InvariantViolation

    scenario = Scenario(id="x/struct", steps=["type ghbdtn", "space"])
    structural = Execution(
        scenario=scenario,
        outcome=OUTCOME_FAILED,
        violations=[InvariantViolation("no-lost-characters", "lost a separator")],
    )
    expectation = Execution(
        scenario=scenario,
        outcome=OUTCOME_FAILED,
        violations=[InvariantViolation("screen-matches-expectation", "mismatch")],
    )
    assert classify(structural) == CONFIRMED_BUG
    assert classify(expectation) == SUSPICION


def test_analyse_classifies_a_bad_step_as_harness_error() -> None:
    scenario = Scenario(id="x/h", steps=["frobnicate"], invariants=[])
    report = analyse(scenario, execute(scenario), minimise=False)
    assert report.classification == HARNESS_ERROR


def test_analyse_classifies_a_wrong_expectation_as_suspicion() -> None:
    scenario = Scenario(
        id="x/susp",
        steps=["type ghbdtn", "space"],
        expect={"screen": "WRONG"},
        invariants=["screen-matches-expectation"],
    )
    report = analyse(scenario, execute(scenario), minimise=False)
    assert report.classification == SUSPICION


def test_minimiser_drops_redundant_steps() -> None:
    scenario = Scenario(
        id="x/min",
        steps=["esc", "esc", "type ghbdtn", "space"],
        expect={"screen": "NOPE"},
        invariants=["screen-matches-expectation"],
    )
    steps, _screen = minimise_scenario(scenario)
    assert steps == ["type ghbdtn", "space"]


# --- Stage 3: the generator -------------------------------------------------


def test_generator_is_deterministic_for_a_seed() -> None:
    a = generate(GeneratorConfig(seed=11, count=12))
    b = generate(GeneratorConfig(seed=11, count=12))
    assert [s.id for s in a.scenarios] == [s.id for s in b.scenarios]


def test_generator_avoids_duplicates() -> None:
    report = generate(GeneratorConfig(seed=2, count=20), known=list(CURATED))
    signatures = {(tuple(s.steps), tuple(sorted(s.config.items()))) for s in report.scenarios}
    assert len(signatures) == len(report.scenarios)


def test_categories_for_files_maps_the_daemon() -> None:
    focus = categories_for_files(["src/klyrshift/daemon.py"])
    assert "layout" in focus
    assert "learning" in focus


def test_generator_focus_restricts_categories() -> None:
    report = generate(GeneratorConfig(seed=4, count=10, focus=["typo"]))
    assert {s.category for s in report.scenarios} == {"typo"}


# --- Stage 7/8/9: store, report, runner ------------------------------------


def test_store_records_and_never_deletes(tmp_path: Path) -> None:
    store = RegressionStore(tmp_path / "reg.json")
    scenario = Scenario(
        id="x/bug",
        steps=["type ghbdtn", "space"],
        expect={"screen": "WRONG"},
        invariants=["screen-matches-expectation"],
    )
    from klyrshift.qa.analyzer import FailureReport

    report = FailureReport(
        scenario=scenario,
        classification=CONFIRMED_BUG,
        invariants=["x"],
        minimal=list(scenario.steps),
    )
    store.record(report, found_at="2026-01-01")
    assert len(store) == 1
    assert store.open_entries()[0].scenario.id == "x/bug"
    assert store.mark_fixed("x/bug") is True
    assert store.open_entries() == []
    assert len(store) == 1  # fixed, not deleted


def test_store_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "reg.json"
    store = RegressionStore(path)
    scenario = Scenario(id="x/b", steps=["space"], invariants=["layout-is-known"])
    from klyrshift.qa.analyzer import FailureReport

    store.record(FailureReport(scenario=scenario, classification=CONFIRMED_BUG))
    again = RegressionStore(path)
    assert [e.scenario.id for e in again.sorted()] == ["x/b"]


def test_report_is_measured_only() -> None:
    from klyrshift.qa.report import RunSummary

    summary = RunSummary(total=3, passed=2, failed=1, duration_s=1.5)
    summary.violations["no-lost-characters"] = 1
    payload = json.loads(to_json(summary))
    assert payload["total"] == 3
    assert "coverage" not in payload
    md = to_markdown(summary)
    assert "no-lost-characters" in md
    assert "%" not in md  # no invented percentage


def test_runner_end_to_end_is_green(tmp_path: Path) -> None:
    config = RunConfig(seed=5, generated=10, store_path=tmp_path / "reg.json")
    corpus = build_corpus(list(CURATED), config)
    summary = run(corpus, config, store=RegressionStore(tmp_path / "reg.json"))
    assert summary.total == len(corpus)
    assert summary.failed == 0, [f["scenario"] for f in summary.failures]
    assert summary.harness_errors == 0
    assert summary.new_bugs == []


def test_runner_does_not_invent_a_bug_on_a_green_corpus(tmp_path: Path) -> None:
    """A passing corpus records nothing -- the engine never invents a failure."""
    bug = Scenario(
        id="qa/green",
        steps=["type ghbdtn", "enter", "space"],
        invariants=["no-lost-characters"],
    )
    store = RegressionStore(tmp_path / "reg.json")
    summary = run([bug], RunConfig(minimise=False), store=store)
    assert summary.failed == 0
    assert len(store) == 0


def test_runner_records_a_confirmed_bug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A structural violation is recorded in the store.

    The live daemon has no such defect, so the failure is injected by replacing
    the executor's run with one that returns a fixed violation. The runner's
    record path is then exercised end to end without weakening any real check.
    """
    from klyrshift.qa import analyzer as analyzer_module, runner as runner_module
    from klyrshift.qa.executor import OUTCOME_FAILED, Execution
    from klyrshift.qa.invariants import InvariantViolation
    from klyrshift.simulate import SimulationResult

    scenario = Scenario(
        id="qa/injected-structural",
        steps=["type ghbdtn", "space"],
        invariants=["no-lost-characters"],
    )
    failure = Execution(
        scenario=scenario,
        outcome=OUTCOME_FAILED,
        result=SimulationResult(screen="\u043f\u0440\u0438\u0432\u0435\u0442"),
        violations=[InvariantViolation("no-lost-characters", "injected")],
        steps=list(scenario.steps),
    )

    def fake_execute(_scenario: Scenario, *, start_layout: str | None = None) -> Execution:
        del start_layout
        return failure

    monkeypatch.setattr(runner_module, "execute", fake_execute)
    monkeypatch.setattr(analyzer_module, "execute", fake_execute)

    store = RegressionStore(tmp_path / "reg.json")
    summary = run([scenario], RunConfig(minimise=False), store=store)
    assert summary.failed == 1
    assert summary.new_bugs == ["qa/injected-structural"]
    assert len(store) == 1
    assert store.open_entries()[0].scenario.id == "qa/injected-structural"


def test_rerun_regressions_marks_a_fixed_entry(tmp_path: Path) -> None:
    store = RegressionStore(tmp_path / "reg.json")
    from klyrshift.qa.analyzer import FailureReport

    # A scenario that passes now: recorded as a bug, it is marked fixed.
    scenario = Scenario(
        id="x/fixed", steps=["type ghbdtn", "space"], invariants=["layout-is-known"]
    )
    store.record(FailureReport(scenario=scenario, classification=CONFIRMED_BUG))
    summary = rerun_regressions(store)
    assert summary.passed == 1
    assert store.open_entries() == []


def test_curated_corpus_is_valid_and_unique() -> None:
    scenarios = load_curated()
    assert len(scenarios) >= 25
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))
    for scenario in scenarios:
        assert scenario.steps
        assert scenario.invariants
        assert scenario.category in {
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
        }
