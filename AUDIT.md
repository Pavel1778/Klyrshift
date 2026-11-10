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

### D3 — more technical tokens leaked into the detector

A sweep of real technical tokens (extensions, protocols, MIME types, config
keys) found a class that the detector still rewrote into Cyrillic. The sweep is
now **generated from the stdlib `mimetypes` table** (an external, maintained
source) plus a static list, so it is wider than the stop-word file it guards.
It found **thirteen** tokens, all added to the technical-token block:

| token | rewritten to | |
| --- | --- | --- |
| `cjs` | `соы` | CommonJS module extension |
| `jsx` | `оыч` | JSX module extension |
| `npz` | `тзя` | NumPy archive |
| `pfx` | `зач` | PKCS#12 certificate |
| `tgz` | `епя` | gzip tarball |
| `hdf` | `рва` | Hierarchical Data Format |
| `jks` | `олы` | Java KeyStore |
| `cdf` | `сва` | Common Data Format |
| `etx` | `уеч` | Text-encoding extension (borderline: also a control byte) |
| `csh` | `сыр` | C-shell script extension (borderline: also a shell name) |
| `jpe` | `озу` | JPEG variant extension |
| `pbm`, `pnm`, `rtx`, `vcf`, `vtt`, `xbm`, `xlb` | *(garbage)* | misc MIME extensions |

None is a word of any shipped language. `etx` and `csh` are borderline (they
name a control byte and a shell, not only a file extension), but both are real
entries of the stdlib `mimetypes` table and neither is a word of en/ru, so
protecting them is correct; they are marked as borderline in `stop_words.txt`.

**The canary is not a tautology.** The reviewer's concern was that a canary
which iterates over the same list that is now in `stop_words.txt` only proves
"the list is applied". The implemented canary is therefore *wider*: it is built
from the stdlib `mimetypes` extension table plus a static list (**242 tokens**),
minus a documented allowlist of nine extensions that are real words (`so`,
`key`, `log`, `mid`, `img`, `tmp`, `dat`, `bin`, `iso`). Two tests assert the
widening (>= 100 tokens independent of the list, >= 150 total), and the canary is
falsifiable: removing a token from `stop_words.txt` makes it fail by name. This
was verified by hand during the review.

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

## Review follow-ups (round 2)

The first review raised two blockers and four non-blocking items; all are closed.

| Item | Resolution |
| --- | --- |
| **B1 — the canary may be a tautology** | Replaced with a corpus generated from the stdlib `mimetypes` table + a static list (242 tokens), wider than `stop_words.txt`. Two tests pin the widening; the canary fails by name when a token is removed from the list (verified). |
| **B2 — undo behaviour at the cap** | Pinned with four tests: past the cap `Ctrl+Z` still undoes the most recent edit, never deletes below empty, never rolls the vocabulary back, and a scenario with more `Ctrl+Z` than the cap still completes. The cap drops the *oldest* snapshot, so the newest edit is always restorable. |
| 3 — rollback-failure path | `apply_config` restores `self.config` *before* rebuilding the caches and, if the rollback itself fails, logs `"Rollback failed: some caches may still hold values from the rejected configuration"`. Covered by a test (the `pragma: no cover` was removed). |
| 4 — exception translation by type | `_apply_config` now translates **any** exception (by class), not a list of values; the traceback is logged at debug and the original type is named in the `ScenarioError`. A `RuntimeError` test covers it. |
| 5 — upgrade path, not just clean install | New `scripts/patch_upgrade_test.sh` (`make patch-upgrade-test`): installs a 0.2.9 stand-in, then upgrades to 0.2.10 and checks the user config survives unchanged, the unit stays enabled, `klyrshift verify` passes and the CLI works. Passes on Debian 13. |
| 6 — coverage of the new branches | The new branches (rollback, rollback-failure, undo cap, config-error translation) are covered; three small `_apply_config` branches got focused tests. Full suite coverage is unchanged at 85 %. |

## Review follow-ups (round 3)

The second review confirmed both blockers closed and asked for three pre-tag
polish items plus two confirmations; all are done.

| Item | Resolution |
| --- | --- |
| 1 — the report's leak count did not match the list | Corrected. The wider corpus found **13** leaks (`cdf`, `csh`, `etx`, `hdf`, `jks`, `jpe`, `pbm`, `pnm`, `rtx`, `vcf`, `vtt`, `xbm`, `xlb`); the earlier "10" was wrong and the earlier "12" (the reviewer's list) omitted `rtx`. The corpus is **242 tokens**, not 266. Fixed in `AUDIT.md`, `CHANGELOG.md` and `AGENTS.md`. |
| 2 — are `etx` and `csh` intentional? | Yes. Both are real entries of the stdlib `mimetypes` table (verified: `etx in mimetypes.types_map` is `True`, likewise `csh`), so they come from the generated corpus, not a manual addition. Neither is a word of en/ru. They are borderline (a control byte and a shell name) and are now marked as such in `stop_words.txt`. |
| 3 — document "screen and learning are independent", and test the adjacent scenario | The invariant is documented in `AGENTS.md` and `docs/UNDO_CONTRACT.md` (undo restores the *screen*; rejection is a separate signal). The adjacent scenario is pinned: a word rejected three times with `Ctrl+Z` **does not** accumulate keeps (`kept == 0`), the same principle as the manual-mode fix. New test: `tests/test_simulate.py::test_a_rejected_word_never_accumulates_keeps`. |
| patch upgrade on Debian 12 | Run: `UPGRADE_IMAGE=debian:12 bash scripts/patch_upgrade_test.sh` passes (the clean install was already covered on 12 and 13). |
| reproducibility: does the script set `SOURCE_DATE_EPOCH` itself? | Yes, and it is now **cross-environment**. Comparing the CI artifact with a local build exposed two host-dependent differences: the date came from the newest commit (a PR's synthetic merge commit differs from the merge), and dpkg's default compressor changed from xz to zstd in 1.22.x (CI produced `.tar.zst`, a local 1.22.22 `.tar.xz`). `build_deb.sh` now pins `-Zxz` and derives the date from the **release date in `CHANGELOG.md`**, so the same commit builds the identical artifact locally and in CI. `SOURCE_DATE_EPOCH` still overrides. Verified: two consecutive local builds match, and the mechanism no longer depends on the host's dpkg version. |

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
  - `sha256: 6c0a55eac54a825a344a2a529a61cafb6928baaeab84cbd55cb0b10d8a82b58a`
    (byte-reproducible across environments: the compressor is pinned to xz and
    the date comes from the CHANGELOG release date, so this tree builds the
    same artifact locally and in CI. Supersedes the earlier hashes, which
    changed both as the tree changed and because a newer dpkg defaulted to
    zstd.)
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
