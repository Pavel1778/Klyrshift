"""Render the 1200x630 social preview (``site/public/og-image.png``).

The previous image was produced by hand, so the ``LinguaFix`` -> ``Klyrshift``
rename never reached it and link previews kept showing the dead name. This
script builds the card from the landing page's own assets so the two cannot
drift again: it reuses ``site/public/logo.svg`` and the exact self-hosted Inter
and JetBrains Mono webfonts that Astro emits, then screenshots the result with
headless Chromium.

Requires a prior ``npm run build`` in ``site/`` (for the built fonts) and a
``chromium`` binary. Usage::

    python3 scripts/make_og_image.py

The font files are gitignored build output, so a clean checkout must build the
site first; the script says so instead of silently falling back to a different
typeface.
"""

from __future__ import annotations

import base64
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
DIST = SITE / "dist"
OUT = SITE / "public" / "og-image.png"
LOGO = SITE / "public" / "logo.svg"

WIDTH, HEIGHT = 1200, 630

# Family aliases so the template never depends on Astro's per-build hashes.
FAMILY_ALIASES = {"Inter": "KlyrshiftOgSans", "JetBrains Mono": "KlyrshiftOgMono"}

FOOTER = "Debian 13+ · GNOME 45+ · Wayland / X11 · MIT"


class SiteNotBuilt(RuntimeError):
    """The site has not been built, so the self-hosted webfonts are absent."""


def _font_css() -> str:
    """Self-hosted font-face CSS with the woff2 files inlined as data URIs."""
    index = DIST / "index.html"
    if not index.is_file():
        raise SiteNotBuilt(f"{index} missing; run `npm run build` in site/ first")
    html = index.read_text(encoding="utf-8")

    rules = []
    for rule in re.findall(r"@font-face\{[^}]*\}", html):
        match = re.search(r'url\("([^"]+\.woff2)"\)', rule)
        if not match:
            continue  # metric-matched Arial/Courier fallbacks; unused here
        for real, alias in FAMILY_ALIASES.items():
            if f"font-family:{real}-" in rule or f'font-family:"{real}-' in rule:
                font_file = DIST / match.group(1).lstrip("/")
                if not font_file.is_file():
                    raise SiteNotBuilt(f"{font_file} missing; run `npm run build` in site/ first")
                data = base64.b64encode(font_file.read_bytes()).decode("ascii")
                rule = re.sub(r'url\("[^"]+"\)', f'url("data:font/woff2;base64,{data}")', rule)
                rule = re.sub(
                    rf'font-family:("?){re.escape(real)}-[0-9a-f]+', rf"font-family:\1{alias}", rule
                )
                rules.append(rule)
                break

    if not rules:
        raise SiteNotBuilt("no self-hosted font-face rules found; is the site built?")
    return "\n".join(rules)


def build_html() -> str:
    """The full card document, from the shipped logo and the site's webfonts."""
    return _card_html(_logo_svg(), _font_css())


def _logo_svg() -> str:
    # Drop the XML declaration so the SVG inlines cleanly.
    return re.sub(r"<\?xml[^>]*\?>", "", LOGO.read_text(encoding="utf-8")).strip()


def _card_html(logo: str, font_css: str) -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><style>
{font_css}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: {WIDTH}px; height: {HEIGHT}px; overflow: hidden; }}
body {{ background: #1e1e1e; font-family: KlyrshiftOgSans; -webkit-font-smoothing: antialiased; }}
.logo {{ position: absolute; left: 79.15px; top: 109.15px; width: 173.4px; height: 173.4px; }}
.logo svg {{ width: 100%; height: 100%; display: block; }}
.title {{ position: absolute; left: 272px; top: 121px; font-size: 97.2px; font-weight: 700;
         color: #fafafa; letter-spacing: -0.015em; line-height: 1.1; }}
.subtitle {{ position: absolute; left: 279px; top: 252px; font-size: 41px; font-weight: 500;
            color: #aaaaaa; letter-spacing: -0.085em; text-transform: uppercase;
            white-space: nowrap; }}
.card {{ position: absolute; left: 90px; top: 400px; width: 1020px; height: 120px;
        background: #2d2d2d; border-radius: 16px; display: flex; align-items: center;
        padding: 0 42px; font-family: KlyrshiftOgMono; font-size: 40px; }}
.card .wrong {{ color: #aaaaaa; }}
.card .arrow {{ color: #3584e4; margin: 0 67px 0 127px; }}
.card .right {{ color: #fafafa; }}
.footer {{ position: absolute; left: 95px; top: 558px; font-size: 34px; color: #aaaaaa; }}
</style></head><body>
<div class="logo">{logo}</div>
<div class="title">Klyrshift</div>
<div class="subtitle">Автоматическое исправление раскладки</div>
<div class="card"><span class="wrong">ghbdtn</span><span class="arrow">-&gt;</span><span class="right">привет</span></div>
<div class="footer">{FOOTER}</div>
</body></html>
"""


def _screenshot(html: str, out: Path) -> None:
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium is None:
        sys.exit("chromium not found; install it to regenerate the OG image")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "og.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                chromium,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={WIDTH},{HEIGHT}",
                f"--screenshot={out}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )


def _png_size(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"{path} is not a PNG")
    return struct.unpack(">II", raw[16:24])


def _distinct_colours(path: Path, step: int = 4) -> int:
    """Rough colour count, to catch a blank or single-colour render."""
    raw = path.read_bytes()
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

    bpp = 4 if colour_type == 6 else 3
    stride = width * bpp
    out = bytearray(height * stride)
    prev = bytearray(stride)
    src = zlib.decompress(idat)
    p = 0
    for y in range(height):
        ftype = src[p]
        p += 1
        line = bytearray(src[p : p + stride])
        p += stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = line[i]
            if ftype == 1:
                x = (x + a) & 0xFF
            elif ftype == 2:
                x = (x + b) & 0xFF
            elif ftype == 3:
                x = (x + (a + b) // 2) & 0xFF
            elif ftype == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                x = (x + pr) & 0xFF
            line[i] = x
        out[y * stride : (y + 1) * stride] = line
        prev = line

    colours = set()
    for y in range(0, height, step):
        for x in range(0, width, step):
            i = y * stride + x * bpp
            colours.add(bytes(out[i : i + 3]))
    return len(colours)


def main() -> int:
    try:
        html = build_html()
    except SiteNotBuilt as exc:
        sys.exit(str(exc))
    if "LinguaFix" in html or "Lingvix" in html:
        sys.exit("refusing to render: the card still mentions an old name")

    _screenshot(html, OUT)
    size = _png_size(OUT)
    colours = _distinct_colours(OUT)
    if size != (WIDTH, HEIGHT):
        sys.exit(f"unexpected size {size}, expected {(WIDTH, HEIGHT)}")
    if colours < 50:
        sys.exit(f"render looks blank ({colours} colours)")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} {size[0]}x{size[1]} ({colours} colours)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
