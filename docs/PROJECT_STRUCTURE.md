# Project structure

A map of the Klyrshift repository: what every top-level directory is for, which
module does what, where the tests, the documentation and the packaging live, and
which files are generated rather than edited. Read this first if you are new to
the codebase; the design rationale behind the modules is in
[ARCHITECTURE.md](ARCHITECTURE.md), and the repository conventions an agent or a
contributor must follow are in [`AGENTS.md`](../AGENTS.md).

## Top level

| Path | What it holds |
|---|---|
| `src/klyrshift/` | The Python package (PEP 621 layout, declared in `pyproject.toml`). |
| `tests/` | The pytest suite; replaces the OS boundary with fakes. |
| `docs/` | The documentation sources, the generated handbook and the screenshots. |
| `scripts/` | Build, packaging, verification and documentation-generation scripts. |
| `data/` | System integration files used by `install.sh` and the `.deb` build. |
| `src/klyrshift/data/` | Data files **shipped inside the package** (what an install reads). |
| `dictionaries/` | Frequency word lists and the thematic dictionary categories. |
| `site/` | The Astro landing page (separate Node project, own lockfile). |
| `.github/` | CI/release workflows, issue and PR templates, Dependabot config. |
| `.openhands/` | Session memory notes for agents (not shipped, not part of the build). |
| `README.md` | The user-facing front page and the entry point to the docs index. |
| `CHANGELOG.md` | Keep-a-Changelog history; the release date is derived from it. |
| `AGENTS.md` | Repository conventions and the invariants that have bitten before. |
| `AUDIT.md` | The daemon audit: baseline numbers, defects found, fixes. |
| `pyproject.toml` | Packaging metadata, dependencies and the tool configuration. |
| `requirements.txt` | The same runtime dependency floors, for the venv installer. |
| `Makefile` | The task entry points (`make check`, `make build-deb`, ...). |
| `install.sh` / `uninstall.sh` | The source installer and its uninstaller. |
| `MANIFEST.in` | Extra files the sdist carries (dictionaries, man page, completions). |
| `coverage-gui.rc` | The coverage config the GUI CI job uses (GUI modules included). |
| `LICENSE`, `.editorconfig`, `.gitignore` | Licence and editor/tooling defaults. |

## The Python package — `src/klyrshift/`

The package is split into small, single-responsibility modules. The daemon is the
centre; everything else is a capability it composes or a boundary it talks to.

### Core runtime

| Module | Responsibility |
|---|---|
| `__init__.py` | The package version (`__version__`) and `__all__`. |
| `__main__.py` | `python -m klyrshift` entry point. |
| `cli.py` | The `argparse` command line: every subcommand and option. |
| `config.py` | The `Config` dataclass, XDG paths, TOML load/save, validation. |
| `daemon.py` | `KlyrshiftDaemon`: the event loop, buffering and orchestration. |
| `daemon_control.py` | Start/stop/reload/undo a daemon however it was launched. |
| `detector.py` | Language detection, context, user dictionary, `target_layout`. |
| `converter.py` | Character maps between layouts (`us`, `ru`, `uk`, `de`, `fr`). |
| `switcher.py` | Layout switching via `g3kb-switch` / `setxkbmap`. |
| `injector.py` | Text replacement via `uinput` / `wtype` / `xdotool`. |
| `dictionary.py` | The user dictionary file and the extended frequency dictionaries. |
| `thematic.py` | Thematic (professional) dictionaries: categories, download, offline fallback. |
| `typo.py` | T9: bounded Damerau-Levenshtein and `TypoCorrector` (opt-in). |
| `punctuation.py` | Opt-in punctuation cleanup for a finished word. |
| `text_expander.py` | Snippet expansion (trigger -> text). |
| `selection_fix.py` | Convert the layout of already-selected text. |
| `learning.py` | Always-on, privacy-preserving learning (counters on disk, words in memory). |
| `app_focus.py` | Best-effort focused-application detection for exceptions. |
| `app_layouts.py` | `AppLayoutManager`: switch layout when a mapped app gains focus. |
| `control.py` | The local control socket for the running daemon. |
| `integrity.py` | Post-install integrity check (`klyrshift verify`). |
| `langpack.py` | Versioned, checksummed language packages. |
| `langstore.py` | Install/remove language dictionaries (the GUI path). |
| `doctor.py` | `klyrshift doctor`: environment and permission diagnosis. |
| `collect_logs.py` | `klyrshift collect-logs`: bundle logs for a bug report. |
| `logs.py` | Read the daemon log for `klyrshift logs`. |
| `logging_setup.py` | Rotating file logger under `~/.local/state/klyrshift/`. |
| `backup.py` | Export/import a JSON bundle of config + dictionary + snippets. |
| `update_check.py` | Opt-in GitHub release check (daily, off by default). |
| `onboarding.py` | Tour steps and help texts as plain data (no GTK import). |
| `tray.py` | Optional AppIndicator tray icon. |
| `i18n.py` | Interface localisation: the Russian source string is the key. |
| `repo.py` | Single source of truth for the project's GitHub URLs. |
| `simulate.py` | The headless behavioural simulator (fakes keyboard/switcher/injector). |

### GUI — `src/klyrshift/gui/`

An optional GTK4 + libadwaita window. It is imported lazily, so the package works
without PyGObject installed.

| Path | Responsibility |
|---|---|
| `app.py` | The `Adw.Application`. |
| `window.py` | The main window: home, settings and advanced tabs. |
| `home_page.py` | Home page: the big on/off toggle and at-a-glance status. |
| `settings_page.py` | Basic settings page (always visible). |
| `advanced_page.py` | Advanced settings page (hidden behind a button). |
| `typo_page.py` | T9 and punctuation cleanup, each with its own mode. |
| `dictionary_page.py` | The user-dictionary page. |
| `history_page.py` | The last corrections, shown as metadata only. |
| `help_page.py` | Tour replay, settings help and diagnostics. |
| `about_page.py` | The About dialog (carries the dictionary-data credit). |
| `prefs_base.py` | Shared base for the settings pages. |
| `state.py` | Shared GUI state: config access and daemon status helpers. |
| `style.py` / `style.css` | Load the bundled stylesheet. |
| `theme.py` | Apply the configured colour scheme. |
| `async_utils.py` | Run blocking probes off the GTK main thread. |
| `widgets/` | The reusable widgets (each in its own module): |
| `widgets/big_toggle.py` | The VPN-style big on/off button. |
| `widgets/mode_switcher.py` | The segmented auto/manual/hybrid switch. |
| `widgets/status_row.py` | The compact status line under the big toggle. |
| `widgets/dictionary_list.py` | The editable user-dictionary list. |
| `widgets/app_exceptions_list.py` | The editable per-application exceptions list. |
| `widgets/app_layout_map.py` | The app-name -> preferred-layout mapping. |
| `widgets/app_mode_map.py` | The app-name -> correction-mode mapping. |
| `widgets/languages_group.py` | Enable a language and install/remove its dictionary. |
| `widgets/hotkey_row.py` | A row that records a keyboard shortcut. |
| `widgets/backup_group.py` | Export/import the whole configuration. |
| `widgets/first_run_wizard.py` | The paginated first-run setup dialog. |
| `widgets/tour_overlay.py` | The guided-tour overlay. |
| `widgets/help_button.py` | The context-help `?` button and its dialog. |
| `widgets/shortcuts_dialog.py` | The keyboard-shortcut reference. |

### Autonomous QA engine — `src/klyrshift/qa/`

A testing layer on top of the pytest suite, driven by the simulator. The corpus
is data (`src/klyrshift/data/qa/scenarios.json`), not Python literals.

| Module | Responsibility |
|---|---|
| `scenario.py` | The scenario model and its JSON format. |
| `curated.py` | The curated scenario library, loaded from bundled JSON. |
| `invariants.py` | Independent correctness checks over a simulation result. |
| `executor.py` | A safe executor: run a scenario through `klyrshift.simulate`. |
| `generator.py` | Deterministic (seeded) generation, with a pluggable LLM hook. |
| `analyzer.py` | Classify a failure and minimise it by delta-debugging. |
| `store.py` | The append-only regression store. |
| `runner.py` / `report.py` | Orchestration and measured-only reports. |

### Shipped data — `src/klyrshift/data/`

| Path | Contents |
|---|---|
| `layouts.json` | The physical-position maps for every supported layout. |
| `ngrams_<lang>.json` | Frequency word lists and bigram maps per language. |
| `stop_words.txt` | Tokens that are never corrected (one per line). |
| `locales/<locale>.json` | Interface translation catalogues (`en`, `de`, `fr`, `uk`). |
| `qa/scenarios.json` | The curated QA scenario corpus. |
| `klyrshift.service`, `klyrshift.desktop`, `klyrshift-autostart.desktop`, `klyrshift.svg` | Copies of the system integration files (see below). |

## System integration — `data/` and `install.sh`

`data/` is the source the source installer (`install.sh`) and the `.deb` build
read; `src/klyrshift/data/` is what an installed package ships and what the CLI
reads. The service, desktop, autostart and icon files exist in **both** places
and must stay byte-identical — `tests/test_data_sync.py` enforces this.

| Path | Contents |
|---|---|
| `data/71-klyrshift.rules` | The udev rule granting device access via `uaccess` (named below `73-`). |
| `data/klyrshift.service` | The systemd **user** unit (enabled globally by the `.deb`). |
| `data/klyrshift.desktop`, `data/klyrshift-autostart.desktop` | The application and XDG-autostart entries. |
| `data/klyrshift.svg` | The application icon. |
| `data/klyrshift.1` | The man page (**generated** by `make cli-docs`). |
| `data/completions/` | The bash/zsh completions (**generated** by `make cli-docs`). |
| `data/copyright` | The DEP-5 copyright, shipped to `/usr/share/doc/<pkg>/copyright`. |

## Tests — `tests/`

88 modules covering logic, config, detector, daemon policy, GUI, packaging,
documentation consistency and privacy. The suite replaces the OS boundary
(evdev, `uinput`, GTK) with fakes and never mocks Klyrshift's own modules, so it
proves logic but **not** packaging — `scripts/smoke_test.sh` installs the real
`.deb` for that. `tests/conftest.py` holds the shared fixtures. See
[TESTING.md](TESTING.md) and [TEST_STRATEGY.md](TEST_STRATEGY.md).

The GUI tests need a display: run them under `xvfb-run -a` with
`PYTHONPATH=/usr/lib/python3/dist-packages` so `gi` (GTK4/libadwaita) imports.

## Documentation — `docs/`

Every guide is a Markdown source in `docs/` and is linked from the README. The
offline handbook (`docs/klyrshift-handbook.md` and `.pdf`) is **generated** by
`scripts/build_docs.py` from the sources listed in its `SOURCES` tuple — a new
guide must be added there or `tests/test_docs_handbook.py` fails.

| Document | Covers |
|---|---|
| [INSTALL.md](INSTALL.md) | Install from the `.deb` or from source; migrate from the old names. |
| [CLI.md](CLI.md) | The command-line reference (generated; same as `man klyrshift`). |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptom-to-fix guide for real systems. |
| [PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md) | X11/Wayland support and what is actually verified. |
| [LANGUAGE_PACKAGES.md](LANGUAGE_PACKAGES.md) | The language-package format: version, checksum, rollback. |
| [INTERFACE_LANGUAGES.md](INTERFACE_LANGUAGES.md) | UI catalogues, the fallback chain and how to add a locale. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Design decisions, data flow and the module map. |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | This file: the repository map. |
| [CONTROL_SOCKET.md](CONTROL_SOCKET.md) | The daemon control-socket protocol. |
| [UNDO_CONTRACT.md](UNDO_CONTRACT.md) | The contract for undoing a correction. |
| [OFFLINE_AND_PRIVACY.md](OFFLINE_AND_PRIVACY.md) | Offline operation and the privacy invariants. |
| [TESTING.md](TESTING.md) | The three test levels and the manual desktop plan. |
| [QA_ENGINE.md](QA_ENGINE.md) | The autonomous QA engine. |
| [AUTOPROGRESS_BREAKAGE.md](AUTOPROGRESS_BREAKAGE.md) | Why the automated run breaks: the defect, its root cause and the fix. |
| [TEST_STRATEGY.md](TEST_STRATEGY.md) | Quality metrics and regression thresholds. |
| [RELEASING.md](RELEASING.md) | The release checklist. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, code standards and commit conventions. |
| [ROADMAP.md](ROADMAP.md) | Where the project is and what comes next. |
| [FEATURES.md](FEATURES.md) | The implemented-feature inventory, grouped by area. |
| [WORK_REPORT.md](WORK_REPORT.md) | The work report: what is done and the results achieved. |
| [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) | The verification report: what is already built, measured on the current tree. |
| [SPECIFICATION_AUDIT.md](SPECIFICATION_AUDIT.md) | The specification audit: declared settings with no reader, and their fixes. |
| [screenshots/](screenshots/README.md) | The README screenshots and how they are rendered. |

## Scripts — `scripts/`

| Script | Purpose |
|---|---|
| `build_deb.sh` | Build the reproducible `.deb` with `dpkg-deb` (no `dh_make`). |
| `build_dict_archives.sh` | One `.tar.gz` per thematic dictionary category. |
| `smoke_test.sh` | Install the `.deb` into a clean container and exercise the CLI. |
| `deb_selfsufficiency_test.sh` | Prove the `.deb` needs no manual step (udev, enable). |
| `upgrade_test.sh` | Install over the pre-rename `linguafix` package. |
| `patch_upgrade_test.sh` | Install the current patch over the previous one. |
| `acceptance_check.sh` | The real-hardware acceptance check (Debian 13 + GNOME). |
| `verify_v028.sh` | Post-install verification for v0.2.8. |
| `build_docs.py` | Render the Markdown handbook and the PDF. |
| `build_cli_docs.py` | Generate the man page and completions from the parser. |
| `build_corpora.py` | Build `ngrams_<lang>.json` from FrequencyWords lists. |
| `build_demo_model.py` | Generate the landing page's `demo-model.json`. |
| `make_screenshots.py` | Render the README screenshots from the real GUI. |
| `make_og_image.py` | Render the social-preview card. |
| `measure_detector.py` | Reproducible detector-quality measurement. |
| `measure_latency.py` | Reproducible latency and memory measurement. |
| `merge_dict_terms.py` | Merge terms into a thematic dictionary file. |
| `refresh_dict_readmes.py` | Rewrite the word count in the thematic READMEs. |
| `release_consistency.py` | Check the tree (and, with `--latest`, the release) for consistency. |
| `dev_setup.sh` | Create the dev venv and install the hooks. |

## Landing page — `site/`

A separate Astro 7 + Tailwind CSS 4 project with its own `package.json` and
lockfile. It carries a port of the detector's plausibility test (the demo), which
must stay in step with the Python detector. See `site/README.md` and the
`site/` notes in [`AGENTS.md`](../AGENTS.md).

| Path | Contents |
|---|---|
| `site/src/pages/` | The pages (`index.astro`, `dictionaries.astro`, `robots.txt.ts`). |
| `site/src/components/` | The page sections (hero, features, comparison, demo, ...). |
| `site/src/layouts/Base.astro` | The shared HTML shell (canonical, hreflang, JSON-LD). |
| `site/src/lib/` | Shared helpers (site constants, theme, dictionary palette). |
| `site/src/data/demo-model.json` | The demo model (**generated** by `build_demo_model.py`). |
| `site/public/` | Static assets (logo, favicons, the generated `og-image.png`). |
| `site/astro.config.mjs`, `site/layero.json`, `site/vercel.json` | Build and deploy config. |

## Dictionaries — `dictionaries/`

The base frequency lists (`en-50k.txt`, `ru-50k.txt`, `uk-50k.txt`, `de-50k.txt`,
`fr-50k.txt`) are CC-BY-SA-4.0 content from FrequencyWords. The thematic
categories (`business/`, `code/`, `medicine/`, ...) are hand-curated and MIT.
`dictionaries/README.md` documents the layout; see also
[LANGUAGE_PACKAGES.md](LANGUAGE_PACKAGES.md) and the licensing notes in
[`AGENTS.md`](../AGENTS.md).

## Build and verify

```bash
bash scripts/dev_setup.sh        # venv + dev dependencies
make check                       # ruff + isort + black + mypy --strict + pytest --cov
make build-deb                   # build the .deb into dist/
make smoke-test                  # install it into a clean Debian container
make docs-pdf                    # regenerate the handbook (Markdown + PDF)
make cli-docs                    # regenerate the man page and completions
```

Generated files that are committed and must be regenerated, never hand-edited:
`docs/klyrshift-handbook.md`/`.pdf`, `data/klyrshift.1`,
`data/completions/*`, `site/src/data/demo-model.json`, `site/public/og-image.png`
and the README screenshots. `AGENTS.md` lists the invariants (duplicated data
files, version strings in five places, reproducible `.deb`) that the tests pin.
