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


def test_promote_adds_a_word_immediately() -> None:
    """``promote`` is the manual counterpart of the automatic promotion."""
    engine = LearningEngine(promote_threshold=99, store=LearningStore(path=Path("/nonexistent")))
    assert engine.learned_words() == []
    assert engine.promote("vercel") is True
    assert engine.learned_words() == ["vercel"]
    assert engine.is_promoted("vercel") is True
    # Promoting the same word twice is a no-op, not a duplicate.
    assert engine.promote("vercel") is False
    assert engine.learned_words() == ["vercel"]


def test_promote_rejects_non_words() -> None:
    engine = LearningEngine(store=LearningStore(path=Path("/nonexistent")))
    assert engine.promote("") is False
    assert engine.promote("   ") is False
    assert engine.promote("два слова") is False
    assert engine.learned_words() == []


def test_forget_removes_a_promoted_word() -> None:
    engine = LearningEngine(store=LearningStore(path=Path("/nonexistent")))
    engine.promote("vercel")
    assert engine.forget("vercel") is True
    assert engine.learned_words() == []
    assert engine.is_promoted("vercel") is False
    # Forgetting a word that is not present changes nothing.
    assert engine.forget("vercel") is False


def test_forget_clears_a_suppressed_word() -> None:
    """A word the user once rejected can be un-rejected by hand."""
    engine = LearningEngine(store=LearningStore(path=Path("/nonexistent")))
    engine.observe_rejected("ghbdtn")
    assert engine.is_suppressed("ghbdtn") is True
    assert engine.forget("ghbdtn") is True
    assert engine.is_suppressed("ghbdtn") is False


def test_promote_evicts_when_at_capacity() -> None:
    """A promoted word never pushes the vocabulary past ``max_words``."""
    engine = LearningEngine(max_words=2, store=LearningStore(path=Path("/nonexistent")))
    engine.promote("один")
    engine.promote("два")
    engine.promote("три")
    assert len(engine.learned_words()) == 2
    assert engine.is_promoted("три") is True


def test_control_handler_lists_promotes_and_forgets() -> None:
    """The daemon's control handler drives the real learning engine."""
    daemon = make_daemon()
    assert daemon._handle_control_request({"cmd": "learn.list"}) == {"words": []}

    promoted = daemon._handle_control_request({"cmd": "learn.promote", "word": "vercel"})
    assert promoted["ok"] is True
    assert promoted["changed"] is True
    assert daemon.learning.learned_words() == ["vercel"]
    # The detector's vocabulary was refreshed, so the word is now "known".
    assert daemon._handle_control_request({"cmd": "learn.list"}) == {"words": ["vercel"]}

    forgotten = daemon._handle_control_request({"cmd": "learn.forget", "word": "vercel"})
    assert forgotten["ok"] is True
    assert forgotten["changed"] is True
    assert daemon.learning.learned_words() == []


def test_control_handler_rejects_a_missing_word() -> None:
    daemon = make_daemon()
    assert daemon._handle_control_request({"cmd": "learn.promote"}) == {"error": "missing word"}
    assert daemon._handle_control_request({"cmd": "nonsense", "word": "x"}) == {
        "error": "unknown command"
    }


def test_forgetting_the_last_word_clears_the_detector_vocabulary() -> None:
    """The early-return bug: forgetting the only word must still update the detector."""
    daemon = make_daemon()
    daemon._handle_control_request({"cmd": "learn.promote", "word": "vercel"})
    assert daemon.detector._learned_words == {"vercel"}
    daemon._handle_control_request({"cmd": "learn.forget", "word": "vercel"})
    assert daemon.detector._learned_words == set()
