# AGENTS.md

Repository-specific notes for agents working on Klyrshift.

## Layout

- `src/klyrshift/` — the Python package (PEP 621, `pyproject.toml`).
- `data/` — system integration files (systemd unit, XDG autostart, udev rule, icon).
- `src/klyrshift/data/` — data files **shipped inside the package** (`layouts.json`,
  `ngrams_*.json`, `stop_words.txt`, and copies of the unit/desktop/icon).
- `scripts/` — `build_deb.sh`, `smoke_test.sh`, `deb_selfsufficiency_test.sh`,
    `upgrade_test.sh`, `dev_setup.sh`, `build_demo_model.py` (generates the
    landing page's demo data).

`klyrshift.service`, `klyrshift.desktop` and `klyrshift.svg` exist in **both**
`data/` and `src/klyrshift/data/` and must stay byte-identical — a test enforces
this. `data/` is read by `install.sh`; `src/klyrshift/data/` is what an installed
package ships and what the CLI reads.

## Build and verify

```bash
pip install -e ".[dev]"
make check                                  # ruff + black --check + mypy --strict + pytest --cov
make build-deb && make smoke-test           # install the .deb into a clean debian:12
SMOKE_IMAGE=ubuntu:22.04 make smoke-test    # Python 3.10 path (tomli)
```

- Quality bar: `ruff check .`, `black --check .`, `mypy --strict .` clean;
  pytest coverage ≥ 80 %.
- GUI tests need a display: run them under `xvfb-run -a` with
  `PYTHONPATH=/usr/lib/python3/dist-packages` so `gi` (GTK4/libadwaita) is
  importable. Without it the GUI modules fail to import, not to assert.
- The pytest suite replaces the OS boundary with fakes, so it **cannot** catch
  packaging bugs. `scripts/smoke_test.sh` installs the real `.deb` into a clean
  container and is the only check that proves the package works.
- The README screenshots are real renders; regenerate them with
  `scripts/make_screenshots.py` after any GUI change. The script is hermetic --
  it pins a placeholder `HOME` and redirects every write into a throwaway tree --
  and a re-run is byte-stable, not merely close. Two animations had to be frozen
  for that to hold: `Adw.ViewStack`'s page cross-fade and the focused entry's
  blinking caret. Both are wall-clock driven, so a render that lands mid-frame
  differs by a handful of antialiasing levels and the committed PNGs drift on
  every regeneration. The script disables the stack transition, waits a fixed
  settle window, and turns `gtk-cursor-blink` off; keep all three if you touch
  it, and note that `transition-running` alone is *not* enough -- the switcher
  underline keeps ticking after the flag clears. `tests/test_screenshots.py`
  guards the flags, and its `KLYRSHIFT_RENDER_TEST=1` case renders twice and
  asserts the bytes match. Do not render against the developer's real `HOME`: a
  first-run tour offer covers the home page and the shot then depends on the
  machine's onboarding state.
- `tests/test_backend_integration.py` is the exception to the "fakes only" rule:
  it writes real stub executables (`g3kb-switch`, `setxkbmap`, `wtype`,
  `xdotool`) onto a throwaway `PATH` and drives the real `LayoutSwitcher` /
  `TextInjector`, so backend *discovery* and argv construction are covered
  without a display server. Talking to a live compositor still needs a desktop.

## Invariants that have bitten before
- **The live hosts are `klyrshift.*`, not `linguafix.*`.** The site's canonical
  origin lives in two places that must agree: `site/astro.config.mjs` (sitemap,
  `robots.txt`) and `site/src/lib/site.ts` (canonical, `og:url`, hreflang). Both
  point at `klyrshift.layero.app` / `klyrshift.vercel.app`; the pre-rename
  `linguafix.*` names return 404, and a canonical that points at a 404 makes
  search engines drop the page. `README.md` badges and links use the same hosts.
  `tests/test_repo_urls.py` pins the live origins and fails if any tracked
  document, template or the config links a `linguafix.*` host.

- **The live GitHub release predates the rename.** Its assets are named
  `linguafix-*` (`linguafix_<v>_all.deb`, `linguafix-dict-<slug>.tar.gz`),
  while the build scripts and `repo.py` emit `klyrshift-*`. A hard-coded
  `klyrshift-dict-*` request 404s against the current release, so
  `thematic.download_category` tries every prefix (`_ASSET_PREFIXES`:
  `klyrshift-`, `lingvix-`, `linguafix-`). The next release built from this tree
  will ship `klyrshift-*`, and the fallbacks keep the old one working meanwhile.
  The landing page's download button points at the release *page*, not a
  versioned asset URL, for the same reason (`site/src/consts.ts`).

- **The version the tree carries is not necessarily the version that is
  published.** The site advertised `0.2.8.2` while the newest release was
  `v0.2.8`; `CHANGELOG.md` even has a `## [0.2.8.2]` heading dated 2026-10-08
  that was never tagged. `tests/test_version_consistency.py` compared the source
  files only with each other, so it could not see this. The check is now split:
  `scripts/release_consistency.py --source` is offline and runs in the suite (the
  tree against itself and against the asset names the build scripts emit), while
  `--tag`/`--latest` need the network and run from the release workflow, which
  gates the publish on them. When you bump the version, expect `--latest` to
  fail until the tag is published; that is the point.

- **Every version string must be derived, never typed.** `Base.astro` wrote
  `softwareVersion: "0.2.8.2"` as a literal while `consts.ts` held `VERSION`, so
  a bump updated the hero and left the JSON-LD behind -- two versions on one
  page. The layout imports `VERSION` now, and
  `test_release_consistency.py::test_jsonld_version_is_not_a_literal` fails if
  the literal returns.

- **A version lives in five files, and the fifth had no reader.** `site/package.json`
  sat at `0.2.8.2` while `consts.ts` said `0.2.8.3`: no test read it, so the drift
  was silent and the npm metadata described a build that no longer existed. It is
  now compared with `pyproject.toml` too (its lockfile carries the same string and
  is bumped with it).

- **The publish step checks the *staged* assets, not a comment.** The release
  workflow lists `dist/*.deb`, `dist/dictionaries/*-50k.txt` and
  `dist/dict-archives/*.tar.gz` into `/tmp/staged-assets.txt` and passes it to
  the consistency check, so an asset a build script emits but the workflow
  forgets to upload is caught before the release is public. It then verifies the
  published download URLs, because only a real request proves an asset is
  downloadable.

- The `.deb` must be **zero-config**: device access is granted by a udev rule
  with `TAG+="uaccess"`, never `GROUP="input"`/`usermod`. The user unit is
  enabled with `systemctl --user enable --global` from `postinst`, not by the
  user. `make zero-config` asserts all of this.
- Keep the apt `Depends:` in `scripts/build_deb.sh` in sync with the runtime
  imports. `tomli` is required on Python < 3.11; `tomli_w` on all versions.
- `data/*.service` and `data/*.desktop` contain a `@BIN@` placeholder. It is
  rendered by `install.sh` (venv launcher), `build_deb.sh` (`/usr/bin/klyrshift`)
  and the CLI (`shutil.which("klyrshift")`). Never ship an unrendered file.
- The daemon tracks the current word as **scancodes** (`_scancodes`), not only
  as characters. `TextInjector.replace_text` takes a *count*, not the old text;
  the daemon passes `len(self._scancodes)`. Do not reintroduce a string-based
  backspace count: it desynchronises from the screen and leaves the first
  character behind (the `рhello` bug).
- `replace_text` on `uinput` flushes the backspaces with one `syn`, sleeps
  `backspace_settle_ms`, then flushes the replacement with a second `syn`.
  Chromium/Electron apply Backspace asynchronously, so a single batch races the
  deletion. Keep the two flushes; a test asserts the order and the pause.
- A boundary-triggered flush (Space/Enter/Tab/punctuation) sleeps
  `trigger_settle_ms` **before** deleting, so the boundary key is processed
  first; otherwise Chromium/Electron coalesce the fast Backspaces and the first
  character survives (`руддщ ` -> `рhello`). Only boundary flushes pass
  `boundary=True`; the idle fallback and hotkey must not pay this pause.
- A single token mixing Latin and Cyrillic (`ghbdtnпривет`) is **never** rewritten
  as a unit: only one half is on the wrong layout, so converting the token
  damages the correct half (`ghйпривет`). `detector._has_mixed_script_word`
  gates `target_layout`, `detect`, `should_fix` and the daemon's T9 pass; the
  separator between the two scripts flushes each half on its own boundary.
  Scripts in *separate* words (`привет hello`) are still converted as a whole —
  `tests/test_mixed_script_word.py` pins both directions.
- A double-tap modifier hotkey fires only when no *other* modifier family is
  held, so `Ctrl+Shift+Shift` is treated as a chord, not a fix.
- Word-boundary triggers (`on_space`, `on_enter`, `on_tab`, `on_punctuation`)
  live in `Config`; Space/Enter are on by default. A token with an internal
  separator (`.` `@` `/` `\` `:` `_` `-`) is never rewritten (URLs, e-mails,
  paths, versions, hyphenated identifiers).
- **Only `en` and `ru` are loaded by default.** The Latin layouts (`us`, `de`,
  `fr`) share physical positions, so loading every shipped corpus at once makes
  them compete and changes default detection. `DEFAULT_DETECTOR_LANGUAGES` in
  `detector.py` must stay `("en", "ru")`; `uk`/`de`/`fr` are opt-in through
  `Config.languages`. `test_languages.py` guards both the new corpora and the
  unchanged default.
- Adding a language is data-only: drop `ngrams_<lang>.json`, extend
  `layouts.json`, and add the code to `SUPPORTED_LANGUAGES` in `config.py`. A
  missing corpus is skipped, never treated as an empty model.
- The user dictionary is consulted in **two directions**. It is an **absolute**
  override: `target_layout` returns `None` for any taught word, in every layout.
  It also validates the *converted* form: if the wrong-layout rendering of the
  buffer is a taught word (``муксуд`` → ``vercel``), the correction fires even
  though the brand is absent from the frequency corpora. This is why an unknown
  brand is silent until `klyrshift dict add` teaches it. It is a vocabulary
  membership test, not a score bonus — a bonus is drowned out by the n-gram
  penalties.
  The file (`~/.local/share/klyrshift/dictionary.txt` by default) is edited
  explicitly (`klyrshift dict add/remove`, the GUI Dictionary tab, or by hand);
  the daemon never writes typed text to it. A config reload always re-reads it.
- The default fix hotkey is **`SHIFT+SHIFT`** (double tap of a modifier within
  `hotkey_double_tap_ms`, default 300 ms), not `PAUSE`. `daemon._parse_hotkey`
  handles chords; `_build_double_tap_hotkeys`/`_handle_modifier` handle double
  taps. A single modifier tap never fixes, and any other key cancels an armed
  tap, so capitalisation is unaffected. `DEFAULT_FIX_HOTKEY` in `config.py` is
  the single source of the default.
- **A hotkey's non-final tokens must be known modifiers.** The matcher fires
  when the held modifier families *equal* the binding's, so an unrecognised
  token (`CMD+Q`, `FN+Q`) contributed no family, left the set empty, and the
  binding then fired on every bare press of its last key. `normalise_hotkey`
  rejects such a chord at config-load time and `daemon._parse_hotkey` drops it
  as well, so a config built in memory cannot reach the matcher. A lone
  modifier (`CTRL`) or a chord ending in one (`CTRL+SHIFT`) is rejected too --
  neither has a key to fire on. `CTRL+CTRL` stays the valid legacy double tap.
- `context_analysis`/`context_weight` may only *add* to a candidate, never push
  the current layout below zero, so a neighbour can tip a borderline word but
  cannot create or suppress a correction on its own.
- `subprocess.run(..., check=False)` still raises `FileNotFoundError` when the
  binary is missing. Guard calls with `OSError`.
- `install.sh` runs under `set -u`; do not reference `USER` directly (it is unset
  in cron/su/containers) — use the `CURRENT_USER` fallback.
- Inside `docker run ... bash -c '...'` single-quoted blocks, do not put an
  apostrophe in a comment: it ends the block early. The smoke and zero-config
  scripts both hit this.
- Running the installed CLI as root creates root-owned `__pycache__` under
  `/usr/lib/klyrshift`, which dpkg does not track; `postrm` cleans it with
  `py3clean` + `rm -rf`.
- **Autostart has two independent mechanisms** and both must be honoured:
  the systemd user unit (`klyrshift.service`, enabled *globally* in
  `/etc/systemd/user` by the `.deb`) and the XDG entry
  (`~/.config/autostart/klyrshift.desktop`, written by `install.sh`). A defect
  survived here twice: `disable_autostart()` removed only the unit, so the XDG
  entry kept starting the daemon and the GUI switch snapped back on; and
  `systemd_enabled()` trusted `systemctl is-enabled`, which reports a globally
  enabled unit as `disabled` in a session that has not reloaded, so a
  working autostart read as off. `daemon_control.disable_autostart` now removes
  the XDG entry **and** masks the unit (an unprivileged user cannot
  `disable --global`); `enable_autostart` removes the mask; `systemd_enabled`
  also probes the `/etc/systemd/user/*/klyrshift.service` wants symlinks directly
  (`globally_enabled`). `tests/test_daemon_control.py` pins all four paths.
  The source installer has its own switch: `install.sh --no-autostart` skips the
  XDG entry, undoes a previous `enable`, and still starts the daemon for the
  current session; re-running with it deletes an entry an earlier default
  install wrote. `tests/test_installer_autostart.py` runs the real script with
  stub system binaries on `PATH` and asserts the recorded `systemctl` argv.
- `site/src/data/demo-model.json` is **generated** from the shipped
  `src/klyrshift/data/ngrams_*.json` by `scripts/build_demo_model.py`; the landing
  page's demo (`site/src/components/Demo.astro`) ports the detector's
  plausibility test to TypeScript on top of it. Never hand-edit the JSON: rerun
  the script after a corpus rebuild. `tests/test_demo_model.py` fails when the
  committed model drifts from the corpora.
  - `site/` is Astro 7 + Tailwind CSS 4 via `@tailwindcss/vite`. The theme lives
    in `site/src/styles/global.css` (`@import "tailwindcss"` + `@theme`); there is
    no `tailwind.config.mjs`. Two migration traps to keep in mind: Tailwind 4
    reserves `--font-mono` as a theme key, so Astro's mono font variable is named
    `--font-jetbrains` (a colliding name silently drops the built `--font-mono`);
    and v4 decouples `text-*` from `leading-*`, so an explicit `leading-tight`
    now overrides `text-5xl`'s line-height where v3 let the breakpoint win — pin
    the intended line-height explicitly. Astro 7 needs Node >=22.22 (see
    `site/package.json` `engines` and the CI `site` job).
  - `site/public/og-image.png` (the 1200x630 link preview) is **generated** by
  `scripts/make_og_image.py`, which inlines `site/public/logo.svg` and the
  self-hosted Inter/JetBrains Mono woff2 that Astro emits, then screenshots the
  card with headless `chromium`. It needs a prior `npm run build` in `site/`
  (the fonts are gitignored build output) and raises `SiteNotBuilt` otherwise.
  The old image was hand-made, so the `LinguaFix` -> `Klyrshift` rename never
  reached it and every link preview showed the dead name; `tests/test_og_image.py`
  now pins the size, a non-blank render, and (via `tesseract`, skipped when
  absent) that the card shows `Klyrshift` and not `LinguaFix`.

## Editing files with non-ASCII text

`file_editor` re-encodes UTF-8 on save and corrupts non-ASCII characters
(Cyrillic, em-dashes, box-drawing) into mojibake. The damage lands on lines
*outside* the edit as well, so a small rename can silently wreck a whole file.
`tests/test_source_encoding.py::test_no_mojibake_in_tracked_sources` fails on it.

- To edit a file that contains Cyrillic, use `python` with an explicit
  `encoding="utf-8"` (`Path(...).read_text/write_text`), not `file_editor`.
- To repair a file already hit: `git checkout HEAD -- <file>`, then re-apply
  the edits with the Python heredoc above.
- Detect damage by scanning tracked files for the mojibake lead characters
  (U+00D1, U+00E2) or by running the encoding test.
- The signature set covers Cyrillic only, so a double-encoded **punctuation**
  mark slipped past it: an arrow (→) re-saved through CP775 becomes the
  three characters `\u014c\u00e5\u00c6`, and an em-dash (—) through
  CP1252 becomes `\u00e2\u20ac\u201d`; the file still imports.
  `test_source_encoding.py`
  now also round-trips every line through the codecs a single-byte pipeline
  plausibly uses (CP1252, CP775, Latin-1, CP437, CP850, MacRoman) and fails on
  any line that decodes cleanly. Measured against the whole tracked tree: no
  false positives, so extend `_MOJIBAKE_CODECS` rather than special-casing
  characters. Note the examples in that file must stay as `\uXXXX` escapes --
  written literally they would trip the guard itself.
- Keep the fix for a damaged file in a Python heredoc / script with an explicit
  `encoding="utf-8"`. Re-applying an edit through `file_editor` after a
  `git checkout` is what produced the corruption in the first place.

## Security / privacy invariants (audited)

- The typed text must never reach disk or a subprocess argv. `_process_buffer`
  and `_handle_event` catch every exception and log a **sanitized** traceback:
  the buffer is replaced with `<redacted>` before logging, because an exception
  message could otherwise embed it. `tests/test_privacy_audit.py` greps the log,
  cache, state, config, journal and argv for a known secret and must stay green.
- **No `%r`/`%s` of a user word in a log call.** `_typo_correction` used to log
  the inspected word and the rejected suggestion at DEBUG, so `log_level=DEBUG`
  wrote the user's typing to `klyrshift.log`. The existing audit missed it because
  its secret is not a plain letter word and never reached those lines. Log a
  length (`len(word)`), never the characters; the guard test for this is
  `test_t9_decision_path_never_logs_the_word`.
- The desktop notification is a fixed label, never the corrected text.
- Replacement on the `uinput` backend is **atomic**: all backspaces and the new
  text are written and flushed with a single `syn`. `wtype`/`xdotool` are not
  atomic (documented limitation).
- `_process_buffer` snapshots and clears the buffer under `self._lock`, then
  releases the lock before the slow switch/inject so keys typed during a fix are
  buffered, not dropped. Do not hold the lock across `replace_text`.
- The buffer is bounded by `Config.max_buffer_size` (default 200) and flushed
  early on overflow, so a held key cannot grow it without bound.
- `klyrshift stop` escalates to `SIGKILL` after 2 s; `klyrshift kill` forces it.
- When the last keyboard disappears the loop re-runs discovery in place (never
  caches a device path); `Restart=always` is the backstop.

## Platform facts (Debian 12 / 13) — do not relearn the hard way

- **Never import the `uinput` package.** On Debian 13 `python-uinput` 1.0.1
  exposes `KEY_*` as `(event_type, code)` tuples and its API is
  `Device`/`emit`; Debian 12's 0.11.2 is the same shape. `int(uinput.KEY_A)`
  raises `TypeError` and `uinput.UInput` does not exist. The virtual keyboard is
  built with `evdev.UInput` and key codes come from `evdev.ecodes` (plain ints).
  `tests/test_injector_uinput_compat.py` guards this contract.
- **`g3kb-switch -s` takes the layout name**, e.g. `g3kb-switch -s ru` (it also
  accepts the numeric group index). `-p` prints the current layout. A non-zero
  exit is the only reliable failure signal; stderr may be non-empty on success.
- **The demo-parity harness needs a Node that runs TypeScript.** Node 20 (what
  CI's lint job used to pin) cannot execute `.ts` at all: it fails with
  `ERR_UNKNOWN_FILE_EXTENSION`, which turned `test_demo_parity.py` red on every
  Python version. Node ≥ 23.6 runs it directly; 22.6+ needs
  `--experimental-strip-types`; older Node now skips. `tests/test_demo_parity.py`
  picks the invocation from `node --version`.
- **The udev rule must be named below `73` and carry `ACTION!="remove"`.** On
  systemd 257+ (Debian 13) `73-seat-late.rules` turns `uaccess` into the ACL. It
  runs in filename order and only processes rules that guard the `remove` event,
  so a `99-*` rule without the guard is silently skipped and `/dev/input` stays
  unreadable. The shipped rule is `data/71-klyrshift.rules`.
- `python3-evdev` ships in Debian and Ubuntu and is the only native runtime
  dependency; `install.sh` reuses it via `--system-site-packages` so no compiler
  is needed. `python-uinput` is **not** a dependency.
- **`python3-gi` is not enough for the GUI: the Cairo override is a separate
  package.** `Gtk.DrawingArea.set_draw_func` (the tour scrim, the fallback power
  glyph) is handed a `cairo.Context`, and PyGObject can only build that converter
  when `_gi_cairo` is importable -- `python3-gi-cairo`, which `python3-gi` does
  not depend on. Without it the window still opens and `from gi.repository import
  cairo` still succeeds, so the only symptom is a blank widget plus
  `Couldn't find foreign struct converter for 'cairo.Context'` on every frame.
  Detect it with `from gi import _gi_cairo` (`klyrshift.gui.cairo_available`), not
  by importing `gi.repository.cairo`. The package is listed in the `.deb`
  `Recommends`, `install.sh`, the CI apt list and the docs; keep them in step.
- **The tour's saved position is the step *index*, not the step key.** The
  overlay reports each displayed index through `on_step_shown`; the window
  writes it to `OnboardingState.last_step` and `start_tour` resumes there. Only
  an *interrupted* tour (the window closed mid-run) resumes: finishing or
  skipping clears the index to `0`, so a deliberate replay starts at the top.
  `_clamp_start_step` returns `start_step - 1` because `open()` then calls
  `_advance(1)` onto the target, which still skips an undisplayable step.
  - **The container's `LD_LIBRARY_PATH` breaks `/usr/local` Python.** It puts
  `/usr/lib/x86_64-linux-gnu` on the loader path, which resolves libffi to the
  distro copy and makes `import ctypes` segfault (so `import evdev`, `black` and
  pytest all die with SIGSEGV). `/usr/bin/python3` is unaffected. When the venv
  interpreter segfaults in `ctypes/__init__.py`, rerun with
  `env -u LD_LIBRARY_PATH`. This is an environment quirk, not a code bug.

## Known limitation

The daemon works on a real GNOME desktop only; the CI and smoke tests do not
exercise the evdev → uinput correction path end to end. See `docs/TESTING.md`.
