"""Reproducible latency and memory measurement for the detector (Stage 7).

The quality numbers in TEST_STRATEGY.md cover correctness; this script covers
cost. It reports the two figures that a user actually feels and that a CI budget
can guard:

* **ms/word** -- time to decide one word, on a fixed slice of the shipped
  corpora, in both directions;
* **peak MiB** -- the detector's peak traced allocation while it is built and
  used, which is what a long-running daemon holds in memory.

Run with ``PYTHONPATH=src python scripts/measure_latency.py``. As with
``measure_detector.py``, only identical slices with identical conditions are
comparable.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from klyrshift.converter import LayoutConverter  # noqa: E402
from klyrshift.detector import LanguageDetector  # noqa: E402

CORPORA = REPO_ROOT / "dictionaries"
DIRECTIONS = (
    ("ru", "ru-50k.txt", "ru", "us"),
    ("en", "en-50k.txt", "us", "ru"),
)

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_LATIN = re.compile(r"[A-Za-z]")


def _read_words(name: str, limit: int) -> list[str]:
    path = CORPORA / name
    words = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [w for w in words if w][:limit]


def _same_script(word: str, script: re.Pattern[str]) -> bool:
    """True when ``word`` uses one script only; see ``measure_detector``."""
    return bool(script.search(word)) and not bool(
        (_LATIN if script is _CYRILLIC else _CYRILLIC).search(word)
    )


def _build_and_measure_memory(converter: LayoutConverter) -> tuple[LanguageDetector, float]:
    """Build the detector and return it with its peak traced allocation in MiB.

    ``tracemalloc`` is stopped before any timing runs: it hooks every
    allocation, so a loop measured under it reports the tracer's cost, not the
    detector's. Memory first, then speed.
    """
    tracemalloc.start()
    detector = LanguageDetector(converter=converter)
    # Touch the detector once so lazy corpus loading is counted rather than
    # deferred to the first timed word.
    detector.target_layout("ghbdtn", "us")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return detector, peak / 1024 / 1024


def measure(limit: int, repeats: int) -> int:
    converter = LayoutConverter()
    detector, peak_mib = _build_and_measure_memory(converter)

    header = f"{'direction':<16}{'words':>8}{'ms/word':>11}"
    print(f"slice: top {limit} words per corpus, {repeats} repeats\n")
    print(header)
    print("-" * len(header))

    for language, corpus, own, other in DIRECTIONS:
        script = _CYRILLIC if own == "ru" else _LATIN
        words = [w for w in _read_words(corpus, limit) if _same_script(w, script)]
        wrong = [converter.convert(word, own, other) for word in words]

        started = time.perf_counter()
        for _ in range(repeats):
            for typed in wrong:
                detector.target_layout(typed, other)
        elapsed = time.perf_counter() - started
        per_word_ms = elapsed / max(len(wrong) * repeats, 1) * 1000
        print(f"{language + ' on ' + other:<16}{len(wrong):>8}{per_word_ms:>11.4f}")

    print(f"\npeak traced memory: {peak_mib:.1f} MiB")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000, help="words per corpus")
    parser.add_argument("--repeats", type=int, default=3, help="timed passes over the slice")
    args = parser.parse_args()
    return measure(args.limit, args.repeats)


if __name__ == "__main__":
    raise SystemExit(main())
