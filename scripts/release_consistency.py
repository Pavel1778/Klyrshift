#!/usr/bin/env python3
"""Release consistency: does the tree describe the release it claims to be?

Two questions are deliberately kept apart, because they fail for different
reasons and at different times:

* **Source consistency** -- ``pyproject.toml``, ``src/klyrshift/__init__.py``,
  ``site/src/consts.ts`` and the landing page's JSON-LD must all name one
  version, and the asset names the build scripts emit must match the ones the
  release workflow attaches. This is checkable offline and is what the unit
  suite runs (``tests/test_release_consistency.py``). It must pass even when no
  release has been published yet -- an unreleased version is not an error here.

* **Published-release consistency** -- the version in the tree must match the
  tag and the assets of the GitHub Release that was actually published, and the
  download URLs must resolve. This needs the network, so it runs only from the
  release workflow (``--tag``) or on demand (``--latest``); it is never part of
  the offline test run.

The distinction matters: the live site advertised ``0.2.8.2`` while the newest
published release was ``v0.2.8``, and a source-only check cannot see that.

Usage::

    python3 scripts/release_consistency.py --source
    python3 scripts/release_consistency.py --tag v0.2.8.2 --assets-file assets.txt
    python3 scripts/release_consistency.py --latest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

# The dictionary families the release workflow attaches. Both are derived from
# the files in ``dictionaries/`` rather than typed, so adding a category or a
# language needs no edit here.
_FREQUENCY_GLOB = "*-50k.txt"
_THEMATIC_ROOT = REPO_DIR / "dictionaries"

_VERSION_RE = re.compile(r'^version = "([^"]+)"', re.MULTILINE)
_CONSTS_VERSION_RE = re.compile(r'export const VERSION = "([^"]+)";')
_SITE_PKG_VERSION_RE = re.compile(r'^\s*"version": "([^"]+)"', re.MULTILINE)
_PYPROJECT_NAME_RE = re.compile(r'^name = "([^"]+)"', re.MULTILINE)
_DEB_PKG_RE = re.compile(r'^PKG="([^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class SourceFacts:
    """What the tree says about the release it would produce."""

    version: str
    package: str
    repo_slug: str
    deb_asset: str
    sdist_asset: str
    frequency_assets: tuple[str, ...]
    dict_archives: tuple[str, ...]
    site_version: str
    site_package_version: str
    jsonld_version: str
    jsonld_is_literal: bool

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    @property
    def all_assets(self) -> tuple[str, ...]:
        return (self.deb_asset, self.sdist_asset, *self.frequency_assets, *self.dict_archives)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def collect_source_facts(repo_dir: Path = REPO_DIR) -> SourceFacts:
    """Read the version and the expected asset names out of the tree."""
    pyproject = _read(repo_dir / "pyproject.toml")
    version_match = _VERSION_RE.search(pyproject)
    name_match = _PYPROJECT_NAME_RE.search(pyproject)
    if version_match is None or name_match is None:
        raise SystemExit("pyproject.toml has no project version/name")
    version = version_match.group(1)
    package = name_match.group(1)

    deb_pkg_match = _DEB_PKG_RE.search(_read(repo_dir / "scripts" / "build_deb.sh"))
    if deb_pkg_match is None:
        raise SystemExit("scripts/build_deb.sh does not declare PKG")

    repo_slug = _read(repo_dir / "src" / package / "repo.py")
    slug_match = re.search(r'REPO_SLUG: Final\[str\] = "([^"]+)"', repo_slug)
    if slug_match is None:
        raise SystemExit("src/<package>/repo.py does not declare REPO_SLUG")

    consts = _read(repo_dir / "site" / "src" / "consts.ts")
    site_version_match = _CONSTS_VERSION_RE.search(consts)
    if site_version_match is None:
        raise SystemExit("site/src/consts.ts does not declare VERSION")

    site_pkg = _read(repo_dir / "site" / "package.json")
    site_pkg_match = _SITE_PKG_VERSION_RE.search(site_pkg)
    if site_pkg_match is None:
        raise SystemExit("site/package.json does not declare a version")

    base = _read(repo_dir / "site" / "src" / "layouts" / "Base.astro")
    literal_match = re.search(r'softwareVersion: "([^"]+)"', base)
    jsonld_is_literal = literal_match is not None
    jsonld_version = (
        literal_match.group(1) if literal_match is not None else site_version_match.group(1)
    )

    frequency = tuple(sorted(p.name for p in (repo_dir / "dictionaries").glob(_FREQUENCY_GLOB)))
    archives = tuple(
        sorted(
            f"klyrshift-dict-{d.name}.tar.gz"
            for d in _THEMATIC_ROOT.iterdir()
            if d.is_dir() and (d / "README.md").is_file()
        )
    )

    return SourceFacts(
        version=version,
        package=package,
        repo_slug=slug_match.group(1),
        deb_asset=f"{deb_pkg_match.group(1)}_{version}_all.deb",
        sdist_asset=f"{package}-{version}.tar.gz",
        frequency_assets=frequency,
        dict_archives=archives,
        site_version=site_version_match.group(1),
        site_package_version=site_pkg_match.group(1),
        jsonld_version=jsonld_version,
        jsonld_is_literal=jsonld_is_literal,
    )


# --- offline: source against source ------------------------------------------


def check_source_consistency(facts: SourceFacts) -> list[str]:
    """Problems that make the tree disagree with itself. No network, no release."""
    problems: list[str] = []
    if facts.site_version != facts.version:
        problems.append(
            f"site/src/consts.ts VERSION={facts.site_version!r} != pyproject {facts.version!r}"
        )
    if facts.site_package_version != facts.version:
        problems.append(
            f"site/package.json version={facts.site_package_version!r} != pyproject {facts.version!r}"
        )
    if facts.jsonld_is_literal:
        problems.append(
            "Base.astro writes softwareVersion as a literal "
            f"({facts.jsonld_version!r}); import VERSION from consts so it cannot drift"
        )
    elif facts.jsonld_version != facts.version:
        problems.append(
            f"Base.astro softwareVersion={facts.jsonld_version!r} != pyproject {facts.version!r}"
        )
    return problems


# --- online: source against a published release ------------------------------


def check_published_release(
    facts: SourceFacts,
    tag: str,
    asset_names: Iterable[str],
    *,
    require_tag: bool = True,
) -> list[str]:
    """Compare the tree with a release that exists. Pure: takes the data as given.

    Keeping this a pure function lets the unit suite exercise the drift with a
    recorded release payload instead of a network call.
    """
    problems: list[str] = []
    if require_tag and tag != facts.tag:
        problems.append(f"release tag {tag!r} != version tag {facts.tag!r}")

    present = set(asset_names)
    missing = [a for a in facts.all_assets if a not in present]
    if missing:
        problems.append("release is missing expected assets: " + ", ".join(missing))

    # The reverse direction is a warning, not a failure: an extra asset (a
    # previous version's dictionary, an editor's scratch file) does not break a
    # download, but an unexpected ``.deb`` under the new tag would be suspicious.
    expected = set(facts.all_assets)
    unexpected_debs = sorted(a for a in present - expected if a.endswith(".deb"))
    if unexpected_debs:
        problems.append("release carries unexpected .deb assets: " + ", ".join(unexpected_debs))
    return problems


def check_latest_matches_source(facts: SourceFacts, latest_tag: str) -> list[str]:
    """The site advertises the version it builds from; so must ``latest``.

    ``/releases/latest/download/...`` serves the newest *published* release, so
    if the tree is ahead of it, every "download the latest" button hands the
    user a build whose version differs from the one the page names.
    """
    if latest_tag != facts.tag:
        return [
            f"the newest published release is {latest_tag!r} but the tree is {facts.tag!r}: "
            "the download button serves a different version than the page advertises"
        ]
    return []


def download_url(facts: SourceFacts, asset: str) -> str:
    return f"https://github.com/{facts.repo_slug}/releases/latest/download/{asset}"


def check_download_urls(facts: SourceFacts, assets: Sequence[str]) -> list[str]:
    """Every expected asset must be fetchable at the stable download URL."""
    problems: list[str] = []
    for asset in assets:
        url = download_url(facts, asset)
        request = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=20):
                pass
        except urllib.error.HTTPError as exc:
            problems.append(f"{asset}: HTTP {exc.code} at {url}")
        except urllib.error.URLError as exc:
            problems.append(f"{asset}: {exc.reason} at {url}")
    return problems


# --- GitHub API ---------------------------------------------------------------


def fetch_release(repo_slug: str, tag: str | None) -> dict[str, object]:
    """Fetch one release (or ``latest`` when ``tag`` is None) from the GitHub API."""
    suffix = f"tags/{tag}" if tag else "latest"
    url = f"https://api.github.com/repos/{repo_slug}/releases/{suffix}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "klyrshift-release-check"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: dict[str, object] = json.loads(response.read().decode("utf-8"))
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"no release found at {url}") from exc
        raise SystemExit(f"GitHub API returned {exc.code} for {url}") from exc


def _release_asset_names(payload: dict[str, object]) -> list[str]:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return []
    return [str(a.get("name", "")) for a in assets if isinstance(a, dict)]


def _release_tag(payload: dict[str, object]) -> str:
    return str(payload.get("tag_name", ""))


# --- CLI ----------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", action="store_true", help="offline: the tree against itself")
    parser.add_argument("--tag", help="check a published tag against the tree")
    parser.add_argument("--latest", action="store_true", help="check the newest published release")
    parser.add_argument(
        "--assets-file",
        help="newline-separated asset names to use instead of the GitHub API",
    )
    parser.add_argument(
        "--check-urls", action="store_true", help="HEAD every expected download URL"
    )
    args = parser.parse_args(argv)

    if not (args.source or args.tag or args.latest):
        parser.error("choose one of --source, --tag, --latest")

    facts = collect_source_facts()
    print(f"[release] tree: {facts.tag}  package={facts.package}  repo={facts.repo_slug}")
    for asset in facts.all_assets:
        print(f"[release]   expected asset: {asset}")

    problems: list[str] = []

    if args.source:
        problems += check_source_consistency(facts)

    # ``--assets-file`` supplies the asset names, so the published release does not
    # have to be fetched to know them. That is what lets the pre-publish gate check
    # the tag being cut: its release does not exist yet, and fetching it would 404
    # and abort the workflow before it can create the release. ``--latest`` is the
    # exception -- the newest tag is knowable only from the API, so it always needs
    # the network.
    needs_release = args.latest or (args.tag is not None and not args.assets_file)

    if args.assets_file:
        names = [
            line.strip()
            for line in Path(args.assets_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        problems += check_published_release(facts, args.tag or facts.tag, names)

    if needs_release:
        payload = fetch_release(facts.repo_slug, args.tag)
        tag = _release_tag(payload)
        names = _release_asset_names(payload)
        print(f"[release] published: {tag}  assets={len(names)}")
        if args.tag:
            problems += check_published_release(facts, tag, names)
        if args.latest:
            problems += check_latest_matches_source(facts, tag)

    if args.check_urls:
        problems += check_download_urls(facts, facts.all_assets)

    if problems:
        for problem in problems:
            print(f"[release] FAIL: {problem}", file=sys.stderr)
        return 1
    print("[release] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
