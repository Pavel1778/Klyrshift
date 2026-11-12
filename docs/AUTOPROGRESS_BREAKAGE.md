# Why the automated run breaks

An investigation into "почему автопрогон ломается" (why the auto-run breaks),
performed with the project's own tooling: the headless simulator
(`klyrshift simulate`) and the autonomous QA engine (`klyrshift qa run`).

This document records what was measured, the defect that reproduces, its root
cause, the blast radius, and the recommendations. It changes no product code;
the fix is proposed, not applied.

## 0. What "автопрогон" is in this repository

The word is ambiguous, so the investigation started by pinning it down. In
Klyrshift the *automated* (unattended) run is the autonomous QA engine:

- `klyrshift qa run` — the documented "Autonomous QA" engine
  ([QA_ENGINE.md](QA_ENGINE.md)); it drives the real daemon through the
  simulator, checks independent invariants, classifies failures, minimises them
  and records regressions.
- the CI job `Autonomous QA (deterministic, offline)` (`.github/workflows/ci.yml`)
  runs exactly `klyrshift qa run --generate 60 --seed 12345 --no-record`.

(The literal phrase "Автономный прогон" is the NEXUS orchestrator's term for one
of *its* runs against this repository; that machinery lives in another project
and is out of scope here. The only automated run that is part of Klyrshift is
the QA engine above, and it is where the breakage reproduces.)

A run is "broken" when it reports a `harness-error` (a scenario the simulator
rejects) and the CLI exits non-zero, which fails the CI job. That is what
happens below.

## 1. Summary

| | |
| --- | --- |
| Symptom | A QA run aborts with `harness-error: scenario rejected by the simulator: unknown key '...'` and exits `1` (CI red). |
| Where | `src/klyrshift/qa/executor.py` (`build_script`) against `src/klyrshift/simulate.py` (`run_scenario`). |
| Trigger | Any scenario whose `config` has a **list or dict with more than one element**. |
| Root cause | The script builder joins steps with `", "`, but the simulator splits the script on `","`. The commas *inside* a rendered `[a, b]` list or `{k: v}` dict are indistinguishable from step separators, so one step is shredded into several bogus steps. |
| Status | Reproducible on the current `main` (HEAD `2a296d0`). Not covered by any test. |

## 2. Reproduction

The smallest reproduction uses the engine's own public surface.

```python
from klyrshift.qa.executor import build_script
from klyrshift.qa.scenario import Scenario
from klyrshift.simulate import run_scenario, ScenarioError

s = Scenario(id="per-app/two", steps=["type ghbdtn", "space"],
             config={"exceptions_apps": ["kitty", "code"]})
script = build_script(s)
# -> 'config exceptions_apps=[kitty, code], type ghbdtn, space'

script.split(",")
# -> ['config exceptions_apps=[kitty', 'code]', 'type ghbdtn', 'space']

run_scenario(script)
# ScenarioError: unknown key 'code]'
```

The same happens from the CLI with a scenario file:

```
$ klyrshift qa run --scenarios two-apps.json --no-record
QA: проверено 37, успешно 36, провалов 0, ошибок стенда 1
$ echo $?
1
```

and directly through the simulator, whose docstring advertises the list form
(`config key=value; ... [a, b] lists and {k: v} dicts are parsed`):

```
$ klyrshift simulate 'config exceptions_apps=[kitty, code], space'
ScenarioError: unknown key 'code]'
```

### Which shapes break

| `config` value | Rendered step | Result |
| --- | --- | --- |
| `{"exceptions_apps": ["kitty"]}` | `config exceptions_apps=[kitty]` | ok |
| `{"exceptions_apps": ["kitty", "code"]}` | `config exceptions_apps=[kitty, code]` | **harness-error** |
| `{"app_modes": {"code": "manual"}}` | `config app_modes={code: manual}` | ok |
| `{"app_modes": {"code": "manual", "chat": "auto"}}` | `config app_modes={code: manual, chat: auto}` | **harness-error** |
| `{"app_layouts": {"code": "us", "chat": "ru"}}` | `config app_layouts={code: us, chat: ru}` | **harness-error** |

A single-element list or dict happens to survive; **any two-or-more-element
list/dict does not**. The failure is silent in the sense that the engine
classifies it as a `harness-error` (a "broken scenario"), not as a product bug —
so the run does not invent a false bug, but it *does* fail, and the scenarios
that exercise multi-entry per-app configuration can never run at all.

## 3. Root cause

Two functions disagree about the separator:

- `src/klyrshift/qa/executor.py`:

  ```python
  def _render_value(value):
      ...
      if isinstance(value, list):
          return "[" + ", ".join(str(item) for item in value) + "]"
      if isinstance(value, dict):
          return "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
      return str(value)

  def build_script(scenario):
      parts = _config_steps(scenario) + list(scenario.steps)
      return ", ".join(parts)
  ```

  It uses `", "` both as the *step* separator and as the *intra-list/dict*
  separator.

- `src/klyrshift/simulate.py`:

  ```python
  for raw_step in scenario.split(","):
  ```

  It splits on a bare `","` with no notion of nesting.

Because the two separators are the same character, a rendered
`[kitty, code]` becomes two steps, `config exceptions_apps=[kitty` and
`code]`, and the second is rejected as an unknown key.

The design intent is visible and inconsistent: `_coerce` in the simulator
explicitly parses `[a, b]` and `{k: v}`, and `test_qa_engine.py` asserts the
builder *emits* `[a, b]` and `{code: manual}` — but nothing ever feeds that
output back through the parser, so the mismatch was never exercised.

## 4. Why the test suite does not catch it

`tests/test_qa_engine.py::test_build_script_renders_lists_and_dicts` checks the
*string* the builder produces, never that the simulator can run it:

```python
script = build_script(Scenario(id="x", steps=["space"],
    config={"stop_words": ["a", "b"], "app_modes": {"code": "manual"}}))
assert "[a, b]" in script
assert "{code: manual}" in script
```

That test passes while the very input it builds is unrunnable. It gives false
confidence: the renderer is "tested", the parser is "tested", but the seam
between them is not.

The curated corpus does not trigger it either: 36 scenarios, exactly one with a
non-empty `config`, and that one has a **single-element** list
(`per-app/exception-applies-immediately` → `{"exceptions_apps": ["myapp"]}`),
which survives by luck. The deterministic generator only ever emits scalar
config (`on_tab=True`, `on_punctuation=True`), so `--generate N` never reaches
the broken shape. The default run is therefore green; the defect only appears
once a scenario (hand-written, LLM-proposed, or a future curated one) carries a
two-element list or dict.

## 5. Blast radius

- **The QA engine (`klyrshift qa run`).** Any scenario with a multi-entry
  per-app config (`exceptions_apps`, `app_modes`, `app_layouts`) is a
  `harness-error`; the CLI exits `1`. The `qa` CI job fails for such a run.
- **`klyrshift simulate` (the CLI and `python -m klyrshift.simulate`).** The
  documented `[a, b]` / `{k: v}` config form is unusable with more than one
  entry.
- **The `--scenarios <file>` input path.** A user-supplied corpus (or an
  LLM-proposed one, which the generator validates as *data* and then hands to
  the same builder) hits it immediately.
- **Not affected:** the curated corpus as shipped, the deterministic generator,
  and the default CI invocation. That is precisely why it has gone unnoticed.

A related, lower-severity sharp edge sits on the same seam: a literal comma
inside a `type` step is also a step separator, so `type hello, world` is parsed
as `type hello` + a bogus `world` step (`ScenarioError: unknown key 'world'`),
and `type a,b` silently types only `ab`. This is a property of the
comma-separated DSL, not of the config renderer, but it is the same class of
"the separator is overloaded" defect and is worth noting when the DSL is
touched.

## 6. Recommendations

Ordered by value; the first is the actual fix.

1. **Make the script separator unambiguous (primary fix).** Teach the
   simulator's splitter to ignore separators inside `[ ... ]` / `{ ... }`, so a
   rendered list/dict stays one step. This is a small, self-contained change in
   `simulate.run_scenario` (track bracket depth while splitting) and fixes both
   the QA engine and the `simulate` CLI at once, with no change to the scenario
   format. Verified locally: with a bracket-aware split, the three broken shapes
   above all run to `привет ` and a plain `type ghbdtn, space` is unchanged.

   *Alternative:* give the config renderer a separator the DSL does not use
   (e.g. `|` or `;` inside lists/dicts) and teach `_coerce` to accept it. This
   touches two places and changes the on-the-wire script text; the splitter fix
   is smaller and keeps the documented `[a, b]` syntax.

2. **Close the test gap at the seam (do this with the fix).** Replace the
   string-only assertion with an end-to-end one: build the script for a scenario
   with a two-element list and a two-element dict, run it through
   `run_scenario`, and assert the screen (not the string). Add at least one
   curated scenario with a multi-entry `exceptions_apps` so the shipped corpus
   exercises the path. The existing test should stay, but it must not be the
   only guard.

3. **Reject an unrunnable step at build time, not at run time.** `build_script`
   could round-trip its own output through the simulator's parser and raise a
   `ScenarioFormatError` naming the scenario if a step does not survive. That
   turns a `harness-error` in the middle of a run into a clear, early failure.

4. **Consider the `RunConfig.repeats` dead knob (unrelated, found while
   reading).** `RunConfig.repeats` is documented as "how many times a failing
   scenario must reproduce", but nothing reads it: `runner.run` calls
   `analyse(...)` which calls `reproduces(scenario)` with the hard-coded
   default `runs=2`. Either wire the knob through or delete it; a knob that
   silently does nothing is a trap for the next reader.

5. **Note the comma-in-`type` limitation in the DSL docs** (`simulate` module
   docstring and [QA_ENGINE.md](QA_ENGINE.md)) so a scenario author knows a
   literal comma cannot appear in typed text, or extend the DSL to escape it.

## 7. What was checked and is clean

- `pytest tests/` — 1776 passed, 111 skipped (the defect is real but uncovered).
- `ruff check .`, `black --check .`, `isort --check-only .` — clean.
- `klyrshift qa run --generate 60 --seed 12345` — 96/96 (the default path).
- 30 seeds × `--generate 120` — 0 failures, 0 harness errors (the generator
  never emits the broken shape).
- The curated corpus — all 36 scenarios' built scripts run without a harness
  error.
- QA determinism — two runs of the same seed agree on every field except the
  wall-clock `duration_s`.
