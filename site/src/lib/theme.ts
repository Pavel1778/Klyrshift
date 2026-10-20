// The browser-chrome colour, in one place.
//
// `theme-color` has to be set from JavaScript (see Base.astro) because the
// visitor's saved theme can differ from their system preference, and the value
// was previously written out by hand in three files. A palette change would
// update `global.css` and leave the browser chrome on the old colour.
// `tests/test_site_theme.py` fails if these drift from the `--color-bg` tokens.
export const THEME_COLOR = {
  light: "#fafafa",
  dark: "#16181c",
} as const;

export type ThemeName = keyof typeof THEME_COLOR;
