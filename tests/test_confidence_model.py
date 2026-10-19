"""The calibrated confidence model (Stage 3).

The detector has always returned a raw plausibility *margin*, which is unbounded
and grows with the word count. That is fine as an internal gate but useless as a
number a user or the GUI can reason about. ``calibrated_confidence`` maps the
same decision onto ``[0, 1]`` and records *how* it was reached, so ``klyrshift
explain`` can answer "why did you (not) touch this word?" without re-running the
decision differently.
"""

from __future__ import annotations

import math

from klyrshift.converter import LayoutConverter
from klyrshift.detector import (
    EVIDENCE_MIXED_SCRIPT,
    EVIDENCE_MODEL,
    EVIDENCE_TAUGHT,
    EVIDENCE_VOCABULARY,
    Confidence,
    LanguageDetector,
)


def _detector(**kwargs: object) -> LanguageDetector:
    return LanguageDetector(converter=LayoutConverter(), stop_words=[], **kwargs)


# --- The value is a probability -------------------------------------------


def test_calibrated_confidence_stays_in_range() -> None:
    detector = _detector()
    for margin in (-5.0, -0.1, 0.0, 0.5, 1.0, 5.0, 50.0, math.inf):
        for text in ("a", "ab", "abcdef", "ghbdtn"):
            confidence = detector.calibrated_confidence(margin, text, "ru")
            assert 0.0 <= confidence.value <= 1.0, (margin, text)


def test_margin_monotonic_in_confidence() -> None:
    """A larger margin must never yield a smaller confidence."""
    detector = _detector()
    values = [
        detector.calibrated_confidence(margin, "ghbdtn", "ru").value
        for margin in (-3.0, -1.0, 0.0, 1.0, 2.0, 4.0, 8.0)
    ]
    assert values == sorted(values)
    assert values[0] < values[-1]


def test_infinite_margin_is_certain() -> None:
    detector = _detector()
    confidence = detector.calibrated_confidence(math.inf, "ghbdtn", "ru")
    assert confidence.value == 1.0


def test_short_buffer_is_penalised() -> None:
    """Same margin, shorter buffer -> lower confidence (more ambiguous)."""
    detector = _detector()
    long = detector.calibrated_confidence(2.0, "ghbdtn", "ru").value
    short = detector.calibrated_confidence(2.0, "abc", "ru").value
    assert short < long


def test_vocabulary_share_raises_confidence() -> None:
    """A target whose words are known scores higher than one that is not."""
    detector = _detector()
    known = detector.calibrated_confidence(1.0, "привет", "ru").value
    unknown = detector.calibrated_confidence(1.0, "ъъъъъъ", "ru").value
    assert known > unknown


# --- Evidence classification ----------------------------------------------


def test_analyze_reports_no_decision_with_zero_confidence() -> None:
    detector = _detector()
    confidence = detector.analyze("hello", "us")
    assert confidence.value == 0.0


def test_analyze_reports_vocabulary_evidence_for_a_known_conversion() -> None:
    """``ghbdtn`` -> ``привет`` is certain because the target is known words."""
    detector = _detector()
    confidence = detector.analyze("ghbdtn", "us")
    assert confidence.evidence == EVIDENCE_VOCABULARY
    assert confidence.is_certain
    assert confidence.value == 1.0


def test_analyze_reports_taught_evidence_for_a_user_word() -> None:
    """``муксуд`` typed on the Russian layout converts to the taught ``vercel``."""
    detector = _detector()
    detector.set_user_words(["vercel"])
    confidence = detector.analyze("муксуд", "ru")
    assert confidence.evidence == EVIDENCE_TAUGHT


def test_analyze_reports_model_evidence_for_a_scored_decision() -> None:
    detector = _detector()
    confidence = detector.analyze("привет", "ru")
    # ``привет`` is already Russian: no conversion, so no model confidence.
    assert confidence.evidence == EVIDENCE_MODEL


def test_describe_is_human_readable() -> None:
    detector = _detector()
    text = detector.analyze("ghbdtn", "us").describe()
    assert "уверенность" in text
    assert "%" in text


def test_is_certain_only_for_score_free_evidence() -> None:
    assert Confidence(1.0, math.inf, EVIDENCE_TAUGHT).is_certain
    assert Confidence(1.0, math.inf, EVIDENCE_VOCABULARY).is_certain
    assert Confidence(1.0, math.inf, EVIDENCE_MIXED_SCRIPT).is_certain
    assert not Confidence(0.7, 2.0, EVIDENCE_MODEL).is_certain
