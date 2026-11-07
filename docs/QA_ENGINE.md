# QA engine

An autonomous testing layer on top of the existing suite. It drives the real
daemon through the headless simulator (`klyrshift simulate`), checks independent
invariants, classifies failures, minimises them and keeps a regression store.

It is **not** a replacement for the pytest suite and it does **not** talk to
`evdev`/`uinput` or a compositor. It tests the *logic and observable behaviour*
of the daemon, exactly like the simulator does; the real device stack still
needs a desktop (see [TESTING.md](TESTING.md)).

## Run it

```bash
klyrshift qa run                        # the curated corpus, deterministic
klyrshift qa run --generate 50 --seed 7 # + 50 generated scenarios
klyrshift qa run --changed src/klyrshift/daemon.py   # focus on what a change touched
klyrshift qa run --report qa/out        # write qa-report.json and qa-report.md
klyrshift qa run --json                 # the whole report on stdout
klyrshift qa list                       # the regression store
klyrshift qa regress                    # re-check every open regression
```

The default run is offline and deterministic: the same seed and corpus produce
the same report with no network and no API key. The exit code is `0` only when
nothing failed and no scenario broke the harness.

## What it checks

Each scenario names the invariants to check. They are pure functions of the
screen, the replacements and what the user pressed (an independent oracle -- the
typed counts come from the steps, not from the simulator):

| Invariant | What it proves |
|---|---|
| `no-lost-characters` | No Space/Enter/Tab the user pressed disappeared |
| `space-preserved` / `enter-preserved` / `tab-preserved` | The boundary key survived its own fix |
| `punctuation-preserved` | A `.`/`,` is not dropped |
| `manual-mode-silent` | `mode = manual` rewrites nothing without a hotkey |
| `ctrl-z-suppressed` | A `Ctrl+Z` rejection is recorded |
| `no-mixed-script-replacement` | A fix never emits a token mixing Latin and Cyrillic |
| `layout-switched` | A fix left the active layout at its target |
| `no-over-deletion` | A replacement never deletes more than was pressed |
| `screen-matches-expectation` | The screen equals the scenario's `expect.screen` |
| `layout-is-known` | The final layout is one the converter knows |

An invariant never mutates anything, and the engine never changes an assertion
to make a failure go away: a failing invariant is reported, classified and
recorded.

## How a failure is classified

| Class | Meaning |
|---|---|
| `confirmed-bug` | A **structural** invariant failed and it reproduces |
| `suspicion` | Only a hand-written `expect` failed; the expectation may itself be wrong |
| `flaky` | The failure did not reproduce on a second run |
| `harness-error` | The simulator rejected a step (a broken scenario, not a product bug) |

A confirmed bug is minimised by delta-debugging: the engine drops steps (and
trims `type` steps) while the failure signature stays identical, so the minimal
reproduction is the shortest step list that still fails the same way.

## The scenario format

A scenario is JSON data, never code:

```json
{
  "id": "layout/wrong-layout-space",
  "title": "A wrong-layout word is fixed on Space",
  "category": "layout",
  "difficulty": "basic",
  "tags": ["layout", "boundary"],
  "steps": ["type ghbdtn", "space"],
  "config": {},
  "layout": "us",
  "expect": {"screen": "привет "},
  "invariants": ["no-lost-characters", "screen-matches-expectation"],
  "seed": 0,
  "notes": "",
  "origin": "manual"
}
```

The bundled corpus lives in `src/klyrshift/data/qa/scenarios.json`; pass your own
with `--scenarios <file-or-dir>`. A scenario is only ever fed to the simulator's
step parser -- no step is executed as a command.

## Generation and the LLM hook

`klyrshift.qa.generator` produces deterministic scenarios from a seeded grammar
and expands around the curated corpus and the known bug classes. It also maps a
changed source file to the functional areas it affects
(`categories_for_files`), so a run can focus on what a change touched.

An LLM provider is an **optional** input: an object with a `propose(focus, seed)`
method returning step lists. The generator validates every proposal through the
scenario model and drops anything malformed; nothing it returns is executed as
code, and the deterministic run never depends on it.

## The regression store

Confirmed bugs are recorded in `qa/regressions.json`: the original scenario, the
minimal reproduction, the violated invariant and a status. The store is only ever
appended to; a fixed entry is marked `fixed` (by `klyrshift qa regress`) and kept,
never deleted.

## Limits

- It tests the same surface the simulator does: the daemon's logic with a faked
  keyboard, switcher and injector. It cannot prove the real `evdev`/`uinput`
  path or a live compositor.
- The generated scenarios are deterministic, not exhaustive; a green run is
  evidence, not proof.
- The report shows only measured numbers. There is no coverage percentage.

## Tests

`tests/test_qa_engine.py` pins each piece and the end-to-end run, including that
the engine records a structural failure and never invents one on a green corpus.
