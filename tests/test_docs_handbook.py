"""The documentation handbook stays complete and self-consistent.

``scripts/build_docs.py`` concatenates the project's Markdown into one document
and renders a PDF. These tests guard the parts that can silently rot: a source
document that is dropped from the build, a heading whose anchor no longer
resolves, and a committed PDF that no longer matches its sources.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_docs.py"
HAND_BOOK_MD = REPO_ROOT / "docs" / "klyrshift-handbook.md"
HANDBOOK_PDF = REPO_ROOT / "docs" / "klyrshift-handbook.pdf"


def _load_build_docs() -> object:
    """Import ``scripts/build_docs.py`` without it being a package."""
    name = "build_docs"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.fixture(scope="module")
def build_docs() -> object:
    return _load_build_docs()


def test_every_listed_source_exists(build_docs: object) -> None:
    for relative in build_docs.SOURCES:
        assert (REPO_ROOT / relative).is_file(), relative


def test_every_docs_page_is_in_the_handbook(build_docs: object) -> None:
    """A new guide must be added to the build, or it is invisible offline."""
    listed = {Path(relative).name for relative in build_docs.SOURCES}
    on_disk = {path.name for path in (REPO_ROOT / "docs").glob("*.md")}
    on_disk -= {HAND_BOOK_MD.name}
    missing = on_disk - listed
    assert not missing, f"not in build_docs.SOURCES: {sorted(missing)}"


def test_handbook_contains_every_source_title(build_docs: object) -> None:
    text = build_docs.build_markdown()
    for relative in build_docs.SOURCES:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        match = re.search(r"^#\s+(.*)$", source, re.MULTILINE)
        assert match, relative
        assert match.group(1).strip() in text, relative


def test_handbook_has_no_link_to_a_missing_section(build_docs: object) -> None:
    """Rewritten ``#anchor`` links must point at a heading in the handbook."""
    text = build_docs.build_markdown()
    anchors = {build_docs._slug(m.group(2)) for m in build_docs.HEADING.finditer(text)}
    anchors.add("contents")
    broken = {target for target in re.findall(r"\]\(#([^)]+)\)", text) if target not in anchors}
    assert not broken, sorted(broken)


def test_committed_handbook_matches_a_fresh_build(build_docs: object) -> None:
    """The committed Markdown is regenerated, so it must not drift."""
    assert HAND_BOOK_MD.is_file(), "run: make docs-pdf"
    assert HAND_BOOK_MD.read_text(encoding="utf-8") == build_docs.build_markdown()


def test_committed_pdf_is_present_and_a_real_pdf() -> None:
    assert HANDBOOK_PDF.is_file(), "run: make docs-pdf"
    data = HANDBOOK_PDF.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-1024:]
    # A handbook of a dozen documents is far larger than a placeholder page.
    assert len(data) > 100_000
