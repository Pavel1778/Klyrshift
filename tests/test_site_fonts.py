"""The landing page's web fonts must be requested as variable ranges.

All three families are variable fonts: one file per subset carries a ``wght``
axis, which is why the build emits a single ``.woff2`` per family and subset.
``astro.config.mjs`` nonetheless listed discrete weights. That produced two
defects that no build step catches:

* one ``@font-face`` per weight, all pointing at the same file (36 blocks where
  12 suffice), and
* no face at all for a weight outside the list -- ``.font-mono.font-bold`` in
  ``dictionaries.astro`` asks for 700 while JetBrains Mono declared only 400 and
  500, so Chromium synthesised a smeared faux-bold from the 500 file.

These tests pin the range form and check that each range covers the weights the
components actually ask for, so shrinking a range back below a used weight fails
here instead of silently degrading the rendering.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
CONFIG = SITE / "astro.config.mjs"

# Tailwind weight utilities mapped to the numeric weight they apply.
_WEIGHT_CLASSES = {
    "font-normal": 400,
    "font-medium": 500,
    "font-semibold": 600,
    "font-bold": 700,
    "font-extrabold": 800,
}

_RANGE = re.compile(r"^(\d{3})\s+(\d{3})$")


def _font_entries() -> list[dict[str, object]]:
    """Parse the ``fonts: [...]`` array of ``astro.config.mjs``.

    The file is JavaScript, but the array is plain data, so it is read with a
    small scanner rather than by importing a Node toolchain into the test run.
    """
    text = CONFIG.read_text(encoding="utf-8")
    start = text.index("fonts: [")
    body = text[start:]
    entries: list[dict[str, object]] = []
    for block in re.findall(r"\{\s*provider:.*?\n    \}", body, re.S):
        name = re.search(r'name:\s*"([^"]+)"', block)
        var = re.search(r'cssVariable:\s*"([^"]+)"', block)
        weights = re.search(r"weights:\s*\[([^\]]*)\]", block)
        if not (name and var and weights):
            continue
        raw = [w.strip().strip('"') for w in weights.group(1).split(",") if w.strip()]
        entries.append({"name": name.group(1), "var": var.group(1), "weights": raw})
    return entries


def _sources() -> list[Path]:
    """Every Astro file that can carry a font utility class."""
    return sorted((SITE / "src").rglob("*.astro"))


def test_all_families_are_requested_as_weight_ranges() -> None:
    """A discrete weight list is the bug this file exists to prevent."""
    entries = _font_entries()
    assert entries, "could not parse any font from astro.config.mjs"
    offenders = [
        f"{e['name']}: {e['weights']}"
        for e in entries
        if not all(_RANGE.match(str(w)) for w in e["weights"])
    ]
    assert not offenders, (
        "these families are variable fonts and must be requested as a range "
        '(e.g. "400 700") so one file serves every weight and no weight falls '
        "back to a synthesised faux-bold:\n" + "\n".join(offenders)
    )


def test_mono_range_covers_the_bold_weight_it_is_used_at() -> None:
    """``font-mono`` is paired with ``font-bold``, which the range must include.

    This is the concrete regression: JetBrains Mono declared 400-500 while
    ``dictionaries.astro`` asked for 700 on the same element.
    """
    mono = next(e for e in _font_entries() if "Mono" in str(e["name"]))
    low, high = _range_bounds(mono)
    required = {
        _WEIGHT_CLASSES[cls]
        for path in _sources()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "font-mono" in line
        for cls in _WEIGHT_CLASSES
        if cls in line
    }
    assert required, "expected at least one weighted font-mono usage to check"
    missing = sorted(w for w in required if not low <= w <= high)
    assert not missing, (
        f"{mono['name']} declares {mono['weights']} but is used at weight(s) "
        f"{missing}; those render as synthesised bold"
    )


def test_display_range_covers_the_heading_weights() -> None:
    """Headings use the display face at semibold, bold and extrabold."""
    display = next(e for e in _font_entries() if "Unbounded" in str(e["name"]))
    low, high = _range_bounds(display)
    required = {
        _WEIGHT_CLASSES[cls]
        for path in _sources()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "<h1" in line or "<h2" in line or "<h3" in line
        for cls in _WEIGHT_CLASSES
        if cls in line
    }
    missing = sorted(w for w in required if not low <= w <= high)
    assert not missing, (
        f"{display['name']} declares {display['weights']} but headings use " f"weight(s) {missing}"
    )


def _range_bounds(entry: dict[str, object]) -> tuple[int, int]:
    """Return the low/high weight of a range-form family."""
    weights = entry["weights"]
    assert (
        isinstance(weights, list) and len(weights) == 1
    ), f"{entry['name']} must declare exactly one weight range, got {weights}"
    match = _RANGE.match(str(weights[0]))
    assert match, f"{entry['name']} weights {weights[0]!r} is not a 'low high' range"
    return int(match.group(1)), int(match.group(2))
