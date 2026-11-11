"""The project-structure guide must describe the tree it lives in.

``docs/PROJECT_STRUCTURE.md`` is the map a newcomer reads first, and a map that
omits a directory, a module or a script is worse than none: the reader trusts it
and never looks. These tests derive the real tree from ``git ls-files`` and fail
when the guide does not name something, so adding a module or a script without
documenting it is caught here instead of by a confused reader.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STRUCTURE = REPO_ROOT / "docs" / "PROJECT_STRUCTURE.md"
PACKAGE = REPO_ROOT / "src" / "klyrshift"

# Top-level entries that are tooling metadata rather than part of the layout a
# reader navigates. They are still documented, but a rename of one of them is
# not a structural change the guide must track by name.
_TOP_LEVEL_EXEMPT = (".editorconfig", ".gitignore")


def _tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    return output.splitlines()


def _structure_text() -> str:
    assert STRUCTURE.is_file(), "docs/PROJECT_STRUCTURE.md is missing"
    return STRUCTURE.read_text(encoding="utf-8")


def test_structure_guide_is_not_a_stub() -> None:
    assert len(_structure_text().splitlines()) > 50


def test_every_top_level_entry_is_documented() -> None:
    """Every tracked top-level file and directory must be named in the guide."""
    entries = {
        name.split("/")[0] for name in _tracked_files() if not name.startswith(_TOP_LEVEL_EXEMPT)
    }
    text = _structure_text()
    missing = sorted(entry for entry in entries if entry not in text)
    assert not missing, "top-level entries not in PROJECT_STRUCTURE.md: " + ", ".join(missing)


def test_every_package_module_is_documented() -> None:
    """A new module under ``src/klyrshift`` must be added to the module tables."""
    modules = {path.name for path in PACKAGE.rglob("*.py")}
    text = _structure_text()
    missing = sorted(name for name in modules if name not in text)
    assert not missing, "modules not in PROJECT_STRUCTURE.md: " + ", ".join(missing)


def test_every_script_is_documented() -> None:
    scripts = {name.split("/")[-1] for name in _tracked_files() if name.startswith("scripts/")}
    text = _structure_text()
    missing = sorted(name for name in scripts if name not in text)
    assert not missing, "scripts not in PROJECT_STRUCTURE.md: " + ", ".join(missing)


def test_every_docs_guide_is_documented() -> None:
    """Each guide in ``docs/`` must appear in the documentation index of the map."""
    guides = {path.name for path in (REPO_ROOT / "docs").glob("*.md")}
    guides.discard("klyrshift-handbook.md")
    text = _structure_text()
    missing = sorted(name for name in guides if name not in text)
    assert not missing, "docs not in PROJECT_STRUCTURE.md: " + ", ".join(missing)


def test_structure_guide_is_linked_from_the_readme() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/PROJECT_STRUCTURE.md" in readme
