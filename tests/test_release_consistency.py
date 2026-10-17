"""The tree must describe the release it claims to be -- and must not lie about it.

The landing page advertised ``v0.2.8.2`` while the newest *published* release
was ``v0.2.8``: the version had been bumped in the source and never tagged, so
every "download the latest release" button served a different build than the
page named. ``test_version_consistency.py`` compared the source files only with
each other and could not see this.

The checks are split on purpose:

* everything here is **offline** -- it compares the tree with itself and with
  the asset names the build scripts emit, so an *unreleased* version is not a
  failure and the normal test run never touches the network;
* the comparison with the *published* release lives in
  ``scripts/release_consistency.py --tag`` / ``--latest`` and runs from the
  release workflow, where the release and the token actually exist.

``check_published_release`` is a pure function so the drift can be exercised
here with a recorded payload instead of a network call.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_consistency.py"


def _load_module() -> object:
    """Import ``scripts/release_consistency.py`` without it being a package.

    The module is registered in ``sys.modules`` before execution: ``@dataclass``
    resolves the defining module by name, and an unregistered module makes it
    raise ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    """
    name = "release_consistency"
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
def rc() -> object:
    return _load_module()


# --- the tree against itself (offline) ---------------------------------------


def test_source_versions_agree(rc: object) -> None:
    """pyproject, consts.ts and the JSON-LD must name one version."""
    facts = rc.collect_source_facts()
    assert rc.check_source_consistency(facts) == []


def test_site_package_version_matches_the_tree(rc: object) -> None:
    """The landing page's package.json must carry the release version too.

    It lagged at ``0.2.8.2`` while ``consts.ts`` said ``0.2.8.3``: nothing read
    it, so nothing failed, and the npm metadata described a build that no longer
    existed.
    """
    facts = rc.collect_source_facts()
    assert facts.site_package_version == facts.version


def test_jsonld_version_is_not_a_literal(rc: object) -> None:
    """The JSON-LD version must be derived, not typed.

    It was a literal ``"0.2.8.2"`` in ``Base.astro`` while ``consts.ts`` held
    ``VERSION``, so a version bump updated the hero and left the structured data
    behind -- two versions on one page, invisible to every other test.
    """
    facts = rc.collect_source_facts()
    assert (
        not facts.jsonld_is_literal
    ), "Base.astro hard-codes softwareVersion; import VERSION from consts instead"


def test_deb_asset_name_matches_the_version(rc: object) -> None:
    facts = rc.collect_source_facts()
    assert facts.deb_asset == f"{facts.package}_{facts.version}_all.deb"


def test_expected_assets_cover_every_dictionary(rc: object) -> None:
    """The release must ship a 50k list and a thematic archive per category."""
    facts = rc.collect_source_facts()
    languages = {a.split("-")[0] for a in facts.frequency_assets}
    assert languages >= {"ru", "en"}, f"frequency assets: {facts.frequency_assets}"
    assert facts.dict_archives, "no thematic archives were derived"
    assert all(a.startswith("klyrshift-dict-") for a in facts.dict_archives)


def test_release_workflow_attaches_every_expected_asset(rc: object) -> None:
    """A build script that emits an asset the workflow never uploads is a 404.

    ``dict install`` fetches ``klyrshift-dict-<slug>.tar.gz`` from the *release*,
    so the workflow's file list is part of the contract, not an implementation
    detail. This compares the names the scripts emit with the globs the workflow
    publishes, without running either.
    """
    facts = rc.collect_source_facts()
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    # The globs the workflow uploads, mapped to what they must cover.
    assert "dist/*.deb" in workflow, "the workflow does not upload the .deb"
    assert "dist/*.tar.gz" in workflow, "the workflow does not upload the sdist"
    assert "dist/dict-archives/*.tar.gz" in workflow, "the workflow does not upload the archives"
    assert "dist/dictionaries/*-50k.txt" in workflow, "the workflow does not upload the 50k lists"

    # And the archives must be built by the same script that names them.
    assert "build_dict_archives.sh" in workflow
    for archive in facts.dict_archives:
        slug = archive.removeprefix("klyrshift-dict-").removesuffix(".tar.gz")
        assert (REPO_ROOT / "dictionaries" / slug / "README.md").is_file(), slug


def test_release_workflow_checks_consistency_before_publishing(rc: object) -> None:
    """The workflow must gate the publish on the version/tag/assets agreeing.

    Without this the tag is cut, the release is created and only then does
    anyone notice the assets or the version disagree.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "release_consistency.py" in workflow, "the release workflow does not run the check"
    assert "--tag" in workflow, "the release workflow does not check the pushed tag"
    # The check must run before the release is created, not after.
    assert workflow.index("release_consistency.py") < workflow.index("action-gh-release")


# --- the tree against a published release (pure; payload supplied by the test) -


def test_published_release_with_matching_tag_and_assets_passes(rc: object) -> None:
    facts = rc.collect_source_facts()
    assert rc.check_published_release(facts, facts.tag, facts.all_assets) == []


def test_a_different_published_tag_is_caught(rc: object) -> None:
    """The exact 0.2.8-vs-0.2.8.2 drift, as a unit test."""
    facts = rc.collect_source_facts()
    problems = rc.check_published_release(facts, "v0.2.8", facts.all_assets)
    assert any("tag" in p for p in problems), problems


def test_a_missing_asset_is_caught(rc: object) -> None:
    facts = rc.collect_source_facts()
    problems = rc.check_published_release(facts, facts.tag, facts.all_assets[:-1])
    assert any("missing expected assets" in p for p in problems), problems


def test_an_unexpected_deb_is_caught(rc: object) -> None:
    facts = rc.collect_source_facts()
    problems = rc.check_published_release(
        facts, facts.tag, [*facts.all_assets, "klyrshift_0.2.8.1_all.deb"]
    )
    assert any("unexpected .deb" in p for p in problems), problems


def test_latest_ahead_of_the_tree_is_caught(rc: object) -> None:
    """``/releases/latest/download`` serving a different version than the page."""
    facts = rc.collect_source_facts()
    assert rc.check_latest_matches_source(facts, facts.tag) == []
    assert rc.check_latest_matches_source(facts, "v0.2.8") != []


def test_download_urls_use_the_repository_that_exists(rc: object) -> None:
    """The stable download URL must be built from the live slug, not a literal."""
    facts = rc.collect_source_facts()
    url = rc.download_url(facts, facts.deb_asset)
    assert url.startswith(f"https://github.com/{facts.repo_slug}/releases/latest/download/")
    assert url.endswith(facts.deb_asset)
