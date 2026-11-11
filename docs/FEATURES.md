# Implemented features

What Klyrshift ships today, grouped by area. Every entry is implemented in
`src/klyrshift/` and covered by the test suite unless the row says otherwise;
the "Where" column names the module or command a reader can open to confirm it.
This is a status inventory, not a plan -- what is *not* built yet lives in
[ROADMAP.md](ROADMAP.md), and the design behind each area is in
[ARCHITECTURE.md](ARCHITECTURE.md).

The version this list describes is the one in `pyproject.toml` (0.2.10 at the
time of writing). The suite that backs it is `pytest` (about 1900 tests,
≥ 80 % coverage) plus the deterministic QA corpus.

## Core correction

| Feature | Where | Notes |
|---|---|---|
| Wrong-layout detection | `detector.py` | Combines character-frequency, n-gram and context signals. |
| Rewrite of already-typed text | `daemon.py`, `injector.py` | `ghbdtn` → `привет`; the daemon tracks the word as scancodes, not characters. |
| Character-level layout conversion | `converter.py` | Same physical keys, other layout. |
| Three correction modes | `config.py` (`mode`) | `auto`, `manual`, `hybrid`; `manual` is the master gate for every automatic pass. |
| Confidence model and withholding | `detector.py`, `daemon.py` | `hybrid` withholds a low-margin fix and offers it via the tray, the accept hotkey or a notification. |
| Word-boundary triggers | `config.py` | Space and Enter on by default; Tab and punctuation opt-in. |
| Configurable hotkeys | `config.py`, `daemon.py` | Fix (`SHIFT+SHIFT`), undo (`SHIFT+BACKSPACE`), toggle layout, T9, punctuation, accept suggestion, reload. |
| Undo of the last fix | `daemon.py` | A bounded, caret-aware history; see [UNDO_CONTRACT.md](UNDO_CONTRACT.md). |
| False-positive guards | `detector.py` | Plausibility, structural-boundary and identifier guards; a token with `. @ / \ : _ -` is never rewritten. |
| Mixed-script protection | `detector.py` | A token mixing Latin and Cyrillic is never converted as a unit. |
| Short-word fix hotkey | `detector.py` | Forces a below-`min_word_length` word on the explicit hotkey. |
| Layout switching | `switcher.py` | `g3kb-switch` (Wayland) and `setxkbmap` (X11). |
| Text injection backends | `injector.py` | `uinput` (atomic), `wtype`, `xdotool`. |

## Learning and text intelligence

| Feature | Where | Notes |
|---|---|---|
| Session learning | `learning.py` | Remembers accepted, rejected and kept words; always on. |
| Rejection suppression | `learning.py`, `daemon.py` | `Ctrl+Z` (or the undo hotkey) suppresses a word for the session; an explicit hotkey still wins. |
| Vocabulary promotion | `learning.py` | A word promoted after `learning_promote_threshold` keeps is never rewritten. |
| Privacy-preserving profile | `learning.py` | Only counters reach disk; no typed word is ever persisted. |
| Typo correction (T9) | `typo.py` | Opt-in; replaces a word only within `max_distance` of exactly one vocabulary word. |
| Punctuation cleanup | `punctuation.py` | Opt-in; dashes, ellipsis, smart quotes, spacing. |
| Text expansion (snippets) | `text_expander.py` | `!!email` → longer text at a word boundary. |
| Selection fix | `selection_fix.py` | Converts an already-selected piece of text on a hotkey. |
| Context analysis | `detector.py` | Neighbouring words may only *add* to a candidate, never suppress one. |

## Dictionaries and languages

| Feature | Where | Notes |
|---|---|---|
| Bundled base dictionaries | `dictionaries/`, `dictionary.py` | Five languages (`en`, `ru`, `uk`, `de`, `fr`); `en`+`ru` loaded by default. |
| Thematic (professional) dictionaries | `thematic.py` | 14 categories (IT, code, names, medicine, legal, finance, engineering, science, business, electronics, media, education, gaming, sport), ru+en. |
| User dictionary | `dictionary.py` | Consulted in two directions; edited explicitly, never auto-written from typed text. |
| Extended dictionary download | `dictionary.py` | Release asset → branch mirror → upstream → bundled source. |
| Versioned language packages | `langpack.py` | `manifest.json` + per-member SHA-256, verified before any write, with rollback on failure. |
| Language install/remove from the GUI | `langstore.py` | Backs the Dictionary tab. |
| Technical-token protection | `data/stop_words.txt` | Short vowel-less tokens (`http`, `pdf`, `jwt`, ...) stay in the typed layout. |

## Interface (GTK4 / libadwaita)

| Feature | Where | Notes |
|---|---|---|
| Preferences window | `gui/window.py`, `gui/*_page.py` | Home, Settings, Advanced, Dictionary, Typo, History, Help, About pages. |
| First-run wizard and guided tour | `gui/widgets/first_run_wizard.py`, `onboarding.py`, `gui/widgets/tour_overlay.py` | Languages, mode and autostart, then the tour. |
| System tray | `tray.py` | Optional AppIndicator icon. |
| Notifications | `daemon.py` | Fixed label, never the corrected text. |
| Light / dark / system theme | `gui/theme.py` | Window appearance only. |
| Interface localisation | `i18n.py`, `data/locales/` | Russian, English, German, French, Ukrainian; a missing entry falls back to the Russian source. |
| Keyboard navigation and shortcuts dialog | `gui/widgets/shortcuts_dialog.py` | Tab reachable; `Ctrl+Page_Down/Up`, `Ctrl+?`. |
| Per-application profiles | `app_layouts.py`, `config.py` | `exceptions_apps` skips an app; `[app_layouts]` pins its layout; `[app_modes]` pins its mode. |
| Quiet hours | `config.py` | Automatic correction silent in a time window; the manual hotkey still works. |
| Password-field guard | `app_focus.py` | Skips correction in password fields. |

## Command line and operations

| Feature | Where | Notes |
|---|---|---|
| Daemon control | `cli.py`, `daemon_control.py` | `start`, `stop`, `kill`, `restart`, `status`, `--dry-run`. |
| Configuration | `cli.py` | `mode`, `app-mode`, `config show/edit/reset/path/migrate`, `hotkeys`, `undo`. |
| Correction tools | `cli.py` | `fix`, `explain`, `simulate`. |
| Learning control | `cli.py` | `learn list/list-rejected/promote/forget`, `--on/--off/--reset`. |
| Dictionary management | `cli.py` | `dict list/add/remove/download/import-file/categories/install/remove-category/list-installed`, `pack/verify/install-file/uninstall-file`. |
| Backup and restore | `backup.py`, `cli.py` | `export` / `import` of config, user dictionary and snippets. |
| Self-diagnosis | `doctor.py` | `doctor` prints a ✅/❌ table with hints. |
| Integrity check | `integrity.py` | `verify` re-checks the `.deb` `md5sums` manifest and honours dpkg `path-exclude`. |
| Logging | `logs.py`, `collect_logs.py` | `logs -n/-f/--level`, `collect-logs` diagnostic archive. |
| Hot config reload | `daemon.py` | `SIGHUP` rebuilds every derived cache atomically. |
| Autostart | `daemon_control.py`, `install.sh` | Systemd user unit plus the XDG entry, both honoured. |
| Update check | `update_check.py` | Opt-in daily GitHub releases check, off the input thread. |

## Testing and quality

| Feature | Where | Notes |
|---|---|---|
| Unit and integration suite | `tests/` | Fakes the OS boundary; about 1900 tests. |
| Headless simulator | `simulate.py` | Drives the real daemon with a faked keyboard and renders the screen. |
| Autonomous QA engine | `qa/` | Curated + seeded scenarios, structural invariants, regression store; deterministic and offline. |
| Detector benchmark | `scripts/measure_detector.py` | Recall, false positives, corruption and latency on fixed slices. |
| Latency/memory budget | `scripts/measure_latency.py` | Fails a CI job past the budget. |
| Package tests | `scripts/*_test.sh` | Smoke, zero-config, self-sufficiency and patch-upgrade on real containers. |
| Reproducible `.deb` | `scripts/build_deb.sh` | Pinned compressor, clamped mtimes, date from the changelog. |
| Debian Policy compliance | `data/copyright`, `scripts/build_deb.sh` | DEP-5 `copyright`, Debian changelog, man page, shell completion. |
| Landing page | `site/` | Astro site with a live detector demo kept in parity by a test. |

## Deliberate limits

These are documented, not defects; see [ROADMAP.md](ROADMAP.md) and
[PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md).

- Atomic replacement is only possible on `uinput`; `wtype` and `xdotool` have
  no atomic primitive.
- The real `evdev` → `uinput` path and a live compositor are not exercised by
  CI; they need a real GNOME desktop.
- `g3kb-switch` is a `Recommends`, not a `Depends` (it is not in Debian), so
  under pure Wayland the layout may not switch without it.
- Flatpak / AppImage and cross-platform adapters are planned, not built.
