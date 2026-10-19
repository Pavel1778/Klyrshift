# Undo contract

This document states what "undo a correction" guarantees in Klyrshift, what it
deliberately refuses to do, and which guarantees are impossible on which
platforms. It is the contract the daemon's undo path and its tests are written
against.

## The one rule

**A correction is undoable only while its word is still under the caret.**

A restore works by deleting a fixed number of characters and retyping the
original. That count is only meaningful if the text at the caret is still the
text the daemon produced. The moment the user types anything else, moves the
caret, or switches application, the count no longer describes what is on screen.
Klyrshift then drops the recorded fix and the undo hotkey becomes a no-op.

A refused undo is always preferable to a corrupted word. This is the same
principle the detector uses for a wrong guess ("a wrong guess is worse than no
guess").

## How undo is performed

Klyrshift never grabs the keyboard (`EVIOCGRAB` is never issued). It cannot
swallow a chord, so it cannot intercept the application's own `Ctrl+Z`. Two
separate mechanisms follow from that:

1. **The application's own undo (`Ctrl+Z`).** The daemon lets the chord through.
   The application reverts the daemon's synthetic rewrite exactly as it reverts
   any other edit, restoring the text the user had typed. Klyrshift only
   *observes* the chord, records the word as rejected, and drops its own history
   so it does not retype the original over text that is already back.
2. **The undo hotkey (`SHIFT+BACKSPACE`, configurable).** The daemon deletes the
   fixed character count and retypes the original, then switches the layout back
   if the fix had switched it.

`Ctrl+Z` is not the default undo hotkey for the same reason: binding it would
fire the application's undo *and* the daemon's restore, and the two would race
over the same characters.

## Guarantees

| Guarantee | Mechanism |
|---|---|
| A fix stays undoable for a bounded time and depth | `undo_window_seconds` (default 10 s), `undo_history_depth` (default 3) |
| A stale fix is never restored | History is cleared on the first keystroke or caret move after a fix |
| A stale GUI undo request is refused | The caller passes the history id; only the newest id is accepted |
| The undo hotkey never re-fixes the restored word | The restored word is recorded as rejected |
| The typed text never reaches disk | The original lives only in the in-memory undo tuple; the history snapshot is metadata-only |
| A dry run never touches the text | `--dry-run` reports the undo without replacing anything |

## What undo does not do

- **It does not undo more than the last fix.** Only the newest entry is
  restorable; the depth bound exists to age entries out, not to walk back a
  chain of edits.
- **It does not undo other applications' edits.** Only Klyrshift's own rewrite
  is restored.
- **It does not run when the daemon could not type the replacement** (an
  untypable character, a missing backend): nothing was changed, so nothing is
  recorded.

## Platform limits

| Situation | Behaviour | Why |
|---|---|---|
| Wayland, no `uinput` access | The fix is refused rather than applied | Without a backend there is no atomic replacement to undo |
| Fallback backends (`wtype`, `xdotool`) | Undo works, but the original replacement was not atomic | Deletion and retyping are separate calls; a crash mid-replacement can leave text truncated |
| A password field | Never fixed, so never undone | Wayland hides the focused widget; a stop-word list is the mitigation |
| An application that eats synthetic keys (some games, Java/Swing) | The fix may not land; undo has nothing to restore | Known limitation |

## Tests

`tests/test_undo_suppression.py` enforces the contract:

- a bare `Ctrl+Z` suppresses the word and is not re-fixed;
- the word is not fixed again after the chord;
- `Ctrl+Shift+Z` (redo) is not treated as a rejection;
- the undo hotkey restores the last fix while its word is still under the caret;
- a fix is **not** restored once new text was typed or the caret moved;
- `Ctrl+Z` followed by the undo hotkey does not retype the already-restored word;
- the undo history is dropped by a caret move.
