// The site ships to two hosts that are both indexed, so they must not compete as
// duplicate content. Each host declares itself canonical and cross-links the other
// with hreflang:
//   - Layero (primary, Russian):  https://klyrshift.layero.app
//   - Vercel (mirror, English):   https://klyrshift.vercel.app
//
// Both hosts are served under the ``klyrshift.*`` names; the ``linguafix.*``
// names the deployments used before the rename now return 404, so the canonical
// URL, ``og:url`` and the sitemap must not point at them. When a host is renamed,
// only these two constants change.
//
// VERCEL_URL is set for every Vercel build (including the stable production
// domain), so it selects the Vercel host. The canonical/OG origin is always the
// stable domain, never the per-deployment VERCEL_URL host.
//
// SITE_URL overrides the origin for local checks. It has to be honoured here as
// well as in astro.config.mjs: the sitemap takes its origin from that config
// while the canonical/og:url/hreflang take theirs from here, so a build that
// sets only one of the two disagrees with itself.
export const LAYERO_URL = "https://klyrshift.layero.app";
export const VERCEL_URL = "https://klyrshift.vercel.app";

export const isVercel = Boolean(import.meta.env.VERCEL_URL);

/** Origin of the host currently being built. */
export const siteUrl = import.meta.env.SITE_URL || (isVercel ? VERCEL_URL : LAYERO_URL);

/** BCP-47 language of the host currently being built. */
export const lang = isVercel ? "en" : "ru";

/** Text shown in a copy's own language, keyed by the host language. */
export function pick<T>(ru: T, en: T): T {
  return isVercel ? en : ru;
}
