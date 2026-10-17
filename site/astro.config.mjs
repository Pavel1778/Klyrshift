// @ts-check
import { defineConfig, fontProviders } from "astro/config";
import tailwind from "@astrojs/tailwind";
import sitemap from "@astrojs/sitemap";

// The site ships to two hosts that are both indexed: Layero (primary, Russian)
// and the Vercel mirror (English). Each build must declare its own origin so the
// canonical URLs, og:url and the sitemap point at the host that serves them,
// otherwise the two copies compete as duplicate content.
//
// The hosts are still named ``linguafix.*``: the ``Klyrshift`` rename is done in
// the source but the DNS entries were never renamed, so ``klyrshift.layero.app``
// and ``klyrshift.vercel.app`` are 404. Pointing the canonical URL at a 404 makes
// search engines drop the page, so the names that resolve are used here. When
// the hosts are renamed, only these two constants change.
//
// VERCEL_URL is set for every Vercel build (including the stable production
// domain). SITE_URL overrides both for local checks.
const LAYERO_ORIGIN = "https://linguafix.layero.app";
const VERCEL_ORIGIN = "https://linguafix.vercel.app";

const site = process.env.SITE_URL || (process.env.VERCEL_URL ? VERCEL_ORIGIN : LAYERO_ORIGIN);

export default defineConfig({
  site,
  output: "static",
  integrations: [tailwind(), sitemap()],
  compressHTML: true,
  experimental: {
    // Self-hosted at build time with metric-matched fallbacks, so the text
    // does not reflow when the webfont swaps in (avoids layout shift).
    fonts: [
      {
        provider: fontProviders.google(),
        name: "Inter",
        cssVariable: "--font-inter",
        weights: [400, 500, 700],
        styles: ["normal"],
        subsets: ["latin", "cyrillic"],
        fallbacks: ["system-ui", "sans-serif"],
      },
      {
        provider: fontProviders.google(),
        name: "JetBrains Mono",
        cssVariable: "--font-mono",
        weights: [400],
        styles: ["normal"],
        subsets: ["latin", "cyrillic"],
        fallbacks: ["ui-monospace", "monospace"],
      },
    ],
  },
});
