# Testing

Testing happens on three levels, from cheapest to most realistic. A layer does
not replace the ones above it — a green pytest run does **not** mean the daemon
works on a real desktop.

| Level | What it runs | How to run | Proves |
|---|---|---|---|
| 1. Unit / integration | Real code, faked OS boundary | `make test` | Logic, parsing, config, conversion |
| 2. Package smoke test | The built `.deb`, installed into a clean `debian:12` container | `make smoke-test` | The package installs, all runtime imports resolve, the CLI starts |
| 3. Manual desktop test | A real GNOME session (Wayland and X11) | This document | Permissions, D-Bus, `uinput`, real applications |

## Level 2: package smoke test

`scripts/smoke_test.sh` builds nothing itself; it installs `dist/*.deb` into a
throwaway `debian:12` container and checks that `klyrshift version`, `--help`,
`status` and `doctor` run, and that the daemon starts in `--dry-run`. It catches
the class of bug that pytest cannot: a missing runtime dependency or a broken
entry point in the installed package. It does **not** need a GUI, so it also
runs in CI (see `release.yml`).

```bash
make build-deb
make smoke-test
```

The container has no keyboard devices, so `doctor` is expected to report
failures there; the smoke test only asserts that the commands execute.

`scripts/deb_selfsufficiency_test.sh` installs the `.deb` with no manual step
and checks that a purge leaves nothing behind. `scripts/upgrade_test.sh`
installs a stand-in for the pre-rename `linguafix` package and then the new
`.deb` over it, and checks that the old package is removed, only one daemon
unit is enabled and the user's config survived the rename. Neither needs a
desktop.

## Level 3: manual test plan

The automated suite runs headless and replaces the operating-system boundary
with fakes. It cannot verify permissions, D-Bus behaviour or how real
applications react to synthetic input. This plan covers what must be checked by
hand on a real desktop.

`scripts/acceptance_check.sh` automates the parts of this plan a script *can*
check on a real machine (installed package, no leftover pre-rename package,
session type, layout backend, text injector, device access, the daemon, the
autostart toggle). Run it first, inside the graphical session:

```bash
scripts/acceptance_check.sh          # diagnose
scripts/acceptance_check.sh --fix    # also load the uinput module
```

It exits non-zero on a hard failure and prints the manual steps that still need
a human (a real correction, the hotkeys, the undo, the log). A container cannot
run it meaningfully: there is no seat and no `/dev/uinput`.

### Quick start (copy-paste)

Run this block first. It installs Klyrshift, prints a diagnosis and starts
watching the log. It is safe to paste as one piece. It exercises the
**zero-config `.deb` path** — the one a regular user takes.

```bash
# 1. Install the package. No usermod, no manual enable.
sudo apt install ./klyrshift_0.2.8.4_all.deb

# 2. Verify that nothing else is required.
systemctl --user is-enabled klyrshift.service   # -> enabled
cat /usr/lib/udev/rules.d/71-klyrshift.rules    # -> TAG+="uaccess", no GROUP="input"

# 3. If a session was already open during install, log out and back in once.
#    uaccess is granted when the user logs in at the seat.

# 4. After (re)login — verify the environment.
getfacl /dev/input/event3 2>/dev/null | grep "user:$(id -un)" && echo "OK: ACL present"
klyrshift doctor
klyrshift status

# 5. Watch the daemon while you test (Ctrl-C to stop).
journalctl --user -u klyrshift.service -f
```

For the **developer path** instead, replace step 1 with:

```bash
git clone https://github.com/Pavel1778/Klyrshift.git
cd Klyrshift
bash install.sh --yes
sudo udevadm control --reload-rules && sudo udevadm trigger
```

If `klyrshift doctor` shows no ❌, continue with the scenarios below. If it
shows a ❌, stop and attach the output to issue #5 — that is already a useful
result.

### Environments

Test on both, in a virtual machine:

| # | Distribution | Session | GNOME |
|---|---|---|---|
| 1 | Debian 12 (netinst, GNOME) | Wayland (default) | 43 |
| 2 | Ubuntu 22.04 LTS (GNOME) | Wayland (default) | 42 |

Then repeat the core scenarios switching to **X11** (choose "GNOME on Xorg" in
GDM).

## A. Installation

`.deb` path (primary):

1. `sudo apt install ./klyrshift_0.2.8.4_all.deb` — note every prompt and any failure.
2. Confirm the udev rule: `cat /usr/lib/udev/rules.d/71-klyrshift.rules` — uses
   `TAG+="uaccess"`, no `GROUP="input"`.
3. `systemctl --user is-enabled klyrshift.service` — prints `enabled`, without
   you running `systemctl --user enable` by hand.
4. Log out completely and back in (only needed if a session was already open).
5. `getfacl /dev/input/event3` — shows a `user:<you>:rw-` ACL entry.
6. `klyrshift status` — daemon running, backends reported.
7. `ls -l /dev/input/event*` — readable by your user.

Developer path:

1. Run `bash install.sh` interactively. Note every prompt and any failure.
2. Confirm the apt packages: `dpkg -l | grep -E 'evdev|uinput|wtype|xdotool|appindicator'`.
3. Confirm the udev rule: `cat /etc/udev/rules.d/71-klyrshift.rules` — `uaccess`.
4. `sudo udevadm control --reload-rules && sudo udevadm trigger`.
5. `klyrshift doctor` — no ❌.

## B. Daemon startup

1. `systemctl --user status klyrshift.service` — active, no restart loop.
2. `journalctl --user -u klyrshift.service -n 50 --no-pager` — no tracebacks.
3. `klyrshift start --foreground --dry-run` — the daemon runs and logs
   "Dry run" instead of touching the text.

## C. Correction matrix

In each application, switch to the **wrong** layout, type `ghbdtn` (meaning
"привет"), and record whether Klyrshift corrected it:

| Application | Wayland | X11 | Notes |
|---|---|---|---|
| gnome-terminal | | | |
| Firefox (address bar + text area) | | | |
| Chrome / Chromium | | | |
| VS Code | | | |
| Gedit / Text Editor | | | |
| SuperTuxKart (chat) | | | |

Also test:

- A Russian word typed on the US layout and vice versa.
- Uppercase (`Ghbdtn`).
- Punctuation (`ghbdtn?`, `;b`).
- A password field: the correction must **not** fire for stop words, but note
  whether it fires for non-stop-word content in a password field (known
  limitation).

## D. Layout switching

1. With `g3kb-switch` installed: `g3kb-switch -p` before and after a correction.
2. Without `g3kb-switch` on Wayland: text is replaced but layout is unchanged
   (document the behaviour).
3. On X11: confirm the `setxkbmap` fallback works.

## E. Tray and notifications

1. Tray icon appears (requires the AppIndicator GNOME extension).
2. "Показать статус" shows a notification with the current layout.
3. "Исправить сейчас" triggers a correction.
4. `notify_on_fix = true` shows a notification after each fix.

## F. Privacy and logs

1. Type a word, trigger a correction, then inspect
   `~/.local/state/klyrshift/klyrshift.log`.
2. The log must contain only metadata (length, layouts) — never the typed text.
3. Confirm rotation config: 5 MB × 3 files.

## G. Conflicts

1. Start IBus or Fcitx and check for double conversions or missed fixes.
2. Document the outcome.

## H. GUI

Run `klyrshift gui` and check the window stays up.

1. **Big on/off toggle** — turns on and off, and the state agrees with
   `klyrshift status` in both directions, several times in a row.
2. **Autostart switch** — toggles, and the setting survives a GUI restart.
   Verify with `systemctl --user is-enabled klyrshift.service` (or the presence of
   `~/.config/autostart/klyrshift.desktop`): turning it off must remove both.
3. **Mode switcher** Auto/Manual/Hybrid — agrees with `klyrshift mode`.
4. **Dictionary tab** — add `vercel`, confirm `klyrshift dict list` shows it, then
   remove it and confirm it disappears. Type `муксуд ` and expect `vercel `.
5. **Advanced tab** — every group expands, and a change is saved to
   `config.toml` and survives `klyrshift restart`.
6. **Export/import** — export to JSON, reset, import; the settings come back
   (`klyrshift export` / `klyrshift import` work too).

7. **Guided tour** — on a fresh config the first-run offer appears; starting it
   walks the steps, each highlighting the widget it describes. Skipping,
   finishing and the "Повторить вводный тур" button on the help page all work,
   and a restart after finishing shows no offer.
8. **Context help** — the "?" on a settings group opens the matching topic; the
   "Помощь и обучение" page lists every topic, runs the environment check and
   shows the known limitations.

## Reporting

File one issue per problem found, using the bug report template
(`.github/ISSUE_TEMPLATE/bug_report.md`). Apply the `needs-testing` label while
triaging.

Attach a diagnostic bundle — one command collects everything a maintainer needs
(the `doctor` output, configuration, log tail, user journal, environment,
device permissions and package versions):

```bash
klyrshift collect-logs
# -> ~/klyrshift-logs-YYYYMMDD-HHMMSS.tar.gz
```

The daemon logs only metadata, so the bundle never contains the text you typed.
See `docs/TROUBLESHOOTING.md` for details.
