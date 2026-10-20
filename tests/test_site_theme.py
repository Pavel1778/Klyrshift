"""The landing page's palette must have one source of truth per colour.

Three defects of the same shape shipped here, and none of them broke a build:

* the stylesheet held 217 literal hex values beside two accent tokens, so the
  accent could be changed in one place and stay wrong in the other 215;
* ``site/public/manifest.webmanifest`` kept ``#1c71d8`` after the accent token
  moved to ``#1a65c2``, so the installed app's chrome disagreed with the page;
* ``theme-color`` was written out by hand in ``Base.astro`` (twice) and
  ``Header.astro``, where a palette change would have to be made three times.

These tests pin the values that must agree, and -- more usefully -- fail when a
component reintroduces a literal colour instead of using a token.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
GLOBAL_CSS = SITE / "src" / "styles" / "global.css"
MANIFEST = SITE / "public" / "manifest.webmanifest"
THEME_TS = SITE / "src" / "lib" / "theme.ts"

# Components may not carry literal colours: everything comes from a token in
# ``global.css``, so one palette edit reaches the whole page. Two exceptions are
# allowed and asserted below rather than waved through:
#   * ``lib/dictionaries.ts`` -- the 12 category colours, which are data;
#   * SVG ``fill``/``stop-color`` attributes -- attribute values cannot hold a
#     CSS ``var()``, so these are the artwork's own colours.
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COMPONENT_GLOBS = ("components/*.astro", "pages/*.astro", "layouts/*.astro")


def _css_tokens(scheme: str = "light") -> dict[str, str]:
    """Return the ``--color-*`` tokens of one scheme from ``global.css``."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    if scheme == "dark":
        start = css.index(".dark {")
        css = css[start:]
    else:
        css = css[: css.index(".dark {")] if ".dark {" in css else css
    return dict(re.findall(r"(--color-[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8});", css))


def _theme_colors() -> dict[str, str]:
    """Parse the ``THEME_COLOR`` map without a TypeScript toolchain."""
    text = THEME_TS.read_text(encoding="utf-8")
    return dict(re.findall(r"(\w+):\s*\"(#[0-9a-fA-F]{3,8})\"", text))


def test_theme_module_matches_the_background_tokens() -> None:
    """``THEME_COLOR`` must be the ``--color-bg`` token of each scheme."""
    light = _css_tokens("light")
    dark = _css_tokens("dark")
    colors = _theme_colors()
    assert colors.get("light") == light["--color-bg"], (
        f"theme.ts light {colors.get('light')} != --color-bg {light['--color-bg']}"
    )
    assert colors.get("dark") == dark["--color-bg"], (
        f"theme.ts dark {colors.get('dark')} != dark --color-bg {dark['--color-bg']}"
    )


def test_manifest_theme_color_matches_the_accent_token() -> None:
    """The installed app's chrome colour must follow the accent token."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    accent = _css_tokens("light")["--color-accent"]
    assert manifest["theme_color"] == accent, (
        f"manifest theme_color {manifest['theme_color']} != --color-accent {accent}"
    )
    background = _css_tokens("light")["--color-bg"]
    assert manifest["background_color"] == background, (
        f"manifest background_color {manifest['background_color']} != --color-bg {background}"
    )


def test_manifest_icons_exist() -> None:
    """A manifest that points at a missing icon silently loses its install."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["icons"], "the manifest must declare at least one icon"
    for icon in manifest["icons"]:
        target = SITE / "public" / icon["src"].lstrip("/")
        assert target.is_file(), f"manifest icon {icon['src']} is missing"


def test_manifest_uses_the_current_brand() -> None:
    """The rename must reach the manifest, which is not covered by the HTML tests."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["name"] == "Klyrshift"
    assert manifest["short_name"] == "Klyrshift"
    blob = json.dumps(manifest)
    assert "LinguaFix" not in blob, "the manifest still carries the old name"
    assert "Lingvix" not in blob, "the manifest still carries the intermediate name"


@pytest.mark.parametrize("glob", _COMPONENT_GLOBS)
def test_components_use_tokens_not_literal_colors(glob: str) -> None:
    """No component may hard-code a colour outside an SVG attribute.

    The check ignores anything inside an SVG element (``fill=``/``stop-color=``)
    because a ``var()`` is not valid there, and the ``stroke``/``fill``
    attributes of inline icons are part of the artwork.
    """
    offenders: list[str] = []
    for path in sorted((SITE / "src").glob(glob)):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not _HEX.search(line):
                continue
            stripped = line.strip()
            # SVG paint attributes and the ``theme-color`` script both legitimately
            # carry a value; the script reads it from ``lib/theme.ts``.
            if any(marker in stripped for marker in ("fill=", "stop-color=", "stroke=")):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped[:90]}")
    assert not offenders, (
        "literal colours in components; use a --color-* token instead:\n"
        + "\n".join(offenders)
    )
