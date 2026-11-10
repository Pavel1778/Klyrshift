# Self-verification

How Klyrshift checks itself without a keyboard. The daemon reads `/dev/input`
through `evdev` and injects through `uinput`, so exercising it end to end
normally needs a real desktop. Two tools make the *logic* verifiable anywhere --
on a laptop, in CI, or by an automated agent:

- **`klyrshift simulate`** -- a headless simulator that drives the **real**
  daemon with a faked keyboard, layout switcher and text injector, and prints
  what the user would see.
- **`klyrshift qa`** -- an autonomous QA engine that runs many scenarios through
  the simulator, checks independent invariants and records confirmed bugs.

They sit on top of the pytest suite; none of them replaces it, and none of them
reaches the kernel input path. [TESTING.md](TESTING.md) describes all levels of
testing, [QA_ENGINE.md](QA_ENGINE.md) is the engine reference, and
[TEST_STRATEGY.md](TEST_STRATEGY.md) records the metrics.

## The questions a change must answer

| Question | Answered by | Runs in CI |
|---|---|---|
| Does the logic still behave? | `pytest` (faked OS boundary) | yes |
| Does the daemon still behave end to end, as a user would see it? | `klyrshift simulate` + `klyrshift qa run` | yes (the `qa` job) |
| Does the *package* still work on a clean machine? | `scripts/smoke_test.sh`, `scripts/deb_selfsufficiency_test.sh`, `scripts/upgrade_test.sh` | yes (release) |
| Does it work on a real keyboard and compositor? | `scripts/acceptance_check.sh` + [TESTING.md](TESTING.md) level 3 | **no** -- needs a desktop |

The first two are the self-verification story: the daemon is real, only the
boundaries are faked, so a regression in the correction logic fails a check
without a keyboard.

## The headless simulator

`klyrshift simulate '<scenario>'` builds a real daemon wired to in-process
fakes -- a fake keyboard that emits the events a key press would, a fake
switcher that tracks the active layout, and a fake injector that records each
replacement and applies it to a model of the screen. The daemon code that
decides *what* to fix is the shipped code, unchanged.

Because the injector renders the screen, a scenario asserts **what the user
would see**, not just the raw replacement calls:

```bash
klyrshift simulate 'type ghbdtn, space'
# Экран: привет
# Режим: auto · раскладка: ru
#   замена −7 +'привет ' @ru

klyrshift simulate --json 'type ghbdtn, space'   # machine-readable
```

A scenario is a comma-separated list of steps:

| Step | Meaning |
|---|---|
| `type <text>` | press the physical keys that produce `text` on a US keyboard |
| `<key>` | a named key: letters, digits, punctuation by name (`dot`, `comma`, `minus`, `slash`, ...) and `space`/`enter`/`tab`/`backspace`/`esc`/arrows/`f1`..`f24` |
| `ctrl+z` | a chord (`ctrl`, `shift`, `alt`, `super` + a key) |
| `dblshift` / `dblctrl` / `dblalt` | a double-tapped modifier |
| `layout <name>` | set the active layout |
| `mode <auto\|manual\|hybrid>` | set the correction mode |
| `app <name>` | pretend that application is focused |
| `config key=value; ...` | override configuration |
| `wait` | the idle flush |

`type` presses keys by **position**, so the active layout decides the glyphs on
screen -- that is how a wrong-layout word (`ghbdtn` on the US layout, meaning
`привет`) is reproduced. The same command is available to a person and to an
agent; it is the smallest unit of self-verification.

## The autonomous QA engine

`klyrshift qa run` feeds a corpus of scenarios to the simulator, checks
invariants over each result, classifies failures, minimises the reproduction and
records confirmed bugs. It is deterministic and offline: the same seed and
corpus produce the same report with no network and no API key.

```bash
klyrshift qa run                                  # the curated corpus
klyrshift qa run --generate 60 --seed 12345       # + generated scenarios (what CI runs)
klyrshift qa run --changed src/klyrshift/daemon.py  # focus on what a change touched
klyrshift qa run --report qa/out                  # qa-report.json + qa-report.md
klyrshift qa list                                 # the regression store
klyrshift qa regress                              # re-check every open regression
```

### The independent oracle

An invariant is a pure function of the screen, the replacements and **what the
user pressed**. The typed counts (`typed_separators`, `typed_punctuation`,
`typed_chars`) are computed from the *steps*, not from the simulator, so they
are an independent oracle: the check does not ask the daemon whether the daemon
is right.

| Invariant | What it proves |
|---|---|
| `no-lost-characters` | no Space/Enter/Tab the user pressed disappeared |
| `space-preserved` / `enter-preserved` / `tab-preserved` | the boundary key survived its own fix |
| `punctuation-preserved` | a `.`/`,` is not dropped |
| `manual-mode-silent` | `mode = manual` rewrites nothing without a hotkey |
| `ctrl-z-suppressed` | a `Ctrl+Z` rejection is recorded |
| `no-mixed-script-replacement` | a fix never emits a token mixing Latin and Cyrillic |
| `layout-switched` | a fix left the active layout at its target |
| `no-over-deletion` | a replacement never deletes more than was pressed |
| `screen-matches-expectation` | the screen equals the scenario's `expect.screen` |
| `layout-is-known` | the final layout is one the converter knows |

The first eight are **structural**: a failure is a confirmed bug. The last two
compare against a hand-written expectation, so a mismatch is only a
*suspicion* -- the expectation itself may be wrong.

### Classification and minimisation

| Class | Meaning |
|---|---|
| `confirmed-bug` | a structural invariant failed and it reproduces |
| `suspicion` | only a hand-written `expect` failed |
| `flaky` | the failure did not reproduce on a second run |
| `harness-error` | the simulator rejected a step (a broken scenario, not a product bug) |

A confirmed bug is minimised by delta-debugging: steps (and `type` steps) are
dropped while the failure signature stays identical, so the recorded
reproduction is the shortest step list that still fails the same way.

### Safety of the corpus

A scenario is **JSON data, never code**. The engine feeds it only to the
simulator's fixed step parser, so no step -- including one an optional LLM
provider proposes -- can execute a command. A malformed proposal is dropped, and
the deterministic run never depends on a provider.

## Where the pieces live

| Path | Role |
|---|---|
| `src/klyrshift/simulate.py` | the simulator and its step DSL |
| `src/klyrshift/qa/scenario.py` | the scenario model |
| `src/klyrshift/qa/invariants.py` | the independent checkers |
| `src/klyrshift/qa/executor.py` | runs a scenario through the simulator |
| `src/klyrshift/qa/generator.py` | deterministic seeded generation |
| `src/klyrshift/qa/analyzer.py` | classification and minimisation |
| `src/klyrshift/qa/store.py` | the append-only regression store |
| `src/klyrshift/qa/runner.py`, `src/klyrshift/qa/report.py` | orchestration and reporting |
| `src/klyrshift/data/qa/scenarios.json` | the curated corpus |
| `tests/test_simulate.py`, `tests/test_qa_engine.py` | the guards for both |

CI runs `klyrshift qa run --generate 60 --seed 12345 --no-record --report qa-out`
in the `qa` job on every push and pull request, and uploads the report. Keep it
offline: an LLM call in the default path would make CI depend on the network.

## What this cannot prove

The simulator and the QA engine test the same surface: the daemon's logic with a
faked keyboard, switcher and injector. Neither reaches the kernel. They cannot
prove that

- real applications accept the synthetic keystrokes;
- `/dev/input` and `/dev/uinput` are reachable under the user's session;
- layout switching works through `g3kb-switch` on the installed GNOME;
- the GTK4 window renders (needs a display).

Those require [TESTING.md](TESTING.md) level 3 on a real machine --
`scripts/acceptance_check.sh` automates what a script can check there -- and
they are why [PLATFORM_SUPPORT.md](PLATFORM_SUPPORT.md) marks those rows
unverified rather than supported.

## See also

- [TESTING.md](TESTING.md) -- the manual desktop plan and the package smoke test.
- [QA_ENGINE.md](QA_ENGINE.md) -- the QA engine in detail.
- [TEST_STRATEGY.md](TEST_STRATEGY.md) -- metrics and regression thresholds.
- [AGENT_SESSIONS.md](AGENT_SESSIONS.md) -- how an agent session uses these tools.
