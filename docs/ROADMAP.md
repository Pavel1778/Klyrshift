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
| Install / remove languages from the GUI | partial — enable/disable exists, install does not |
| Package rollback on a failed update | done — `langpack.install_package` restores on failure |
| Integrity check before install | done — SHA-256 per member, verified before any write |

## Stage 3 — Learning and text intelligence — **partial**

| Item | Status |
|---|---|
| Remember confirmed corrections | done |
| Remember rejected corrections (`Ctrl+Z`) | done |
| Session vocabulary promotion | done |
| Manual add / remove of learned words | partial — `--reset` and `--off` exist, per-word edit does not |
| Separate dictionaries per domain (names, code, general) | planned |
| Local confidence model | partial — bigram + vocabulary scoring exists |
| Suggestions instead of auto-change at low confidence | partial — `hybrid` withholds; no inline suggestion UI |

## Stage 4 — UX / UI redesign — **partial**

| Item | Status |
|---|---|
| GTK4 + libadwaita preferences window | done |
| First-run tour | done |
| Status, dictionary, history, typo, help pages | done |
| System tray | done |
| Light / dark / system theme | partial — follows the system, no explicit switch |
| First-run wizard | partial — tour exists, wizard does not |
| Per-application profiles | partial — exceptions and layout map exist |
| Full keyboard navigation and scaling audit | planned |
| Interface localisation | partial — Russian strings are inline, not a catalogue |

## Stage 5 — Install and maintenance — **partial**

| Item | Status |
|---|---|
| Self-contained `.deb` | done |
| Install / uninstall guide | done |
| `doctor` diagnostics | done |
| Config migration between versions | done |
| Package integrity check | planned |
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
| Mixed / ambiguous / code corpus | planned |
| Latency and memory budget in CI | planned |

## Order of work

1. Finish Stage 1 on a real desktop (the only blocker is hardware).
2. Close the Stage 3 gaps that do not need new architecture (per-word learning
   edit, suggestions).
3. Build the versioned language-package format (Stage 2).
4. The UX wizard and theme switch (Stage 4).

Cross-platform (Stage 6) and alternative packaging (Stage 5) come last: they
need the Linux path to be finished first.
