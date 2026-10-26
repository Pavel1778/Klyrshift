# Platform support

What Klyrshift supports today, on which platform, and what it does not. The
table separates **implemented and tested** from **implemented but unverified on
real hardware** from **not implemented**. Nothing here claims support that has
not been exercised.

## Verification status legend

| Mark | Meaning |
|---|---|
| ✅ | Implemented; covered by automated tests |
| 🟡 | Implemented; automated tests only, needs a real session/keyboard to confirm |
| ❌ | Not implemented |
| ⛔ | Technically not possible on this platform as designed |

## Linux

| Capability | X11 | Wayland (GNOME) | Notes |
|---|---|---|---|
| Wrong-layout detection | ✅ | ✅ | Pure logic; platform-independent |
| Automatic text replacement | 🟡 `xdotool` / `uinput` | 🟡 `uinput` / `wtype` | Needs `/dev/input` + `/dev/uinput` |
| Atomic replacement | 🟡 `uinput` only | 🟡 `uinput` only | `wtype`/`xdotool` delete and retype separately |
| Layout switching | 🟡 `setxkbmap` / `gnome-shortcut` | ✅ `gnome-shortcut` (GNOME), 🟡 `g3kb-switch` | `gnome-shortcut` needs only GNOME and the `uinput` injector; `g3kb-switch` is not in the Debian repos |
| Password-field detection | ⛔ | ⛔ | Both hide the focused widget from unprivileged clients |
| Focused-application exceptions | 🟡 | 🟡 | Best-effort; depends on the compositor |
| System tray | 🟡 | 🟡 | Optional AppIndicator |
| GUI settings (GTK4 + libadwaita) | 🟡 | 🟡 | Runs under either session |
| Autostart | ✅ | ✅ | systemd user service |

The daemon does not grab the keyboard on either session. It reads `evdev` events
and injects through `uinput`; this is why it never swallows a chord (see
[UNDO_CONTRACT.md](UNDO_CONTRACT.md)).

## Distribution formats

| Format | Status | Notes |
|---|---|---|
| `.deb` | ✅ Built and released | Self-contained: udev rule, systemd user service, `uinput` module load |
| Source install (`install.sh`) | ✅ | Installs into a venv under `~/.local/share/klyrshift` |
| Flatpak | ❌ Not implemented | Investigated as a future option; needs a portal-based input path |
| AppImage | ❌ Not implemented | Needs the same input path as Flatpak |

A distribution format is only listed as supported once it has been exercised on
a real image; see `docs/RELEASING.md` for the checks that gate a release.

## Languages

| Language | Layout conversion | Frequency dictionary | Detector | Status |
|---|---|---|---|---|
| `en` | ✅ | ✅ `en-50k` | ✅ | Default |
| `ru` | ✅ | ✅ `ru-50k` | ✅ | Default |
| `uk` | ✅ | ✅ `uk-50k` | 🟡 | Manual enable; less tested than `en`/`ru` |
| `de` | ✅ | ✅ `de-50k` | 🟡 | Manual enable; less tested |
| `fr` | ✅ | ✅ `fr-50k` | 🟡 | Manual enable; less tested |

Adding a language is a data change: a word list, an n-gram model, and an entry in
the layout map. See the extension points in
[ARCHITECTURE.md](ARCHITECTURE.md#extension-points).

## Other operating systems

| Platform | Status | What it would need |
|---|---|---|
| Windows | ❌ Not implemented | A `WH_KEYBOARD_LL` hook and `SendInput` adapter; the detector core is reusable |
| macOS | ❌ Not implemented | Accessibility permissions and a CGEvent tap; the detector core is reusable |
| Android | ❌ Not implemented | A separate IME built on `InputMethodService`; the detector core is reusable |
| ChromeOS / BSD | ❌ Not implemented | Not investigated |

The detection core (`detector.py`, `converter.py`, `typo.py`, `dictionary.py`)
has no GTK, evdev, or session dependency and is the part worth reusing. The
input adapters (`injector.py`, `switcher.py`, `app_focus.py`) are
platform-specific by nature. No claim of cross-platform support is made: the
core compiling elsewhere is not the same as the product working elsewhere.

## Environment this matrix was written against

- Debian 13 (trixie) — the development container runs this.
- The container has **no GNOME, no display, no `/dev/input`, no `/dev/uinput`**,
  so every 🟡 row is unverified here. The 🟡 marks are honest, not optimistic:
  they mean "the code and its tests exist, a real session has not confirmed it".

### What a real Debian 13 container does verify

The package layer is checked against real `debian:13` containers (Docker), not
the dev container alone. These run in CI and were re-run for this revision:

- `scripts/smoke_test.sh` with `SMOKE_IMAGE=debian:13` — the `.deb` installs,
  the daemon starts, `doctor` reports `backend=setxkbmap` with no `g3kb-switch`
  present, and the data files load. **Passed.**
- `scripts/upgrade_test.sh` (image `debian:13`) — the pre-rename `linguafix`
  package is displaced, the old unit file is removed, exactly one daemon unit is
  enabled, and `mode=manual` survives the rename. **Passed.**
- `scripts/deb_selfsufficiency_test.sh` with `SMOKE_IMAGE=debian:13` — no manual
  step is needed (no group change), reinstall is idempotent, and
  `apt remove --purge` leaves nothing behind. **Passed.**

What these still cannot reach is the kernel input path and the GNOME session:
`/dev/uinput`, `/dev/input/event*`, the live layout switch and the real focus
tracking need a seat. Those stay 🟡 and are what
`scripts/acceptance_check.sh` is for on a physical machine.

