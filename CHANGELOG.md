# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The detector's latency and memory are now budgeted in CI.** The
  `latency-budget` job runs `scripts/measure_latency.py` with `--budget-ms 0.5`
  and `--budget-mib 64`; the script exits non-zero when the slowest direction or
  the peak traced allocation crosses the line. The thresholds are loose on
  purpose — a shared runner is noisy, and the regression worth catching is an
  order of magnitude (a corpus reloaded per word, an accidental O(n²)), not a
  few percent. `--budget-ms`/`--budget-mib` also make the script usable as a
  local check.
- **Hybrid mode now offers the fix it will not apply.** Hybrid mode has always
  withheld a low-confidence conversion instead of rewriting the word, but the
  offer was only reachable through the fix hotkey. The withheld suggestion is
  now kept explicitly and can be applied deliberately: the tray gains an
  "Apply suggestion" entry (disabled until an offer is waiting), a new
  `hotkey_accept_suggestion` binding does the same from the keyboard, and
  `suggest_on_withhold` (off by default) shows a notification when an offer
  appears. The offer is dropped as soon as the next word is flushed, so a
  stale suggestion is never applied to text the user has moved past. The typed
  text stays in memory: the offer is never logged and the notification body is
  a fixed label, preserving the "no typed text on disk or in argv" invariant.
- **The `.deb` now ships an `md5sums` manifest, and `klyrshift verify` checks
  it.** `dpkg-deb --build` does not generate the manifest, so a corrupted or
  edited file had no way to be detected after installation. `scripts/build_deb.sh`
  writes one entry per installed file; `klyrshift verify` (and the `doctor`
  "Целостность пакета" row) compares the files on disk against it and reports
  a missing file distinctly from a modified one, because the fix differs.
  `dpkg --verify klyrshift` now works as well. A source checkout or a venv
  install has no manifest and is reported as "not installed from a .deb",
  not as a pass.

### Fixed

- **The withheld-conversion log line leaked the typed word.** The hybrid-mode
  DEBUG message used `%r` on the buffer, so `log_level=DEBUG` wrote the user's
  text to `klyrshift.log` -- the same class of leak the T9 path had already
  fixed. It now logs the confidence and the word length only.


## [0.2.9] - 2026-10-19

Adds always-on learning, and makes a correction safe to reverse even after
the caret has moved.

### Added

- **Always-on learning.** Klyrshift now watches how it is used and adapts. A
  word whose correction the user rejects (`Ctrl+Z`, or the undo hotkey) is not
  corrected again for the rest of the session, so a fix the user undoes never
  "changes back". A word the user keeps unchanged often enough
  (`learning_promote_threshold`, default 3) joins the detector's vocabulary for
  the session and stops being "corrected" -- brands, names and jargon are
  picked up without a manual `klyrshift dict add`. The learned words live in
  the daemon's memory only; the persisted profile holds counters, never a
  word, so the "no typed text on disk" invariant still holds. `klyrshift
  learn` shows the counters, `--off` disables learning, `--reset` clears
  them, and the GUI's Продвинутые page has a matching group.

### Changed

- **The release workflow smoke-tests Debian 13, not only Debian 12.** Debian
  13 (trixie) is the current stable and the target this package is written
  for (the udev rule is named `71-*` to run before `73-seat-late.rules`,
  systemd 257), but the workflow installed the `.deb` only in a `debian:12`
  container, so a trixie-only regression could ship. Both images are tested.

### Fixed

- **The Layero deploy failed before Astro ran.** Astro 7 refuses to build below
  Node `22.22.0` (`site/package.json` `engines.node`), and the build aborted with
  `Node.js v22.18.0 is not supported by Astro!`. The deploy log names the source it
  used: `[config] node=22.18.0 (engines.node)`. `layero.json` had no `nodeVersion`
  then and no `.nvmrc` existed, so Layero read the *major* `22` out of the
  `>=22.22.0` range and built on its own 22-line image, `22.18.0` — below the very
  floor `engines.node` stated — because Layero keeps one build per major and
  updates the patch inside it itself (the docs: name the major, we update the exact
  build within it). Pinning the patch does not help. The pin is therefore a major
  whose *whole* range clears the floor: `site/layero.json` sets
  `nodeVersion: "24"` (`24.0.0 >= 22.22.0`, whereas `22.0.0 < 22.22.0`), and
  `site/.nvmrc` and the CI `site` job name the same major. `layero.json` outranks
  the project setting, `.nvmrc`, `.node-version` and `engines.node`, so the file's
  `nodeVersion` decides.
  `tests/test_layero_config.py` enforces the rule — a pin whose major can resolve
  below the `engines.node` floor fails the test — so the deploy cannot silently
  drop back under Astro's minimum. The CI `site` job builds on
  24 too, and `site/deploy.sh` refuses to run a local build below the
  `engines.node` floor with a readable message instead of Astro's abort. One
  caveat the docs disagree on: Layero's `layero.json` page and its `layero-v2`
  schema both say the file wins, while its runtime-versions page lists the panel's
  project setting first and never mentions the file, so the panel's
  "Версия Node.js" must stay on "Авто"/`24`.

- **A `Ctrl`/`Alt` chord leaked its key into the buffer.** Typing a word, then
  pressing `Ctrl+C` (or any command chord), left the chord's own key in the
  buffer -- the `c` of `Ctrl+C` -- so the next Space analysed a stray
  one-letter fragment. A key pressed while `Ctrl`/`Alt`/`Super` is held is now
  dropped instead of buffered. This is also what makes `Ctrl+Z` observable as
  "the user undid the last fix" without the chord polluting the buffer.

- **The landing page still canonised the pre-rename hosts.** The hosts were
  renamed with the project, so `klyrshift.layero.app` and `klyrshift.vercel.app`
  are the live origins and the old `linguafix.*` names now return 404. The
  canonical origin, `og:url`, the `hreflang` alternates, the sitemap and
  `robots.txt` still named `linguafix.*`, so every page advertised a dead address
  that search engines drop. `astro.config.mjs`, `src/lib/site.ts`, the footer,
  the `README.md` badges and the dictionary link now name the live hosts, and
  `tests/test_repo_urls.py` pins them and fails if a `linguafix.*` host reappears
  in the site source, the README or `docs/`.

- **A fix could be undone onto the wrong text.** The undo history was
  bounded by time and depth only, so it did not notice that the user had
  moved on. After a correction, typing anything else and then pressing the
  undo hotkey deleted the recorded character count from the *new* text and
  retyped the old word over it, corrupting what had just been written. The
  history is now dropped as soon as the caret moves: any key that is neither
  a hotkey action nor the observed `Ctrl+Z` clears it (an ordinary key
  changes the text, a command chord such as `Alt+Tab` or `Ctrl+V` changes
  focus or pastes). A Space that triggers a new correction records a fresh
  entry, so that correction stays undoable; a refused undo is safer than a
  corrupted word.
- **`pyproject.toml` and `requirements.txt` disagreed on the `tomli` floor.**
  A dependency bump raised the floor in `requirements.txt` only, so
  `install.sh`, which installs from `pyproject.toml`, kept the older `tomli`.
  Both now require `tomli>=2.5.0` below Python 3.11, and
  `tests/test_version_consistency.py` fails on the next drift.

## [0.2.8.4] - 2026-10-18

A fixes-only patch. The guided tour no longer loses the user's place when the
window is closed mid-tour.

### Fixed

- **An interrupted guided tour restarted from the first step.**
  `OnboardingState.last_step` was documented as "the index of the last step
  shown, so an interrupted tour can be resumed", but nothing ever wrote it, so
  the value stayed `0` and closing the window mid-tour lost the user's place.
  The overlay now reports each step it displays, the window persists the index,
  and `start_tour` resumes an unfinished tour there. Finishing or skipping the
  tour clears the stored position.
- **The home page claimed auto-switching was paused whenever any app had focus.**
  The pause banner's reason treated *any* running application as a reason to
  pause, so an ordinary auto-mode session that had nothing on the exception list
  still read «приостановлено (приложение «…»)» as soon as any window was
  focused — for example the GUI's own window, or a terminal. The reason is now
  built from the never-touch list the daemon actually honours: it names the
  application only when that app is on it, and otherwise stays quiet.
- **The GUI silently needed `python3-gi-cairo`, which no dependency list named.**
  The guided tour's scrim and the fallback power glyph paint through
  `Gtk.DrawingArea`'s `set_draw_func`, and PyGObject can only hand that callback a
  `cairo.Context` when the `_gi_cairo` override module is present. `python3-gi`
  does not pull it in, so a stock `python3-gi` install left both widgets blank,
  logging `Couldn't find foreign struct converter for 'cairo.Context'` for every
  frame. `klyrshift gui` now refuses to start with a message that names the fix
  instead of opening a window that draws nothing, `doctor` reports the missing
  module, and the `.deb`, `install.sh` and CI package lists install it.
- **The screenshot generator depended on the machine's onboarding state.** A
  first-run tour offer covered the home page, so the rendered images changed with
  whatever the developer had already seen, and the committed images carried a
  stale `lingvix` path. `scripts/make_screenshots.py` now renders against a fixed
  throwaway `HOME`, so the output is identical from run to run, and the three
  committed screenshots are regenerated with the current branding.

## [0.2.8.3] - 2026-10-17

The project is renamed to its final name, the GitHub repository follows, and the
release tree, the changelog and the published release are reconciled.

### Changed

- **The project is renamed Lingvix → Klyrshift.** `LinguaFix` collided with the
  Windows/Microsoft utility of the same name, and the intermediate `Lingvix` was
  never published; `Klyrshift` is the final name. It is used everywhere: the
  Python package (`src/klyrshift/`, import `klyrshift`), the CLI (`klyrshift`),
  the systemd unit (`klyrshift.service`), the udev rule (`71-klyrshift.rules`),
  the desktop/autostart entries, the config, state and cache directories
  (`~/.config/klyrshift`, `~/.local/share/klyrshift`, `~/.local/state/klyrshift`,
  `~/.cache/klyrshift`), the Debian package (`klyrshift`), the release assets
  (`klyrshift_<version>_all.deb`, `klyrshift-dict-<slug>.tar.gz`) and the landing
  page. The GitHub repository is renamed `Pavel1778/LinguaFix` →
  `Pavel1778/Klyrshift`; GitHub redirects the old slug, so existing clones keep
  working.
- **An upgrade from an older install keeps the user's settings.** The config
  directory follows the application name, so a rename silently starts from
  defaults. On first load the new package copies `config.toml` (and
  `snippets.toml`) from `~/.config/lingvix` or `~/.config/linguafix` into
  `~/.config/klyrshift` — once, only when the new directory has no config yet, and
  by copying rather than moving, so the old file stays where it is and a current
  config is never overwritten.
- `README.md`, `AGENTS.md`, `docs/*` and the site reflect the new name. Historical
  identifiers are kept only where they are load-bearing: the `Conflicts`/`Replaces`
  fields, the legacy config names above, and the asset-name fallbacks.

### Fixed

- **A `SITE_URL` build emitted two different origins.** The sitemap and
  `robots.txt` take their origin from `astro.config.mjs`, but
  `<link rel="canonical">`, `og:url` and the `hreflang` alternates take theirs
  from `site.ts`. Only the config read the `SITE_URL` override, so a local
  check produced a Vercel sitemap beside a Layero canonical and reported a
  canonical the deployment would never ship. `site.ts` now honours the
  override too, and a test fails if either side stops reading it.
- **An upgrade from `linguafix` left two daemons installed.** dpkg treats a
  package rename as unrelated packages: installing the new `.deb` over
  `linguafix` left the old package installed, and *both* kept a systemd user
  unit enabled at login, so two daemons fought over the keyboard. The control
  file now declares `Conflicts: linguafix, lingvix` and
  `Replaces: linguafix, lingvix`, so apt removes the old package first. Both
  earlier names are listed because the package was renamed twice and a locally
  built `.deb` may carry the intermediate one. Verified in `debian:13`: before
  the change both `linguafix` and `klyrshift` stayed installed with both units
  enabled; after it, only `klyrshift` remains and only `klyrshift.service` is
  enabled.
- **A fresh Debian install had no layout-switching backend.** `g3kb-switch` (the
  Wayland backend) is not in the Debian repositories (no candidate on Debian 12
  or 13), and the X11 fallback `setxkbmap` (from `x11-xkb-utils`) was not in any
  dependency list. A plain `apt install ./klyrshift.deb` therefore reported
  `backend=none` and could not switch the layout at all. `x11-xkb-utils` is now
  a `Recommends` in the `.deb` and part of `install.sh`'s apt list;
  `klyrshift doctor` reports `backend=setxkbmap` on a fresh Debian 13.
- **The source-install snippet would break at the next rename.** The landing
  page cloned from `${REPO}` (derived from `REPO_SLUG`) but then ran a
  hard-coded `cd LinguaFix`. Both spell the same name today, so it works; the
  moment the repository is renamed, the clone lands in the new directory and
  `cd` fails for everyone who copies the snippet. `consts.ts` now exposes
  `REPO_NAME` and the snippet derives the directory from it. A new guard pins
  the `git clone`/`cd` pairs in `README.md` and `docs/*` to the live repository
  name, so a rename cannot leave a stale one behind.
- **The source installer had no way to opt out of autostart.** `install.sh`
  always wrote the XDG autostart entry and always ran
  `systemctl --user enable --now`, so a user who did not want the daemon
  starting at every login had to install first and disable afterwards. It now
  takes `--no-autostart`, which skips the entry, undoes a previous `enable`, and
  still starts the daemon for the current session. Re-running with the flag also
  removes an entry a previous install left behind, so the opt-out holds.
  `tests/test_installer_autostart.py` runs the real script against stub system
  binaries and fails if the flag is ignored.
- **Autostart could not be turned off.** `disable_autostart()` removed only the
  systemd user unit, but `install.sh` also writes an XDG entry
  (`~/.config/autostart/klyrshift.desktop`). That entry kept launching the daemon,
  so the GUI switch snapped back on at the next refresh. Disabling now removes
  the XDG entry *and* masks the unit; enabling removes the mask.
- **Autostart always read as off.** `systemd_enabled()` trusted
  `systemctl --user is-enabled`, which reports a unit enabled *globally*
  (`/etc/systemd/user`, what the `.deb` does) as `disabled` until the session
  reloads. A working autostart therefore showed as off in the GUI. The probe now
  also checks the global wants symlink directly.
- **The landing page told search engines to index a 404.** `astro.config.mjs`
  and `src/lib/site.ts` declared the canonical origin as `klyrshift.layero.app`
  and `klyrshift.vercel.app`, but only the `linguafix.*` hosts were ever
  configured, so both `klyrshift.*` names return 404. Astro writes that origin
  into `<link rel="canonical">`, `og:url`, the `hreflang` alternates, the
  sitemap and `robots.txt`, so the live page advertised a dead address and the
  footer linked it. `README.md` carried the same dead origin in its three
  status badges, its dictionary link and its "where to find us" list, so the
  repository advertised 404s as well. All of them now name the hosts that
  resolve, and `tests/test_repo_urls.py` fails if a `klyrshift.*` host reappears
  in the site source, the README or `docs/`.
- **`dict install` never used the release archive.** The live release predates
  the rename and attaches its thematic archives as
  `linguafix-dict-<slug>.tar.gz`, while the code requested
  `klyrshift-dict-<slug>.tar.gz`. Every install therefore 404'd on the first
  source and fell through to the branch mirror -- an extra round trip, and the
  archive path never exercised. All three spellings are tried now, newest first
  (`klyrshift-`, then `lingvix-`, then `linguafix-`), so the command works against
  the published release and against the next one.
- **An unrecognised modifier in a hotkey silently became a bare key.** The
  matcher fires when the held modifier families equal the binding's, so
  `hotkey_fix_last_word = "CMD+Q"` dropped the unknown `CMD`, left an empty
  family set, and then triggered on *every* press of `Q`. `normalise_hotkey()`
  now rejects a chord whose non-final token is not a known modifier, and the
  same guard runs in the daemon's parser so a config built in memory cannot
  slip past it. A lone modifier (`"CTRL"`) and a chord ending in one
  (`"CTRL+SHIFT"`) are rejected too, since neither has a key to fire on;
  `CTRL+CTRL` remains the valid legacy double tap.
- **The rename relationship was documented nowhere.** A user upgrading from
  `linguafix` had no instructions: `docs/INSTALL.md` now has an "Upgrading from
  the old `linguafix` package" section. It also records what a raw `dpkg -i`
  does differently from `apt install ./…`: the old package is removed, but
  dpkg keeps an empty `linguafix` record in its database (state `ic`) and
  reports `1 not upgraded`. That is cosmetic — verified on Debian 12 and 13
  that no file, unit or daemon survives — and `apt-get -f install` clears
  it. `Breaks:` was measured against `Conflicts:` and rejected: `Breaks` leaves
  the old unit on disk and still enabled, so both daemons would run.
  - **The release gate could never pass on the tag it was checking.** The
    workflow runs `release_consistency.py --source --tag <tag> --assets-file
    <staged>` *before* it creates the release, but the script fetched the
    release whenever `--tag` was present. The tag has no release yet, so the
    fetch 404ed and the job failed before publishing anything — the gate was
    added after the last tag was cut, so it had never run for real.
    `--assets-file` already supplies the asset names, so the release is now
    fetched only when the API is the only source: with `--latest`, or with
    `--tag` and no `--assets-file`.

### Added

- **A guided tour, context help and a "Помощь и обучение" page.** A first-run
  offer leads into a six-step tour — home screen, languages, mode, fix hotkey,
  environment check, closing card — that highlights the real widget at each step
  and can be skipped or replayed. The tour and the help texts live in `klyrshift.onboarding`
  as plain data, so the scenario is validated without a display and each topic
  names the `Config` fields it explains — a renamed field fails the suite instead
  of silently orphaning its text. Settings groups carry a "?" button that opens
  the matching topic, the help page repeats the tour, lists every topic, runs the
  environment check and states the known limitations, and finishing or skipping
  records the tour version so a routine start stays quiet.
- **`scripts/acceptance_check.sh` now checks detection and the modes without a
  keyboard.** It drives the *installed* package's detector directly and pins
  nine cases: a word typed in the wrong layout converts in both directions, an
  already-correct word is left alone, and a URL, an e-mail, a file path, a
  version string and a hyphenated identifier are protected. It then sets each
  mode (`auto`, `hybrid`, `manual`) through the CLI and reads it back. These are
  real checks, not substitutes for the manual session steps, which now also
  cover both session types (Wayland and X11), the per-mode behaviour, the
  exceptions list, and that exactly one daemon runs.
- **The JSON-LD version could drift from the page's own version.**
  `Base.astro` wrote `softwareVersion: "0.2.8.2"` as a literal while
  `consts.ts` held `VERSION`, so a bump updated the hero and left the structured
  data behind — two versions on one page, invisible to every other test. The
  layout now imports `VERSION`, and `scripts/release_consistency.py` fails if the
  literal returns.
- **`scripts/release_consistency.py`, a release-consistency check.**
  `tests/test_version_consistency.py` compared the source files only with each
  other, so it could not see that the site advertised `0.2.8.2` while the newest
  *published* release was `v0.2.8`. The new script splits the two questions:
  `--source` compares the tree with itself and with the asset names the build
  scripts emit (offline, run by the unit suite), while `--tag` / `--latest`
  compare it with the release that actually exists (network, run by the release
  workflow). The workflow now gates the publish on the tag, the tree version and
  the staged asset list agreeing, and checks the published download URLs
  afterwards. `tests/test_release_consistency.py` pins both halves, exercising
  the published-release drift with a recorded payload so the normal test run
  never touches the network.
- **`docs/RELEASING.md`.** The release steps were spread across
  `CONTRIBUTING.md`, `TESTING.md` and the workflow. They are now one checklist:
  the version sources, the Debian 12/13 package checks, the upgrade from the old
  `linguafix` package, the asset list, the documentation and canonical checks,
  the real-keyboard test CI cannot run, and the two blockers outside this
  repository.
- **The mojibake guard missed double-encoded punctuation.** It only looked for
  the byte signatures of double-encoded *Cyrillic*, so a file whose arrows or
  em-dashes had been re-saved through a single-byte pipeline passed the test
  while shipping garbage to the user. It now also round-trips each line back
  through the codecs such a save uses and fails on any line that decodes
  cleanly, with a unit test that pins the arrow and em-dash cases.

- **Hybrid mode now differs from auto.** Previously `hybrid` behaved exactly
  like `auto`, so the mode existed in name only. The detector gained
  `target_layout_with_confidence()`, which reports the plausibility margin by
  which a candidate beat the text as typed (and `inf` for a conversion that is
  certain rather than scored: a taught word, or one whose every word is already
  known in the target language). Hybrid applies an automatic fix only when that
  margin clears `hybrid_confidence` (default `3.0`, tunable in the GUI under
  Детектор); an uncertain guess is withheld for the manual hotkey instead of
  being rewritten. `auto` still applies everything the detector accepts, and a
  forced fix (double Shift, force-in-manual app) ignores the threshold. The
  default was measured over the top 2000 Russian words typed on US: ~2.6% of
  true fixes fall below 3.0, the median margin is ~7.6.
- **The landing-page demo no longer disagrees with the daemon.** It had no
  vocabulary-validated override, so it left `ltym` untouched while the app
  corrected it to `день`; porting the override then exposed a second bug — the
  demo tokenised with JS `\w`, which is ASCII-only, so a Cyrillic conversion
  never matched and the override was a silent no-op. `tests/test_demo_parity.py`
  now runs the demo's TypeScript under Node and compares it with the real
  detector, so the two cannot drift again.
- **Live demo on the landing page** (`site/src/components/Demo.astro`). It ports
  the detector's per-word plausibility test to TypeScript, so a visitor can try
  the correction in the browser. Its vocabulary and bigram tables are generated
  from the shipped corpora by `scripts/build_demo_model.py`
  (`tests/test_demo_model.py` fails if they drift).
- `scripts/measure_detector.py` — reproducible recall / false-positive /
  corruption / latency measurement on fixed slices of the shipped corpora.
- `tests/test_demo_model.py` and new autostart cases in
  `tests/test_daemon_control.py`, plus hybrid-mode regression tests in
  `tests/test_modes_hotkeys.py` and `tests/test_demo_parity.py`.

### Removed

- `docs/TESTING_v0.2.0.md` — superseded by `docs/TESTING.md`; its still-useful
  GUI checklist is merged into the latter as section H.

## [0.2.8.2] - 2026-10-08

Follow-up to 0.2.8.1 for two defects reported after the 0.2.8 live test, plus
an independent-mode model for T9 and punctuation.

### Fixed

- **The config-migration fix now actually ships.** The atomic write-back that
  persists migrations to `config.toml` was committed to `main` (`089afee`) but
  was not in the `v0.2.8` tag, so a user who installed that build still saw the
  stale file. It is part of this release; on first load the migrated values are
  written back and the next `lingvix config show` agrees with the daemon.
- **T9 no longer rewrites correct words ("T9-спам").** The reported build
  predated the v0.2.8.1 guard (`typo_in_manual`); it is now part of the shipped
  code. On top of it, the typo pass is gated by its own mode (below) rather than
  the global layout mode, so in `manual` layout mode a correct word is never
  auto-rewritten and the automatic pass only runs when `typo_mode = "auto"`.

### Added

- **Independent per-feature modes.** `typo_mode` and `punctuation_mode`
  (`off` / `manual` / `auto` / `hybrid`) are the source of truth for T9 and
  punctuation, decoupled from the global layout `mode`. A legacy config is
  migrated on load: `typo_correction = true` with `mode = "manual"` becomes
  `typo_mode = "manual"`, otherwise the global mode is used. The legacy booleans
  are kept mirrored for compatibility. New manual hotkeys:
  `CTRL+SHIFT+F` (T9) and `CTRL+SHIFT+P` (punctuation).
- **T9 tab on `lingvix gui`.** Both features have an independent mode combo,
  the full parameter set (min word length, max edit distance for short/long
  words, long-word threshold, confidence margin), an expander with examples, a
  "Проверить сейчас" preview dialog, and a link to the documentation. The tab
  was previously a plain on/off toggle.
- **Expanded thematic dictionaries to 1000+ words.** The priority categories
  were too small for professional text (T9 could not recognise terms like
  `kubectl`, `фотосинтез`, `энтальпия`). Now: `it` ru 328→1010 / en 295→1263,
  `medicine` ru 228→1579 / en 215→2136, `science` ru 149→1077 / en 152→1692.
  The remaining categories keep their current size. README counts are
  regenerated from the files (`scripts/refresh_dict_readmes.py`).
- Expanded `README.md` and `docs/FAQ.md` with honest dictionary numbers.

### Changed

- **`/dictionaries` page redesign.** A summary band (categories / words /
  licence), per-category accent monograms, per-language word counts and sizes,
  and a cleaner base-list grid. Counts are read from the shipped files at build
  time, never typed.
- Thematic category `README.md` word counts are now exact and regenerated by
  `scripts/refresh_dict_readmes.py` (with a `--check` mode); a test fails if the
  documented count drifts from the file.

## [0.2.8.1] - 2026-10-08

Hotfix for three defects reported after the 0.2.8 live test.

### Fixed

- **Config migrations now reach the file.** A migration applied on load (the
  `CTRL+CTRL` undo hotkey, the `300 ms` double-tap window, the `gedit` →
  `texteditor` exception) lived only in memory, so `lingvix config show` —
  which reads the file — kept displaying the stale values while the daemon
  logged the migrated ones. `load_config` now writes the migrated config back
  atomically (temp file + `os.replace`) and logs
  `Config: migrated and saved ...`. `lingvix config migrate [--dry-run]`
  previews the change and `config show` warns when file and effective values
  diverge. Deliberate user values (`mode`, `backspace_settle_ms`,
  `min_word_length`, a hand-picked double-tap window) are never migrated.
- **T9 no longer rewrites correct words ("T9-спам").** A typo pass now refuses a
  word that is known in *any* loaded language (a name or loanword the frequency
  corpus omitted, e.g. `саша`), a word already corrected within
  `typo_debounce_seconds` (default 5 s), and a "correction" that would replace a
  plausible current-language word with a less plausible one (`суток` → `сутак`).
  In `mode = "manual"` the automatic T9 pass is silent by default; set
  `typo_in_manual = true` to restore it. The explicit fix hotkey is unaffected.
- **A mixed-script buffer is never rewritten as one word.** Text containing both
  Latin and Cyrillic (`ghbdtnпривет`) is left for the separator between the two
  scripts to flush, so a fast typist no longer gets `ghйпривет`.

### Added

- Seven new thematic dictionary categories — `science`, `business`,
  `electronics`, `media`, `education`, `gaming`, `sport` (ru + en, ~150 words
  each), on top of the original five. Each ships as a
  `lingvix-dict-<slug>.tar.gz` release asset and is listed on the landing
  page. Install with `lingvix dict install <category> --lang ru`.

### Changed

- `site/layero.json` is confirmed as the Layero build config; the root
  `layero.json` added by the previous session was removed (Layero reads the
  project config, and the change was based on a misdiagnosis of a Layero
  infrastructure incident).

## [0.2.8] - 2026-10-08

### Added

- `lingvix dict download <lang>` and `lingvix dict import-file <path>` load
  extended frequency word lists (`ru`, `en`, `uk`, `de`, `fr`) into
  `$XDG_DATA_HOME/lingvix/dictionaries/<lang>.txt`. The detector reads them in
  addition to the bundled corpora, widening vocabulary membership only — n-gram
  scoring is unchanged, so already-correct words keep their verdict while rarer
  words are recognised. Lists mirror FrequencyWords (MIT) under the repository's
  `dictionaries/` folder. A new landing-page section links them.
- `dict download` now tries the stable
  `releases/latest/download/<lang>-50k.txt` asset first, then the branch mirror,
  then upstream, and finally copies a locally shipped list — so it succeeds with
  no network. Every list is attached to each GitHub Release and bundled in the
  `.deb` (`lingvix/data/dictionaries/`), and the landing page links the
  release assets rather than a branch path.
- A `toggle_layout` hotkey (default `CTRL+SHIFT+T`) force-retypes the last word
  in the other layout, the manual reverse of a correction. Configurable as
  `hotkey_toggle_layout_last_word`.
- **Thematic (professional) dictionaries.** `lingvix dict categories`,
  `dict install <category> [--lang ru]`, `dict list-installed` and
  `dict remove-category <category>` add domain vocabularies on top of the base
  frequency list: `it`, `medicine`, `legal`, `finance`, `engineering` (ru + en).
  Installed categories are recorded in `installed_dict_categories` (default
  `["base"]`) and loaded as membership on top of the corpora. Detection priority
  is **user dictionary → thematic → base → T9**. Thematic lists are **not**
  bundled in the `.deb`; each is published as a `lingvix-dict-<slug>.tar.gz`
  release asset, fetched first, then from the branch mirror, then from the
  offline repository copy. The `/dictionaries` landing page lists the sections
  with language, word count, size and licence (MIT).

### Changed

- The undo hotkey default (`SHIFT+BACKSPACE`) and the new toggle hotkey are shown
  by `lingvix hotkeys` and the GUI. A stale `CTRL+CTRL` value left by an older
  install is migrated to the default on load and the change is logged.
- A config still on the pre-0.2.8 double-tap window (`hotkey_double_tap_ms = 300`)
  is widened to the current default (2000 ms): 300 ms is too short to catch a
  deliberate double tap reliably. Any other value is treated as a deliberate
  choice and kept.
- A config still carrying the old default exception `gedit` (not installed on
  Debian 13 / GNOME 48) is migrated to `texteditor` (GNOME Text Editor) on load,
  so the current default text editor is actually excepted.
- **`manual` mode semantics (contract change).** Previously `mode = "manual"`
  gated *every* automatic correction, so an opt-in T9 pass never fired
  (`langauge` → `language` did nothing). Now only the automatic *layout switch*
  is manual; layout-neutral passes (T9 typo, punctuation) run whenever their own
  switches are on, in every mode. A user who wants a fully quiet daemon turns
  `typo_correction` and `punctuation_correction` off (both default off). The
  settings-tab subtitle says so; `tests/test_typo_daemon.py` and
  `tests/test_user_config_migration.py` pin the behaviour.

### Fixed

- The GUI tab icons now fall back to text when a symbolic icon is missing from
  the theme, instead of failing to draw the tab.
- The two desktop notifications (correction and update-available) had been
  corrupted into mojibake by an earlier edit; they are readable again. A test
  now fails on double-encoded UTF-8 anywhere in the tracked sources.
- The install examples in `README.md`, `docs/INSTALL.md` and `docs/TESTING.md`
  named an old package version (`0.2.0`/`0.2.1`), so copying them failed with
  "no such file"; they match the current release and a test pins them to it.

## [0.2.7] - 2026-10-08

### Fixed

- The undo hotkey documented in `README.md` and `docs/TROUBLESHOOTING.md` now
  matches the real default, `SHIFT+BACKSPACE` (both files said `CTRL+Z`). The
  default has been `SHIFT+BACKSPACE` since v0.2.2 precisely because `CTRL+Z`
  collides with the application's own undo; the daemon does not grab the
  keyboard, so it cannot swallow the chord. A user who followed the docs pressed
  `CTRL+Z`, the daemon's undo never fired, and the *application* undid the
  corrected word — deleting it without the daemon retyping the original, leaving
  the cursor in an empty spot, exactly as reported. A regression test pins the
  documented value to `DEFAULT_UNDO_HOTKEY`.

### Added

- The daemon logs the effective hotkeys at startup (`fix`, `undo`, `toggle`,
  `reload`) so the binding is discoverable without opening the GUI. The log
  holds the binding names only, never typed text. The undo path also logs
  `backspace count` and the layout transition at DEBUG level.

### Changed

- CI: every job now sets `timeout-minutes: 15`. A stuck GitHub runner once left
  the Python 3.12 job pending for ~49 minutes (the same suite finishes in ~1
  minute), which hung the whole check; the timeout bounds that. A regression
  test asserts every job keeps a timeout.

## [0.2.6] - 2026-10-08

### Fixed

- The `Received SIGUSR2` log spam is gone for real. The daemon now rewrites its
  metadata-only history snapshot itself whenever the history changes (a fix or
  an undo); the GUI only *reads* the file and no longer signals the daemon on a
  2 s poll timer. The v0.2.5 fix gated one tab's timer but the daemon's own
  per-fix write was never triggered without the signal, so the log stayed noisy.
- `typo_correction` (and any other GUI setting) is no longer reset to `false`
  after a reinstall or a mode change. The daemon's `_persist_config` used to
  dump its whole, possibly stale, in-memory config over the file; it now applies
  only the field it changed onto the current file contents.
- A double Shift now fixes 1-2 character tokens (`фт` -> `an`), which the
  ordinary detector skips below `min_word_length`. A conversion is applied only
  when it is unambiguous: the result must be a known word of the target language
  and the token must not already be a word of the current one; a taught word
  always wins. Ambiguous tokens (for example a lone letter) are left untouched.
- An invalid `config.toml` value now logs the exact key it dropped, so a silent
  revert to a default is traceable to the offending line.

### Added

- The `.deb` `postinst` runs `systemctl --user daemon-reload` after replacing
  the unit, so the next `systemctl --user restart lingvix.service` no longer
  warns that the unit changed on disk.
- `lingvix doctor` gains a "Графический интерфейс" check that names the exact
  packages to install (`python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`) when the
  GTK4/libadwaita stack is absent. The GUI stack is a `Recommends` of the
  `.deb` (a headless install does not need it), so a download followed by
  `--no-install-recommends` previously failed with a bare message; the
  requirement is now documented and diagnosed up front.

### Changed

- The Home tab's 1.5 s status poll is paused while the tab is hidden and
  refreshes on open, so a background window does not keep probing
  `systemctl`/`g3kb-switch`/D-Bus.

### Fixed

- `apt remove --purge` now leaves no empty `/usr/lib/lingvix` directories
  behind. The new `doctor` GUI check imports `lingvix.gui`; run as root, that
  writes root-owned `gui/__pycache__` under `/usr/lib`, which dpkg does not
  track. `postrm` now removes every nested `__pycache__` and prunes the
  directories it leaves empty.

## [0.2.5] - 2026-10-08

### Fixed

- The History tab no longer signals the daemon every 2 seconds (`Received
  SIGUSR2` log spam). The GUI polled the history snapshot regardless of which
  tab was visible; it now pauses while the page is hidden and refreshes on open.
- A layout correction can no longer rewrite text in the *same* layout. If the
  detector returned the current layout, the daemon deleted and retyped the word
  in place, which could deform it (the reported `Fixing buffer of length N (ru
  -> ru)`); such a fix is now refused and logged with `reason=`.
- One invalid value in `config.toml` no longer resets *every* setting to its
  default. `Config.from_dict` now drops only the offending keys, so a hand-edited
  typo cannot silently turn `typo_correction` (or anything else) back off.
- The big power button falls back to a Cairo-drawn glyph when the active icon
  theme cannot resolve `system-shutdown-symbolic`, so it is never a broken-image
  placeholder on a non-Adwaita theme.
- The default `backspace_settle_ms` is now 120 ms (was 80 ms), giving Chromium
  and Electron more time to apply the synthetic Backspaces before the
  replacement characters arrive.

### Added

- `lingvix logs [-n N] [-f] [--level LEVEL]` prints (or follows) the daemon
  log, with an optional level filter.
- The `Fixing buffer ...` log line now carries `reason=layout|typo|punctuation`,
  so a correction can be told apart from a typo fix without guessing.


## [0.2.4] - 2026-10-04

### Fixed

- The big power button now uses `system-shutdown-symbolic`. The old name
  `power-symbolic` does not exist in adwaita-icon-theme 48, so the button
  rendered as a broken-image placeholder. A new `tests/test_icons_exist.py`
  scans every `icon_name` in the GUI and asserts it exists in the installed
  icon theme.
- `lingvix fix` now applies the opt-in typo corrector when layout detection
  finds nothing, matching the daemon; `lingvix fix --text "превет"` gives
  `привет` when `typo_correction` is on.
- `lingvix status` now uses the same "running" definition as `stop` and the
  GUI (the flock PID lock, or an active systemd user unit), so a service daemon
  without a lock file is no longer reported as not running.
- `lingvix start` delegates to the shared control module instead of spawning
  and polling on its own, so `start` and the next `status` can no longer
  disagree.
- The manual-fix hotkey now resolves a taught short token (`ы` -> `s`) even when
  it is below `min_word_length`; only a conversion present in the user
  dictionary qualifies.

## [0.2.3] - 2026-10-07

### Added

- Two-edit typo correction for long words: a word of at least six characters may
  now be corrected within `typo_max_distance_long` edits (default 2), but only
  when the best candidate is clearly more frequent than the runner-up. Short
  words keep the strict one-edit rule. Config keys: `typo_max_distance_long`,
  `typo_long_word_threshold`, `typo_top1_ratio_strict`.
- Adaptive idle timeout (`analysis_timeout_adaptive`, on by default): the
  fallback that flushes a word typed without a separator now follows the user's
  typing speed — shorter for a fast typist, longer for a slow one — clamped to
  0.3–2.0 s. Only inter-key timing is recorded, never characters.
- A "Т9" tab in the GUI with a single master toggle for typo correction and the
  new punctuation cleanup, plus per-rule rows.
- Opt-in punctuation cleanup (`punctuation.py`): dashes, ellipsis, Cyrillic smart
  quotes and spacing, applied only when layout detection and typo correction both
  decline. A replacement the input backend cannot type is refused wholesale rather
  than half-applied. Off by default.
- Search-engine metadata for two indexed hosts: each host declares itself
  canonical (`https://lingvix.layero.app` for the Russian primary,
  `https://lingvix.vercel.app` for the English mirror) and cross-links the other
  with `hreflang` (`ru`, `en`, `x-default`), so the copies do not compete as
  duplicate content. A generated `robots.txt` and a sitemap are emitted per host,
  the default `description`/`og:locale`/JSON-LD follow the host language, and the
  README carries a keyword paragraph plus both site links.
- Google and Yandex site-verification files served on both hosts, an
  `apple-touch-icon`, and a footer "About" block in the host language.
- Packaging contract tests (`tests/test_packaging_contract.py`): the systemd
  user unit (no `Nice`/`CPUSchedulingPolicy`, `Restart=always`), the desktop
  entry, package-data coverage, bytecode stripping in `build_deb.sh`, the
  release workflow's tag filter, and a real `dpkg-deb` contents check.

### Changed

- `lingvix fix` now loads the user dictionary before detection, so a taught
  brand such as `vercel` is corrected by the CLI exactly as the daemon does.

### Fixed

- The GUI no longer freezes ("приложение не отвечает"): the home page ran its
  daemon probes (`systemctl`, `g3kb-switch`, `xprop`, the focused-app D-Bus query)
  synchronously on the GTK main thread on a timer and on every toggle click. They
  now run on a worker thread (`gui/async_utils.run_in_background`) and report back
  on the main thread; the toggle click and its reconcile poll are async too.
- The window tab labels are no longer truncated ("Глав…"): the fixed wide
  `ViewSwitcher` is replaced by a header `ViewSwitcherTitle` plus a bottom
  `ViewSwitcherBar` that appears only on narrow windows.
- `daemon_control._systemctl` backs off for 10 s after a timeout so a hung user
  D-Bus cannot re-pay the 5 s timeout on every GUI refresh.
- The desktop launcher declares `StartupWMClass` equal to the application id, so
  GNOME associates the running window with its installed entry.
- Both hosts publish their own sitemap and `robots.txt` instead of the preview
  suppressing them, so each is independently discoverable without duplicate content.

- Landing page mobile audit (8 items): removed the leaked developer note
  «Плейсхолдер — замените реальным скриншотом» from all four mock-up SVGs;
  replaced the external shields.io footer badges (broken behind a slow/blocked
  CDN, and not proxied by the host) with self-hosted SVGs in
  `site/public/badges/`; the footer now names the single canonical host
  (lingvix.layero.app) instead of a mirror link that hit a login wall; code
  blocks now wrap instead of clipping
  at 375 px; the install tabs stack vertically on mobile; localised the
  «Privacy First» feature title to «Приватность»; softened the step-03 copy to
  «Атомарно, одной транзакцией».

- The opt-in update check no longer blocks the keyboard event loop: the daily
  network request runs on a worker thread, so a slow or offline network cannot
  freeze typing for the whole request timeout.
- Landing page: the power glyph in the hero and the placeholder window is centred
  again. The arc's sweep flag was inverted, which pushed the icon to the top of
  the button instead of forming a ring around its centre.
- Landing page demo leaves URL, e-mail, path and version tokens untouched,
  matching the daemon's structural-separator rule.
- Re-synced `black` formatting of `tests/test_data_sync.py` with the current
  release of the formatter.

### Removed

- Stale release tag `v0.2.0-stage2` and the merged feature branches; `main` is
  the only branch left in `origin`.

## [0.2.2] - 2026-10-07

### Fixed

- `lingvix stop` (and `kill`) now actually stop a packaged daemon. The CLI
  only sent `SIGTERM` to the lock-file PID, so under the systemd user unit
  (`Restart=always`) systemd respawned the daemon about 5 s later and it looked
  unstoppable. Both commands now go through `daemon_control`, which stops the
  unit first; `kill` gained a force-stop path that does the same before sending
  `SIGKILL`.
- GUI settings now reach a running daemon. Every `GuiState.save` asks a live
  daemon to reload, so a switch flipped in the GUI (T9, a trigger, a guard) is
  applied immediately instead of only after a restart. This is why T9 appeared
  "on" but never corrected: the toggle was written to `config.toml` but the
  daemon kept its old in-memory copy.
- The window no longer resizes itself and breaks. The bottom switcher's
  `reveal` had two writers (the `ViewSwitcherTitle` binding and a manual
  `notify::default-width` handler with a different threshold); the duplicate
  handler is gone. The advanced page is added to the stack once at construction
  (hidden until revealed) instead of being appended at runtime to a homogeneous
  `ViewStack`, and the plain pages scroll, so the window shrinks cleanly.

### Changed

- The big on/off button looks like the GNOME quick-settings power button: a
  white circle with a soft outer ring and a thin `power-symbolic` glyph that
  turns accent-coloured when active. The `big-toggle`/`active-state`/`busy-state`
  classes previously had no stylesheet at all. Colours are libadwaita named
  colours, so light/dark themes follow automatically, and the transitions are
  dropped when the system asks for reduced motion.

## [0.2.1] - 2026-10-07

### Fixed

- GUI toggle: удалены невозможные для user-service директивы
  Nice/CPUScheduling из systemd unit (это была причина, почему
  сервис не запускался).
- GUI toggle: расширено окно reconcile до 10 секунд (совпадает
  с START_TIMEOUT).
- GUI toggle: показ реальной причины ошибки через toast
  (systemctl stderr / spawn failure / daemon exited immediately).
- Icon: добавлена зависимость `librsvg2-common` — без неё GNOME
  не рендерит SVG-иконку.
- Icon: добавлена зависимость `hicolor-icon-theme`.
- daemon: `_start_tray()` перенесён внутрь try/finally, чтобы
  исключение в трее не оставляло stale lock.

## [0.2.0] - 2026-10-04

### Added

- Full 10 000-word frequency dictionaries for all five supported languages
  (`en`, `ru`, `uk`, `de`, `fr`), built from the FrequencyWords lists. The
  detector now loads any of them; `uk`/`de`/`fr` remain opt-in through
  `Config.languages`.
- A Ctrl/Alt chord abandons the word being typed, so `Ctrl+C` no longer leaves a
  stale word for the next Space to "correct". A Ctrl-based fix hotkey
  (`CTRL+F12`) and the `CTRL+CTRL` double tap still see the suspended word.
- A word taught in the user dictionary is honoured as a *converted* form before
  the false-positive guards run, so a brand typed in the wrong layout
  (`муксуд` -> `vercel`) is always fixed.
- Opt-in typo correction (T9). When the layout is already correct, a word within
  one edit (Damerau-Levenshtein) of exactly one dictionary word is replaced
  (`langauge` -> `language`, `teh` -> `the`). Ambiguous words, taught words and
  tokens with a separator are left alone. Toggle it in the GUI (**Advanced** ->
  **Typo correction (T9)**) or with `typo_correction = true`;
  `typo_max_distance` (1 or 2) and `typo_min_word_length` tune it.
- Password-field guard (AT-SPI): a fix is skipped while the focused element is a
  password entry, even if the stop-word list does not cover it.
- Text expansion (snippets). A `[snippets]` table in `snippets.toml` maps a
  trigger to text (with `{date}` / `{time}` placeholders); the daemon expands it
  before layout analysis. Toggle with `text_expander_enabled`.
- Selection fix. `CTRL+SHIFT+L` converts the layout of already-selected text
  (copy, convert, paste, restore) and can be rebound in the GUI.
- Per-app default layout. `app_layouts` maps an application name to a layout
  that is switched to when that application gains focus (`app_layout_switch`).
- Settings export/import. `lingvix export` / `lingvix import` (and the GUI
  **Backup** group) bundle the config, user dictionary and snippets into one
  JSON file. `lingvix restart` restarts the daemon preserving whether it runs
  as a user service; `lingvix config path` prints the config location.
- Opt-in update check. Once a day, when `update_check_enabled` is set, the
  daemon asks the GitHub releases API for the latest tag and logs (and
  notifies) when a newer version exists. Off by default — it is the only
  feature that uses the network. The GUI job now runs under xvfb and includes
  the GUI package in coverage (`.github/workflows/ci.yml`, `coverage-gui.rc`).
- Pre-filled exception list. `exceptions_apps` now ships with terminals, IDEs,
  editors and games (`gnome-terminal`, `code`, `vim`, `steam`, ...), where the
  text typed is a command or an identifier rather than a word. A manual fix
  (`SHIFT+SHIFT`) bypasses the list, so it still works inside a terminal.
- Quiet hours (`quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`).
  Inside the daily window (may wrap midnight) automatic correction is paused;
  the manual fix keeps working. The GUI home tab explains the pause.
- A correction-history tab in the GUI, backed by a bounded ring of recent fixes
  (`history_size`). Entries hold metadata only — word length, layouts, time and
  an `undone` flag — and the newest can be undone from the tab.

### Changed

- Default undo hotkey `CTRL+Z` -> `SHIFT+BACKSPACE` (Ctrl+Z collides with the
  application's own undo).
- The systemd unit runs the daemon with `Nice=-10` and round-robin scheduling so
  a fix wins the race against the compositor's handling of the boundary key.
- `dictionary_size` truncation now keeps the most frequent words (the corpora
  are stored frequency-first) instead of an alphabetical slice.

### Fixed

- A user-taught brand whose source text looks plausible (`муксуд`) was rejected
  by the plausibility guard before the user dictionary was consulted.

## [0.1.0] - 2026-10-04

### Added

- Automatic keyboard-layout correction (`ru` <-> `en`; `uk`/`de`/`fr` opt-in).
- Word-boundary triggers: Space, Enter, Tab, punctuation, plus an idle timeout.
- Scancode-replay replacement with an atomic Backspace batch and
  `backspace_settle_ms` / `trigger_settle_ms` pauses for Chromium/Electron.
- GUI (GTK4 + libadwaita): big on/off toggle, mode switcher, autostart switch,
  user-dictionary page, per-app exceptions.
- Working modes `auto` / `manual` / `hybrid` with undo via `Ctrl+Z`.
- Manual fix hotkey bound to a double tap of Shift by default (configurable).
- Per-app exceptions, context analysis and a user dictionary.
- CLI: `start`, `stop`, `kill`, `status`, `config`, `fix`, `doctor`,
  `collect-logs`, `dict`, `gui`, `mode`, `undo`.
- Zero-config `.deb`: `uaccess` udev rule, systemd user service, autostart entry
  and an application-menu entry.

### Fixed

- Truncation when a fix was triggered by Space/Enter (`руддщ ` -> `рhello`):
  a boundary flush now waits `trigger_settle_ms` before deleting, so the
  boundary key is processed before the Backspaces arrive.
- `Ctrl+Shift+Shift` (and other chords) no longer fire the double-tap fix
  hotkey; a tap counts only when no other modifier family is held.
- Application menu entry appears immediately after install
  (`update-desktop-database` in the `.deb` postinst and `install.sh`).
- False-positive corrections on plausible text, hyphenated identifiers and
  tokens with internal separators.
- Multi-character undo is reliable through the daemon (`lingvix undo`).

### Known limitations

- Password-field detection is not possible on Wayland; stop words are the
  mitigation.
- The `wtype` and `xdotool` backends are not atomic (only `uinput` is).
- GNOME layout switching requires `g3kb-switch`.
- The `uk`/`de`/`fr` corpora are opt-in and have not been calibrated against
  live input.

[0.2.9]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.9
[0.2.8.4]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.8.4
[0.2.8.3]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.8.3
[0.2.3]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.3
[0.2.2]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.2
[0.2.1]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.1
[0.2.0]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.2.0
[0.1.0]: https://github.com/Pavel1778/Klyrshift/releases/tag/v0.1.0
