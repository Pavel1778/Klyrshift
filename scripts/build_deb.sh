#!/usr/bin/env bash
#
# Build a Debian package for Klyrshift without dh_make, using dpkg-deb directly.
#
# Layout of the resulting package:
#   /usr/bin/klyrshift                              launcher wrapper
#   /usr/lib/klyrshift/klyrshift/...                Python package + data
#   /usr/share/applications/klyrshift.desktop       desktop entry
#   /usr/share/icons/hicolor/scalable/apps/*.svg    icon
#   /usr/lib/systemd/user/klyrshift.service         systemd user unit
#   /usr/lib/udev/rules.d/71-klyrshift.rules        udev rule
#   /usr/share/man/man1/klyrshift.1                 man page
#   /usr/share/bash-completion/completions/klyrshift  bash completion
#   /usr/share/zsh/vendor-completions/_klyrshift    zsh completion
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"
PKG="klyrshift"
ARCH="all"
BUILD_DIR="${REPO_DIR}/build/${PKG}_${VERSION}_${ARCH}"
DIST_DIR="${REPO_DIR}/dist"

echo "[klyrshift] Building ${PKG} ${VERSION} (${ARCH})"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
# A setgid bit inherited from the parent directory makes dpkg-deb reject the
# control directory, so strip it explicitly.
chmod g-s "${BUILD_DIR}" "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/${PKG}"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${BUILD_DIR}/usr/lib/systemd/user"
mkdir -p "${BUILD_DIR}/usr/lib/udev/rules.d"
mkdir -p "${BUILD_DIR}/usr/share/man/man1"
mkdir -p "${BUILD_DIR}/usr/share/bash-completion/completions"
mkdir -p "${BUILD_DIR}/usr/share/zsh/vendor-completions"
mkdir -p "${BUILD_DIR}/usr/share/doc/${PKG}"
mkdir -p "${DIST_DIR}"

# --- Python package ---------------------------------------------------------
cp -r "${REPO_DIR}/src/${PKG}" "${BUILD_DIR}/usr/lib/${PKG}/${PKG}"
find "${BUILD_DIR}/usr/lib/${PKG}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${BUILD_DIR}/usr/lib/${PKG}" -name '*.pyc' -delete
# Ship the frequency dictionaries inside the package so ``dict download`` works
# offline (and so the lists are present on the user's machine without a network
# fetch). The source of truth is the repository ``dictionaries/`` folder.
install -d "${BUILD_DIR}/usr/lib/${PKG}/${PKG}/data/dictionaries"
install -m 0644 "${REPO_DIR}"/dictionaries/*-50k.txt \
    "${BUILD_DIR}/usr/lib/${PKG}/${PKG}/data/dictionaries/"
# Normalise permissions regardless of the developer's umask.
chmod -R a+rX "${BUILD_DIR}/usr/lib/${PKG}"

# --- Launcher wrapper -------------------------------------------------------
cat > "${BUILD_DIR}/usr/bin/${PKG}" <<'EOF'
#!/bin/sh
# Klyrshift launcher: run the packaged module with the system Python.
PYTHONPATH="/usr/lib/klyrshift${PYTHONPATH:+:${PYTHONPATH}}" \
    exec /usr/bin/python3 -m klyrshift "$@"
EOF
chmod 0755 "${BUILD_DIR}/usr/bin/${PKG}"

# --- Data files -------------------------------------------------------------
install -m 0644 "${REPO_DIR}/data/${PKG}.svg" \
    "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps/${PKG}.svg"
# The service and desktop files carry a "@BIN@" placeholder for the launcher
# path: install.sh renders it with the venv binary, the .deb with /usr/bin.
render_unit() {
    local src="$1" dest="$2" bin="$3"
    sed "s|@BIN@|${bin}|g" "${src}" > "${dest}"
    chmod 0644 "${dest}"
}
render_unit "${REPO_DIR}/data/${PKG}.desktop" \
    "${BUILD_DIR}/usr/share/applications/${PKG}.desktop" "/usr/bin/${PKG}"
render_unit "${REPO_DIR}/data/${PKG}.service" \
    "${BUILD_DIR}/usr/lib/systemd/user/${PKG}.service" "/usr/bin/${PKG}"
install -m 0644 "${REPO_DIR}/data/71-${PKG}.rules" \
    "${BUILD_DIR}/usr/lib/udev/rules.d/71-${PKG}.rules"

# --- Manual page and shell completion ---------------------------------------
# Debian Policy 12.1 expects every binary to ship a man page; without one
# lintian reports ``no-manual-page``. Both files are generated from the live
# argument parser (scripts/build_cli_docs.py), so they cannot describe a
# command that no longer exists. ``make cli-docs`` regenerates them; the test
# suite fails if the committed copies drift.
install -m 0644 "${REPO_DIR}/data/${PKG}.1" \
    "${BUILD_DIR}/usr/share/man/man1/${PKG}.1"
# Debian Policy 12.1 wants man pages compressed; lintian reports
# ``uncompressed-manual-page`` at error level otherwise. ``-n`` keeps the
# timestamp out of the archive so the build stays reproducible. The user-level
# copy install.sh writes stays uncompressed, which is what man-db expects under
# ``~/.local/share/man``.
gzip -9n "${BUILD_DIR}/usr/share/man/man1/${PKG}.1"
install -m 0644 "${REPO_DIR}/data/completions/${PKG}.bash" \
    "${BUILD_DIR}/usr/share/bash-completion/completions/${PKG}"
install -m 0644 "${REPO_DIR}/data/completions/_${PKG}" \
    "${BUILD_DIR}/usr/share/zsh/vendor-completions/_${PKG}"

# --- Documentation ----------------------------------------------------------
# Debian Policy 12.5 requires every binary package to ship its copyright and
# licence statement under /usr/share/doc/<package>. Without it the base
# frequency lists -- which are CC-BY-SA-4.0 content, not MIT -- ship with no
# attribution at all.
install -m 0644 "${REPO_DIR}/data/copyright" \
    "${BUILD_DIR}/usr/share/doc/${PKG}/copyright"
# Debian Policy 12.7 asks for the upstream changelog as changelog.gz. Lintian
# validates its syntax as a Debian changelog, so a Keep a Changelog file copied
# here raises ``syntax-error-in-debian-changelog``. Emit a minimal Debian-format
# entry that points at the real history, and ship that history alongside it.
cat > "${BUILD_DIR}/usr/share/doc/${PKG}/changelog" <<EOF
${PKG} (${VERSION}) unstable; urgency=medium

  * Upstream release ${VERSION}. The full, human-readable history lives in
    /usr/share/doc/${PKG}/CHANGELOG.md.

 -- Pavel1778 <noreply@github.com>  $(date -R)
EOF
gzip -9n "${BUILD_DIR}/usr/share/doc/${PKG}/changelog"
install -m 0644 "${REPO_DIR}/CHANGELOG.md" \
    "${BUILD_DIR}/usr/share/doc/${PKG}/CHANGELOG.md"

# --- DEBIAN/control ---------------------------------------------------------
# The package was renamed twice -- ``linguafix`` -> ``lingvix`` -> ``klyrshift`` --
# which dpkg sees as three unrelated packages: without a relationship, installing
# the new .deb leaves the old one installed, and *both* keep a systemd user unit
# enabled at login, so two daemons fight over the keyboard. ``Conflicts`` makes apt
# remove the old package first; ``Replaces`` is the counterpart Debian Policy asks
# for when one package supersedes another. Both earlier names are listed: the
# published ``linguafix`` package and the ``lingvix`` name that was used in the
# source (and in locally built .debs) between the two renames. The installed-file
# paths do not overlap, so the removal is a plain uninstall, not a file takeover.
INSTALLED_SIZE="$(du -sk "${BUILD_DIR}" | cut -f1)"
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-tomli | python3 (>= 3.11), python3-tomli-w, python3-evdev, libnotify-bin, wtype, librsvg2-common, hicolor-icon-theme
Recommends: g3kb-switch, xdotool, x11-xkb-utils, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-appindicator3-0.1, python3-pyatspi, gir1.2-atspi-2.0, wl-clipboard, xclip
Conflicts: linguafix, lingvix
Replaces: linguafix, lingvix
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Pavel1778 <noreply@github.com>
Homepage: https://github.com/Pavel1778/Klyrshift
Description: Automatic keyboard layout switcher for Debian GNOME
 Klyrshift is a background daemon that detects text typed in the wrong
 keyboard layout (for example "ghbdtn" instead of "привет") and fixes it
 automatically. It works on both X11 and Wayland.
EOF

# --- DEBIAN/postinst --------------------------------------------------------
# The package is zero-config: installing it must not ask the user to run
# usermod, to relogin or to enable anything by hand.
#
#   * device access is granted by the udev rule via TAG+="uaccess" (see
#     data/71-klyrshift.rules), so no group membership is touched;
#   * the uinput module is loaded so /dev/uinput appears;
#   * the user unit is enabled globally so it starts at the next login. It is
#     deliberately not started here: the package may be installed without a
#     running graphical session.
cat > "${BUILD_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

# Reload udev so the uaccess ACLs are applied to the device nodes.
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi

# Refresh the desktop database so the application menu shows Klyrshift right
# after installation, without waiting for a re-login or a desktop refresh.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi

# Rebuild the icon cache so the launcher picks up the icon immediately.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

# Load uinput so /dev/uinput exists (best effort; a container may lack it).
if command -v modprobe >/dev/null 2>&1; then
    modprobe uinput 2>/dev/null || true
fi

# Reload the systemd user manager after the unit file was replaced, so a later
# ``systemctl --user restart klyrshift.service`` does not warn that the unit
# changed on disk. Best effort: an install without a running user bus still
# succeeds.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

# Enable the user unit for every user, without touching anyone's session.
# --global writes the symlink under /etc/systemd/user, which is what makes the
# service start on the next login. Do not fail the install if systemd is absent.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user enable --global klyrshift.service >/dev/null 2>&1 || true
fi

echo "Klyrshift установлен. Сервис запустится при следующем входе в сессию."
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/postinst"

# --- DEBIAN/prerm -----------------------------------------------------------
# Called on remove and on upgrade. Disable the global enablement so an upgrade
# can re-establish it, and stop the unit for any user who has a session.
cat > "${BUILD_DIR}/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --global klyrshift.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/prerm"

# --- DEBIAN/postrm ----------------------------------------------------------
# On purge, remove the global enablement and the per-user state, and reload
# udev so the ACLs are dropped. Other users' data is never touched beyond the
# files that belong to this package.
cat > "${BUILD_DIR}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

case "${1:-}" in
    remove|purge)
        # Running the CLI (and ``doctor``) as root leaves root-owned bytecode
        # under /usr/lib, which dpkg does not track. Drop it, then prune the
        # directories it leaves empty, so a purge leaves nothing behind.
        if command -v py3clean >/dev/null 2>&1; then
            py3clean /usr/lib/klyrshift >/dev/null 2>&1 || true
        fi
        if [ -d /usr/lib/klyrshift ]; then
            find /usr/lib/klyrshift -type d -name '__pycache__' \
                -prune -exec rm -rf {} + 2>/dev/null || true
            find /usr/lib/klyrshift -depth -type d -empty \
                -exec rmdir {} + 2>/dev/null || true
        fi
        ;;
esac

case "${1:-}" in
    purge)
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --user disable --global klyrshift.service >/dev/null 2>&1 || true
        fi
        rm -rf /etc/systemd/user/default.target.wants/klyrshift.service
        # Per-user state for the user that requested the install, when known.
        for candidate in "${SUDO_USER:-}" "${USER:-}"; do
            [ -n "${candidate}" ] || continue
            [ "${candidate}" = "root" ] && continue
            home="$(getent passwd "${candidate}" | cut -d: -f6)"
            [ -n "${home}" ] || continue
            rm -rf "${home}/.config/klyrshift" \
                   "${home}/.local/share/klyrshift" \
                   "${home}/.local/state/klyrshift" \
                   "${home}/.cache/klyrshift"
        done
        ;;
esac

if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi
exit 0
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/postrm"

# --- Build ------------------------------------------------------------------
# Ship an md5sums manifest so ``dpkg --verify klyrshift`` (and our own
# ``klyrshift verify``) can detect a file that was truncated, corrupted or
# edited after installation. ``dpkg-deb --build`` does not generate one, so it
# is written here: one ``<md5>  <path>`` line per regular file, paths relative
# to the filesystem root, which is the format dpkg expects.
( cd "${BUILD_DIR}" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' \
    | sort -z | xargs -0 md5sum ) > "${BUILD_DIR}/DEBIAN/md5sums"

dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DIST_DIR}/${PKG}_${VERSION}_${ARCH}.deb"

echo "[klyrshift] Package built: ${DIST_DIR}/${PKG}_${VERSION}_${ARCH}.deb"
