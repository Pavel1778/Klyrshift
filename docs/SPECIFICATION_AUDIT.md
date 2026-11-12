# Specification audit — nothing declared, nothing left unaddressed

The task behind this document is "Ок, что уже готово?" — *what is already
built?* [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) answers that by running
every check the repository documents. This document answers the follow-up: is
any *declared specification* still unaddressed — a setting the user can toggle,
a knob the code documents, or a claim a document makes, that no code honours?

The method is mechanical, not a reading: the specification surface is the set of
**user-visible settings** (`Config` fields, GUI switches, CLI options) and
**documented claims**. Each item is checked for a reader — an attribute read
somewhere outside `config.py`, or a call path that consumes it. An item with no
reader is an *unused specification*: the user changes it and nothing happens.

Everything found was addressed in the same change, and
`tests/test_spec_coverage.py` now pins the result so the class of defect cannot
return silently.

## 1. The specification surface

| Surface | Where it lives | Count | How it was checked |
|---|---|---|---|
| Configuration fields | `Config` in `src/klyrshift/config.py` | 90 | attribute read outside `config.py` |
| GUI settings rows | `gui/*_page.py` (`add_switch`/`add_spin`/`add_combo`) | — | the field each row binds by name |
| CLI options | `build_parser()` in `src/klyrshift/cli.py` | 39 | read as `args.<dest>` |
| QA knobs | `qa.runner.RunConfig` | 8 | attribute read in `qa/` |
| Documented claims | `docs/*.md`, `README.md` | — | the code path each names |

## 2. Unused specifications found

### 2.1 `notify_on_error` — a switch that notified nothing

`Config.notify_on_error` is exposed as a GUI switch («Уведомлять об ошибке») and
documented in the help topic, but **no code read it**: the daemon never called a
notification on a failure. The user could turn it on and nothing would ever
happen.

**Addressed.** The daemon now calls `_notify_error()` on its failure paths — a
survived key-event exception, a survived buffer-processing exception, and a
failed undo replacement. The notification body is a fixed label
(«Не удалось исправить раскладку»), never the typed text, so the privacy
contract in [OFFLINE_AND_PRIVACY.md](OFFLINE_AND_PRIVACY.md) still holds.

### 2.2 `sound_on_fix` — a switch that played nothing

`Config.sound_on_fix` is exposed as «Звук при исправлении» and documented
("Показывать уведомление или звук при исправлении"), but **no code read it**
either: the daemon only ever called `notify-send`.

**Addressed.** A completed fix now goes through `_announce_fix()`, which fires
the notification and/or the sound independently. The sound uses
`canberra-gtk-play -i bell` (from `gnome-session-canberra`, the standard way to
ask the session for an event sound); when it is absent the call is a no-op, so a
missing player degrades to silence rather than an error.

### 2.3 `log_rotation_mb` — a spin that set nothing

`Config.log_rotation_mb` is exposed as the «Ротация, МБ» spin (1–50 MB) and
documented in the logs help topic, but the log handler was hard-coded to
`MAX_BYTES = 5 * 1024 * 1024`. The user could set 1 or 50 and the file always
rotated at 5 MB.

**Addressed.** `logging_setup.setup_logging` takes a `rotation_mb` argument and
uses it for the handler's `maxBytes`; both callers pass it — `cmd_start`
(foreground) passes `config.log_rotation_mb`, and the GUI entry point passes the
same value for `gui.log`. The value is clamped to at least 1 MB so a nonsensical
setting cannot produce a zero-byte cap.

### 2.4 `RunConfig.repeats` — a dead knob

`qa.runner.RunConfig.repeats` is documented ("How many times a failing scenario
must reproduce to count as a confirmed bug") but **nothing read it**:
`runner.run` → `analyse` → `reproduces(scenario)` with a hard-coded `runs=2`.
This was already recorded as a known discrepancy in
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §2.2.

**Addressed.** `analyse` now takes a `repeats` argument and threads it into
`reproduces(scenario, runs=repeats)`; `runner.run` passes `cfg.repeats`. The
knob is also reachable from the command line as `klyrshift qa run --repeats N`,
which was missing.

### 2.5 `title_en` — a documented authority no test checked

`thematic.DictionaryCategory.title_en` carries a docstring that says it "stays as
the authoritative English spelling the catalogue is checked against in the
test-suite" — but **no test checked it**, and it had already drifted from
`en.json`: `gaming` said "Gaming and esports" in code and "Games and esports" in
the catalogue, `sport` said "Sport" versus "Sports".

**Addressed.** `en.json` is realigned to the authoritative `title_en` (the site's
`dictionaries.ts` already agreed with the code), so the two spellings match
again. (A guard test for this specific pair is a natural follow-up; it is noted
in §4 rather than added here, because the audit's scope is the *unused* surface,
and the pair is now consistent.)

### 2.6 `hotkey_swallow` — an inert switch that promised an effect

`Config.hotkey_swallow` is exposed as a GUI switch («Не передавать хоткей в
приложение») and its help text claimed it "поглощает нажатие, чтобы оно не дошло
до активного окна". The daemon never reads the field, and it *cannot*: it never
issues `EVIOCGRAB`, so it cannot swallow a chord (this is the very reason the
default undo hotkey is `SHIFT+BACKSPACE` and not `CTRL+Z`).
[ARCHITECTURE.md](ARCHITECTURE.md) already documented the field as inert.

**Addressed as documentation, not code.** The field is genuinely inert by
design, so the fix is honesty: the help text now says it is a reserved setting
that has no effect and is kept for compatibility. The field stays in
`Config` (removing it would break existing config files) and is listed in the
new guard test's allowlist with its reason.

## 3. What was checked and found already addressed

The audit is only useful if it also states what it cleared:

- **Every other `Config` field has a reader.** The 90 fields were scanned; after
  the fixes above, every field except the documented-inert `hotkey_swallow` is
  read as an attribute outside `config.py`.
- **Every CLI option is read.** The four `argparse` dests that are not read as
  `args.<dest>` (`file`, `learn_action`, `qa_action`, `version`) are read through
  `getattr(args, ...)` or by `argparse` itself (`--version` action) — not dead.
- **Documented config keys exist.** The keys the docs name
  (`typo_max_distance`, `typo_in_manual`, …) were compared with `Config`; the
  only apparent gaps were false positives (a substring of a real key, or a
  removed key mentioned in a migration comment).
- **Every `docs/*.md` is linked and built.** Each guide is linked from the
  README, listed in `docs/PROJECT_STRUCTURE.md` and in
  `scripts/build_docs.py`; `tests/test_project_structure.py` and
  `tests/test_docs_handbook.py` enforce it.
- **The version is derived, not typed.** `scripts/release_consistency.py
  --source` is green; the five files that carry a version agree.

## 4. The guard

`tests/test_spec_coverage.py` pins the addressed items so the class of defect
cannot come back quietly:

- every `Config` field has an attribute reader outside `config.py`, unless it is
  listed as intentionally inert *and* explained in `ARCHITECTURE.md`;
- `log_rotation_mb` sets the handler's `maxBytes` (and the default stays 5 MB,
  and a value below 1 MB is clamped);
- `sound_on_fix` and `notify_on_error` reach the subprocess call, and a missing
  player is survived;
- `RunConfig.repeats` is threaded into `reproduces`, and the run count is
  honoured.

The guard deliberately keys on an **attribute read**, not a string mention: a
GUI binding or a help topic that merely names a field is exactly how
`notify_on_error`, `sound_on_fix` and `log_rotation_mb` looked "used" while
nothing read them.

## 5. Not in scope

- **Removing `hotkey_swallow`.** It is inert but harmless, and dropping the key
  would break a config file that carries it. Honest documentation is the fix.
- **A test for the `title_en`↔`en.json` pair.** The drift is fixed; a dedicated
  guard would need to special-case the Russian keys that are not category titles,
  which is more machinery than the pair is worth today.
- **Persisting anything new.** No change here writes typed text anywhere; the
  new notifications and sound carry fixed labels only.
