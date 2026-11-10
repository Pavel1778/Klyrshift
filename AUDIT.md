# Klyrshift audit — configuration atomicity, error surfacing and simulator bounds

This document records a full audit of the Klyrshift daemon performed with the
project's own tooling (the headless simulator `klyrshift simulate` and the
autonomous QA engine `klyrshift qa run`). It lists what was measured, the four
defects found, how each was fixed, and what was deliberately left out of scope.

## Phase 0 — baseline (before any change)

| Check | Command | Result |
| --- | --- | --- |
| Tests | `pytest` | 1505 passed, 111 skipped |
| Coverage | `pytest --cov=klyrshift` | 85 % (bar: 80 %) |
| Types | `mypy --strict .` | clean |
| Lint | `ruff check .` / `black --check .` / `isort --check-only .` | clean |
| QA (default) | `klyrshift qa run --generate 60 --seed 12345` | 94/94 |
| QA (scale) | `klyrshift qa run --generate 200 --seed 999` | 234/234 |
| Flagships | `simulate 'type ghbdtn, space'` etc. | `ghbdtn`→`привет`, `rfr`→`как`, `ltkf`→`дела` |

The QA engine is deterministic: two runs with the same seed produce the same
pass/fail results (only the wall-clock `duration_s` field differs).

## Phase 1 — defects found

Each defect is stated with the measurement that proved it, not a hypothesis.

### D1 — `apply_config` was not atomic (config/cache divergence)

`KlyrshiftDaemon.apply_config` replaced `self.config` and then rebuilt a dozen
derived caches (parsed hotkeys, the exception set, detector tuning, the per-app
layout manager). A failure part-way through left the daemon with the **new**
config while the caches still held the **old** values.

Reproduction (a hand-edited `dictionary_custom_path` with a typo'd `~user` —
`Path.expanduser()` raises `RuntimeError`):

```
config.exceptions_apps -> ["newapp"]   # new
daemon._excepted_apps  -> {"oldapp"}   # old  => mixed state
```

This is reachable from a plain config reload: an exception list that does not
match the config file, hotkeys that do not match the file.

### D2 — an invalid config value escaped as a raw `ValueError`

`klyrshift simulate 'config mode=bogus, …'` printed a Python traceback instead
of the one-line scenario error the CLI is designed to print, because
`Config.validate()` raises `ValueError` and the simulator did not translate it.
The QA executor already classifies such a run as a `harness-error`, so it was
not reported as a product bug — but the CLI path was visibly broken.

```
$ klyrshift simulate 'config mode=bogus, type ghbdtn, space'
ValueError: mode must be one of ('auto', 'manual', 'hybrid')   # traceback
```

### D3 — five more technical tokens leaked into the detector

A broad sweep of real technical tokens (extensions, protocols, MIME types,
config keys) found five that the detector still rewrote into Cyrillic:

| token | rewritten to | |
| --- | --- | --- |
| `cjs` | `соы` | CommonJS module extension |
| `jsx` | `оыч` | JSX module extension |
| `npz` | `тзя` | NumPy archive |
| `pfx` | `зач` | PKCS#12 certificate |
| `tgz` | `епя` | gzip tarball |

None is a word of any shipped language. They are the same class as the tokens
already fixed, and they are not covered by any test.

### D4 — the simulator's undo stack grew without bound

The faithful per-edit undo model (added so `Ctrl+Z` reverts the most recent edit)
took one full screen snapshot per keystroke: a 600-character scenario kept 601
copies, i.e. O(n²) memory over a long run.

```
undo_stack depth after 600 typed chars: 601
total snapshot chars: ~180 000
```

### Not defects (checked, clean)

- **QA determinism** — the generator is seeded (`random.Random(seed)`); two runs
  agree on every result.
- **Manual-mode "late maturation"** — a word kept three times in `manual` mode
  does not count toward promotion; three fresh keeps in `auto` are required.
  Verified hermetically.
- **Snapshot vs. session vocabulary** — the undo snapshot restores the *screen*
  only; it never touches the learned vocabulary, which is correct (an undo is a
  text edit, not a learning event).

## Phase 2 — fixes

All four were fixed test-first (a failing test, then the minimal change).

| Defect | Fix | Test |
| --- | --- | --- |
| D1 | `apply_config` wraps the rebuild in a rollback: on any exception it re-applies the previous config (rebuilding every cache from the known-good object) and re-raises. The rebuild body moved to `_apply_config_inner`. | `tests/test_daemon_robustness.py::test_apply_config_is_atomic_on_a_midway_failure` |
| D2 | The simulator translates `ValueError`/`TypeError` from `validate()`/`apply_config` into a `ScenarioError`. | `tests/test_simulate.py::test_invalid_config_value_raises_a_scenario_error` |
| D3 | The five tokens join the "technical tokens" block of `src/klyrshift/data/stop_words.txt`. | `tests/test_false_positives.py::test_tech_token_corpus_is_never_rewritten` |
| D4 | The simulator caps the undo history at `UNDO_HISTORY_LIMIT` (100) snapshots. | `tests/test_simulate.py::test_undo_stack_is_bounded_for_a_long_typing_run` |

Two QA scenarios were added: `guards/tech-token-corpus-untouched` and
`robustness/config-error-does-not-corrupt`.

## Phase 3 — numbers after the change

| Check | Before | After |
| --- | --- | --- |
| Tests | 1505 passed | 1585 passed |
| Coverage | 85 % | 85 % |
| QA (default) | 94/94 | 96/96 |
| QA (scale) | 234/234 | 236/236 |
| `mypy --strict` / `ruff` / `black` / `isort` | clean | clean |
| Flagships `ghbdtn`/`rfr`/`ltkf` | intact | intact |

## Out of scope (with reasons)

- **The stop-word list is not replaced by a heuristic.** A vowel/consonant or
  length rule was measured to drop real wrong-layout fixes (`rfr`→`как`,
  `lfkj`→`дало`) and the flagship `ghbdtn`→`привет`. The list is the sanctioned
  mechanism; the new canary test guards its coverage.
- **The simulator's undo model stays per-edit, not a full application model.**
  It models what the daemon observes (the chord) and what the screen shows; it
  does not emulate a real editor's coalesced undo groups. Bounded history is the
  correct trade-off.
- **The QA engine is not extended with an LLM provider in the default path.**
  The deterministic, offline run is a CI invariant.
- **No public CLI/API changed.** The only user-visible change is that an invalid
  `config` step now prints a one-line error instead of a traceback, and that five
  more tokens are protected — both documented in `CHANGELOG.md`.

## Phase 4 — release

- **Version bump: `0.2.9` → `0.2.10` (patch).** All changes are bug fixes plus
  internal tooling and documentation; no public CLI or API changed and no new
  feature was added, so a patch bump is correct under semver. Bumped in the five
  places that carry it (`pyproject.toml`, `src/klyrshift/__init__.py`,
  `site/src/consts.ts`, `site/package.json`, `site/package-lock.json`) plus the
  install docs' `.deb` examples, then the man page and shell completion were
  regenerated (`scripts/build_cli_docs.py`) and the handbook rebuilt.

- **Artifact.** `dist/klyrshift_0.2.10_all.deb`
  - `sha256: 23ef1d6a787c17515ad9aa03c5d8aee247621c559c0efc3d066589cabb87185a`
  - Built with `scripts/build_deb.sh` (dpkg-deb, `--root-owner-group`).
  - `Depends:` unchanged and minimal: `python3 (>= 3.10)`,
    `python3-tomli | python3 (>= 3.11)`, `python3-tomli-w`, `python3-evdev`,
    `libnotify-bin`, `wtype`, `librsvg2-common`, `hicolor-icon-theme`.

- **Verified on a clean install** (`scripts/smoke_test.sh`):
  - Debian 12 and Debian 13: `version`, `--help`, `status`, `doctor` all run;
    the daemon dry-run starts and reports the expected hotkeys; the packaged data
    files load; the systemd unit points at the packaged launcher; the udev rule
    grants `uaccess`; `klyrshift verify` matches all 108 files against the
    `md5sums` manifest; `collect-logs` works.
  - `scripts/deb_selfsufficiency_test.sh` passes: the `.deb` installs with no
    manual step, enables autostart itself, and `--purge` leaves no file behind.

- **Final checklist** (all green):
  - `pytest` — 1585 passed, 111 skipped
  - `mypy --strict` / `ruff` / `black --check` / `isort --check-only` — clean
  - `klyrshift qa run` — 96/96
  - `klyrshift qa run --generate 200` — 236/236
  - flagships `ghbdtn`/`rfr`/`ltkf` — intact
  - coverage — 85 %
