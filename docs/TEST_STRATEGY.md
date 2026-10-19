# Test strategy

How Klyrshift is tested, which numbers are tracked, and how a change is judged.
This complements [TESTING.md](TESTING.md), which describes the three levels and
the manual desktop plan; this document covers the *quality metrics* and the
regression thresholds.

## Layers

| Layer | Tool | Runs in CI | Proves |
|---|---|---|---|
| Lint / types | `ruff`, `isort`, `black --check`, `mypy --strict` | Yes | Style, imports, type soundness |
| Unit / integration | `pytest`, coverage floor 80 % | Yes | Logic, parsing, config, conversion, daemon policy |
| Detector quality | `scripts/measure_detector.py` | Manually | Recall, false positives, corruption, speed on fixed corpora |
| Package smoke | `scripts/smoke_test.sh` | Yes | The built `.deb` installs and its entry points run |
| Manual desktop | `docs/TESTING.md` level 3 | No | Permissions, D-Bus, `uinput`, real applications |

Tests replace the OS boundary (evdev, GTK, `uinput`) with fakes but always run
real project code. There are no mocks of Klyrshift's own modules.

## Detector metrics

`scripts/measure_detector.py` measures four numbers on a fixed slice of the
shipped corpora. **Only identical slices with identical conditions are
comparable**; a top-1000 run and a top-3000 run are different measurements.

| Metric | Definition | Want |
|---|---|---|
| Recall | share of target-language words typed on the wrong layout that are sent back | high |
| Missed | the complement of recall | low |
| False positives | real, correctly-typed words that would still be moved (a wrong fix) | **0** |
| Corruption | conversions where a character is lost or mangled | **0** |
| ms/word | processing time per word | flat or lower |

```bash
PYTHONPATH=src python scripts/measure_detector.py --limit 1000
PYTHONPATH=src python scripts/measure_detector.py --limit 3000
```

### Recorded baseline

Measured on the current tree, Debian 13, Python 3.13:

| Slice | Direction | Recall | False pos. | Corruption | ms/word |
|---|---|---|---|---|---|
| top 1000 | ru on us | 92.8 % | 0.0 % | 0 | 0.008 |
| top 1000 | en on ru | 95.1 % | 0.0 % | 0 | 0.008 |
| top 3000 | ru on us | 93.6 % | 0.0 % | 0 | 0.008 |
| top 3000 | en on ru | 97.3 % | 0.0 % | 0 | 0.008 |

The residual miss rate on short words (1–2 characters) is expected: they carry
almost no statistical signal and are skipped by `min_word_length`.

## Regression thresholds

A change must not:

- introduce a false positive or a corruption (both must stay at **0**);
- lower recall on a recorded slice by more than 0.5 percentage points;
- raise `ms/word` by more than 20 % on a recorded slice;
- drop coverage below the 80 % CI floor;
- turn a passing test into a skip.

Improving one metric at the cost of another must be stated explicitly in the PR.
An "improvement" that trades a false positive for recall is a regression.

## Adding a regression test

Every defect fixed gets a test that fails before the fix and passes after. The
test is named for the behaviour, not the change, and it asserts on the same
surface the user saw (the replacement list, the buffer, the history), not on an
internal counter that could drift.

Example: the stale-undo defect (a fix restored after the user typed new text)
is covered by `tests/test_undo_suppression.py`, which asserts the second
replacement never happens.

## What the automated suite cannot prove

- That real applications accept the synthetic keystrokes.
- That `uinput` and `/dev/input` are reachable under the user's session.
- That layout switching works through `g3kb-switch` on the installed GNOME.
- That the GTK4 GUI renders (needs a display).

These require `docs/TESTING.md` level 3 on a real machine and are the reason the
platform matrix in [PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md) marks those rows
as unverified rather than supported.
