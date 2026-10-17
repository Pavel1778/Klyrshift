"""Reproducible detector quality measurement (Stage H).

Reports, on fixed slices of the shipped corpora:

* **recall** -- share of target-language words typed on the wrong layout that
  ``target_layout`` sends back to the right layout;
* **false positives** -- share of real words, typed correctly, that
  ``target_layout`` would still move to another layout (a wrong fix);
* **corruption** -- conversions where the result is not a pure layout
  substitution of the input (a lost or mangled character).

Run with ``PYTHONPATH=src python scripts/measure_detector.py``. The slice size
is fixed on the command line so two runs are comparable; different slices are
not.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from klyrshift.converter import LayoutConverter  # noqa: E402
from klyrshift.detector import LanguageDetector  # noqa: E402

CORPORA = REPO_ROOT / "dictionaries"
# (corpus language, corpus file, the word's own layout, the layout typed by mistake)
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
    """True when ``word`` uses one script only.

    The shipped corpora carry a few loanwords in the other script (``the``,
    ``you`` inside the Russian list). They are not layout targets and would be
    counted as "corruption" if the round trip were applied to them, so the
    measurement keeps to words written in the corpus's own script.
    """
    return bool(script.search(word)) and not bool(
        (_LATIN if script is _CYRILLIC else _CYRILLIC).search(word)
    )


def measure(limit: int) -> int:
    detector = LanguageDetector()
    converter = LayoutConverter()

    print(f"slice: top {limit} words per corpus\n")
    header = (
        f"{'direction':<16}{'recall':>9}{'missed':>9}{'falsepos':>10}{'corrupt':>9}{'ms/word':>10}"
    )
    print(header)
    print("-" * len(header))

    for language, corpus, own, other in DIRECTIONS:
        script = _CYRILLIC if own == "ru" else _LATIN
        words = [w for w in _read_words(corpus, limit) if _same_script(w, script)]

        hit = missed = corrupt = 0
        started = time.perf_counter()
        for word in words:
            wrong = converter.convert(word, own, other)
            if detector.target_layout(wrong, other) == own:
                hit += 1
            else:
                missed += 1
            # A character is lost or mangled when the round trip does not restore
            # the original word.
            if converter.convert(wrong, other, own) != word:
                corrupt += 1
        elapsed = time.perf_counter() - started

        # A real word typed correctly in its own layout must not be moved.
        false_positives = sum(
            1 for word in words if detector.target_layout(word, own) not in (None, own)
        )

        total = len(words)
        recall = 100.0 * hit / total if total else 0.0
        fp_rate = 100.0 * false_positives / total if total else 0.0
        ms = 1000.0 * elapsed / total if total else 0.0
        print(
            f"{language + ' on ' + other:<16}{recall:>8.1f}%{missed:>9}"
            f"{fp_rate:>9.1f}%{corrupt:>9}{ms:>10.3f}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000, help="words per corpus")
    args = parser.parse_args()
    return measure(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
