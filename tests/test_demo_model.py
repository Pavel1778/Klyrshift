"""The landing-page demo model must stay in sync with the shipped corpora.

The demo ports the detector's per-word plausibility test to TypeScript so a
visitor can try it without installing anything. Its inputs (the vocabulary and
bigram tables) are generated from ``src/lingvix/data/ngrams_*.json`` by
``scripts/build_demo_model.py``. If a corpus is rebuilt and the generated file
is not, the demo silently disagrees with the product it advertises -- it would
start "correcting" words the daemon leaves alone. This test regenerates the
model in memory and fails when the committed file differs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_demo_model.py"
MODEL_FILE = REPO_ROOT / "site" / "src" / "data" / "demo-model.json"


def _load_builder() -> ModuleType:
    """Import ``scripts/build_demo_model.py`` without it being a package."""
    spec = importlib.util.spec_from_file_location("build_demo_model", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_model_matches_shipped_corpora() -> None:
    builder = _load_builder()
    expected = {lang: builder.build(lang) for lang in builder.LANGUAGES}
    committed = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    assert committed == expected, (
        "site/src/data/demo-model.json is stale; run "
        "`python scripts/build_demo_model.py` and commit the result"
    )


@pytest.mark.parametrize("language", ["ru", "en"])
def test_model_has_vocabulary_and_bigrams(language: str) -> None:
    """A missing half would make every word look implausible (or plausible)."""
    model = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    assert model[language]["words"], f"{language}: empty vocabulary"
    assert model[language]["bigrams"], f"{language}: empty bigram table"
