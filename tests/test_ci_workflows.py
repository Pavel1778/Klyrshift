"""CI workflow contract: runner pinning, release safety, reproducibility.

These guard the workflow files the way ``test_packaging_contract.py`` guards the
package: a change that silently un-pins a runner, drops the re-publish guard or
removes the reproducibility check would otherwise only be visible in CI, long
after the edit. They are pure text/parse checks, so they run offline.

The rules encoded here are the ones the repository deliberately chose, not
"every job must be pinned":

* jobs that *build the .deb* must share one pinned image, because the
  reproducible-build contract is "same tree -> same sha256" and the packaging
  toolchain is part of the build environment;
* the GUI job must pin an image whose distribution PyGObject matches the test
  interpreter ABI;
* every other job stays on ``ubuntu-latest`` on purpose, so it exercises the
  newest Ubuntu first.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"

# ``uses: owner/action@<ref>``; the ref is the text after the last ``@``.
_USE_REF = re.compile(r"^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@(\S+)", re.MULTILINE)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _job_runner(text: str, job: str) -> str:
    """Return the ``runs-on:`` value of ``job`` (a top-level job id)."""
    match = re.search(
        rf"^  {re.escape(job)}:\n(?:.*\n)*?    runs-on: (\S+)",
        text,
        re.MULTILINE,
    )
    assert match is not None, f"job {job!r} has no runs-on"
    return match.group(1)


# --- runner pinning ---------------------------------------------------------


def test_package_job_is_pinned() -> None:
    """The .deb-building job must pin its image, not float on ubuntu-latest.

    The published artifact and the CI artifact must be the same bytes; a moving
    image could change the packaging toolchain between them without a code
    change.
    """
    assert _job_runner(CI.read_text(encoding="utf-8"), "package") == "ubuntu-24.04"


def test_release_job_pins_the_same_image_as_the_package_job() -> None:
    """CI's package job and the release job must build on the same image.

    Otherwise the artifact a reviewer downloads from the PR and the artifact
    that is published could differ for the same commit.
    """
    ci = CI.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    assert _job_runner(release, "build-and-release") == _job_runner(ci, "package")


def test_gui_job_is_pinned_for_the_distro_pygobject_abi() -> None:
    """The GUI job imports the *distribution* PyGObject, so its image is fixed."""
    assert _job_runner(CI.read_text(encoding="utf-8"), "gui") == "ubuntu-24.04"


@pytest.mark.parametrize("job", ["lint-and-test", "latency-budget", "qa", "site"])
def test_code_jobs_stay_on_latest_on_purpose(job: str) -> None:
    """Jobs that validate code (not the package) run on the newest Ubuntu.

    Pinning them would hide the "does the code still work on the next Ubuntu"
    signal, which is the whole point of running them on ``ubuntu-latest``.
    """
    assert _job_runner(CI.read_text(encoding="utf-8"), job) == "ubuntu-latest"


# --- action pinning ---------------------------------------------------------


@pytest.mark.parametrize("path", [CI, RELEASE])
def test_actions_are_pinned_to_a_commit_sha(path: Path) -> None:
    """Every ``uses:`` must be a full commit SHA, not a floating tag.

    A floating major tag (``@v7``) lets an upstream release change the action
    under us; a SHA pin makes the workflow reproducible and the supply chain
    reviewable.
    """
    text = path.read_text(encoding="utf-8")
    refs = _USE_REF.findall(text)
    assert refs, f"{path.name} has no pinned action"
    floating = [ref for ref in refs if not _SHA40.match(ref)]
    assert not floating, f"{path.name} uses floating action refs: {floating}"


# --- release safety ---------------------------------------------------------


def test_release_refuses_to_re_publish_an_existing_release() -> None:
    """A tag whose release already exists must abort, never overwrite it."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "gh release view" in text, "no re-publish guard"
    assert "already exists" in text, "the re-publish guard does not refuse"
    # It must run before the release is created.
    assert text.index("gh release view") < text.index("action-gh-release")


def test_release_requires_green_ci_on_the_tagged_commit() -> None:
    """The tagged commit must have a successful CI run before publishing."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "gh run list --workflow ci.yml --commit" in text
    assert text.index("gh run list --workflow ci.yml --commit") < text.index("action-gh-release")


def test_release_verifies_the_build_is_reproducible() -> None:
    """The published bytes must be reproducible from the tree before upload."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "byte-reproducible" in text
    assert text.index("byte-reproducible") < text.index("action-gh-release")


def test_ci_enforces_reproducibility() -> None:
    """CI must build the .deb twice and require identical bytes."""
    text = CI.read_text(encoding="utf-8")
    assert "byte-reproducible" in text
    assert "second build" in text


@pytest.mark.parametrize("path", [CI, RELEASE])
def test_workflows_have_a_concurrency_group(path: Path) -> None:
    """A superseded run must not pile up (CI) or cancel a release (release)."""
    text = path.read_text(encoding="utf-8")
    assert "concurrency:" in text, f"{path.name} has no concurrency group"


def test_release_never_cancels_in_progress() -> None:
    """A cancelled publish could leave a partial asset set."""
    assert "cancel-in-progress: false" in RELEASE.read_text(encoding="utf-8")


def test_every_job_has_a_timeout() -> None:
    """A stuck runner must not hang a job for the default six hours."""
    for path in (CI, RELEASE):
        text = path.read_text(encoding="utf-8")
        # Only look at the ``jobs:`` block, so ``on: push:`` is not mistaken for
        # a job id.
        jobs_block = text[text.index("\njobs:") :]
        jobs = re.findall(r"^  ([a-z][a-z0-9-]*):$", jobs_block, re.MULTILINE)
        assert jobs, f"{path.name}: no jobs found"
        for job in jobs:
            block = re.search(
                rf"^  {re.escape(job)}:\n(?:.*\n)*?(?=^  \S|\Z)", jobs_block, re.MULTILINE
            )
            assert block is not None, job
            assert "timeout-minutes:" in block.group(0), f"{path.name}:{job} has no timeout"
