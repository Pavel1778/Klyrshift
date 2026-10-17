"""Regression tests for the false-positive guards (task A).

Text that already reads as real words in the layout it was typed in must never
be rewritten, however plausible another layout looks. These tests pin the three
guards: plausibility, structural boundaries and identifier detection.
"""

from __future__ import annotations

import pytest

from klyrshift.converter import LayoutConverter
from klyrshift.detector import LanguageDetector


@pytest.fixture
def det() -> LanguageDetector:
    """Return a detector with the bundled corpora and no stop words."""
    return LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)


# --- the reported false positive -------------------------------------------------

# Typed in the Russian layout, this is a symbol-heavy string that the detector
# used to convert to the US layout. It must be left alone.
FALSE_POSITIVES = [
    ("сb cj,jq?ye;yjn/g/", "ru"),
    ("github.com", "us"),
    ("user@example.com", "us"),
    ("3.14", "us"),
    ("snake_case", "us"),
    ("camelCase", "us"),
    ("x86_64", "us"),
    ("https://example.com/path", "us"),
    ("/usr/local/bin", "us"),
    ("my-var", "us"),
]


@pytest.mark.parametrize(("text", "layout"), FALSE_POSITIVES)
def test_false_positives_are_left_alone(det: LanguageDetector, text: str, layout: str) -> None:
    assert det.target_layout(text, layout) is None


@pytest.mark.parametrize(("text", "layout"), FALSE_POSITIVES)
def test_false_positives_never_flagged(det: LanguageDetector, text: str, layout: str) -> None:
    assert det.should_fix(text, layout) is False


# --- the genuine wrong-layout words must still be fixed --------------------------


@pytest.mark.parametrize(
    ("text", "layout", "expected"),
    [
        ("ghbdtn", "us", "ru"),
        ("руддщ", "ru", "us"),
        ("Руддщ", "ru", "us"),
        ("привет", "us", "ru"),
        ("hello", "ru", "us"),
        ("ghbdtn vbh", "us", "ru"),
        ("Руддщ цщкл", "ru", "us"),
    ],
)
def test_real_wrong_layout_words_are_still_fixed(
    det: LanguageDetector, text: str, layout: str, expected: str
) -> None:
    assert det.target_layout(text, layout) == expected


def test_rare_real_word_is_protected(det: LanguageDetector) -> None:
    """A real but uncommon Russian word must not be "corrected" into noise."""
    assert det.target_layout("нот", "ru") is None


# --- guards can be disabled independently ----------------------------------------


def test_plausibility_guard_can_be_disabled() -> None:
    guarded = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    unguarded = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=[],
        min_word_length=3,
        plausibility_check=False,
        structural_boundaries=False,
        identifier_guard=False,
    )
    # With every guard off, the reported phrase converts again: this proves the
    # guards, not some other change, are what suppress it. (A pure-Cyrillic
    # sample is used because a mixed-script token is skipped by a separate,
    # independent rule that stays on even when these guards are disabled.)
    sample = "ыв сл,дж?ые;ынп/g/"
    assert guarded.target_layout(sample, "ru") is None
    assert unguarded.target_layout(sample, "ru") is not None


def test_structural_boundary_guard_ignores_urls() -> None:
    det = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    assert det._has_structural_marker("github.com") is True
    assert det._has_structural_marker("user@example.com") is True
    assert det._has_structural_marker("hello") is False
    assert det._has_structural_marker("привет") is False


def test_identifier_guard_detects_code_tokens() -> None:
    det = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    for token in ("snake_case", "camelCase", "x86_64", "A1", "my-var"):
        assert det._has_structural_marker(token) or det._should_guard(token, "us")
    # Plain words are not identifiers.
    assert det._should_guard("ghbdtn", "us") is False


def test_taught_word_wins_over_plausibility_guard() -> None:
    """A user-taught word must be fixed even if the source looks plausible."""
    det = LanguageDetector(
        converter=LayoutConverter(), stop_words=[], min_word_length=3, user_words=["vercel"]
    )
    assert det.target_layout("муксуд", "ru") == "us"


# --- a real wrong-layout word whose source spelling looks plausible --------------
#
# ``ltym`` is not an English word, but its bigram score clears the plausibility
# floor, so the false-positive guard used to veto the conversion even though
# ``день`` is a common Russian word. A conversion that yields *only* known
# words of the target language is stronger evidence than the source's
# plausibility, so it now overrides the guard. These cases include letters whose
# US keys are punctuation (``;`` -> ``ж``, ``[`` -> ``х``), which the word tokenizer
# splits, so the whole-token vocabulary check is what makes them work.


@pytest.mark.parametrize(
    ("typed", "layout", "expected"),
    [
        ("ltym", "us", "ru"),
        (",eltn", "us", "ru"),
        ("vj;tn", "us", "ru"),
        ("ye;yj", "us", "ru"),
        ("b[", "us", None),
    ],
)
def test_plausible_source_word_is_still_corrected(
    det: LanguageDetector, typed: str, layout: str, expected: str | None
) -> None:
    assert det.target_layout(typed, layout) == expected


@pytest.mark.parametrize(
    ("typed", "layout", "expected"),
    [
        ("ltym", "us", "день"),
        (",eltn", "us", "будет"),
        ("vj;tn", "us", "может"),
        ("ye;yj", "us", "нужно"),
    ],
)
def test_plausible_source_word_converts_to_the_expected_word(
    det: LanguageDetector, typed: str, layout: str, expected: str
) -> None:
    target = det.target_layout(typed, layout)
    assert target is not None
    assert det.convert_buffer(typed, layout, target) == expected


def test_vocabulary_validated_override_respects_a_real_source_word(
    det: LanguageDetector,
) -> None:
    """A word that really is a current-layout word is never overridden."""
    # Short pairs such as ``lf`` -> ``да`` stay on the explicit-hotkey path; a
    # full-length real word must stay put here.
    assert det._vocabulary_validated_layout("hello", "us") is None
    assert det._vocabulary_validated_layout("привет", "ru") is None
    assert det.target_layout("hello", "us") is None


def test_vocabulary_validated_override_is_not_applied_to_urls(
    det: LanguageDetector,
) -> None:
    """The override must not resurrect a structural false positive."""
    for token in ("github.com", "user@example.com", "/usr/local/bin", "snake_case"):
        assert det._vocabulary_validated_layout(token, "us") is None
