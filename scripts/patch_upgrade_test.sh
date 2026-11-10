#!/usr/bin/env bash
# Verify the patch-upgrade path: install 0.2.10 over an installed 0.2.9.
#
# The smoke test installs the package into a clean container; it never proves
# that an *upgrade* preserves the user's settings and keeps the autostart
# working. A patch release is normally installed over the previous one, so this
# is part of release quality. The pytest suite replaces the OS boundary with
# fakes, so it cannot see dpkg's ordering or the systemd unit either.
#
#   bash scripts/patch_upgrade_test.sh
#
# It builds a stand-in for the previous patch release from the current tree
# (the same files, version rewritten to the one named below), installs it in a
# clean Debian container, seeds a user config, then installs the current .deb
# over it and checks the config survived and the package verifies.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

IMAGE="${UPGRADE_IMAGE:-debian:13}"
# The version we upgrade *from*; the current tree is the version we upgrade to.
FROM_VERSION="${FROM_VERSION:-0.2.9}"
TO_VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
fi

log() { printf '\033[1;34m[patch-upgrade]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[patch-upgrade] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }

TO_DEB="$(ls -1 "${REPO_DIR}"/dist/klyrshift_"${TO_VERSION}"_all.deb 2>/dev/null | tail -1 || true)"
[ -f "${TO_DEB}" ] || fail "build the current .deb first: bash scripts/build_deb.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# --- a stand-in for the previous patch release -------------------------------
# Unpack the current .deb and rewrite only the version. The file set is
# identical, which is exactly what a patch release is; what this test exercises
# is dpkg's upgrade handling, not a source difference.
log "Building a ${FROM_VERSION} stand-in from the current tree"
FROM_DIR="${WORK}/from"
mkdir -p "${FROM_DIR}"
# Payload at the top level, control in DEBIAN/: what `dpkg-deb --build` expects.
# Extracting the payload into a `root/` subdir would ship it under /root/.
dpkg-deb -x "${TO_DEB}" "${FROM_DIR}"
dpkg-deb -e "${TO_DEB}" "${FROM_DIR}/DEBIAN"
sed -i -E "s/^Version: .*/Version: ${FROM_VERSION}/" "${FROM_DIR}/DEBIAN/control"
# The CLI reads __version__ from the packaged package, so the stand-in must
# report the old version too -- otherwise "before" and "after" would be equal
# and the upgrade would not be exercised.
sed -i -E "s/^__version__ = \"[^\"]+\"/__version__ = \"${FROM_VERSION}\"/" \
    "${FROM_DIR}/usr/lib/klyrshift/klyrshift/__init__.py"
# Regenerate the manifest so `klyrshift verify` inside the old package is honest.
( cd "${FROM_DIR}" && find . -path ./DEBIAN -prune -o -type f -printf '%P\n' | sort \
    | while read -r f; do
        printf '%s  %s\n' "$(md5sum "${f}" | cut -d' ' -f1)" "./${f#./}"
      done ) > "${FROM_DIR}/DEBIAN/md5sums"
FROM_DEB="${WORK}/klyrshift_${FROM_VERSION}_all.deb"
dpkg-deb --build --root-owner-group "${FROM_DIR}" "${FROM_DEB}" >/dev/null

DEB_DIR="$(cd "$(dirname "${TO_DEB}")" && pwd)"
TO_DEB_NAME="$(basename "${TO_DEB}")"
FROM_DEB_NAME="$(basename "${FROM_DEB}")"

# The container script is written to a file and mounted, rather than passed as a
# nested `bash -c "..."`: the quoting inside a heredoc that itself contains
# heredocs is fragile, and a failure there reads as "the package is broken".
cat > "${WORK}/run.sh" <<'CONTAINER_SCRIPT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
FROM_VERSION="$1"
TO_VERSION="$2"
FROM_DEB_NAME="$3"
TO_DEB_NAME="$4"

apt-get update -qq
apt-get install -y -qq "/work/${FROM_DEB_NAME}" >/dev/null 2>&1

# A user config that must survive the upgrade.
mkdir -p /root/.config/klyrshift
cat > /root/.config/klyrshift/config.toml <<'CFG'
mode = "manual"
min_word_length = 4
# marker-for-upgrade-test
CFG

before="$(klyrshift version 2>/dev/null || true)"
echo "[patch-upgrade] installed version: ${before}"
case "${before}" in
  *"${FROM_VERSION}"*) ;;
  *) echo "[patch-upgrade] FAIL: expected ${FROM_VERSION} before upgrade, got '${before}'" >&2; exit 1 ;;
esac

apt-get install -y -qq "/to/${TO_DEB_NAME}" >/dev/null 2>&1

after="$(klyrshift version 2>/dev/null || true)"
echo "[patch-upgrade] upgraded version: ${after}"
case "${after}" in
  *"${TO_VERSION}"*) ;;
  *) echo "[patch-upgrade] FAIL: expected ${TO_VERSION} after upgrade, got '${after}'" >&2; exit 1 ;;
esac

# 1. The user's config survived, byte for byte.
grep -q 'marker-for-upgrade-test' /root/.config/klyrshift/config.toml \
  || { echo '[patch-upgrade] FAIL: user config was lost' >&2; exit 1; }
grep -q 'min_word_length = 4' /root/.config/klyrshift/config.toml \
  || { echo '[patch-upgrade] FAIL: user config value was changed' >&2; exit 1; }

# 2. The daemon unit is present and enabled globally.
[ -f /usr/lib/systemd/user/klyrshift.service ] \
  || { echo '[patch-upgrade] FAIL: unit missing' >&2; exit 1; }
ls /etc/systemd/user/*.wants/klyrshift.service >/dev/null 2>&1 \
  || { echo '[patch-upgrade] FAIL: unit not enabled' >&2; exit 1; }

# 3. The package verifies against its own manifest.
klyrshift verify >/dev/null 2>&1 \
  || { echo '[patch-upgrade] FAIL: klyrshift verify failed after upgrade' >&2; exit 1; }

# 4. The CLI still works.
klyrshift --help >/dev/null 2>&1 \
  || { echo '[patch-upgrade] FAIL: klyrshift --help failed' >&2; exit 1; }

echo '[patch-upgrade] all checks passed'
CONTAINER_SCRIPT

log "Installing ${FROM_VERSION} then upgrading to ${TO_VERSION} in ${IMAGE}"
$DOCKER run --rm \
    -v "${WORK}:/work:ro" \
    -v "${DEB_DIR}:/to:ro" \
    "${IMAGE}" bash /work/run.sh "${FROM_VERSION}" "${TO_VERSION}" "${FROM_DEB_NAME}" "${TO_DEB_NAME}" \
    || fail "upgrade checks failed"

log "Patch upgrade ${FROM_VERSION} -> ${TO_VERSION} passed."
