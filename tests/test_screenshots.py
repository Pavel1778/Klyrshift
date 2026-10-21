"""The README screenshots must be real renders of the real GUI.

They were SVG placeholders with a note telling the reader to replace them, which
is a promise the repository never kept. ``scripts/make_screenshots.py`` now
builds the actual ``KlyrshiftWindow`` and renders it, so these tests fail if the
PNGs are deleted, replaced by placeholders, or dropped from the README.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
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


def _render_script() -> Path:
    return REPO_ROOT / "scripts" / "make_screenshots.py"


def test_render_disables_blink_and_transitions() -> None:
    """The render must freeze both the view transition and the text caret.

    ``Adw.ViewStack`` cross-fades a page switch and a focused entry keeps a
    blinking caret; either one lands at a different point in its animation on a
    re-run and the PNG then differs by a handful of antialiasing levels. The
    capture is only reproducible if both are turned off first.
    """
    source = _render_script().read_text(encoding="utf-8")
    assert "gtk-cursor-blink" in source
    assert "set_enable_transitions(False)" in source


def test_render_captures_the_advanced_page() -> None:
    """``advanced-settings.png`` must be the "Продвинутые" page, not "Настройки".

    The name and the ``docs/screenshots/README.md`` table promise the advanced
    page (Детектор / Триггеры / раскладка по приложениям / исключения), but the
    window keeps that page out of the switcher until it is revealed. Rendering
    the plain ``settings`` page under this name produced a screenshot that
    contradicted its own caption.
    """
    source = _render_script().read_text(encoding="utf-8")
    assert '("advanced", "advanced-settings.png")' in source
    assert '("settings", "advanced-settings.png")' not in source


def test_render_suppresses_both_first_run_offers() -> None:
    """Neither the wizard nor the tour may cover a page.

    Both are first-run offers that ``KlyrshiftWindow`` raises on a fresh state,
    and the wizard is versioned separately from the tour, so marking only the
    tour as seen still let the wizard cover the window on the machine's
    onboarding state instead of the code.
    """
    source = _render_script().read_text(encoding="utf-8")
    assert "wizard_completed_version" in source
    assert "wizard_skipped_version" in source


@pytest.mark.skipif(
    not os.environ.get("KLYRSHIFT_RENDER_TEST"),
    reason="renders the GUI; set KLYRSHIFT_RENDER_TEST=1 under a display to run",
)
def test_screenshots_render_byte_identically(tmp_path: Path) -> None:
    """Two renders of the same code must produce byte-identical PNGs.

    This is the regression guard for the animation jitter: with the transitions
    and the caret left running the two runs disagree, and the committed
    screenshots silently drift every time they are regenerated.
    """
    if shutil.which("xvfb-run") is None:
        pytest.skip("xvfb-run not installed")
    first = tmp_path / "a"
    second = tmp_path / "b"
    env = dict(os.environ)
    env["PYTHONPATH"] = "/usr/lib/python3/dist-packages"
    for out in (first, second):
        subprocess.run(
            ["xvfb-run", "-a", sys.executable, str(_render_script()), str(out)],
            check=True,
            env=env,
            capture_output=True,
        )
    for name in EXPECTED:
        a = (first / name).read_bytes()
        b = (second / name).read_bytes()
        assert a == b, f"{name} is not byte-stable across renders"


@pytest.mark.skipif(
    not os.environ.get("KLYRSHIFT_RENDER_TEST"),
    reason="renders the GUI; set KLYRSHIFT_RENDER_TEST=1 under a display to run",
)
def test_committed_screenshots_match_a_fresh_render(tmp_path: Path) -> None:
    """The committed PNGs must be current, not a stale snapshot of an older GUI.

    Byte-stability alone only proves two runs of *today's* script agree; it does
    not notice that the committed images were rendered before a GUI change (the
    theme switch added a whole settings group, and a stale shot then contradicted
    the README). This renders once and compares against ``docs/screenshots``, so a
    GUI edit that is not followed by ``scripts/make_screenshots.py`` fails here.
    """
    if shutil.which("xvfb-run") is None:
        pytest.skip("xvfb-run not installed")
    fresh = tmp_path / "fresh"
    env = dict(os.environ)
    env["PYTHONPATH"] = "/usr/lib/python3/dist-packages"
    subprocess.run(
        ["xvfb-run", "-a", sys.executable, str(_render_script()), str(fresh)],
        check=True,
        env=env,
        capture_output=True,
    )
    stale = [
        name
        for name in EXPECTED
        if (fresh / name).read_bytes() != (SCREENSHOT_DIR / name).read_bytes()
    ]
    assert (
        stale == []
    ), f"{stale} differ from a fresh render; regenerate with scripts/make_screenshots.py"
