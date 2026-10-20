# Installation

Klyrshift targets Debian 12+ / Ubuntu 22.04+ with GNOME 45+ on either X11 or
Wayland. Python 3.10 or newer is required.

## Zero-config .deb path (recommended)

This is the path for regular users. Nothing has to be configured by hand:

```bash
sudo apt install ./klyrshift_0.2.9_all.deb
```

That is the whole procedure. The package:

- installs `/usr/lib/udev/rules.d/71-klyrshift.rules`, which grants access to
  `/dev/input/event*` and `/dev/uinput` to the active session user with
  `TAG+="uaccess"` — no `usermod`, no group membership, no relogin;
- loads the `uinput` module so `/dev/uinput` exists;
- enables the systemd user service **globally**
  (`systemctl --user enable --global klyrshift.service`), so it starts at the
  next login. It is not started during installation because there may be no
  graphical session yet;
- ships the man page (`man klyrshift`) and the bash and zsh completions, so
  `klyrshift <Tab>` completes commands and their options.

After the next login the daemon is running. Verify with:

```bash
klyrshift doctor
systemctl --user is-enabled klyrshift.service   # -> enabled
```

`uaccess` grants the ACL when the user logs in at the seat. If the package is
installed while a session is already open, the ACL appears at the next login or
after a reboot; that is expected and needs no manual command. If `doctor` still
reports a permission problem after a relogin, see
[TROUBLESHOOTING: после установки .deb doctor жалуется на права /dev/input или /dev/uinput](TROUBLESHOOTING.md#после-установки-deb-doctor-жалуется-на-права-devinput-или-devuinput).

> Why `uaccess` and not the `input` group: the ACL is granted only to the user
> physically logged in at the seat, is applied dynamically and is revoked when
> the session ends. Permanent membership of the `input` group would give every
> member access to every keyboard, always.

## Upgrading from the old `linguafix` package

The project was renamed twice — `LinguaFix` → `Lingvix` → `Klyrshift` — and the
Debian package with it (`linguafix` → `klyrshift`). Install the new package the
same way:

```bash
sudo apt install ./klyrshift_0.2.9_all.deb
```

apt sees `Conflicts: linguafix, lingvix` and `Replaces: linguafix, lingvix` in the
new package and removes the old one first, so the two do not coexist. Do not end up
with both: each package ships a systemd user unit, and two enabled units means two
daemons reading the keyboard at once.

Verify that only the new package remains:

```bash
dpkg -l | grep -E 'linguafix|lingvix|klyrshift'   # only 'ii  klyrshift' expected
systemctl --user is-enabled klyrshift.service    # -> enabled
```

The configuration directory **is migrated** on first load. The old package used
`~/.config/linguafix` (and, between the renames, `~/.config/lingvix`) while the new
one uses `~/.config/klyrshift`; on the first start the new package copies
`config.toml` and `snippets.toml` across. The copy happens once, only when
`~/.config/klyrshift/config.toml` does not exist yet, and it leaves the old file in
place — so an existing current config is never overwritten and a downgrade still
finds its settings. To migrate by hand instead (or to check what was copied):

```bash
ls ~/.config/klyrshift/config.toml
# manual equivalent, if you prefer:
mkdir -p ~/.config/klyrshift
cp ~/.config/linguafix/config.toml ~/.config/klyrshift/config.toml
```

A `dpkg -i` install (rather than `apt install ./…`) also removes the old
package, but leaves an empty `linguafix` record in dpkg's database and reports
`1 not upgraded`. That is cosmetic — no files, no unit and no daemon remain.
Clear it with `sudo apt-get -f install`, or by `sudo dpkg --purge linguafix`.

## GNOME version and layout switching

On GNOME Wayland the active layout is changed through `g3kb-switch`, which
talks to a GNOME Shell extension and is tied to the shell's D-Bus API. That API
has changed between GNOME releases, so the supported range is **GNOME 45+ (tested on 48)**.
`install.sh` prints a warning when it detects a GNOME version outside that
range. If `g3kb-switch` is missing or incompatible, Klyrshift still replaces the
text but cannot change the active layout.

`g3kb-switch` is **not in the Debian repositories** (verified: no candidate in
Debian 12 or 13), so it is only a `Recommends`, never a `Depends` — apt would
otherwise refuse to install the package. The X11 backend `setxkbmap` ships in
`x11-xkb-utils`, which *is* in Debian and *is* recommended, so a default Debian
install keeps a working layout backend. Check what is available with:

```bash
klyrshift doctor     # reports the detected layout backend
gnome-shell --version
```

## Quick install (developer path)

This path is for contributors who work from a clone. Regular users should use
the `.deb` above.

```bash
git clone https://github.com/Pavel1778/Klyrshift.git
cd Klyrshift
bash install.sh
```

The installer is idempotent and can be re-run safely. Pass `--yes` for a
non-interactive run (useful in scripts):

```bash
bash install.sh --yes
```

To install without starting the daemon at login, pass `--no-autostart`. The
daemon still runs for the current session; it is simply not enabled at login.
Re-running the installer with this flag also removes an autostart entry a
previous install wrote, so the opt-out always holds:

```bash
bash install.sh --no-autostart
```

Either way the autostart can be toggled later from the GUI switch, or with
`klyrshift install-autostart` / `klyrshift uninstall-autostart`.

## What the installer does

1. Checks that the host looks like Debian/Ubuntu (warns, but continues, if not).
2. Verifies Python 3.10+.
3. Installs system packages with `apt`:
   `python3-evdev python3-gi python3-gi-cairo gir1.2-appindicator3-0.1 wtype
   xdotool libnotify-bin`.
4. Optionally helps you install `g3kb-switch` for GNOME Wayland layout
   switching.
5. Creates a virtual environment in `~/.local/share/klyrshift/venv/` and
   installs the package with `pip install -e .`.
6. Installs the udev rule `/etc/udev/rules.d/71-klyrshift.rules` (asks for sudo).
   The rule grants access with `TAG+="uaccess"`, so no group change is needed.
7. Loads the `uinput` module.
8. Installs the systemd user service `~/.config/systemd/user/klyrshift.service`.
9. Installs the XDG autostart entry
   `~/.config/autostart/klyrshift.desktop` (skipped with `--no-autostart`).
10. Copies the icon to
    `~/.local/share/icons/hicolor/scalable/apps/klyrshift.svg`.
11. Installs the man page (`~/.local/share/man/man1/klyrshift.1`) and the bash
    and zsh completions (`~/.local/share/bash-completion/completions/klyrshift`,
    `~/.local/share/zsh/site-functions/_klyrshift`).
12. Enables and starts the service (with `--no-autostart`, starts it without
    enabling it at login).
13. Sends a desktop notification.

## After installing (developer path)

The udev rule grants the ACL to the active session user. If the rule was just
installed, reload it so the ACL is applied:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

A full logout/login also applies it. No `usermod` and no group change is
involved.

## Verifying the install

```bash
klyrshift status
systemctl --user status klyrshift.service
journalctl --user -u klyrshift.service -n 50 --no-pager
```

`klyrshift status` should report that the daemon is running, the current layout,
and the active injector backend.

Run the built-in self-diagnosis to check permissions, devices, tools, the GNOME
version and the resolved backends at once:

```bash
klyrshift doctor
```

The output is a table with a marker per check (`✅` pass, `⚠️` warning, `❌`
failure) and a hint for every check that did not pass. The command exits
non-zero when a check fails, so `install.sh` runs it as a final self-test.

To check the installed files themselves, not the environment:

```bash
klyrshift verify
```

The `.deb` ships an `md5sums` manifest (one digest per installed file), and
`verify` compares the files on disk against it. A file that is missing is
reported separately from one that was modified, because the fix is the same
either way — reinstall:

```bash
sudo apt install --reinstall klyrshift
```

`dpkg --verify klyrshift` performs the same comparison using dpkg's own copy of
the manifest. A source checkout or a `pip install` has no manifest; `verify`
says so instead of claiming a pass.

## Ubuntu notes

Some package names differ between Debian and Ubuntu. `install.sh` installs the
APT packages one by one and skips any name that is not available in the current
repository, so a missing package never aborts the install:

- The `uinput` backend uses `evdev.UInput` from `python3-evdev`, so the
  `python-uinput` package is not required. `python3-evdev` ships in Debian and
  Ubuntu; `install.sh` reuses it through `--system-site-packages`, so no
  compiler is needed.
- `wtype` and `g3kb-switch` may need a third-party repository on older Ubuntu
  releases. Without `wtype`, Klyrshift falls back to `xdotool` (X11) or
  `uinput`.

## Manual install

If you prefer to install by hand:

```bash
python3 -m venv ~/.local/share/klyrshift/venv
~/.local/share/klyrshift/venv/bin/pip install -e .
mkdir -p ~/.config/systemd/user
cp data/klyrshift.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now klyrshift.service
```

Then install the udev rule manually (it uses `uaccess`, so no group change is
needed):

```bash
sudo cp data/71-klyrshift.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Uninstalling

For a `.deb` install:

```bash
sudo apt remove --purge klyrshift
```

For a source install:

```bash
bash uninstall.sh
```

Both stop and disable the service, remove the udev rule, the unit, the autostart
entry and the icon, and delete the per-user configuration and logs.
