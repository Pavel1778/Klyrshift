"""Tests for :mod:`klyrshift.integrity` -- the package integrity check.

The manifest is written by ``scripts/build_deb.sh`` (``dpkg-deb --build`` does
not emit one), so these tests build a manifest against a throwaway tree and
verify it, rather than relying on a real ``.deb`` being installed. The one thing
the tests cannot do is prove that ``build_deb.sh`` writes a *complete* manifest;
``scripts/deb_selfsufficiency_test.sh`` checks that against a real package.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from klyrshift import integrity


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


@pytest.fixture
def fake_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the dpkg info directory at a throwaway tree."""
    info = tmp_path / "info"
    info.mkdir()
    monkeypatch.setattr(integrity, "_INFO_DIR", info)
    return info


def _write_manifest(info: Path, package: str, entries: dict[str, str]) -> Path:
    manifest = info / f"{package}.md5sums"
    manifest.write_text(
        "".join(f"{digest}  {path.lstrip('/')}\n" for path, digest in entries.items()),
        encoding="utf-8",
    )
    return manifest


def test_parse_manifest_basic() -> None:
    parsed = integrity.parse_manifest("abc123  usr/lib/klyrshift/x.py\ndef456  etc/klyrshift/foo\n")
    assert parsed == {
        "/usr/lib/klyrshift/x.py": "abc123",
        "/etc/klyrshift/foo": "def456",
    }


def test_parse_manifest_tolerates_binary_marker_and_blanks() -> None:
    parsed = integrity.parse_manifest("\n\na1  *bin/tool\n   \n")
    assert parsed == {"/bin/tool": "a1"}


def test_parse_manifest_ignores_malformed_lines() -> None:
    assert integrity.parse_manifest("garbage-without-a-digest\n") == {}


def test_manifest_path_none_when_absent(fake_info: Path) -> None:
    assert integrity.manifest_path("klyrshift") is None


def test_manifest_path_accepts_arch_qualified(fake_info: Path) -> None:
    (fake_info / "klyrshift:all.md5sums").write_text("", encoding="utf-8")
    assert integrity.manifest_path("klyrshift") == fake_info / "klyrshift:all.md5sums"


def test_verify_package_ok(fake_info: Path, tmp_path: Path) -> None:
    real = tmp_path / "installed.py"
    real.write_text("print('hi')\n", encoding="utf-8")
    _write_manifest(fake_info, "klyrshift", {str(real): _md5(real)})

    report = integrity.verify_package("klyrshift")
    assert report.ok
    assert report.manifest == fake_info / "klyrshift.md5sums"
    assert len(report.files) == 1
    assert report.files[0].status == integrity.OK


def test_verify_package_detects_modified(fake_info: Path, tmp_path: Path) -> None:
    real = tmp_path / "installed.py"
    real.write_text("print('hi')\n", encoding="utf-8")
    _write_manifest(fake_info, "klyrshift", {str(real): _md5(real)})

    real.write_text("print('tampered')\n", encoding="utf-8")
    report = integrity.verify_package("klyrshift")
    assert not report.ok
    assert report.modified == [str(real)]
    assert report.missing == []


def test_verify_package_detects_missing(fake_info: Path, tmp_path: Path) -> None:
    gone = tmp_path / "gone.py"
    _write_manifest(fake_info, "klyrshift", {str(gone): "0" * 32})
    report = integrity.verify_package("klyrshift")
    assert not report.ok
    assert report.missing == [str(gone)]
    assert report.modified == []
    assert report.excluded == []


def test_parse_path_rules_reads_exclude_and_include() -> None:
    rules = integrity._parse_path_rules(
        "# comment\n"
        "path-exclude=/usr/share/man/*\n"
        "\n"
        "path-include=/usr/share/man/man1/*\n"
        "path-exclude = /usr/share/doc/*\n"
    )
    assert rules == [
        (False, "/usr/share/man/*"),
        (True, "/usr/share/man/man1/*"),
        (False, "/usr/share/doc/*"),
    ]


def test_parse_path_rules_accepts_a_space_separator() -> None:
    """Real dpkg configs separate the keyword from the glob with whitespace.

    ``/etc/dpkg/dpkg.cfg.d/docker`` ships ``path-exclude /usr/share/man/*`` and
    Ubuntu's image does the same, so an ``=``-only parser reads zero rules and
    the exclusion is never recognised on the systems the check exists for.
    """
    rules = integrity._parse_path_rules(
        "path-exclude /usr/share/doc/*\n"
        "path-include /usr/share/doc/*/copyright\n"
        "path-exclude=/usr/share/man/*\n"
        "path-exclude\t/usr/share/info/*\n"
    )
    assert rules == [
        (False, "/usr/share/doc/*"),
        (True, "/usr/share/doc/*/copyright"),
        (False, "/usr/share/man/*"),
        (False, "/usr/share/info/*"),
    ]


def test_excluded_by_policy_last_rule_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later matching rule decides, so an include can override an exclude."""
    monkeypatch.setattr(
        integrity,
        "_config_texts",
        lambda: [
            "path-exclude=/usr/share/doc/*\npath-include=/usr/share/doc/*/copyright\n",
        ],
    )
    assert integrity._excluded_by_policy("/usr/share/doc/klyrshift/CHANGELOG.md")
    assert not integrity._excluded_by_policy("/usr/share/doc/klyrshift/copyright")


def test_excluded_by_policy_uses_every_config_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        integrity,
        "_config_texts",
        lambda: ["path-exclude=/usr/share/man/*\n", "path-exclude=/usr/share/doc/*\n"],
    )
    assert integrity._excluded_by_policy("/usr/share/man/man1/klyrshift.1.gz")
    assert integrity._excluded_by_policy("/usr/share/doc/klyrshift/CHANGELOG.md")
    assert not integrity._excluded_by_policy("/usr/bin/klyrshift")


def test_verify_package_excluded_file_is_not_missing(
    fake_info: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest entry dpkg's policy drops must not read as corruption.

    Ubuntu's dpkg excludes ``/usr/share/man/*`` and ``/usr/share/doc/*``, so the
    packaged man page and CHANGELOG never reach disk. Before the fix that made a
    healthy install fail ``klyrshift verify`` with two phantom "missing" files.
    """
    monkeypatch.setattr(
        integrity,
        "_config_texts",
        lambda: ["path-exclude=/usr/share/man/*\npath-exclude=/usr/share/doc/*\n"],
    )
    present = tmp_path / "installed.py"
    present.write_text("x", encoding="utf-8")
    gone_man = "/usr/share/man/man1/klyrshift.1.gz"
    gone_doc = "/usr/share/doc/klyrshift/CHANGELOG.md"
    _write_manifest(
        fake_info,
        "klyrshift",
        {str(present): _md5(present), gone_man: "0" * 32, gone_doc: "0" * 32},
    )

    report = integrity.verify_package("klyrshift")
    assert report.ok
    assert report.missing == []
    assert sorted(report.excluded) == sorted([gone_man, gone_doc])
    assert report.matched == 1
    assert integrity.run_verify("klyrshift") == 0


def test_verify_package_still_reports_a_deleted_installed_file(
    fake_info: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An excluded path is tolerated, but a real file removed after install is not."""
    monkeypatch.setattr(integrity, "_config_texts", lambda: ["path-exclude=/usr/share/man/*\n"])
    gone = str(tmp_path / "usr" / "lib" / "klyrshift" / "cli.py")
    _write_manifest(fake_info, "klyrshift", {gone: "0" * 32})
    report = integrity.verify_package("klyrshift")
    assert not report.ok
    assert report.missing == [gone]
    assert report.excluded == []


def test_verify_package_without_manifest_is_not_a_claim(fake_info: Path) -> None:
    """No manifest (source checkout / venv) is not a pass, just no check."""
    report = integrity.verify_package("klyrshift")
    assert report.manifest is None
    assert report.files == []
    assert report.ok  # nothing was found to be wrong


def test_format_report_names_reinstall(fake_info: Path, tmp_path: Path) -> None:
    gone = tmp_path / "gone.py"
    _write_manifest(fake_info, "klyrshift", {str(gone): "0" * 32})
    text = integrity.format_report(integrity.verify_package("klyrshift"))
    assert "отсутствует" in text
    assert "reinstall" in text


def test_format_report_mentions_excluded_files(
    fake_info: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A healthy install with policy-dropped files says so, and never says "missing"."""
    monkeypatch.setattr(integrity, "_config_texts", lambda: ["path-exclude=/usr/share/man/*\n"])
    gone = "/usr/share/man/man1/klyrshift.1.gz"
    _write_manifest(fake_info, "klyrshift", {gone: "0" * 32})
    report = integrity.verify_package("klyrshift")
    text = integrity.format_report(report)
    assert report.ok
    assert "отсутствует" not in text
    assert "пропущено политикой dpkg" in text


def test_format_report_without_manifest_says_so(fake_info: Path) -> None:
    text = integrity.format_report(integrity.verify_package("klyrshift"))
    assert "не установлен из .deb" in text


def test_run_verify_exit_codes(fake_info: Path, tmp_path: Path) -> None:
    real = tmp_path / "installed.py"
    real.write_text("x", encoding="utf-8")
    _write_manifest(fake_info, "klyrshift", {str(real): _md5(real)})
    assert integrity.run_verify("klyrshift") == 0

    real.write_text("y", encoding="utf-8")
    assert integrity.run_verify("klyrshift") == 1


def test_dpkg_verify_returns_none_without_dpkg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrity.shutil, "which", lambda _name: None)
    assert integrity.dpkg_verify("klyrshift") is None


def test_dpkg_verify_returns_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrity.shutil, "which", lambda _name: "/usr/bin/dpkg")
    monkeypatch.setattr(
        integrity.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, "??5?????? c /usr/bin/klyrshift\n", ""
        ),
    )
    out = integrity.dpkg_verify("klyrshift")
    assert out is not None and "klyrshift" in out


def test_dpkg_verify_survives_a_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrity.shutil, "which", lambda _name: "/usr/bin/dpkg")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("exec failed")

    monkeypatch.setattr(integrity.subprocess, "run", boom)
    assert integrity.dpkg_verify("klyrshift") is None
