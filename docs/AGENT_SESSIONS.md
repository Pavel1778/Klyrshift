# Agent sessions

Klyrshift is developed with automated agents (OpenHands) as well as by hand.
This document records how an agent session works on this repository: how it
starts, how it proves its work with the [self-verification](SELF_VERIFICATION.md)
tools, and how it hands off or resumes after the sandbox is recreated.

Nothing here changes the product; it is process. The rules an agent must not
break are in [AGENTS.md](../AGENTS.md), which is the repository's standing
instruction file and is loaded for every session.

## The session lifecycle

A session runs in four phases. The middle two repeat until the change is done.

### 1. Orient

The sandbox may be freshly recreated, and a previous session may have left work
uncommitted in the tree. Never trust a task description over the repository
state: read the state first.

```bash
git status                 # is the tree clean? what is already changed?
git log --oneline -20      # what landed recently?
git fetch origin && git log --oneline origin/main -5   # is a change already merged?
cat AGENTS.md              # the standing instructions and invariants
cat .openhands/memory/MEMORY.md        # durable project memory
ls .openhands/memory/                  # dated session logs
```

Two failures this phase prevents, both seen in this repository:

- **Re-implementing merged work.** A second session once rebuilt the GUI
  non-blocking fix and T9 support that were already on `main`. A duplicate PR
  was opened and closed. `git fetch` plus `git log origin/main` is the cure.
- **Mistaking uncommitted work for a clean tree.** A sandbox can be recreated
  with a previous session's edits still present but uncommitted. `git status`
  and `git diff` tell you whether you are continuing or starting over.

### 2. Work

Make the change in small, atomic commits. The conventions -- commit prefixes,
the quality bar, the non-ASCII editing rule -- are in
[CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](../AGENTS.md).

### 3. Verify

Never claim a change is done because it "looks right". Run the checks that
answer the question the change raises (see
[SELF_VERIFICATION.md](SELF_VERIFICATION.md)):

```bash
make check                     # ruff + black --check + mypy --strict + pytest --cov
klyrshift qa run --generate 60 --seed 12345   # the deterministic QA engine
```

A GUI change also needs the display-bound suite, because the headless run
*skips* those tests rather than failing them:

```bash
PYTHONPATH=/usr/lib/python3/dist-packages xvfb-run -a pytest tests/ -q \
  --cov=klyrshift --cov-config=coverage-gui.rc --cov-fail-under=85
```

A packaging change also needs the real `.deb` check, which the pytest suite
cannot replace (it fakes the OS boundary):

```bash
make build-deb && make smoke-test
```

An agent must not weaken a check to make it pass. If a test is wrong, fix the
test and say why in the commit; never delete an assertion, skip a test, or lower
a threshold to reach green.

### 4. Record

Two durable records, both written before the session ends:

- **Commit** the change with a conventional message; the code and its test are
  the primary record.
- **Update the memory** under `.openhands/memory/`. `MEMORY.md` holds the
  durable facts (invariants, environment quirks, release state); a dated file
  (`YYYY-MM-DD.md`) holds what this session did. The memory is how the next
  session -- in a new sandbox -- learns what the last one found.

## Restart and hand-off

A session can end at any time: the sandbox is recreated, the context is
compacted, or the work passes to another agent. The restart procedure is the
same whether a human or an agent resumes.

### What survives, and where

| State | Lives in | Survives a sandbox restart |
|---|---|---|
| Committed code and tests | git (pushed to `origin`) | yes |
| Uncommitted edits | the working tree | **no** -- lost with the sandbox |
| Durable project facts | `.openhands/memory/MEMORY.md`, `AGENTS.md` | yes (committed) |
| Session notes | `.openhands/memory/YYYY-MM-DD.md` | yes (committed) |
| Environment setup (venv, GTK, xvfb) | the container | **no** -- re-install if needed |

The consequence: **commit early, and push before the sandbox is at risk.** Work
that exists only in the working tree is not durable.

### The restart checklist

1. `git status` and `git diff` -- is there uncommitted work to keep or discard?
2. `git fetch origin` and compare with `origin/main` -- did a parallel session
   land the same change? If the tree matches `origin/main`, reconcile with
   `git reset --hard origin/main` only after confirming `git diff --stat main
   origin/main` is empty.
3. Read `AGENTS.md` and the newest `.openhands/memory/*.md` entries -- the
   invariants and the last session's findings.
4. Re-establish the environment if the checks need it (see below).
5. Re-run the relevant check (`make check`, the GUI job, the QA engine) before
   continuing, so you know the starting point is green.

### Re-establishing the environment

The container is not preserved across a restart, so tools installed by a
previous session may be gone. What the checks need:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # or: bash scripts/dev_setup.sh
```

The GUI suite additionally needs a display and the distribution PyGObject
(`python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`) plus
`xvfb`; the `.deb` checks need Docker. The `docs` extra
(`weasyprint`, `markdown`) is needed only to rebuild the handbook.

One environment quirk that looks like a code bug: the container's
`LD_LIBRARY_PATH` can make the `/usr/local` Python segfault on `import ctypes`
(so `import evdev`, `black` and pytest all die with `SIGSEGV`). Run the command
under `env -u LD_LIBRARY_PATH` when that happens; it is the environment, not the
code.

### Avoiding a duplicate session

Two agents can work the same repository at once, and a clean textual merge is
not proof of a clean change. Before starting a task:

- `git fetch` and check `origin/main` and the open pull requests for work that
  already covers it.
- If two branches touched the same widget, re-run the **GUI** suite under
  `xvfb-run` after merging, not only the headless suite -- a semantic conflict
  (a method that reads a renamed attribute) merges without a conflict marker and
  only fails at run time.

## What an agent may and may not do

- An agent verifies with the tools above; it does not assert success without
  running them.
- The privacy and security invariants in [AGENTS.md](../AGENTS.md) are absolute
  and are guarded by `tests/test_privacy_audit.py`: the daemon never writes
  typed text to disk, and no log line may print a user's word.
- Do not push to the remote or open a pull request unless asked; when asked,
  open one pull request per issue and update it rather than opening another.
- A "fix" that silences a check instead of addressing the cause is not a fix.
  The QA engine and the pytest suite are there to catch exactly that.

## See also

- [SELF_VERIFICATION.md](SELF_VERIFICATION.md) -- the simulator and the QA engine.
- [TESTING.md](TESTING.md) -- all testing levels, including the manual desktop plan.
- [CONTRIBUTING.md](CONTRIBUTING.md) -- the quality bar and commit conventions.
- [AGENTS.md](../AGENTS.md) -- the standing repository instructions.
