"""Packaging contract: the shipped unit, desktop entry and package data.

These tests guard the artefacts that a broken packaging change would silently
drop: the systemd user unit (a negative ``Nice`` once made the unit restart
forever), the CSS file the GUI needs at runtime, and the build script's own
invariants. They are pure file/config checks so they run in CI without a
graphical session or Docker.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from klyrshift import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIT = REPO_ROOT / "data" / "klyrshift.service"
UNIT_IN_PACKAGE = REPO_ROOT / "src" / "klyrshift" / "data" / "klyrshift.service"
DESKTOP = REPO_ROOT / "data" / "klyrshift.desktop"
GUI_CSS = REPO_ROOT / "src" / "klyrshift" / "gui" / "style.css"
BUILD_DEB = REPO_ROOT / "scripts" / "build_deb.sh"


# --- systemd user unit ------------------------------------------------------


def test_unit_files_are_identical() -> None:
    assert UNIT.read_text(encoding="utf-8") == UNIT_IN_PACKAGE.read_text(encoding="utf-8")


def test_unit_has_no_scheduling_directives() -> None:
    text = UNIT.read_text(encoding="utf-8")
    # A user unit has no CAP_SYS_NICE: a negative Nice or a real-time policy
    # makes systemd treat startup as fatal (exit 201) and the unit never runs.
    active = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("Nice=") for line in active)
    assert not any(line.startswith("CPUSchedulingPolicy") for line in active)


def _active_unit_lines() -> list[str]:
    text = UNIT.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_unit_is_sandboxed() -> None:
    """The daemon reads every keystroke, so its unit drops what it never needs."""
    active = _active_unit_lines()
    for directive in (
        "NoNewPrivileges=yes",
        "LockPersonality=yes",
        "RestrictRealtime=yes",
        "RestrictNamespaces=yes",
        "SystemCallArchitectures=native",
    ):
        assert directive in active
    families = next(line for line in active if line.startswith("RestrictAddressFamilies="))
    allowed = set(families.split("=", 1)[1].split())
    # D-Bus and the control socket, device hotplug, and the opt-in update check.
    assert allowed == {"AF_UNIX", "AF_NETLINK", "AF_INET", "AF_INET6"}


def test_unit_avoids_directives_that_need_user_namespaces() -> None:
    """File-system sandboxing needs a user namespace in a *user* unit.

    Ubuntu restricts unprivileged user namespaces through AppArmor, so
    ``ProtectSystem=``, ``PrivateTmp=`` and friends would make the unit fail
    to start there -- the same restart loop as a negative ``Nice=``.
    """
    active = _active_unit_lines()
    for prefix in (
        "ProtectSystem=",
        "ProtectHome=",
        "PrivateTmp=",
        "PrivateUsers=",
        "PrivateDevices=",
    ):
        assert not any(line.startswith(prefix) for line in active)


def test_offline_drop_in_resets_the_address_families() -> None:
    """The documented offline drop-in must reset the unit's allow-list first.

    systemd merges repeated ``RestrictAddressFamilies=`` allow-lists, so a
    drop-in that only lists ``AF_UNIX AF_NETLINK`` would keep the unit's
    ``AF_INET AF_INET6`` -- the network would stay open.
    """
    doc = (REPO_ROOT / "docs" / "OFFLINE_AND_PRIVACY.md").read_text(encoding="utf-8")
    snippet = doc.split("offline.conf <<'UNIT'", 1)[1].split("UNIT", 1)[0]
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    families = [line for line in lines if line.startswith("RestrictAddressFamilies=")]
    assert families[0] == "RestrictAddressFamilies="
    assert families[-1] == "RestrictAddressFamilies=AF_UNIX AF_NETLINK"


def test_unit_restarts_and_runs_in_foreground() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "Restart=always" in text
    assert "ExecStart=@BIN@ start --foreground" in text
    assert "WantedBy=default.target" in text


def test_desktop_entry_points_at_gui() -> None:
    text = DESKTOP.read_text(encoding="utf-8")
    assert "Exec=@BIN@ gui" in text
    assert "Icon=klyrshift" in text
    assert "StartupWMClass=io.github.pavel1778.Klyrshift" in text


# --- package data -----------------------------------------------------------


def test_gui_css_exists_and_is_declared() -> None:
    assert GUI_CSS.is_file()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # The GUI loads style.css via importlib.resources, so it must be package
    # data or the installed app raises FileNotFoundError at startup.
    assert re.search(r'"klyrshift\.gui"\s*=\s*\["\*\.css"\]', pyproject)


def test_package_data_covers_runtime_assets() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = pyproject.split("[tool.setuptools.package-data]", 1)[1]
    for pattern in ('"data/*.json"', '"data/*.txt"', '"data/*.svg"', '"data/*.desktop"'):
        assert pattern in block, f"package-data is missing {pattern}"


def test_build_script_strips_bytecode() -> None:
    script = BUILD_DEB.read_text(encoding="utf-8")
    # Stale .pyc under the installed tree shadow edited sources and were a
    # reported bug; the build must strip them.
    assert "__pycache__" in script
    assert "*.pyc" in script


def test_postinst_reloads_systemd_user_daemon() -> None:
    script = BUILD_DEB.read_text(encoding="utf-8")
    # Without a daemon-reload after the unit file is replaced, the next
    # ``systemctl --user restart klyrshift.service`` warns that the unit changed
    # on disk.
    assert "systemctl --user daemon-reload" in script


def test_postrm_prunes_nested_bytecode_and_empty_dirs() -> None:
    script = BUILD_DEB.read_text(encoding="utf-8")
    # ``doctor`` imports ``klyrshift.gui``; run as root (before a session
    # exists) that writes root-owned ``gui/__pycache__`` under /usr/lib, which
    # dpkg does not track. The purge must remove every nested ``__pycache__``
    # and prune the now-empty package directories, or the zero-config test
    # finds ``/usr/lib/klyrshift`` leftovers after ``apt remove --purge``.
    assert "find /usr/lib/klyrshift -type d -name '__pycache__'" in script
    assert "find /usr/lib/klyrshift -depth -type d -empty" in script


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb not available")
def test_deb_carries_css_and_unit(tmp_path: Path) -> None:
    """Build a throwaway .deb and assert the GUI CSS and unit are inside it."""
    build = subprocess.run(
        ["bash", str(BUILD_DEB)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    deb = REPO_ROOT / "dist" / f"klyrshift_{__version__}_all.deb"
    assert deb.is_file(), f"build produced no {deb.name}"
    listing = subprocess.run(
        ["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True, check=True
    ).stdout
    assert "/gui/style.css" in listing
    assert "/systemd/user/klyrshift.service" in listing
    assert "/usr/bin/klyrshift" in listing


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb not available")
def test_deb_ships_a_complete_md5sums_manifest(tmp_path: Path) -> None:
    """The built .deb carries an md5sums manifest covering every file.

    ``dpkg-deb --build`` does not write one, so without an explicit step
    ``dpkg --verify klyrshift`` would pass vacuously. Build a throwaway package
    and check the manifest lists exactly the packaged files, with digests that
    match their contents.
    """
    build = subprocess.run(["bash", str(BUILD_DEB)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    deb = REPO_ROOT / "dist" / f"klyrshift_{__version__}_all.deb"

    control = subprocess.run(
        ["dpkg-deb", "--ctrl-tarfile", str(deb)], capture_output=True, check=True
    ).stdout
    listing = subprocess.run(
        ["dpkg-deb", "--fsys-tarfile", str(deb)], capture_output=True, check=True
    ).stdout
    extract = tmp_path / "extract"
    extract.mkdir()
    subprocess.run(["tar", "x", "-C", str(extract)], input=listing, check=True)
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    subprocess.run(["tar", "x", "-C", str(ctrl)], input=control, check=True)
    assert (ctrl / "md5sums").is_file(), "the .deb has no md5sums member"

    entries = dict(
        line.split("  ", 1)[::-1]
        for line in (ctrl / "md5sums").read_text(encoding="utf-8").splitlines()
        if line
    )
    packaged = {str(p.relative_to(extract)) for p in extract.rglob("*") if p.is_file()}
    assert set(entries) == packaged, "manifest does not cover exactly the packaged files"

    for path, digest in entries.items():
        actual = hashlib.md5((extract / path).read_bytes()).hexdigest()
        assert actual == digest, f"{path}: manifest digest does not match content"


# --- Debian policy: copyright and changelog ---------------------------------


COPYRIGHT = REPO_ROOT / "data" / "copyright"


def test_copyright_file_exists_and_is_dep5() -> None:
    """Debian Policy 12.5: the package must ship a copyright statement.

    The base frequency lists are FrequencyWords *content* (CC-BY-SA-4.0), not
    MIT like the code, so the package must attribute them. Without this file the
    lists shipped with no licence statement at all.
    """
    text = COPYRIGHT.read_text(encoding="utf-8")
    assert text.startswith("Format: https://www.debian.org/doc/packaging-manuals/")
    assert "License: MIT" in text
    assert "CC-BY-SA-4.0" in text
    # The content licence must cover the bundled lists, and only those. The
    # glob has to name a path that actually exists: the lists live in
    # ``dictionaries/`` at the repository root, and the build script installs
    # them to ``<pkg>/data/dictionaries/`` inside the package.
    assert "dictionaries/*-50k.txt" in text


def test_copyright_glob_matches_the_files_it_claims() -> None:
    """A ``Files:`` glob that matches nothing attributes nothing.

    The first draft pointed at ``src/klyrshift/data/dictionaries/*.txt``, a path
    that exists neither in the repository (the lists live in ``dictionaries/``)
    nor in the installed package, so the CC-BY-SA paragraph covered no file at
    all. Resolve every glob instead of trusting the string, and keep the
    in-package path in step with what ``build_deb.sh`` installs.
    """
    text = COPYRIGHT.read_text(encoding="utf-8")

    patterns: list[str] = []
    in_files_field = False
    for line in text.splitlines():
        if line.startswith("Files:"):
            in_files_field = True
            patterns.append(line[len("Files:") :].strip())
        elif in_files_field and line[:1] == " " and line.strip():
            patterns.append(line.strip())
        else:
            in_files_field = False

    patterns = [p for p in patterns if p and p != "*"]
    assert patterns, "copyright declares no file-specific stanza"

    repo_patterns = [p for p in patterns if not p.startswith("usr/")]
    assert repo_patterns, "the content stanza names no repository path"
    for pattern in repo_patterns:
        assert list(REPO_ROOT.glob(pattern)), f"{pattern!r} matches no file"

    # The installed copy must land where the build script puts the lists:
    # /usr/lib/<pkg>/<pkg>/data/dictionaries/.
    script = BUILD_DEB.read_text(encoding="utf-8")
    install_dir = "/usr/lib/${PKG}/${PKG}/data/dictionaries/"
    assert install_dir in script
    expected_pkg_dir = install_dir.replace("${PKG}", "klyrshift").lstrip("/")
    assert any(
        p.startswith(expected_pkg_dir) for p in patterns
    ), f"no Files: glob covers {expected_pkg_dir!r}"


def test_copyright_names_the_upstream_source() -> None:
    """CC-BY-SA requires attribution, so the upstream must be named."""
    text = COPYRIGHT.read_text(encoding="utf-8")
    assert "hermitdave/FrequencyWords" in text
    assert "CC-BY-SA-4.0" in text


def _is_debian() -> bool:
    """Return whether the host is Debian, whose ``base-files`` adds CC licences.

    The presence of ``/usr/share/common-licenses`` is not enough to tell: Ubuntu
    ships the directory too, but its ``base-files`` carries only the GNU
    licences, so ``CC-BY-SA-4.0`` is absent there and the check would fail on a
    runner that is not the target platform.
    """
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(line.strip() == "ID=debian" for line in release.splitlines())


def test_copyright_points_at_a_license_that_debian_ships() -> None:
    """A reference to a licence file that does not exist is worse than none."""
    text = COPYRIGHT.read_text(encoding="utf-8")
    referenced = re.findall(r"/usr/share/common-licenses/([A-Za-z0-9+-]+(?:\.[0-9]+)*)", text)
    assert referenced, "copyright references no on-disk licence text"
    if not _is_debian():
        pytest.skip("the common-licenses layout is only fixed on Debian")
    for name in referenced:
        path = Path("/usr/share/common-licenses") / name
        assert path.is_file(), f"{path} does not exist"


def test_build_script_installs_copyright_and_changelog() -> None:
    script = BUILD_DEB.read_text(encoding="utf-8")
    assert "/usr/share/doc/${PKG}/copyright" in script
    assert "changelog.gz" in script


def test_dictionaries_are_attributed_in_the_interface() -> None:
    """The GUI and the landing page must not claim the lists are MIT-only."""
    site_data = (REPO_ROOT / "site" / "src" / "lib" / "dictionaries.ts").read_text(encoding="utf-8")
    assert "CC-BY-SA-4.0" in site_data
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "CC-BY-SA-4.0" in readme


def test_package_declares_the_rename_relationship() -> None:
    """The renamed package must supersede both earlier names.

    dpkg treats a rename as unrelated packages: without a relationship,
    ``apt install klyrshift_*.deb`` on a machine that has ``linguafix`` (the
    published name) or ``lingvix`` (the name used between the two renames) leaves
    both installed, and both keep a systemd user unit enabled at login, so two
    daemons run at once. Verified in debian:13 -- with ``Conflicts``/``Replaces``
    the old package is removed and only ``klyrshift.service`` stays enabled.
    """
    script = BUILD_DEB.read_text(encoding="utf-8")
    assert "Conflicts: linguafix, lingvix" in script
    assert "Replaces: linguafix, lingvix" in script


def test_package_recommends_a_layout_backend_that_exists_in_debian() -> None:
    """A fresh Debian install must end up with a working layout backend.

    ``g3kb-switch`` (the Wayland backend) is not in the Debian repositories --
    ``apt-cache policy g3kb-switch`` has no candidate on Debian 12 or 13 -- so it
    cannot be a ``Depends``. ``setxkbmap`` ships in ``x11-xkb-utils``, which is
    in Debian. Verified in debian:13: without ``x11-xkb-utils`` a plain
    ``apt install ./klyrshift.deb`` reports ``backend=none``; with it,
    ``backend=setxkbmap``.
    """
    script = BUILD_DEB.read_text(encoding="utf-8")
    assert "x11-xkb-utils" in script


def test_release_workflow_only_fires_on_release_tags() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # A stage tag such as ``v0.2.0-stage2`` must never publish a release, or it
    # would ship the previous version's .deb under the stage name.
    assert "tags:" in text
    assert '"v[0-9]+.[0-9]+.[0-9]+"' in text


def test_release_workflow_builds_and_verifies_the_deb() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "build_deb.sh" in text
    assert "smoke_test.sh" in text
    assert "deb_selfsufficiency_test.sh" in text
    assert "upgrade_test.sh" in text
    assert "action-gh-release" in text


# --- CI workflow ------------------------------------------------------------


def test_ci_jobs_have_a_timeout() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # A stuck runner once left the Python 3.12 job pending for ~49 minutes; a
    # timeout-minutes on every job bounds that instead of hanging the check.
    _, _, jobs_text = text.partition("\njobs:\n")
    assert jobs_text, "ci.yml has no jobs section"
    jobs = re.findall(
        r"(?m)^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        jobs_text,
        re.S,
    )
    assert jobs, "ci.yml declares no jobs"
    for name, body in jobs:
        assert re.search(
            r"(?m)^    timeout-minutes:\s*\d+", body
        ), f"CI job {name!r} has no timeout-minutes"
