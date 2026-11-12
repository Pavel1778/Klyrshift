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

echo "Klyrshift acceptance check -- $(date -u +%Y-%m-%dT%H:%M:%SZ)"

head_ "0. the package is installed and is the only one"
if dpkg -s klyrshift >/dev/null 2>&1; then
    ok "klyrshift $(dpkg-query -W -f='${Version}' klyrshift) installed"
else
    bad "klyrshift is not installed"
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
    # The rule opens keyboards only, so look for a readable keyboard node
    # rather than the first event* node (often the power button or a mouse).
    readable_kbd=""
    for node in /dev/input/by-path/*-event-kbd /dev/input/by-id/*-event-kbd; do
        if [ -e "$node" ] && [ -r "$node" ]; then
            readable_kbd="$node"
            break
        fi
    done
    if [ -n "$readable_kbd" ]; then
        ok "the active session can read a keyboard ($readable_kbd, uaccess ACL applied)"
    else
        bad "no keyboard under /dev/input is readable -- is this the active seat? relogin after install"
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
if systemctl --user is-active --quiet klyrshift.service 2>/dev/null; then
    ok "klyrshift.service is active"
else
    meh "klyrshift.service is not active -- run: systemctl --user start klyrshift"
fi
if klyrshift status >/dev/null 2>&1; then
    ok "klyrshift status responds"
else
    bad "klyrshift status failed"
fi

head_ "5. autostart toggles and holds"
# There is no ``autostart-status`` subcommand; the GUI reads the same probe
# (``daemon_control.autostart_enabled``). Mirror the launcher's PYTHONPATH to
# call it exactly as the installed package does.
probe_autostart() {
    if [ -d /usr/lib/klyrshift/klyrshift ]; then
        PYTHONPATH="/usr/lib/klyrshift${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY' 2>/dev/null
from klyrshift.daemon_control import autostart_enabled
print("on" if autostart_enabled() else "off")
PY
    else
        echo "unknown"
    fi
}
before="$(probe_autostart)"
if klyrshift uninstall-autostart >/dev/null 2>&1; then
    off="$(probe_autostart)"
    if [ "$off" = "off" ]; then
        ok "autostart turns off and reads back as off"
    else
        bad "autostart was disabled but reads back as '$off'"
    fi
    if klyrshift install-autostart >/dev/null 2>&1; then
        on="$(probe_autostart)"
        if [ "$on" = "on" ]; then
            ok "autostart turns back on (was '$before')"
        else
            bad "autostart was enabled but reads back as '$on'"
        fi
    else
        bad "klyrshift install-autostart failed"
    fi
else
    bad "klyrshift uninstall-autostart failed"
fi

head_ "6. detection and the protective guards (deterministic, no keyboard)"
# Drive the installed package's detector directly: this needs no seat, so it is
# a real check and not a substitute for one. It pins the behaviour the manual
# test below then confirms end to end.
if [ -d /usr/lib/klyrshift ]; then
    det="$(PYTHONPATH="/usr/lib/klyrshift" python3 - <<'PY' 2>/dev/null
from klyrshift.converter import LayoutConverter
from klyrshift.detector import LanguageDetector
d = LanguageDetector(converter=LayoutConverter(), min_word_length=3)
cases = [
    ("us", "ghbdtn", "ru"),          # typed Russian on the US layout
    ("ru", "ghbdtn", "us"),          # and the reverse
    ("ru", "\u043f\u0440\u0438\u0432\u0435\u0442", None),  # already correct
    ("us", "hello", None),           # already correct
    ("us", "https://example.com/path", None),   # URL
    ("us", "user@example.com", None),           # e-mail
    ("us", "src/klyrshift/config.py", None),      # path
    ("us", "v0.2.8.2", None),                   # version
    ("us", "well-known", None),                 # hyphenated id
]
bad = 0
for cur, text, want in cases:
    got = d.target_layout(text, cur)
    if got != want:
        print(f"MISMATCH {cur} {text!r}: got {got!r}, want {want!r}")
        bad += 1
print(f"detector: {len(cases) - bad}/{len(cases)} cases as expected")
PY
)"
    printf '%s\n' "$det" | sed 's/^/  /'
    if echo "$det" | grep -q "^detector: 9/9"; then
        ok "detector converts real words and protects URLs, paths, versions and ids"
    else
        bad "detector behaviour differs from the documented contract (see above)"
    fi
else
    bad "the installed package is not importable at /usr/lib/klyrshift"
fi

head_ "7. modes are switchable"
for m in auto hybrid manual; do
    if klyrshift mode "$m" >/dev/null 2>&1; then
        back="$(klyrshift status 2>/dev/null | grep -i 'Режим' | tail -1)"
        case "$back" in *"$m"*) ok "mode $m set and read back";; *) bad "mode $m set but status shows '$back'";; esac
    else
        bad "klyrshift mode $m failed"
    fi
done
klyrshift mode auto >/dev/null 2>&1

head_ "8. a real correction (needs a human, in a real session)"
printf '  MANUAL: in a text field type   ghbdtn   then press Space.\n'
printf '          Expect the text to become   привет   (and the layout to switch\n'
printf '          to ru if g3kb-switch is installed). Then type  привет  and press\n'
printf '          Space: it must stay  привет  (no false positive).\n'
printf '  MANUAL: press the fix hotkey (SHIFT+SHIFT) on  ghbdtn  with no Space:\n'
printf '          it must be corrected too.\n'
printf '  MANUAL: press SHIFT+BACKSPACE: the last fix must be undone.\n'
printf '  MANUAL: repeat the three lines above in the other session type:\n'
printf '            Wayland:  log out, choose "GNOME on Wayland" at the login screen\n'
printf '            X11:      choose "GNOME on Xorg"\n'
printf '          Both must correct the text. On Wayland the layout changes only\n'
printf '          with g3kb-switch; with setxkbmap the text changes and the layout\n'
printf '          does not.\n'
printf '  MANUAL: in each mode, type  ghbdtn  and press Space:\n'
printf '            auto    -> corrected without asking\n'
printf '            hybrid  -> a borderline word waits for the hotkey; a certain one is corrected\n'
printf '            manual  -> nothing happens until you press the hotkey\n'
printf '          Switch with:  klyrshift mode auto|hybrid|manual\n'
printf '  MANUAL: add a word to the exceptions list, then type it: it must be left alone.\n'
printf '          Edit  ~/.config/klyrshift/config.toml  (exceptions_apps) or the GUI list.\n'
printf '  MANUAL: type  https://example.com/a_b  and  /usr/lib/klyrshift/x.py  and\n'
printf '          press Space: neither may be rewritten (the guards checked above).\n'
printf '  MANUAL: check the log has no typed text:  grep -c привет ~/.local/state/klyrshift/klyrshift.log  ->  0\n'
printf '  MANUAL: only ONE daemon may run:\n'
printf '            pgrep -af "klyrshift start" | wc -l    ->  1\n'

head_ "9. upgrade from the pre-rename package (destructive; use a VM)"
printf '  This is automated on clean images by scripts/deb_selfsufficiency_test.sh,\n'
printf '  but confirm it on the target machine:\n'
printf '    sudo apt install ./linguafix_0.2.8_all.deb\n'
printf '    sudo apt install ./klyrshift_<version>_all.deb\n'
printf '    dpkg -l | grep -E "linguafix|lingvix|klyrshift"   # only "ii  klyrshift" may remain\n'
printf '    ls /etc/systemd/user/default.target.wants/  # only klyrshift.service\n'
printf '    pgrep -af klyrshift | wc -l               # one daemon, not two\n'
printf '  The config IS migrated on first load (~/.config/lingvix or\n'
printf '  ~/.config/linguafix -> ~/.config/klyrshift, copied, not moved);\n'
printf '  see docs/INSTALL.md "Upgrading from the old linguafix package".\n'

printf '\n----------------------------------------\n'
printf 'ok=%d  warn=%d  fail=%d\n' "$pass" "$warn" "$fail"
if [ "$fail" -gt 0 ]; then
    printf 'failed checks:\n'
    for f in "${FAILED[@]}"; do printf '  - %s\n' "$f"; done
    exit 1
fi
printf 'no hard failures. Complete the MANUAL steps above before calling it verified.\n'
exit 0
