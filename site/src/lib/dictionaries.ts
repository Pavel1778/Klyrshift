// Shared dictionary metadata for the landing page and the /dictionaries page.
//
// The base frequency lists and the thematic (professional) lists are described
// once here, so the download section and the catalogue never drift apart. Sizes
// and word counts are read from the repository at build time, so a card always
// reflects what is actually shipped.
import fs from "node:fs";
import path from "node:path";

import { REPO, REPO_SLUG } from "../consts";

/** Stable URL prefix for release assets (attached to every GitHub Release). */
export const DICTIONARY_ASSET_BASE = `${REPO}/releases/latest/download`;

// Thematic files are linked from the repository mirror, not a release asset:
// the release publishes a ``<pkg>-dict-<slug>.tar.gz`` archive for only a
// subset of categories, so a release link 404s for the rest. The mirror file
// (``dictionaries/<slug>/<lang>-<slug>-1k.txt``) exists for every category and
// is the same file ``klyrshift dict install`` fetches, so a card link always
// works and always matches the CLI.
export const DICTIONARY_MIRROR_BASE =
  `https://raw.githubusercontent.com/${REPO_SLUG}/main/dictionaries`;

export type BaseLanguage = { code: string; title: string };

/**
 * Languages that ship a base frequency list (`<code>-50k.txt`).
 *
 * These lists are FrequencyWords content, so they are CC-BY-SA-4.0 -- unlike
 * the hand-curated thematic lists, which are MIT. The two are kept separate
 * everywhere the licence is shown.
 */
export const baseLanguages: BaseLanguage[] = [
  { code: "ru", title: "Русский" },
  { code: "en", title: "English" },
  { code: "uk", title: "Українська" },
  { code: "de", title: "Deutsch" },
  { code: "fr", title: "Français" },
];

/** Licence of the base frequency lists (FrequencyWords content). */
export const BASE_LIST_LICENSE = "CC-BY-SA-4.0";

/** Licence of the hand-curated thematic lists and of the code itself. */
export const THEMATIC_LIST_LICENSE = "MIT";

export type ThematicCategory = {
  slug: string;
  /** Localised titles; the site picks one per host language. */
  title: { ru: string; en: string };
  blurb: { ru: string; en: string };
  license: string;
  /** Accent hex used for the card monogram (light and dark share it). */
  color: string;
};

/** Thematic (professional) categories, one release archive each. */
export const thematicCategories: ThematicCategory[] = [
  {
    slug: "it",
    title: { ru: "IT / программирование", en: "IT / programming" },
    blurb: {
      ru: "Языки, фреймворки, git, БД, сети, DevOps.",
      en: "Languages, frameworks, git, databases, networks, DevOps.",
    },
    license: "MIT",
    color: "#3584e4",
  },
  {
    slug: "medicine",
    title: { ru: "Медицина и биология", en: "Medicine and biology" },
    blurb: {
      ru: "Анатомия, болезни, препараты, диагностика.",
      en: "Anatomy, diseases, drugs, diagnostics.",
    },
    license: "MIT",
    color: "#e01b24",
  },
  {
    slug: "legal",
    title: { ru: "Юриспруденция", en: "Law" },
    blurb: { ru: "Кодексы, процессы, договоры, суд.", en: "Codes, proceedings, contracts, courts." },
    license: "MIT",
    color: "#986a44",
  },
  {
    slug: "finance",
    title: { ru: "Финансы и бухгалтерия", en: "Finance and accounting" },
    blurb: {
      ru: "Банки, налоги, отчётность, инвестиции.",
      en: "Banking, taxes, reporting, investments.",
    },
    license: "MIT",
    color: "#2ec27e",
  },
  {
    slug: "engineering",
    title: { ru: "Инженерия и строительство", en: "Engineering" },
    blurb: {
      ru: "Сопромат, механизмы, материалы, ГОСТы.",
      en: "Mechanics, materials, drawings, standards.",
    },
    license: "MIT",
    color: "#e66100",
  },
  {
    slug: "science",
    title: { ru: "Наука", en: "Science" },
    blurb: {
      ru: "Физика, химия, математика, биология, астрономия.",
      en: "Physics, chemistry, mathematics, biology, astronomy.",
    },
    license: "MIT",
    color: "#9141ac",
  },
  {
    slug: "business",
    title: { ru: "Бизнес и менеджмент", en: "Business and management" },
    blurb: {
      ru: "Менеджмент, маркетинг, продажи, финансы, HR.",
      en: "Management, marketing, sales, finance, HR.",
    },
    license: "MIT",
    color: "#1c71d8",
  },
  {
    slug: "electronics",
    title: { ru: "Электроника", en: "Electronics" },
    blurb: {
      ru: "Схемы, компоненты, микроконтроллеры, Arduino, RTOS.",
      en: "Circuits, components, microcontrollers, Arduino, RTOS.",
    },
    license: "MIT",
    color: "#f5c211",
  },
  {
    slug: "media",
    title: { ru: "Медиа и журналистика", en: "Media and journalism" },
    blurb: {
      ru: "Журналистика, редактура, жанры, издательство.",
      en: "Journalism, editing, genres, publishing.",
    },
    license: "MIT",
    color: "#c061cb",
  },
  {
    slug: "education",
    title: { ru: "Образование", en: "Education" },
    blurb: {
      ru: "Педагогика, методика, статистика, ML-термины.",
      en: "Pedagogy, methodology, statistics, ML terms.",
    },
    license: "MIT",
    color: "#26a269",
  },
  {
    slug: "gaming",
    title: { ru: "Игры и киберспорт", en: "Gaming and esports" },
    blurb: {
      ru: "Жанры, движки, игровой жаргон, киберспорт.",
      en: "Genres, engines, gaming jargon, esports.",
    },
    license: "MIT",
    color: "#ff7800",
  },
  {
    slug: "sport",
    title: { ru: "Спорт", en: "Sport" },
    blurb: {
      ru: "Виды спорта, термины, правила, инвентарь.",
      en: "Sports, terms, rules, equipment.",
    },
    license: "MIT",
    color: "#33d17a",
  },
];

const dictRoot = path.resolve(process.cwd(), "..", "dictionaries");

/**
 * Text colour for a category chip, picked so the label stays readable on the
 * category's own colour. The palette spans light yellows and deep purples, so a
 * fixed white label failed WCAG AA on the light ones (white on #f5c211 is
 * 1.8:1). Relative luminance decides: dark text on light chips, white on dark.
 */
export function onCategoryColor(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const channel = parseInt(hex.slice(i, i + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const contrastWithWhite = 1.05 / (luminance + 0.05);
  const contrastWithBlack = (luminance + 0.05) / 0.05;
  return contrastWithWhite >= contrastWithBlack ? "#ffffff" : "#111113";
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function countWords(file: string): number {
  try {
    return fs
      .readFileSync(file, "utf-8")
      .split("\n")
      .filter((line) => line.trim().length > 0).length;
  } catch {
    return 0;
  }
}

function fileSize(file: string): number {
  try {
    return fs.statSync(file).size;
  } catch {
    return 0;
  }
}

export type CategoryFile = { lang: string; title: string; size: number; words: number };
export type CategoryCard = ThematicCategory & { files: CategoryFile[] };

/** Categories with per-language file size and word count read from the repo. */
export const categoryCards: CategoryCard[] = thematicCategories.map((cat) => ({
  ...cat,
  files: [
    { lang: "ru", title: "Русский" },
    { lang: "en", title: "English" },
  ].map(({ lang, title }) => {
    const file = path.join(dictRoot, cat.slug, `${lang}-${cat.slug}-1k.txt`);
    return { lang, title, size: fileSize(file), words: countWords(file) };
  }),
}));

/** Total number of words across every thematic category (both languages). */
export const thematicWordTotal = categoryCards.reduce(
  (sum, cat) => sum + cat.files.reduce((n, file) => n + file.words, 0),
  0,
);
