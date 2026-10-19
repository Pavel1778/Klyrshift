"""The versioned, checksummed language-package format.

A package is a ``.tar.gz`` with a ``manifest.json`` that records the format
version, the language, the kind, the licence, the provenance and the SHA-256 of
every member. The tests pin the four properties the roadmap asks for:

* a package round-trips (build -> read manifest -> verify -> install);
* a tampered member is refused before anything is written;
* an undeclared member is refused;
* a failed install rolls back to the previous dictionaries.

Nothing here receives typed text, and the tests assert that too: a package is a
curated word list.
"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

import pytest

from klyrshift import langpack
from klyrshift.langpack import (
    FORMAT_VERSION,
    MANIFEST_NAME,
    Manifest,
    PackageError,
    build_package,
    install_package,
    read_manifest,
    sha256_bytes,
    uninstall_package,
    verify_package,
)


@pytest.fixture
def word_file(tmp_path: Path) -> Path:
    """Return a small word list on disk."""
    path = tmp_path / "ru-50k.txt"
    path.write_text("привет\nмир\nкод\n", encoding="utf-8")
    return path


@pytest.fixture
def package(tmp_path: Path, word_file: Path) -> Path:
    """Return a built package containing one word list."""
    destination = tmp_path / "ru-50k.tar.gz"
    build_package(
        [word_file],
        destination,
        name="ru-50k",
        language="ru",
        kind="frequency",
        version="1.2.3",
        license="MIT",
        source="test",
        created="2026-10-19T00:00:00Z",
    )
    return destination


def test_build_and_read_manifest(package: Path) -> None:
    manifest = read_manifest(package)
    assert manifest.name == "ru-50k"
    assert manifest.language == "ru"
    assert manifest.kind == "frequency"
    assert manifest.version == "1.2.3"
    assert manifest.format == FORMAT_VERSION
    assert manifest.license == "MIT"
    assert [f.name for f in manifest.files] == ["ru-50k.txt"]
    assert manifest.files[0].words == 3


def test_build_is_reproducible(tmp_path: Path, word_file: Path) -> None:
    """A fixed input produces a byte-identical archive (so it can be pinned)."""
    first = tmp_path / "a.tar.gz"
    second = tmp_path / "b.tar.gz"
    for destination in (first, second):
        build_package(
            [word_file],
            destination,
            name="ru-50k",
            language="ru",
            created="2026-10-19T00:00:00Z",
        )
    assert first.read_bytes() == second.read_bytes()


def test_verify_passes_for_a_good_package(package: Path) -> None:
    assert verify_package(package) == []


def test_install_writes_the_files(package: Path, tmp_path: Path) -> None:
    base = tmp_path / "dictionaries"
    result = install_package(package, base)
    assert result.manifest.name == "ru-50k"
    installed = base / "ru-50k.txt"
    assert installed.read_text(encoding="utf-8").startswith("привет")
    assert installed in result.installed


def test_install_replaces_and_reports_the_previous_file(package: Path, tmp_path: Path) -> None:
    base = tmp_path / "dictionaries"
    base.mkdir(parents=True)
    (base / "ru-50k.txt").write_text("старый\n", encoding="utf-8")
    result = install_package(package, base)
    assert (base / "ru-50k.txt") in result.replaced
    assert "привет" in (base / "ru-50k.txt").read_text(encoding="utf-8")
    assert not (base / "ru-50k.txt.bak").exists()


def test_thematic_kind_installs_into_its_subdirectory(package: Path, tmp_path: Path) -> None:
    thematic = tmp_path / "medicine.tar.gz"
    source = tmp_path / "ru-medicine-1k.txt"
    source.write_text("диагноз\nтерапия\n", encoding="utf-8")
    build_package([source], thematic, name="medicine", language="ru", kind="thematic")
    base = tmp_path / "dictionaries"
    install_package(thematic, base)
    assert (base / "thematic" / "ru" / "ru-medicine-1k.txt").is_file()


def test_tampered_member_is_refused(package: Path, tmp_path: Path) -> None:
    """A member whose bytes no longer match the manifest is refused."""
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(package, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            stream = src.extractfile(member) if member.isfile() else None
            payload = stream.read() if stream is not None else b""
            if member.name == "ru-50k.txt":
                payload = b"evil\n"
            info = tarfile.TarInfo(member.name)
            info.size = len(payload)
            info.mtime = 0
            import io

            dst.addfile(info, io.BytesIO(payload))

    problems = verify_package(tampered)
    assert any("checksum mismatch" in p for p in problems)

    base = tmp_path / "dictionaries"
    with pytest.raises(PackageError, match="integrity"):
        install_package(tampered, base)
    # Nothing was written.
    assert not (base / "ru-50k.txt").exists()


def test_undeclared_member_is_refused(package: Path, tmp_path: Path) -> None:
    """An archive carrying a file the manifest does not describe is refused."""
    extra = tmp_path / "extra.tar.gz"
    with tarfile.open(package, "r:gz") as src, tarfile.open(extra, "w:gz") as dst:
        import io

        for member in src.getmembers():
            stream = src.extractfile(member) if member.isfile() else None
            payload = stream.read() if stream is not None else b""
            info = tarfile.TarInfo(member.name)
            info.size = len(payload)
            info.mtime = 0
            dst.addfile(info, io.BytesIO(payload))
        payload = b"surprise\n"
        info = tarfile.TarInfo("surprise.txt")
        info.size = len(payload)
        info.mtime = 0
        dst.addfile(info, io.BytesIO(payload))

    problems = verify_package(extra)
    assert any("undeclared member" in p for p in problems)


def test_install_rolls_back_when_a_later_member_fails(
    tmp_path: Path, word_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a later file cannot be committed, the earlier one is restored.

    A real filesystem error is hard to trigger deterministically, so the failure
    is injected at the commit primitive (``os.replace``) on its second call.
    That is the exact call the rollback wraps, so this exercises the real
    rollback path rather than a stand-in for it.
    """
    second = tmp_path / "en-50k.txt"
    second.write_text("hello\nworld\n", encoding="utf-8")
    package = tmp_path / "multi.tar.gz"
    build_package([word_file, second], package, name="multi", language="ru")

    base = tmp_path / "dictionaries"
    base.mkdir(parents=True)
    original = base / "ru-50k.txt"
    original.write_text("оригинал\n", encoding="utf-8")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src: object, dst: object) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated"):
        install_package(package, base)

    # The file committed before the failure is back to its original contents.
    assert original.read_text(encoding="utf-8") == "оригинал\n"
    assert not (base / "ru-50k.txt.bak").exists()
    assert not (base / "en-50k.txt.bak").exists()
    # No staging leftovers.
    assert [p.name for p in base.iterdir() if p.name.startswith(".")] == []


def test_newer_format_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "future.tar.gz"
    import io

    manifest = {
        "format": FORMAT_VERSION + 1,
        "name": "ru-50k",
        "language": "ru",
        "kind": "frequency",
        "files": [{"name": "ru-50k.txt", "sha256": "0" * 64}],
    }
    payload = json.dumps(manifest).encode("utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(PackageError, match="newer than this build"):
        read_manifest(archive)


def test_manifest_rejects_a_path_as_a_member_name() -> None:
    with pytest.raises(PackageError, match="plain name"):
        Manifest.from_dict(
            {
                "name": "x",
                "language": "ru",
                "files": [{"name": "../etc/passwd", "sha256": "0" * 64}],
            }
        )


def test_manifest_rejects_an_unknown_kind() -> None:
    with pytest.raises(PackageError, match="unknown package kind"):
        Manifest.from_dict(
            {
                "name": "x",
                "language": "ru",
                "kind": "malware",
                "files": [{"name": "a.txt", "sha256": "0" * 64}],
            }
        )


def test_uninstall_removes_the_named_files(package: Path, tmp_path: Path) -> None:
    base = tmp_path / "dictionaries"
    install_package(package, base)
    removed = uninstall_package("frequency", "ru", ["ru-50k.txt"], base)
    assert removed == [base / "ru-50k.txt"]
    assert not (base / "ru-50k.txt").exists()


def test_build_refuses_an_empty_file_list(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="at least one file"):
        build_package([], tmp_path / "empty.tar.gz", name="x", language="ru")


def test_package_carries_no_typed_text(package: Path) -> None:
    """A package is a curated list; the only text is the list itself."""
    manifest = read_manifest(package)
    assert {f.name for f in manifest.files} == {"ru-50k.txt"}
    with tarfile.open(package, "r:gz") as archive:
        names = set(archive.getnames())
    assert names == {MANIFEST_NAME, "ru-50k.txt"}


def test_sha256_bytes_matches_hashlib() -> None:
    import hashlib

    assert sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_langpack_has_no_network_import() -> None:
    """The format module must not reach the network (offline guarantee)."""
    source = Path(langpack.__file__).read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "socket" not in source
    assert "requests" not in source
