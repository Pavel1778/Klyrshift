#!/usr/bin/env python3
"""Generate ``site/src/data/demo-model.json`` for the landing-page demo.

The demo runs the same per-word plausibility test as the daemon, so it needs the
same inputs: a frequency vocabulary and a character-bigram model per language.
Both are derived here from the shipped corpora (``src/lingvix/data/ngrams_*.json``,
which ``scripts/build_corpora.py`` builds from the dictionaries). Keeping it
generated means the demo can never drift from the shipped model.

The bigram tables are small (a few hundred entries each), so the full model is
shipped; only the vocabulary is trimmed, because the demo never needs the long
tail.

Usage::

    python scripts/build_demo_model.py
"""

from __future__ import annotations

import json
from pathlib import Path

# The two languages enabled out of the box (``Config.languages`` defaults to
# en+ru). Shipping all five would double the bundle to serve a demo of a feature
# the default install does not even turn on.
LANGUAGES = ("ru", "en")
# Words kept per language. The demo only needs the common words a visitor is
# likely to type; a larger list would bloat the page bundle for no gain.
VOCAB_LIMIT = 3000
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "src" / "lingvix" / "data"


def build(language: str) -> dict[str, object]:
    """Return the trimmed vocabulary and full bigram table for ``language``."""
    corpus = json.loads((DATA_DIR / f"ngrams_{language}.json").read_text(encoding="utf-8"))
    words = [str(w).lower() for w in corpus.get("words", [])][:VOCAB_LIMIT]
    bigrams = {str(k): float(v) for k, v in corpus.get("bigrams", {}).items()}
    return {"words": words, "bigrams": bigrams}


def main() -> int:
    model = {lang: build(lang) for lang in LANGUAGES}
    destination = ROOT / "site" / "src" / "data" / "demo-model.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(model, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    summary = ", ".join(
        f"{lang}: {len(payload['words'])} words, {len(payload['bigrams'])} bigrams"  # type: ignore[arg-type]
        for lang, payload in model.items()
    )
    print(f"Wrote {destination.relative_to(ROOT)} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
