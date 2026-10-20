"""The landing page must not hide content in a keyboard-unreachable scroll box.

``axe-core`` flagged ``scrollable-region-focusable`` on the dictionary pages: a
horizontally scrollable ``<pre>`` is not reachable by keyboard, so a keyboard
user cannot scroll it to read the rest of a command. That is a WCAG 2.1.1
(Level A) failure, and it only showed up at a 320px viewport -- wide enough
viewports never overflowed, which is why it survived the earlier audits.

The fix is to wrap instead of scroll, so nothing is clipped at any width. A
browser run is the real proof (and the 12-combination axe sweep is recorded in
the task notes), but a browser is not always available in CI, so this module
keeps a static guard: the command panels must not declare a scroll axis.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
GLOBAL_CSS = SITE / "src" / "styles" / "global.css"

# A scroll container, in either syntax the stylesheet uses: a plain declaration
# (``overflow-x: auto``) or a Tailwind utility applied through ``@apply``
# (``overflow-x-auto``). Both make the element scrollable.
_SCROLL_UTILITY = r"overflow(?:-x)?(?::\s*(?:auto|scroll)\b|-(?:auto|scroll)\b)"

# These carry command text. Wrapping keeps the whole command visible; scrolling
# hides its tail behind a bar that many platforms do not even draw.
_WRAPPING_RULES = {".code-block", ".code-panel"}

# ``.code-panel`` wraps in the stylesheet, but ``.code-block`` wraps on the
# ``<pre>`` inside its component, so the check follows the text to each place.
_WRAP_SOURCES = {
    ".code-block": SITE / "src" / "components" / "CodeBlock.astro",
    ".code-panel": GLOBAL_CSS,
}


def _rule_bodies(css: str) -> dict[str, str]:
    """Map each class selector (with its leading dot) to its declaration body."""
    return {
        "." + match.group(1): match.group(2)
        for match in re.finditer(r"\.([a-z][a-z0-9-]*)\s*\{([^}]*)\}", css, re.S)
    }


def test_command_panels_do_not_scroll_horizontally() -> None:
    """A scrollable command panel is a keyboard trap under WCAG 2.1.1."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    bodies = _rule_bodies(css)
    offenders = [
        selector
        for selector in _WRAPPING_RULES
        if re.search(_SCROLL_UTILITY, bodies.get(selector, ""), re.I)
    ]
    assert not offenders, (
        "these command panels declare a horizontal scroll axis, which is "
        "unreachable by keyboard; use whitespace-pre-wrap + break-words so the "
        "command wraps instead: " + ", ".join(sorted(offenders))
    )


def test_command_panels_wrap_their_text() -> None:
    """Wrapping is what removes the scroll axis, so it must stay declared."""
    missing = [
        selector
        for selector, source in _WRAP_SOURCES.items()
        if "whitespace-pre-wrap" not in source.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "these command panels no longer wrap, so a long command can overflow: "
        + ", ".join(sorted(missing))
    )


def test_no_component_creates_an_unfocusable_scroll_region() -> None:
    """A scrollable element in a component must be reachable by keyboard.

    ``overflow`` with ``auto``/``scroll`` on a plain element is a keyboard trap
    (axe's ``scrollable-region-focusable``, WCAG 2.1.1 Level A). An element that
    is genuinely meant to scroll must therefore carry ``tabindex`` so it can be
    focused and scrolled from the keyboard; otherwise the content should wrap.
    """
    offenders: list[str] = []
    for path in sorted(SITE.glob("src/**/*.astro")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(_SCROLL_UTILITY, line, re.I):
                continue
            if "tabindex" in line:
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "these elements create a scroll container with no keyboard access; wrap "
        "the content or add tabindex so it can be scrolled by keyboard:\n"
        + "\n".join(offenders)
    )
