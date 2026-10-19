// Single source of truth for the landing page's external URLs and version.
//
// The GitHub repository is named ``Klyrshift``: the rename from ``LinguaFix`` is
// done both in the source and on GitHub, and GitHub redirects the old slug.
//
// The canonical hosts are the ``klyrshift.*`` ones, matching the repository name.
// The origins below are written into ``<link rel="canonical">``, ``og:url`` and
// the sitemap; the two origin constants in ``astro.config.mjs``/``lib/site.ts``
// must agree with them.
export const VERSION = "0.2.9";

export const REPO_OWNER = "Pavel1778";
export const REPO_NAME = "Klyrshift";
export const REPO_SLUG = `${REPO_OWNER}/${REPO_NAME}`;
export const REPO = `https://github.com/${REPO_SLUG}`;
export const AUTHOR_URL = `https://github.com/${REPO_OWNER}`;
export const RELEASES = `${REPO}/releases`;
export const LATEST_RELEASE = `${RELEASES}/latest`;
// The download button points at the release page rather than a versioned asset
// URL: the tag may not exist yet while the page is live, so a hard-coded asset
// URL 404s. The release page always lists whatever the latest tag actually ships.
export const DOWNLOAD_URL = LATEST_RELEASE;
export const ISSUES = `${REPO}/issues`;
export const CONTRIBUTING = `${REPO}/blob/main/docs/CONTRIBUTING.md`;
export const INSTALL_DOC = `${REPO}/blob/main/docs/INSTALL.md`;
export const LICENSE = `${REPO}/blob/main/LICENSE`;
export const CI_BADGE = `${REPO}/actions/workflows/ci.yml/badge.svg`;
