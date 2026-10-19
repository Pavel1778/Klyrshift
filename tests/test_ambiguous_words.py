"""A token that is a real word in both layouts is never rewritten (Stage 7).

The detector benchmark measures recall and false positives on words from one
language at a time. That misses the hardest class: a token whose layout
conversion is *also* a real word of the other language. ``руку`` converts to
``here``; ``that`` converts to ``that``. A detector that only asks "is the
target plausible?" rewrites both, and the user watches a correct word change
under the caret.

These tests pin the stronger property: when a token is a known word in the
layout it was typed in, it stays put -- whatever the other layout would make of
it. That is why membership is checked before plausibility, and it is worth a
sweep rather than a hand-written list, because a collision is rare enough to be
missed by review and common enough to hit a real user.
"""

from __future__ import annotations

import pytest

from klyrshift.converter import LayoutConverter
from klyrshift.detector import LanguageDetector


def _detector() -> LanguageDetector:
    """Return a detector with the shipped corpora and no stop words.

    Stop words are excluded so the membership check below is the only thing
    protecting the token; a stop word would be left alone for a different
    reason and would hide a regression in this guard.
    """
    return LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)


def _collisions(
    detector: LanguageDetector, converter: LayoutConverter
) -> list[tuple[str, str, str]]:
    """Return ``(typed, layout, converted)`` for every cross-layout collision.

    Both directions are covered: a Russian word whose US-layout form is an
    English word, and the reverse. Only pairs where *both* spellings are in the
    detector's own vocabularies are returned, because that is the case the guard
    promises to protect.
    """
    russian = detector.vocabulary("ru")
    english = detector.vocabulary("en")
    pairs: list[tuple[str, str, str]] = []

    for word in russian:
        latin = converter.convert(word, "ru", "us")
        if latin in english:
            pairs.append((word, "ru", latin))
    for word in english:
        cyrillic = converter.convert(word, "us", "ru")
        if cyrillic in russian:
            pairs.append((word, "us", cyrillic))
    return pairs


def test_the_sweep_finds_real_collisions() -> None:
    """Guard the guard: an empty sweep would make the tests below vacuous."""
    assert _collisions(_detector(), LayoutConverter())


def test_a_known_word_in_both_languages_is_never_converted() -> None:
    """Every collision is left alone, in both spellings and both directions."""
    detector = _detector()
    converter = LayoutConverter()
    violations: list[tuple[str, str, str]] = []

    for typed, layout, converted in _collisions(detector, converter):
        other = "us" if layout == "ru" else "ru"
        if detector.target_layout(typed, layout) is not None:
            violations.append((typed, layout, "typed"))
        if detector.target_layout(converted, other) is not None:
            violations.append((converted, other, "converted"))

    assert violations == []


@pytest.mark.parametrize(
    ("typed", "layout", "converted"),
    [
        ("руку", "ru", "here"),
        ("that", "us", "that"),
        ("here", "us", "руку"),
    ],
)
def test_a_named_collision_stays_put(typed: str, layout: str, converted: str) -> None:
    """The sweep's contract, spelled out on the pairs that motivated it."""
    detector = _detector()
    language = detector._layout_language(layout)
    assert language is not None and typed in detector.vocabulary(language)
    assert detector.target_layout(typed, layout) is None
    assert detector.target_layout(converted, "us" if layout == "ru" else "ru") is None
