"""Tests for the onboarding scenario, help texts and persisted state.

These run without GTK: the module under test is plain data plus a small JSON
state file, which is exactly why it was kept out of the GUI package.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klyrshift.config import Config
from klyrshift.onboarding import (
    FIELD_HELP,
    HELP_TOPICS,
    TOUR_STEPS,
    TOUR_VERSION,
    OnboardingState,
    help_for_field,
    load_onboarding_state,
    onboarding_path,
    save_onboarding_state,
    should_offer_tour,
)


def test_help_topics_only_reference_real_config_fields() -> None:
    """A renamed Config field must not silently orphan its help text."""
    known = set(Config.__dataclass_fields__)
    for topic in HELP_TOPICS.values():
        unknown = [field for field in topic.fields if field not in known]
        assert unknown == [], f"help topic {topic.key!r} documents unknown fields: {unknown}"


def test_every_help_topic_has_both_levels() -> None:
    for topic in HELP_TOPICS.values():
        assert topic.title.strip()
        assert len(topic.short) > 20
        assert len(topic.details) > len(topic.short)


def test_tour_steps_are_well_formed_and_unique() -> None:
    keys = [step.key for step in TOUR_STEPS]
    assert len(keys) == len(set(keys))
    for step in TOUR_STEPS:
        assert step.title.strip()
        assert step.short.strip()
        assert step.details.strip()
        assert step.position in {"auto", "top", "bottom"}


def test_tour_covers_the_essential_setup_actions() -> None:
    """The scenario must walk the user through the core first-run decisions."""
    keys = {step.key for step in TOUR_STEPS}
    assert {"home", "languages", "mode", "hotkey", "diagnostics"} <= keys
    # The closing step carries no target: it is the "you are done" card.
    assert TOUR_STEPS[-1].target == ""


def test_tour_targets_are_namespaced_by_page() -> None:
    """A non-empty target is ``page.widget`` so the window can resolve it."""
    for step in TOUR_STEPS:
        if step.target:
            page, _, widget = step.target.partition(".")
            assert page == step.page
            assert widget


def test_field_help_index_matches_topics() -> None:
    for field_name, key in FIELD_HELP.items():
        assert key in HELP_TOPICS
        assert field_name in HELP_TOPICS[key].fields
    assert help_for_field("typo_correction") is HELP_TOPICS["typo"]
    assert help_for_field("no_such_field") is None


def test_state_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    state = OnboardingState(completed_version=TOUR_VERSION, skipped_version=0, last_step=3)
    assert save_onboarding_state(state, path) is True
    assert load_onboarding_state(path) == state


def test_missing_state_file_yields_defaults(tmp_path: Path) -> None:
    state = load_onboarding_state(tmp_path / "absent.json")
    assert state == OnboardingState()
    assert should_offer_tour(state) is True


def test_corrupt_state_file_is_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_onboarding_state(path) == OnboardingState()


def test_state_file_with_wrong_types_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    path.write_text(json.dumps({"completed_version": "yes", "last_step": None}), encoding="utf-8")
    assert load_onboarding_state(path) == OnboardingState()


def test_state_file_that_is_not_an_object_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_onboarding_state(path) == OnboardingState()


def test_completing_the_tour_stops_the_offer() -> None:
    assert should_offer_tour(OnboardingState(completed_version=TOUR_VERSION)) is False


def test_skipping_the_tour_also_stops_the_offer() -> None:
    """A declined tour must never be re-opened on the next start."""
    assert should_offer_tour(OnboardingState(skipped_version=TOUR_VERSION)) is False


def test_an_older_completion_offers_the_new_tour() -> None:
    assert should_offer_tour(OnboardingState(completed_version=TOUR_VERSION - 1)) is True


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    assert save_onboarding_state(OnboardingState(last_step=2), path) is True
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_save_reports_failure_instead_of_raising(tmp_path: Path) -> None:
    # A directory in place of the file makes the write fail; the GUI must not crash.
    target = tmp_path / "onboarding.json"
    target.mkdir()
    assert save_onboarding_state(OnboardingState(), target) is False


def test_onboarding_path_is_under_the_state_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert onboarding_path() == tmp_path / "state" / "klyrshift" / "onboarding.json"
