// Single source of truth for the landing page's external URLs and version.
//
// The repository is still named ``LinguaFix`` on GitHub: the ``Lingvix``
// rename is done in the source but the GitHub repository rename has not been
// performed yet, and a link to ``.../Lingvix`` is a 404. When the rename is
// finally done, only ``REPO_SLUG`` changes here.
export const VERSION = "0.2.8.2";

export const REPO_OWNER = "Pavel1778";
export const REPO_SLUG = `${REPO_OWNER}/LinguaFix`;
export const REPO = `https://github.com/${REPO_SLUG}`;
export const AUTHOR_URL = `https://github.com/${REPO_OWNER}`;
export const RELEASES = `${REPO}/releases`;
export const LATEST_RELEASE = `${RELEASES}/latest`;
// The download button points at the release page rather than a versioned asset
// URL: the published asset is named after the *previous* package name
// (``linguafix_<version>_all.deb``) and the ``v${VERSION}`` tag may not exist
// yet, so a hard-coded asset URL 404s. The release page always lists whatever
// the latest tag actually ships.
export const DOWNLOAD_URL = LATEST_RELEASE;
export const ISSUES = `${REPO}/issues`;
export const CONTRIBUTING = `${REPO}/blob/main/docs/CONTRIBUTING.md`;
export const INSTALL_DOC = `${REPO}/blob/main/docs/INSTALL.md`;
export const LICENSE = `${REPO}/blob/main/LICENSE`;
export const CI_BADGE = `${REPO}/actions/workflows/ci.yml/badge.svg`;
