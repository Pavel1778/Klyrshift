"""The repository URLs must not drift between the code, the package and the site.

The GitHub repository is still named ``LinguaFix`` (the ``Lingvix`` rename is
done in the source only), so every download URL has to be built from
:data:`lingvix.repo.REPO_SLUG`. A stray literal is not cosmetic: a link to a
non-existent repository returns 404, and ``dict install`` fails for every
category that is not a published release asset. These tests fail on the next
drift instead of at download time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lingvix import repo

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "lingvix"
SITE_CONSTS = REPO_ROOT / "site" / "src" / "consts.ts"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def test_repo_urls_are_built_from_the_slug() -> None:
    assert repo.REPO_URL == f"https://github.com/{repo.REPO_SLUG}"  # noqa: SIM300
    assert repo.RELEASES_URL == f"{repo.REPO_URL}/releases"  # noqa: SIM300
    assert repo.LATEST_ASSET_BASE == f"{repo.RELEASES_URL}/latest/download"  # noqa: SIM300
    assert repo.RAW_MIRROR_BASE.startswith("https://raw.githubusercontent.com/")
    assert repo.REPO_SLUG in repo.RAW_MIRROR_BASE


@pytest.mark.parametrize(
    "module, attribute",
    [
        ("lingvix.dictionary", "_RELEASE_ASSET_BASE"),
        ("lingvix.dictionary", "_BUNDLED_RAW_BASE"),
        ("lingvix.thematic", "_RELEASE_ASSET_BASE"),
        ("lingvix.thematic", "_BRANCH_MIRROR_BASE"),
        ("lingvix.update_check", "RELEASES_URL"),
        ("lingvix.update_check", "RELEASES_PAGE"),
    ],
)
def test_download_urls_point_at_the_real_repository(module: str, attribute: str) -> None:
    """Every network URL is derived from the slug, never a stale literal."""
    import importlib

    value = getattr(importlib.import_module(module), attribute)
    assert repo.REPO_SLUG in value, f"{module}.{attribute} does not name {repo.REPO_SLUG}"


def test_no_hardcoded_repository_slug_in_source() -> None:
    """No source file repeats the owner/repo pair outside ``repo.py``."""
    pattern = re.compile(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "repo.py":
            continue
        for match in pattern.findall(path.read_text(encoding="utf-8")):
            # Third-party references (hermitdave/FrequencyWords) are allowed; the
            # project's own repository must come from ``repo.py``.
            if "Pavel1778" in match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match}")
    assert not offenders, "hardcoded project repository URLs: " + ", ".join(offenders)


def test_site_consts_match_the_python_slug() -> None:
    """The landing page links to the same repository the code downloads from."""
    text = SITE_CONSTS.read_text(encoding="utf-8")
    assert f'REPO_SLUG = `${{REPO_OWNER}}/{repo.REPO_SLUG.split("/")[1]}`' in text


def test_site_version_matches_the_package() -> None:
    """The version shown on the landing page is the packaged version."""
    version = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert version is not None
    site = SITE_CONSTS.read_text(encoding="utf-8")
    assert f'export const VERSION = "{version.group(1)}";' in site
