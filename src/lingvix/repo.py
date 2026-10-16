"""Single source of truth for the project's GitHub URLs.

The repository was renamed ``LinguaFix`` → ``Lingvix`` in the source, but the
GitHub repository rename has not happened yet: ``Pavel1778/Lingvix`` is a 404
while ``Pavel1778/LinguaFix`` resolves. Every download URL therefore has to be
built from the repository that actually exists, or ``dict download`` /
``dict install`` fail with HTTP 404 (the branch mirror is derived from the same
slug). When the rename is finally done, only :data:`REPO_SLUG` changes here.

Release **asset** names are a separate concern from the repository name: the
build scripts already emit ``lingvix_*`` artifacts, so the asset prefix stays
``lingvix`` even while the repository is still called ``LinguaFix``.
"""

from __future__ import annotations

from typing import Final

# The repository that exists today. Flip to ``Pavel1778/Lingvix`` once the
# GitHub rename is unblocked.
REPO_SLUG: Final[str] = "Pavel1778/LinguaFix"
REPO_URL: Final[str] = f"https://github.com/{REPO_SLUG}"
RELEASES_URL: Final[str] = f"{REPO_URL}/releases"
LATEST_RELEASE_URL: Final[str] = f"{RELEASES_URL}/latest"

# Stable prefix for assets attached to the latest GitHub Release. The asset
# name itself is produced by ``scripts/build_deb.sh`` / ``build_dict_archives.sh``.
LATEST_ASSET_BASE: Final[str] = f"{LATEST_RELEASE_URL}/download"

# Branch mirror used when a release asset is missing (a category that has not
# been published yet). Points at the default branch of the same repository.
RAW_MIRROR_BASE: Final[str] = f"https://raw.githubusercontent.com/{REPO_SLUG}/main/"
