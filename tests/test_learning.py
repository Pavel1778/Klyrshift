"""Always-on learning: the daemon adapts to what the user keeps and undoes.

The engine observes every flushed word (kept / corrected), promotes a word the
user keeps often enough into the detector's vocabulary, and suppresses a word
whose correction the user rejected (``Ctrl+Z``). The typed words live in memory
only; the persisted profile holds counters, never a word, which the last test
here pins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from klyrshift.config import Config
from klyrshift.daemon import KlyrshiftDaemon
from klyrshift.detector import LanguageDetector
from klyrshift.learning import (
    LearningEngine,
    LearningStats,
    LearningStore,
    profile_path,
)

evdev = pytest.importorskip("evdev")

EV_KEY = evdev.ecodes.EV_KEY


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeSwitcher:
    current: str = "us"
    backend: str = "fake"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    backend: str = "fake"

    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True


@pytest.fixture(autouse=True)
def _hermetic_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every XDG directory so no test touches the real state."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def make_daemon(**kwargs: object) -> KlyrshiftDaemon:
    options: dict[str, object] = {"analysis_timeout": 0.8, "stop_words": []}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=None, stop_words=config.stop_words, min_word_length=config.min_word_length
    )
    return KlyrshiftDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


def type_word(daemon: KlyrshiftDaemon, text: str) -> None:
    for char in text:
        name = "KEY_" + char.upper()
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))


def _injector(daemon: KlyrshiftDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


# ---------------------------------------------------------------------------
# Engine unit tests
# ---------------------------------------------------------------------------
def test_promotes_only_after_the_threshold(tmp_path: Path) -> None:
    engine = LearningEngine(promote_threshold=3, store=LearningStore(tmp_path / "p.json"))
    assert engine.observe_kept("Vercel") is False
    assert engine.observe_kept("Vercel") is False
    assert engine.observe_kept("vercel") is True
    assert engine.learned_words() == ["vercel"]
    assert engine.stats.promoted == 1


def test_rejected_word_is_suppressed_and_not_learned(tmp_path: Path) -> None:
    engine = LearningEngine(promote_threshold=1, store=LearningStore(tmp_path / "p.json"))
    engine.observe_kept("ghbdtn")
    assert engine.learned_words() == ["ghbdtn"]
    engine.observe_rejected("ghbdtn")
    assert engine.is_suppressed("GHBDTN") is True
    assert engine.learned_words() == []
    assert engine.stats.rejected == 1


def test_only_plain_letter_words_are_learned(tmp_path: Path) -> None:
    engine = LearningEngine(promote_threshold=1, store=LearningStore(tmp_path / "p.json"))
    for word in ("a1", "http://x", "", "привет!", "x" * 100):
        assert engine.observe_kept(word) is False
    assert engine.learned_words() == []
    assert engine.stats.observed == 0


def test_vocabulary_cap_evicts_the_least_typed(tmp_path: Path) -> None:
    engine = LearningEngine(
        promote_threshold=1, max_words=2, store=LearningStore(tmp_path / "p.json")
    )
    engine.observe_kept("alpha")
    engine.observe_kept("beta")
    engine.observe_kept("beta")
    engine.observe_kept("gamma")
    assert set(engine.learned_words()) == {"beta", "gamma"}


def test_disabled_engine_is_a_no_op(tmp_path: Path) -> None:
    engine = LearningEngine(enabled=False, store=LearningStore(tmp_path / "p.json"))
    assert engine.observe_kept("word") is False
    engine.observe_corrected("word")
    engine.observe_rejected("word")
    assert engine.learned_words() == []
    assert engine.is_suppressed("word") is False
    assert engine.stats == LearningStats()


def test_stats_round_trip_and_reset(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "p.json")
    engine = LearningEngine(promote_threshold=1, store=store)
    engine.observe_kept("word")
    engine.observe_corrected("other")
    engine.observe_rejected("third")
    engine.persist(force=True)
    reloaded = LearningStore(tmp_path / "p.json").load()
    assert reloaded == LearningStats(observed=2, kept=1, corrected=1, rejected=1, promoted=1)
    engine.reset()
    assert store.load() == LearningStats()


def test_corrupt_profile_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not json", encoding="utf-8")
    assert LearningStore(path).load() == LearningStats()


def test_profile_never_contains_a_typed_word(tmp_path: Path) -> None:
    """The persisted profile is counters only -- no word the user typed."""
    secret = "sekretnoeslovo"
    store = LearningStore(tmp_path / "p.json")
    engine = LearningEngine(promote_threshold=1, store=store)
    engine.observe_kept(secret)
    engine.observe_corrected(secret)
    engine.observe_rejected(secret)
    engine.persist(force=True)
    raw = (tmp_path / "p.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert set(json.loads(raw)) == {"observed", "kept", "corrected", "rejected", "promoted"}


# ---------------------------------------------------------------------------
# Daemon integration
# ---------------------------------------------------------------------------
def test_daemon_records_a_correction() -> None:
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]
    assert daemon.learning.stats.corrected == 1


def test_daemon_promotes_a_kept_word_into_the_vocabulary() -> None:
    daemon = make_daemon(learning_promote_threshold=3)
    for _ in range(3):
        type_word(daemon, "vercel")
        daemon._handle_event(make_event("KEY_SPACE", 1))
    # A correct word is never rewritten, and after the threshold the detector
    # treats it as known vocabulary.
    assert _injector(daemon).replacements == []
    assert daemon.learning.learned_words() == ["vercel"]
    assert "vercel" in daemon.detector.vocabulary("en")
    assert daemon.learning.stats.promoted == 1


def test_daemon_disabled_learning_never_promotes() -> None:
    daemon = make_daemon(learning_enabled=False, learning_promote_threshold=1)
    for _ in range(3):
        type_word(daemon, "vercel")
        daemon._handle_event(make_event("KEY_SPACE", 1))
    assert daemon.learning.learned_words() == []
    assert daemon.learning.stats == LearningStats()


def test_learning_snapshot_is_metadata_only() -> None:
    daemon = make_daemon()
    type_word(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_SPACE", 1))
    snapshot = daemon.learning_snapshot()
    assert snapshot["corrected"] == 1
    assert "ghbdtn" not in json.dumps(snapshot)
    assert "привет" not in json.dumps(snapshot)


def test_profile_path_lives_under_the_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert profile_path() == tmp_path / "klyrshift" / "learning.json"
