"""Build the documentation as a single PDF (and the Markdown handbook).

The project documents itself in ``docs/*.md`` plus ``README.md`` and
``CHANGELOG.md``. Reading them means opening a dozen files, which is fine in a
repository and awkward everywhere else: a reviewer, a distributor or a user
offline wants one file to open. This script renders the same Markdown into one
document, so the PDF never drifts from the sources it is built from.

Two outputs are written:

* ``docs/klyrshift-handbook.md`` -- every document concatenated under a table of
  contents, with the relative links rewritten so they still resolve;
* ``docs/klyrshift-handbook.pdf`` -- the same content laid out for print.

The Markdown is generated, not edited: a change belongs in the source document,
and rebuilding replaces it. The build is offline and deterministic -- no
network, no template fetch -- so it can run in CI beside the test suite.

Requirements: ``weasyprint`` and ``markdown`` (``make docs-pdf`` installs the
``docs`` extra). Both are development-only; nothing here ships in the package.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"

# Reading order: the front matter first, then the operational guides, then the
# design notes. Every file listed must exist; a missing one fails the build
# rather than silently producing a shorter handbook.
SOURCES: tuple[str, ...] = (
    "README.md",
    "docs/INSTALL.md",
    "docs/CLI.md",
    "docs/TROUBLESHOOTING.md",
    "docs/PLATFORM_SUPPORT.md",
    "docs/LANGUAGE_PACKAGES.md",
    "docs/INTERFACE_LANGUAGES.md",
    "docs/ARCHITECTURE.md",
    "docs/CONTROL_SOCKET.md",
    "docs/UNDO_CONTRACT.md",
    "docs/OFFLINE_AND_PRIVACY.md",
    "docs/TESTING.md",
    "docs/TEST_STRATEGY.md",
    "docs/RELEASING.md",
    "docs/CONTRIBUTING.md",
    "docs/ROADMAP.md",
    "CHANGELOG.md",
)

# A heading is demoted so each document's ``#`` becomes a section under the
# handbook's own title, keeping one coherent outline in the PDF bookmarks.
HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\]\(([^)#\s]+\.md)(#[^)\s]*)?\)")


def _slug(text: str) -> str:
    """A stable anchor id from a heading, matching GitHub's slugs.

    GitHub lowercases, drops everything that is not a letter, digit, space,
    hyphen or underscore (so an emoji or a ``/`` disappears) and turns each
    remaining space into one hyphen. It does not collapse runs or trim, which is
    why a heading like ``### 📋 Требования / Requirements`` anchors as
    ``-требования--requirements`` -- the same anchor the sources link to.
    """
    cleaned = re.sub(r"`([^`]*)`", r"\1", text)
    cleaned = re.sub(r"[^\w\s-]", "", cleaned, flags=re.UNICODE).lower()
    return re.sub(r"\s", "-", cleaned)


def _rewrite_links(text: str) -> str:
    """Point every ``foo.md#bar`` link at the section inside this document."""

    def replace(match: re.Match[str]) -> str:
        fragment = match.group(2) or ""
        return f"](#{_slug(fragment.lstrip('#'))})" if fragment else "](#contents)"

    return MARKDOWN_LINK.sub(replace, text)


def _shift_headings(text: str) -> str:
    """Demote every heading by one level so the outline nests under the title."""

    def replace(match: re.Match[str]) -> str:
        level = min(len(match.group(1)) + 1, 6)
        return f"{'#' * level} {match.group(2)}"

    return HEADING.sub(replace, text)


def build_markdown() -> str:
    """Return the concatenated handbook as Markdown."""
    parts: list[str] = [
        "# Klyrshift handbook\n",
        "This handbook is generated from the project's Markdown sources by",
        "`scripts/build_docs.py`. Edit the source documents, not this file.\n",
        "## Contents\n",
    ]
    bodies: list[tuple[str, str]] = []
    for relative in SOURCES:
        path = REPO_ROOT / relative
        if not path.exists():
            raise SystemExit(f"missing documentation source: {relative}")
        text = path.read_text(encoding="utf-8").strip()
        title_match = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else relative
        bodies.append((relative, text))
        parts.append(f"- [{title}](#{_slug(title)})")

    for relative, text in bodies:
        parts.append(f'\n<a id="{relative}"></a>\n')
        parts.append(_shift_headings(_rewrite_links(text)))

    return "\n".join(parts).rstrip() + "\n"


PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm; @bottom-center { content: counter(page); } }
body { font-family: "DejaVu Sans", sans-serif; font-size: 10pt; line-height: 1.5;
       color: #1a1a1a; font-variant-ligatures: none; }
h1 { font-size: 22pt; border-bottom: 2px solid #1c71d8; padding-bottom: 4pt;
     string-set: chapter content(); }
h2 { font-size: 15pt; margin-top: 18pt; color: #1c71d8; }
h3 { font-size: 12pt; margin-top: 12pt; }
h4, h5, h6 { font-size: 11pt; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
       background: #f2f2f2; padding: 0 2pt; font-variant-ligatures: none; }
pre { background: #f6f6f6; border: 1px solid #ddd; border-radius: 3pt;
      padding: 6pt; font-size: 8pt; white-space: pre-wrap; word-wrap: break-word;
      font-variant-ligatures: none; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th, td { border: 1px solid #ccc; padding: 3pt 5pt; text-align: left;
         vertical-align: top; }
th { background: #eef2f7; }
a { color: #1c71d8; text-decoration: none; }
blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 8pt;
             color: #444; }
img { max-width: 100%; }
h1 { break-before: page; }
h1:first-of-type { break-before: avoid; }
"""


def build_pdf(markdown_text: str, output: Path) -> None:
    """Render ``markdown_text`` to ``output`` as PDF."""
    try:
        import markdown as md
        from weasyprint import CSS, HTML
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "PDF build needs the 'docs' extra: pip install weasyprint markdown"
        ) from exc

    body = md.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
    )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Klyrshift handbook</title></head><body>{body}</body></html>"
    )
    HTML(string=document, base_url=str(REPO_ROOT)).write_pdf(
        str(output), stylesheets=[CSS(string=PRINT_CSS)]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=str(DOCS), help="where to write the handbook")
    parser.add_argument("--markdown-only", action="store_true", help="skip the PDF step")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    markdown_text = build_markdown()
    md_path = out_dir / "klyrshift-handbook.md"
    md_path.write_text(markdown_text, encoding="utf-8")
    print(f"wrote {md_path.relative_to(REPO_ROOT)} ({len(markdown_text)} bytes)")

    if args.markdown_only:
        return 0
    pdf_path = out_dir / "klyrshift-handbook.pdf"
    build_pdf(markdown_text, pdf_path)
    print(f"wrote {pdf_path.relative_to(REPO_ROOT)} ({pdf_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
