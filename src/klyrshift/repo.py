"""Single source of truth for the project's GitHub URLs.

The project is called **Klyrshift**; the GitHub repository was renamed from
``LinguaFix`` to ``Klyrshift`` and GitHub redirects the old slug, so every URL
here is built from the current name.

Release **asset** names are a separate concern from the repository name. The
build scripts emit ``klyrshift_*`` artifacts from this tree; the older releases
(``v0.2.8`` and earlier) still carry ``lingvix-*`` and ``linguafix-*`` assets,
which is why the download helpers keep those prefixes as fallbacks.
"""

from __future__ import annotations

from typing import Final

REPO_SLUG: Final[str] = "Pavel1778/Klyrshift"
REPO_URL: Final[str] = f"https://github.com/{REPO_SLUG}"
RELEASES_URL: Final[str] = f"{REPO_URL}/releases"
LATEST_RELEASE_URL: Final[str] = f"{RELEASES_URL}/latest"

# Stable prefix for assets attached to the latest GitHub Release. The asset
# name itself is produced by ``scripts/build_deb.sh`` / ``build_dict_archives.sh``.
LATEST_ASSET_BASE: Final[str] = f"{LATEST_RELEASE_URL}/download"

# Branch mirror used when a release asset is missing (a category that has not
# been published yet). Points at the default branch of the same repository.
RAW_MIRROR_BASE: Final[str] = f"https://raw.githubusercontent.com/{REPO_SLUG}/main/"
