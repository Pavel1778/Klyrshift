"""The social preview image must be a real render and must not carry the old name.

``site/public/og-image.png`` is what every link preview shows, but it was
produced by hand before the ``LinguaFix`` -> ``Klyrshift`` rename, so the old name
survived in the one asset a search engine and a chat client display. The
generator (``scripts/make_og_image.py``) now builds it from the landing page's
own logo and webfonts, and these tests fail if the card is replaced by a blank,
resized, or rendered from the wrong brand string.
"""

from __future__ import annotations

import importlib.util
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OG_IMAGE = REPO_ROOT / "site" / "public" / "og-image.png"
GENERATOR = REPO_ROOT / "scripts" / "make_og_image.py"
BASE_LAYOUT = REPO_ROOT / "site" / "src" / "layouts" / "Base.astro"

EXPECTED_SIZE = (1200, 630)


def _png_info(path: Path) -> tuple[int, int, int]:
    """Return ``(width, height, distinct_colours)``, sampled on a grid."""
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


def test_og_image_is_a_real_render_at_the_expected_size() -> None:
    assert OG_IMAGE.is_file(), "site/public/og-image.png missing"
    width, height, colours = _png_info(OG_IMAGE)
    assert (width, height) == EXPECTED_SIZE, (width, height)
    # A hand-made flat card has a handful of colours; a text render has many.
    assert colours > 50, f"og-image looks blank ({colours} colours)"


def _load_generator() -> ModuleType:
    """Import ``scripts/make_og_image.py`` without it being a package."""
    spec = importlib.util.spec_from_file_location("make_og_image", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_builds_the_card_from_the_current_brand() -> None:
    generator = _load_generator()
    try:
        html = generator.build_html()
    except generator.SiteNotBuilt as exc:
        pytest.skip(f"site not built: {exc}")
    assert "Klyrshift" in html
    assert "LinguaFix" not in html, "the card still renders an old name"
    assert "Lingvix" not in html, "the card still renders an intermediate name"
    # The card must come from the shipped logo and the site's own webfonts, so
    # a rebrand or a font change reaches the preview without a manual redraw.
    assert "<svg" in html
    assert "@font-face" in html


def test_layout_serves_the_png_preview() -> None:
    text = BASE_LAYOUT.read_text(encoding="utf-8")
    assert "/og-image.png" in text
    assert "og:image" in text and "twitter:image" in text


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_og_image_does_not_show_the_old_name() -> None:
    """OCR the rendered card, since the defect was a text string in a bitmap."""
    result = subprocess.run(
        ["tesseract", str(OG_IMAGE), "-", "--psm", "6"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout.replace(" ", "").lower()
    assert "linguafix" not in text, result.stdout
    assert "klyrshift" in text, f"brand not found in OCR output: {result.stdout!r}"
