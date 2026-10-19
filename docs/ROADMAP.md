# Roadmap

Where Klyrshift is, where it is going, and in what order. Every item is marked
by real status, not intent. This is a plan, not a promise: a later stage does
not begin until the one before it is working and tested.

Status legend: **done** (implemented and tested), **partial** (works, with
documented limits), **planned** (not started), **blocked** (needs something
outside the codebase).

## Where the product is today

Klyrshift is a working Debian/GNOME layout switcher: it detects wrong-layout
words, rewrites them, switches the layout, and can undo the change. The core is
strong (1100+ tests, 87 % coverage, 0 false positives and 0 corruption on the
detector benchmark). The gaps are system integration on real hardware, the
first-run experience, and packaging beyond a manual `.deb`.

## Stage 0 — Audit and foundations — **done**

| Item | Status |
|---|---|
| Audit of detector, modes, undo, GUI, storage, CI | done |
| `docs/ARCHITECTURE.md` (existing, extended) | done |
| `docs/PLATFORM_SUPPORT.md` | done |
| `docs/OFFLINE_AND_PRIVACY.md` | done |
| `docs/UNDO_CONTRACT.md` | done |
| `docs/TEST_STRATEGY.md` | done |
| `docs/ROADMAP.md` (this file) | done |

## Stage 1 — Reliability and undo — **partial**

The main goal is that a correction is always safe to reverse.

| Item | Status |
|---|---|
| `Ctrl+Z` lets the application undo the rewrite | done |
| The undo hotkey restores the last fix | done |
| A fix is dropped once the caret moves or new text is typed | done |
| Undo history bounded by time and depth | done |
| Atomic replacement on `uinput` | done |
| Atomic replacement on `wtype` / `xdotool` fallbacks | **blocked** — those tools have no atomic primitive |
| Confirmed on real editors, browser, terminal | **blocked** — needs a real desktop |

## Stage 2 — Offline language platform — **partial**

| Item | Status |
|---|---|
| Bundled dictionaries for five languages | done |
| Thematic dictionaries with offline fallback | done |
| User dictionary add / remove / import / export | done |
| A versioned, checksummed language-package format | done — `langpack.py`, `dict pack/verify/install-file` |
| Install / remove languages from the GUI | done |
| Package rollback on a failed update | done — `langpack.install_package` restores on failure |
| Integrity check before install | done — SHA-256 per member, verified before any write |

## Stage 3 — Learning and text intelligence — **partial**

| Item | Status |
|---|---|
| Remember confirmed corrections | done |
| Remember rejected corrections (`Ctrl+Z`) | done |
| Session vocabulary promotion | done |
| Manual add / remove of learned words | done — `klyrshift learn list/promote/forget` edits the running daemon's in-memory vocabulary |
| Separate dictionaries per domain (names, code, general) | done — `names` and `code` categories ship for ru+en and install offline |
| Local confidence model | done — `Confidence` maps the margin onto `[0, 1]` and records its evidence; `klyrshift explain` shows it |
| Suggestions instead of auto-change at low confidence | done — `hybrid` withholds and offers the fix through the tray entry, the accept hotkey and an optional notification |

## Stage 4 — UX / UI redesign — **partial**

| Item | Status |
|---|---|
| GTK4 + libadwaita preferences window | done |
| First-run tour | done |
| Status, dictionary, history, typo, help pages | done |
| System tray | done |
| Light / dark / system theme | done |
| First-run wizard | done — languages, mode and autostart, then the tour |
| Per-application profiles | partial — exceptions and layout map exist |
| Full keyboard navigation and scaling audit | done — every page is reachable with Tab, `Ctrl+Page_Down/Up` cycles the visible tabs, `Ctrl+?` opens a keyboard reference built from the live config, and the layout was checked at 360–1200 px |
| Interface localisation | done — strings live in `klyrshift.i18n`, an English catalogue ships in `data/locales/en.json`, `--lang` switches the CLI and `Config.ui_locale` the GUI; a missing entry falls back to the Russian source |

## Stage 5 — Install and maintenance — **partial**

| Item | Status |
|---|---|
| Self-contained `.deb` | done |
| Install / uninstall guide | done |
| `doctor` diagnostics | done |
| Config migration between versions | done |
| Package integrity check | done — the `.deb` ships an `md5sums` manifest; `klyrshift verify` and `dpkg --verify klyrshift` detect a corrupted file |
| Flatpak / AppImage | planned — needs a portal input path |

## Stage 6 — Cross-platform — **planned**

The detector core is platform-independent and worth reusing. The input adapters
are not. Nothing here is started; see
[PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md) for what each platform would need.

## Stage 7 — Quality and competitiveness — **partial**

| Item | Status |
|---|---|
| Reproducible detector benchmark | done |
| Recorded baseline and thresholds | done |
| Mixed / ambiguous / code corpus | done — `tests/test_ambiguous_words.py` sweeps cross-layout collisions |
| Latency and memory budget in CI | done — `scripts/measure_latency.py --budget-ms/--budget-mib` fails the `latency-budget` CI job |

## Order of work

1. Finish Stage 1 on a real desktop (the only blocker is hardware).
2. Close the Stage 3 gaps that do not need new architecture (suggestions).
3. Build the versioned language-package format (Stage 2).
4. The UX wizard and theme switch (Stage 4).

Cross-platform (Stage 6) and alternative packaging (Stage 5) come last: they
need the Linux path to be finished first.
