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
      cssVariable: "--font-jetbrains",
      weights: [400],
      styles: ["normal"],
      subsets: ["latin", "cyrillic"],
      fallbacks: ["ui-monospace", "monospace"],
    },
  ],
});
