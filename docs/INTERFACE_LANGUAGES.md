# Interface languages

Klyrshift detects text typed in the wrong keyboard layout. That is a problem
that has nothing to do with the language a menu is written in, so the interface
language is a separate setting from the languages the detector knows. This
document explains how the interface is translated, which languages ship, and how
to add one.

## What is translated, and what is not

Only the *interface* is translated: menu items, setting labels, explanations,
notifications and CLI output. Three things are deliberately left alone.

* **The Russian source strings are the keys.** Every user-facing string in the
  source is written in Russian, and the catalogues map that Russian text to a
  translation. There is no invented message id, so a reader of the source sees
  the sentence that is actually shown, and a missing catalogue entry degrades to
  Russian rather than to a placeholder like `settings.title`.
* **Words the detector processes are never translated.** A dictionary entry, a
  stop word or a snippet is data, not interface. Translating it would change what
  the daemon corrects.
* **Diagnostic output that a bug report depends on** stays in one form. The
  layout tables, the `doctor` check identifiers and the manifest fields are
  matched literally by tests and by support, so they are not localised.

## The languages that ship

| Code | Language | Catalogue | Plural forms |
|---|---|---|---|
| `ru` | Русский | source (no file) | 3 |
| `en` | English | `data/locales/en.json` | 2 |
| `de` | Deutsch | `data/locales/de.json` | 2 |
| `fr` | Français | `data/locales/fr.json` | 2 |
| `uk` | Українська | `data/locales/uk.json` | 3 |

The list lives in one place, `klyrshift.i18n.SUPPORTED_LOCALES`. The config
validator (`config.VALID_UI_LOCALES`) and the GUI selector
(`gui.settings_page.UI_LOCALE_ORDER`) both derive their lists from it, so a new
catalogue cannot appear in one and be rejected by another. A test asserts this.

### How complete the catalogues are

A new catalogue is not expected to be complete on the first commit. German,
French and Ukrainian each carry 381 of the 675 source strings (56%), which
covers everything the settings window, the CLI and the first-run tour and
context help render. The remainder — the tray labels and some daemon messages —
is not translated yet and falls back to English. The English catalogue is the
complete one and a test fails the build if a source string is missing from it,
so a gap can never be a missing key, only an untranslated one.

| Area | Covered in `de`/`fr`/`uk` |
|---|---|
| Settings window (all pages and widgets) | yes |
| CLI output (`hotkeys`, `status`, `doctor`, …) | mostly |
| First-run tour and context help | yes |
| Tray, some daemon messages | no (falls back to English) |

## Choosing a language

There are three ways, in order of precedence.

1. **`--lang <code>`** on any CLI invocation localises that one run:
   `klyrshift --lang de hotkeys`. This also works for `--help`, which is built
   before the flag is parsed.
2. **The `ui_locale` setting** (`[general] ui_locale` in `config.toml`, or the
   "Interface language" combo on the settings page). The value `auto` follows the
   desktop; any other value forces a shipped catalogue. It is applied at startup
   without a restart.
3. **`auto`** reads the environment, honouring `LANGUAGE`, `LC_ALL`,
   `LC_MESSAGES` and `LANG` in that order. A value like `ru_RU.UTF-8` or
   `de_AT@euro` is reduced to its language part; an unsupported one falls back to
   Russian.

The combo lists every language **in its own script** (`Deutsch`, `Français`,
`Українська`) rather than in the currently active language. A user who cannot
read the current interface language is exactly the user who needs the selector,
and "German" written in Russian does not help them.

## Falling back

A catalogue is translated incrementally, so it may not cover every string. When
an entry is missing the lookup walks a chain before giving up:

```
active locale  →  en  →  Russian source
```

German, French and Ukrainian therefore fall back to **English**, not to Russian.
An incomplete German build shows an English label here and there; it never shows
a German speaker a Cyrillic sentence. `en` and `ru` are terminals: the chain is
empty and the source text is used. `i18n.LOCALE_FALLBACKS` holds the chains and a
test forbids a self-referential entry.

The same principle governs plurals. `i18n.plural_form(count, locale)` returns a
form index for a list-valued entry. Russian and Ukrainian use three forms (1,
2–4, 5+); English and German use two; French uses two but treats zero as
singular ("0 mot"), which is why it is not folded into the default branch.

## Adding a language

1. Add the code to `SUPPORTED_LOCALES` in `src/klyrshift/i18n.py`.
2. Add its native name to `LOCALE_NAMES` and its fallback chain to
   `LOCALE_FALLBACKS`.
3. Add `data/locales/<code>.json`. Start from `en.json` and translate the
   strings the interface renders; leave the rest out and the chain fills them.
4. Run `tests/test_i18n.py`. It fails the build when a catalogue entry is
   orphaned (a key that is not a source string), when a plural helper
   mis-selects a form, and when the config or GUI list drifts from the registry.

Nothing else changes: the combo, the validator and `--lang` all read the
registry. A catalogue that is valid JSON but wrong is a cosmetic defect, never a
crash — every lookup falls back to the source string.
