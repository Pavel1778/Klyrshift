"""The landing-page demo must correct exactly what the daemon corrects.

``site/src/components/Demo.astro`` reimplements the detector in TypeScript, so
it can silently drift from the product it advertises: an earlier revision had no
vocabulary-validated override, so the demo left ``ltym`` alone while the daemon
rewrote it to ``день``. The demo's per-token decision is executed here with Node
and compared against the real ``LanguageDetector``; the test skips when Node is
unavailable (it runs in CI's ``site`` job, which has it).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from lingvix.converter import LayoutConverter
from lingvix.detector import LanguageDetector

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "site" / "src" / "components" / "Demo.astro"
MODEL = REPO_ROOT / "site" / "src" / "data" / "demo-model.json"

# Typed on US (Latin) and on RU (Cyrillic), plus tokens every guard must leave
# alone. Each pair is (token, layout it was typed in).
CASES: list[tuple[str, str]] = [
    ("ghbdtn", "us"),  # привет
    ("ltym", "us"),  # день — the vocabulary-validated override
    (",eltn", "us"),  # будет — same override
    ("руддщ", "ru"),  # hello
    ("Rfr", "us"),  # Как
    ("привет", "ru"),  # already correct, left alone
    ("hello", "us"),  # already correct, left alone
    ("https://example.com", "us"),
    ("snake_case", "us"),
    ("x86_64", "us"),
    ("v0.2.8.2", "us"),
    ("user@host.tld", "us"),
]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    return node


def _extract_script() -> str:
    """Return the demo's inline script, adapted to run under plain Node.

    The component's script is a module: it imports the JSON model and then binds
    to the DOM. The tail from the first ``document.getElementById`` is dropped,
    and the import is rewritten to a ``require`` so the file runs as a CommonJS
    script in a temporary directory.
    """
    source = DEMO.read_text(encoding="utf-8")
    body = re.search(r"<script>(.*?)</script>", source, re.S)
    assert body is not None, "Demo.astro has no inline <script>"
    script = body.group(1)
    cut = script.index("const input = document.getElementById")
    head = script[:cut].replace(
        'import model from "../data/demo-model.json";',
        f'const model = JSON.parse(require("fs").readFileSync({str(MODEL)!r}, "utf8"));',
    )
    return head


def _demo_convert(tokens: list[str], tmp_dir: Path) -> dict[str, str]:
    """Run the demo's ``convert()`` over ``tokens`` and return its output."""
    harness = (
        _extract_script()
        + "\nconst tokens = "
        + json.dumps(tokens)
        + ";\nconsole.log(JSON.stringify(Object.fromEntries(tokens.map((t) => [t, convert(t)]))));\n"
    )
    path = tmp_dir / "demo_harness.ts"
    path.write_text(harness, encoding="utf-8")
    result = subprocess.run(
        [_node(), str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    parsed: dict[str, str] = json.loads(result.stdout)
    return parsed


def _detector() -> LanguageDetector:
    return LanguageDetector(converter=LayoutConverter(), stop_words=set(), min_word_length=3)


def _expected(detector: LanguageDetector, token: str, current: str) -> str:
    """What the daemon would put on screen for ``token`` typed in ``current``."""
    target = detector.target_layout(token, current)
    if target is None or target == current:
        return token
    return detector.converter.convert(token, current, target)


def test_demo_matches_detector_on_every_case(tmp_path: Path) -> None:
    detector = _detector()
    tokens = [token for token, _ in CASES]
    demo = _demo_convert(tokens, tmp_path)

    mismatches: list[str] = []
    for token, current in CASES:
        expected = _expected(detector, token, current)
        if demo[token] != expected:
            mismatches.append(
                f"{token!r} typed in {current}: demo={demo[token]!r} daemon={expected!r}"
            )
    assert not mismatches, "the demo disagrees with the detector:\n" + "\n".join(mismatches)
    # The override cases are the regression this test exists for; assert the
    # demo does not merely echo them back.
    assert demo["ltym"] != "ltym"
    assert detector.target_layout("ltym", "us") is not None
