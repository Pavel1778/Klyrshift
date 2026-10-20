// @ts-check
import { defineConfig, fontProviders } from "astro/config";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

// The site ships to two hosts that are both indexed: Layero (primary, Russian)
// and the Vercel mirror (English). Each build must declare its own origin so the
// canonical URLs, og:url and the sitemap point at the host that serves them,
// otherwise the two copies compete as duplicate content.
//
// Both hosts are served under the ``klyrshift.*`` names; the ``linguafix.*``
// names that the deployments used before the rename now return 404, so the
// canonical URL must not point at them. When a host is renamed, only these two
// constants change.
//
// VERCEL_URL is set for every Vercel build (including the stable production
// domain). SITE_URL overrides both for local checks.
const LAYERO_ORIGIN = "https://klyrshift.layero.app";
const VERCEL_ORIGIN = "https://klyrshift.vercel.app";

const site = process.env.SITE_URL || (process.env.VERCEL_URL ? VERCEL_ORIGIN : LAYERO_ORIGIN);

export default defineConfig({
  site,
  output: "static",
  integrations: [sitemap()],
  vite: {
    plugins: [tailwindcss()],
  },
  compressHTML: true,
  // Self-hosted via the Astro Fonts API (no blocking third-party request at
  // runtime). The display face carries the brand; Golos Text is the body face
  // because it has a full Cyrillic set and stays legible at small sizes.
  //
  // All three families are *variable* fonts (a single file per subset carries a
  // `wght` axis), so each is requested as a range rather than as a list of
  // discrete weights. Listing discrete weights emits one `@font-face` per weight
  // that all point at the same file, and -- worse -- a weight outside the list
  // (the `font-bold` on a `font-mono` label) has no face at all, so the browser
  // synthesises a smeared faux-bold instead of using the axis. The ranges are
  // the widest the page actually asks for: Golos 400-700, Unbounded 600-800
  // (h3/h2/h1 are semibold/bold/extrabold), JetBrains Mono 400-700.
  fonts: [
    {
      provider: fontProviders.google(),
      name: "Unbounded",
      cssVariable: "--font-unbounded",
      weights: ["600 800"],
      styles: ["normal"],
      subsets: ["latin", "cyrillic"],
      fallbacks: ["system-ui", "sans-serif"],
    },
    {
      provider: fontProviders.google(),
      name: "Golos Text",
      cssVariable: "--font-golos",
      weights: ["400 700"],
      styles: ["normal"],
      subsets: ["latin", "cyrillic"],
      fallbacks: ["system-ui", "sans-serif"],
    },
    {
      provider: fontProviders.google(),
      name: "JetBrains Mono",
      cssVariable: "--font-jetbrains",
      weights: ["400 700"],
      styles: ["normal"],
      subsets: ["latin", "cyrillic"],
      fallbacks: ["ui-monospace", "monospace"],
    },
  ],
});
