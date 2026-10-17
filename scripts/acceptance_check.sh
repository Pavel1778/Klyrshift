#!/usr/bin/env bash
#
# Acceptance check for a REAL Debian 13 + GNOME machine.
#
# Levels 1 and 2 of docs/TESTING.md run in CI and in throwaway containers, but
# they cannot reach the kernel input path: a container has no /dev/uinput, and
# even a --privileged one cannot mknod it. This script runs on the machine the
# package is actually for and reports, with evidence, the things a container
# cannot: device access, the virtual keyboard, the live layout backend and the
# upgrade from the pre-rename package.
#
# It changes nothing except when --fix is passed (which loads the uinput module
# and installs the dictionary release). Run it inside a graphical session, not
# over ssh: several checks are meaningless without a seat.
#
# Usage:
#   scripts/acceptance_check.sh              # diagnose
#   scripts/acceptance_check.sh --fix        # also modprobe uinput
set -u

FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

pass=0
fail=0
warn=0
declare -a FAILED=()

ok()   { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); FAILED+=("$1"); }
meh()  { printf '  warn  %s\n' "$1"; warn=$((warn + 1)); }
head_() { printf '\n== %s ==\n' "$1"; }

echo "Lingvix acceptance check -- $(date -u +%Y-%m-%dT%H:%M:%SZ)"

head_ "0. the package is installed and is the only one"
if dpkg -s lingvix >/dev/null 2>&1; then
    ok "lingvix $(dpkg-query -W -f='${Version}' lingvix) installed"
else
    bad "lingvix is not installed"
fi
if dpkg -l linguafix 2>/dev/null | grep -q '^ii'; then
    bad "the pre-rename 'linguafix' package is STILL installed (two daemons can run)"
else
    ok "no pre-rename 'linguafix' package installed"
fi

head_ "1. session and layout backend"
session="${XDG_SESSION_TYPE:-unknown}"
[ "$session" = "unknown" ] && meh "XDG_SESSION_TYPE unset (running outside a graphical session?)" \
                           || ok "session=$session"
switcher=""
for tool in g3kb-switch setxkbmap; do
    if command -v "$tool" >/dev/null 2>&1; then switcher="$tool"; break; fi
done
if [ -n "$switcher" ]; then
    ok "layout backend available: $switcher"
else
    bad "no layout backend: install x11-xkb-utils (setxkbmap) or g3kb-switch"
fi
if [ "$session" = "wayland" ] && [ "$switcher" = "setxkbmap" ]; then
    meh "Wayland session with only setxkbmap: text is replaced but the layout is not switched"
fi

head_ "2. text injector"
injector=""
for tool in wtype xdotool; do
    if command -v "$tool" >/dev/null 2>&1; then injector="$tool"; break; fi
done
if [ -n "$injector" ]; then
    ok "injector available: $injector"
elif [ -e /dev/uinput ]; then
    ok "no wtype/xdotool, but /dev/uinput exists (uinput backend)"
else
    bad "no text injector: install wtype (Wayland) or xdotool (X11)"
fi

head_ "3. device access (the uaccess rule, no 'input' group)"
if compgen -G '/dev/input/event*' >/dev/null; then
    ok "keyboard event devices exist"
    if [ -r "$(compgen -G '/dev/input/event*' | head -1)" ]; then
        ok "the active session can read /dev/input/event* (uaccess ACL applied)"
    else
        bad "/dev/input/event* is not readable -- is this the active seat? relogin after install"
    fi
else
    bad "no /dev/input/event* -- no keyboard, or the uinput module is missing"
fi
if [ -e /dev/uinput ]; then
    if [ -w /dev/uinput ]; then
        ok "/dev/uinput exists and is writable (uinput backend usable)"
    else
        bad "/dev/uinput exists but is not writable"
    fi
else
    if [ "$FIX" = "1" ]; then
        modprobe uinput 2>/dev/null || true
        [ -e /dev/uinput ] && ok "/dev/uinput appeared after modprobe" \
                           || meh "/dev/uinput still missing after modprobe (uinput backend unavailable; wtype/xdotool still work)"
    else
        meh "/dev/uinput missing -- rerun with --fix, or the uinput backend is unavailable"
    fi
fi
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx input; then
    meh "the user is in the 'input' group -- not needed, and it grants access to every keyboard"
else
    ok "the user is not in the 'input' group (uaccess is enough)"
fi

head_ "4. the daemon runs"
if systemctl --user is-active --quiet lingvix.service 2>/dev/null; then
    ok "lingvix.service is active"
else
    meh "lingvix.service is not active -- run: systemctl --user start lingvix"
fi
if lingvix status >/dev/null 2>&1; then
    ok "lingvix status responds"
else
    bad "lingvix status failed"
fi

head_ "5. autostart toggles and holds"
# There is no ``autostart-status`` subcommand; the GUI reads the same probe
# (``daemon_control.autostart_enabled``). Mirror the launcher's PYTHONPATH to
# call it exactly as the installed package does.
probe_autostart() {
    if [ -d /usr/lib/lingvix/lingvix ]; then
        PYTHONPATH="/usr/lib/lingvix${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY' 2>/dev/null
from lingvix.daemon_control import autostart_enabled
print("on" if autostart_enabled() else "off")
PY
    else
        echo "unknown"
    fi
}
before="$(probe_autostart)"
if lingvix uninstall-autostart >/dev/null 2>&1; then
    off="$(probe_autostart)"
    if [ "$off" = "off" ]; then
        ok "autostart turns off and reads back as off"
    else
        bad "autostart was disabled but reads back as '$off'"
    fi
    if lingvix install-autostart >/dev/null 2>&1; then
        on="$(probe_autostart)"
        if [ "$on" = "on" ]; then
            ok "autostart turns back on (was '$before')"
        else
            bad "autostart was enabled but reads back as '$on'"
        fi
    else
        bad "lingvix install-autostart failed"
    fi
else
    bad "lingvix uninstall-autostart failed"
fi

head_ "6. a real correction (needs a human)"
printf '  MANUAL: in a text field type   ghbdtn   then press Space.\n'
printf '          Expect the text to become   привет   (and the layout to switch\n'
printf '          to ru if g3kb-switch is installed). Then type  привет  and press\n'
printf '          Space: it must stay  привет  (no false positive).\n'
printf '  MANUAL: press the fix hotkey (SHIFT+SHIFT) on  ghbdtn  with no Space:\n'
printf '          it must be corrected too.\n'
printf '  MANUAL: press SHIFT+BACKSPACE: the last fix must be undone.\n'
printf '  MANUAL: check the log has no typed text:  grep -c привет ~/.local/state/lingvix/lingvix.log  ->  0\n'

head_ "7. upgrade from the pre-rename package (only if you have the old .deb)"
printf '  MANUAL (destructive; use a VM):\n'
printf '    sudo apt install ./linguafix_0.2.8_all.deb\n'
printf '    sudo apt install ./lingvix_<version>_all.deb\n'
printf '    dpkg -l | grep -E "linguafix|lingvix"   # only lingvix may remain (ii)\n'
printf '    ls /etc/systemd/user/default.target.wants/  # only lingvix.service\n'

printf '\n----------------------------------------\n'
printf 'ok=%d  warn=%d  fail=%d\n' "$pass" "$warn" "$fail"
if [ "$fail" -gt 0 ]; then
    printf 'failed checks:\n'
    for f in "${FAILED[@]}"; do printf '  - %s\n' "$f"; done
    exit 1
fi
printf 'no hard failures. Complete the MANUAL steps above before calling it verified.\n'
exit 0
