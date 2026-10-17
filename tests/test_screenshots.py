"""The README screenshots must be real renders of the real GUI.

They were SVG placeholders with a note telling the reader to replace them, which
is a promise the repository never kept. ``scripts/make_screenshots.py`` now
builds the actual ``LingvixWindow`` and renders it, so these tests fail if the
PNGs are deleted, replaced by placeholders, or dropped from the README.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = REPO_ROOT / "docs" / "screenshots"
README = REPO_ROOT / "README.md"

EXPECTED = ("main-window.png", "advanced-settings.png", "dictionary.png")


def _png_info(path: Path) -> tuple[int, int, int]:
    """Return ``(width, height, distinct_colours)`` for a PNG file.

    Colour count is sampled on a grid; a real render has hundreds of shades
    (text antialiasing, gradients), a placeholder or a blank frame has a handful.
    """
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    pos = 8
    width = height = colour_type = 0
    idat = b""
    while pos < len(raw):
        length = struct.unpack(">I", raw[pos : pos + 4])[0]
        chunk = raw[pos + 4 : pos + 8]
        data = raw[pos + 8 : pos + 8 + length]
        if chunk == b"IHDR":
            width, height, _, colour_type = struct.unpack(">IIBB", data[:10])
        elif chunk == b"IDAT":
            idat += data
        elif chunk == b"IEND":
            break
        pos += 12 + length

    pixels = zlib.decompress(idat)
    bpp = 4 if colour_type == 6 else 3
    stride = width * bpp + 1
    colours = set()
    for y in range(0, height, 5):
        row = y * stride
        for x in range(0, width, 5):
            i = row + 1 + x * bpp
            colours.add(bytes(pixels[i : i + 3]))
    return width, height, len(colours)


@pytest.mark.parametrize("name", EXPECTED)
def test_screenshot_is_a_real_render(name: str) -> None:
    path = SCREENSHOT_DIR / name
    assert path.is_file(), f"{name} missing; run scripts/make_screenshots.py"

    width, height, colours = _png_info(path)
    assert width >= 800 and height >= 600, (name, width, height)
    # A flat placeholder has a couple of colours; a real GTK render has many.
    assert colours > 50, f"{name} looks blank/placeholder ({colours} colours)"


def test_readme_shows_the_screenshots() -> None:
    text = README.read_text(encoding="utf-8")
    for name in EXPECTED:
        assert f"docs/screenshots/{name}" in text, name
    assert "docs/screenshots/main-window.svg" not in text


def test_no_placeholder_screenshot_assets_remain() -> None:
    """The unused site SVG mock-ups are gone; nothing should reintroduce them."""
    stale = list((REPO_ROOT / "site" / "public" / "screenshots").glob("*.svg"))
    assert stale == [], stale
