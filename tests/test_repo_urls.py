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
ASTRO_CONFIG = REPO_ROOT / "site" / "astro.config.mjs"
SITE_LIB = REPO_ROOT / "site" / "src" / "lib" / "site.ts"
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
    repo_name = repo.REPO_SLUG.split("/")[1]
    text = SITE_CONSTS.read_text(encoding="utf-8")
    assert f'export const REPO_NAME = "{repo_name}";' in text
    assert "export const REPO_SLUG = `${REPO_OWNER}/${REPO_NAME}`;" in text


def test_site_install_snippet_uses_the_derived_repository_name() -> None:
    """``cd`` into the cloned directory must not hard-code the repository name.

    The snippet cloned from ``REPO`` (derived from the slug) but then ran
    ``cd LinguaFix``. Today both spell the same name, so it works; the moment
    the repository is renamed, the clone lands in the new directory and the
    ``cd`` breaks every source install. Derive it from the same constant.
    """
    text = (REPO_ROOT / "site" / "src" / "components" / "Install.astro").read_text(encoding="utf-8")
    assert "cd ${REPO_NAME}" in text
    assert "cd LinguaFix" not in text


def test_document_clone_instructions_name_the_current_repository() -> None:
    """``git clone`` and ``cd`` in the docs must match the live repository name.

    Markdown cannot derive the name from ``repo.py``, so the four install docs
    spell it out. Pin them to :data:`repo.REPO_SLUG` so the rename cannot leave
    a stale ``cd`` behind that breaks the copy-paste install.
    """
    name = repo.REPO_SLUG.split("/")[1]
    targets = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    offenders: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for match in re.findall(r"git clone \S+/([A-Za-z0-9_.-]+)\.git", text):
            if match != name:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: clone {match}")
        for match in re.findall(r"^cd (\S+)", text, re.M):
            if match != name:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: cd {match}")
    assert not offenders, "stale repository name in docs: " + ", ".join(offenders)


def test_site_version_matches_the_package() -> None:
    """The version shown on the landing page is the packaged version."""
    version = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert version is not None
    site = SITE_CONSTS.read_text(encoding="utf-8")
    assert f'export const VERSION = "{version.group(1)}";' in site


def test_site_canonical_origins_are_hosts_that_resolve() -> None:
    """The canonical origin must not point at a host that does not exist.

    ``lingvix.layero.app`` and ``lingvix.vercel.app`` are 404 because the DNS
    entries were never renamed along with the source. The origin is written into
    ``<link rel="canonical">``, ``og:url``, the ``hreflang`` alternates and the
    sitemap, so a 404 origin makes search engines drop the page instead of
    indexing the live one.
    """
    expected = {"https://linguafix.layero.app", "https://linguafix.vercel.app"}
    for path in (ASTRO_CONFIG, SITE_LIB):
        origins = set(re.findall(r"https://[a-z0-9.-]+", path.read_text(encoding="utf-8")))
        assert origins == expected, f"{path.name}: {origins}"


def test_no_document_links_the_renamed_but_nonexistent_hosts() -> None:
    """No tracked document may link a ``lingvix.*`` host: those names do not resolve.

    The templates were the first place this surfaced, but ``README.md`` carried
    the same dead origin in its status badges, its dictionary link and its
    "where to find us" list. Scanning the live documentation and the site source
    -- not the changelog or the session logs, which record the old name as
    history -- catches the next one wherever it appears.
    """
    targets = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    targets += sorted((REPO_ROOT / "site" / "src").rglob("*.astro"))
    targets += sorted((REPO_ROOT / "site" / "src").rglob("*.ts"))
    targets += [ASTRO_CONFIG]
    offenders: list[str] = []
    for path in targets:
        for match in re.findall(r"https://lingvix\.[a-z0-9.-]+", path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match}")
    assert not offenders, "links to nonexistent hosts: " + ", ".join(offenders)


def test_both_origins_honour_site_url_override() -> None:
    """A ``SITE_URL`` build must not contradict itself.

    The sitemap and ``robots.txt`` take their origin from ``astro.config.mjs``
    (``site``), while ``<link rel="canonical">``, ``og:url`` and the ``hreflang``
    alternates take theirs from ``site.ts`` (``siteUrl``). When only the config
    read the override, a ``SITE_URL`` build emitted a Vercel sitemap next to a
    Layero canonical -- so a local check reported a canonical it would never
    ship, and the two origins silently disagreed. Both files must read the
    override.
    """
    config = ASTRO_CONFIG.read_text(encoding="utf-8")
    lib = SITE_LIB.read_text(encoding="utf-8")
    assert "process.env.SITE_URL" in config, "astro.config.mjs ignores SITE_URL"
    assert "import.meta.env.SITE_URL" in lib, "site.ts ignores SITE_URL"
