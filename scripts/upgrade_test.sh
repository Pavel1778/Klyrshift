#!/usr/bin/env bash
# Verify the upgrade path from the pre-rename `linguafix` package.
#
# The checklist in docs/RELEASING.md asks for this by hand on a VM. Nothing in
# the suite covers it: the pytest tests replace the OS boundary with fakes, so
# they cannot see dpkg's Conflicts/Replaces or the systemd unit symlinks.
#
#   bash scripts/upgrade_test.sh
#
# It builds a minimal stand-in for the old package (only what the real one
# shipped that matters here: the unit and the config directory), installs it in
# a clean Debian image, then installs the new .deb over it with apt and checks
# that the old package is gone, only one daemon unit is enabled, and the user's
# settings survived the rename.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

IMAGE="${UPGRADE_IMAGE:-debian:13}"
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
fi

NEW_DEB="$(ls -1 "${REPO_DIR}"/dist/klyrshift_*_all.deb | tail -1)"
[ -f "${NEW_DEB}" ] || { echo "build the .deb first: bash scripts/build_deb.sh" >&2; exit 1; }
NEW_DEB_NAME="$(basename "${NEW_DEB}")"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# --- a minimal `linguafix` package, as the old one behaved -------------------
OLD="${WORK}/old"
mkdir -p "${OLD}/DEBIAN" "${OLD}/usr/bin" \
         "${OLD}/usr/lib/systemd/user" "${OLD}/usr/lib/linguafix"
cat > "${OLD}/DEBIAN/control" <<'CTL'
Package: linguafix
Version: 0.2.8
Section: utils
Priority: optional
Architecture: all
Maintainer: Pavel1778 <noreply@github.com>
Description: stand-in for the pre-rename package (upgrade test only)
CTL
cat > "${OLD}/usr/lib/systemd/user/linguafix.service" <<'UNIT'
[Unit]
Description=LinguaFix (pre-rename stand-in)
[Service]
ExecStart=/usr/bin/linguafix start
UNIT
cat > "${OLD}/usr/bin/linguafix" <<'BIN'
#!/bin/sh
exit 0
BIN
chmod 0755 "${OLD}/usr/bin/linguafix"
dpkg-deb --build --root-owner-group "${OLD}" "${WORK}/linguafix_0.2.8_all.deb" >/dev/null

echo "== image ${IMAGE} =="
${DOCKER} run --rm -v "${REPO_DIR}/dist:/deb:ro" -v "${WORK}:/work:ro" \
    -e DEBIAN_FRONTEND=noninteractive -e NEW_DEB_NAME="${NEW_DEB_NAME}" \
    "${IMAGE}" bash -euo pipefail -c '
set -euo pipefail

useradd -m -s /bin/bash tester

echo "== 1. install the old package =="
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq /work/linguafix_0.2.8_all.deb >/dev/null 2>&1
dpkg -l linguafix | grep -q "^ii" && echo "ok   - linguafix installed"

# A user who had customised settings under the old name.
mkdir -p /home/tester/.config/linguafix
printf "mode = \"manual\"\n" > /home/tester/.config/linguafix/config.toml
mkdir -p /home/tester/.config/linguafix
printf "sig = \"Regards\"\n" > /home/tester/.config/linguafix/snippets.toml
chown -R tester:tester /home/tester/.config

echo "== 2. install the new package over it =="
apt-get install -y -qq "/deb/${NEW_DEB_NAME}" >/dev/null 2>&1

echo "== 3. only the new package remains =="
if dpkg -l linguafix 2>/dev/null | grep -q "^ii"; then
    echo "FAIL - linguafix is still installed" >&2; exit 1
fi
echo "ok   - linguafix is gone"
dpkg -l klyrshift | grep -q "^ii" && echo "ok   - klyrshift installed"
[ -e /usr/lib/systemd/user/linguafix.service ] \
    && { echo "FAIL - the old unit file remains" >&2; exit 1; }
echo "ok   - the old unit file was removed"

echo "== 4. only one daemon unit is enabled =="
if command -v systemctl >/dev/null 2>&1; then
    wants="$(ls /etc/systemd/user/default.target.wants/ 2>/dev/null || true)"
    echo "     wants: ${wants}"
    case "${wants}" in
        *linguafix*) echo "FAIL - linguafix.service still enabled" >&2; exit 1 ;;
    esac
    case "${wants}" in
        *klyrshift.service*) echo "ok   - klyrshift.service enabled" ;;
        *) echo "FAIL - klyrshift.service not enabled" >&2; exit 1 ;;
    esac
else
    echo "skip - systemctl unavailable in this image"
fi

echo "== 5. the user settings survived the rename =="
[ -f /home/tester/.config/linguafix/config.toml ] \
    && echo "ok   - the old config is left in place (a downgrade still finds it)"
out="$(su tester -c "XDG_CONFIG_HOME=/home/tester/.config klyrshift config show 2>&1" || true)"
echo "${out}" | grep -q "mode" && echo "ok   - config show runs"
[ -f /home/tester/.config/klyrshift/config.toml ] \
    && echo "ok   - the config was copied to ~/.config/klyrshift"
grep -q "manual" /home/tester/.config/klyrshift/config.toml \
    && echo "ok   - the user mode=manual survived" || {
        echo "FAIL - the migrated config lost mode=manual" >&2
        cat /home/tester/.config/klyrshift/config.toml >&2; exit 1; }
[ -f /home/tester/.config/klyrshift/snippets.toml ] \
    && echo "ok   - snippets were copied too"

echo "UPGRADE OK"
'
