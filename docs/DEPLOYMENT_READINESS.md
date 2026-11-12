# Deployment readiness

This document answers one question: **is Klyrshift ready to deploy and use?**
It is an *evidence* record, not a restatement of the guides. Every row is a
command that was run on this tree and its actual output; anything that could not
be run here is listed under [what this host cannot check](#3-what-this-host-cannot-check)
rather than claimed.

Verified tree: commit `e27806b` (`main`, version **0.2.10**), host
Debian 13 (trixie), Python 3.13.15. Re-run the commands to reproduce.

**Verdict: ready.** The package installs and runs on clean Debian 12 and 13,
every check the repository documents is green, and the only open items are a
known QA-tooling defect that does not touch the shipped product and the
un-testable real-device path (both pre-existing and documented).

## 1. Checks that passed

| Check | Command | Result |
|---|---|---|
| Linter | `ruff check .` | `All checks passed!` |
| Import order | `isort --check-only .` | clean |
| Format | `black --check .` | 178 files unchanged |
| Types | `mypy --strict .` | `Success: no issues found in 174 source files` |
| Tests (headless) | `pytest tests/ -q --cov=klyrshift` | **1793 passed, 107 skipped**, coverage **85 %** |
| Tests (strongest: GUI under xvfb) | `PYTHONPATH=/usr/lib/python3/dist-packages KLYRSHIFT_RENDER_TEST=1 xvfb-run -a pytest tests/ -q --cov=klyrshift --cov-config=coverage-gui.rc --cov-fail-under=85` | **1899 passed, 1 skipped**, coverage **85.82 %** |
| Autonomous QA | `klyrshift qa run --generate 60 --seed 12345 --no-record` | **96 checked, 96 passed, 0 harness errors**, exit 0 |
| Detector benchmark | `python3 scripts/measure_detector.py` | ru→us recall 92.8 %, en→ru 95.1 %, **0 false positives, 0 corruption** |
| Latency / memory | `python3 scripts/measure_latency.py --limit 3000 --repeats 2` | 0.0130 / 0.0099 ms per word, **4.3 MiB** peak |
| Version consistency (tree) | `python3 scripts/release_consistency.py --source` | `ok` |
| Version consistency (published) | `python3 scripts/release_consistency.py --latest` | `ok` — published `v0.2.10`, 22 assets |
| `.deb` build | `bash scripts/build_deb.sh` | `dist/klyrshift_0.2.10_all.deb` |
| `.deb` reproducibility | build twice, `cmp` | **byte-identical** (`sha256 79e710a8…`) |
| Integrity manifest | `dpkg-deb -R … && md5sum -c DEBIAN/md5sums` | **108 files, all OK**, covers exactly the packaged files |
| Package smoke (Debian 12) | `bash scripts/smoke_test.sh` | `Smoke test passed.` |
| Package smoke (Debian 13) | `SMOKE_IMAGE=debian:13 bash scripts/smoke_test.sh` | `Smoke test passed.` |
| Zero-config install (Debian 12) | `bash scripts/deb_selfsufficiency_test.sh` | passed |
| Zero-config install (Debian 13) | `SMOKE_IMAGE=debian:13 bash scripts/deb_selfsufficiency_test.sh` | passed |
| Upgrade from `linguafix` (Debian 13) | `bash scripts/upgrade_test.sh` | passed — old package gone, config and mode survive |
| Landing page | `cd site && npm ci && npm run build` | 2 pages built |
| Interface locales | `klyrshift --lang ru/en/de/fr/uk status` | all five answer |
| Flag-fix scenario | `klyrshift simulate 'type ghbdtn, space'` | screen becomes `привет`, layout `ru` |

The `.deb` is **zero-config**: `apt install ./klyrshift_0.2.10_all.deb` grants
device access through the udev `uaccess` rule and enables the user unit globally
in `postinst` — no `usermod`, no re-login, no manual `systemctl --user enable`.
The zero-config tests assert exactly this on both target images, and the upgrade
test proves a machine that already had the pre-rename `linguafix` package ends
with only `klyrshift`, one enabled unit and its settings preserved.

## 2. Open items (pre-existing, not blocking)

Neither of these is a regression introduced by this verification; both were
already recorded and are repeated here so the readiness picture is complete.

- **QA-engine splitter defect.** `qa/executor.build_script` joins steps with
  `", "` while `simulate.run_scenario` splits on `","`, so a `config` step with a
  **two-or-more-element** list/dict is shredded and rejected. It reproduces:
  `klyrshift simulate 'config exceptions_apps=[kitty, code], …'` →
  `Ошибка сценария: unknown key 'code]'`. This is a defect in the *QA tooling*,
  not in the shipped daemon: the default QA run and the curated corpus are green,
  and the simulator's own step parser is unaffected for hand-written scripts. The
  cause and a recommended fix are in
  [AUTOPROGRESS_BREAKAGE.md](AUTOPROGRESS_BREAKAGE.md).
- **Stale prose snapshots.** A few counts in the snapshot guides lag the tree
  (`docs/WORK_REPORT.md` "19 руководств" → 24 guides, "333 коммита" → 337;
  `docs/PROJECT_STRUCTURE.md` "88 modules" → 90 test modules;
  `docs/ROADMAP.md` "1300+ tests" → 1900). These are historical snapshots with
  no test pinning them; they are cosmetic and do not affect the product.

## 3. What this host cannot check

These are boundaries of the stand, identical to
[PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md) and [TESTING.md](TESTING.md) — not
defects:

- **The real `evdev` → `uinput` path and a live compositor.** There is no
  graphical session or input device here; only the logic is exercised, through
  the simulator.
- **`g3kb-switch`** (Wayland layout switching) is not in the Debian archive and
  is not installed; it stays a `Recommends`, with `setxkbmap` as the fallback.
- **A real desktop** (editors, browsers, terminals) — the manual plan in
  [TESTING.md](TESTING.md) and `scripts/acceptance_check.sh` cover it on the
  target machine.

## 4. How to reproduce

```bash
bash scripts/dev_setup.sh                     # venv + dev dependencies
make check                                    # ruff + isort + black + mypy + pytest --cov
make qa                                       # autonomous QA (offline)
make build-deb                                # reproducible .deb
make smoke-test                               # install it in a clean debian:12
SMOKE_IMAGE=ubuntu:22.04 make smoke-test      # Python 3.10 path (tomli)
make zero-config                              # prove the .deb needs no manual step
```

For the strongest local run (needs a display and `python3-gi`):

```bash
sudo apt install -y xvfb python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
PYTHONPATH=/usr/lib/python3/dist-packages KLYRSHIFT_RENDER_TEST=1 \
  xvfb-run -a pytest tests/ -q --cov=klyrshift --cov-config=coverage-gui.rc --cov-fail-under=85
```

## 5. Conclusion

Klyrshift 0.2.10 is **ready for deployment and usage**: the `.deb` installs
zero-config on Debian 12 and 13, upgrades cleanly from the pre-rename package,
and every automated gate (lint, types, tests, QA, detector, packaging, site,
i18n) is green. The two open items above are a QA-tooling defect that does not
reach users and stale prose in snapshot documents; neither blocks a release.
