"""Versioned, checksummed language packages.

A *language package* is a single ``.tar.gz`` that carries one or more word
lists (or an n-gram model) plus a ``manifest.json`` describing them. It is the
transport for everything ``dict download`` / ``dict install`` fetch today, and
it adds the three things the roadmap asks for that a bare word list cannot
give:

* **Integrity.** Every file's SHA-256 is recorded in the manifest and checked
  before anything is written, so a truncated download or a tampered archive is
  refused instead of silently poisoning the detector's vocabulary.
* **Provenance and compatibility.** The manifest names the format version, the
  package version, the language, the kind and the licence, so an installer can
  reject a package built for a newer format than it understands.
* **Atomic install with rollback.** Files are staged next to their destination
  and swapped in one at a time, each previous file kept as a backup; any
  failure restores every file already swapped. A failed update therefore leaves
  the previous dictionaries exactly as they were.

Nothing here receives typed text: a package is a curated list read from disk or
downloaded from a fixed URL, exactly like the lists it replaces.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# Bumped when the manifest or archive layout changes incompatibly. An installer
# refuses a package whose format it does not understand rather than guessing.
FORMAT_VERSION: Final[int] = 1

MANIFEST_NAME: Final[str] = "manifest.json"
# Refuse absurdly large members so a crafted archive cannot fill the disk.
MAX_MEMBER_BYTES: Final[int] = 64 * 1024 * 1024
# Refuse a manifest that lists more files than any real package needs.
MAX_FILES: Final[int] = 256

VALID_KINDS: Final[tuple[str, ...]] = ("frequency", "thematic", "ngrams")

# Where each kind is installed, relative to the extended-dictionary directory.
# ``frequency`` lists sit at the top level (``<dir>/ru.txt``); the other kinds
# are namespaced per language, matching ``thematic.thematic_dir``.
_KIND_DIRS: Final[dict[str, str]] = {
    "frequency": "",
    "thematic": "thematic",
    "ngrams": "ngrams",
}


class PackageError(Exception):
    """A package is malformed, incompatible, or fails its integrity check."""


@dataclass(frozen=True)
class PackageFile:
    """One member of a package: its name, size and recorded checksum."""

    name: str
    sha256: str
    bytes: int = 0
    words: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "name": self.name,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "words": self.words,
        }


@dataclass
class Manifest:
    """The description of a language package."""

    name: str
    language: str
    kind: str = "frequency"
    version: str = "0.0.0"
    format: int = FORMAT_VERSION
    license: str = ""
    source: str = ""
    created: str = ""
    files: list[PackageFile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "format": self.format,
            "name": self.name,
            "kind": self.kind,
            "language": self.language,
            "version": self.version,
            "license": self.license,
            "source": self.source,
            "created": self.created,
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, data: object) -> Manifest:
        """Build a manifest from untrusted JSON, validating every field.

        Raises:
            PackageError: A required field is missing or has the wrong type, the
                format is newer than this build understands, or the kind is
                unknown.
        """
        if not isinstance(data, dict):
            raise PackageError("manifest is not a JSON object")

        raw_format = data.get("format", FORMAT_VERSION)
        if not isinstance(raw_format, int) or isinstance(raw_format, bool):
            raise PackageError("manifest 'format' must be an integer")
        if raw_format > FORMAT_VERSION:
            raise PackageError(
                f"package format {raw_format} is newer than this build "
                f"understands ({FORMAT_VERSION})"
            )

        name = _require_str(data, "name")
        language = _require_str(data, "language")
        kind = str(data.get("kind", "frequency")).strip().lower()
        if kind not in VALID_KINDS:
            raise PackageError(f"unknown package kind {kind!r}; expected one of {VALID_KINDS}")

        raw_files = data.get("files", [])
        if not isinstance(raw_files, list):
            raise PackageError("manifest 'files' must be a list")
        if not raw_files:
            raise PackageError("manifest lists no files")
        if len(raw_files) > MAX_FILES:
            raise PackageError(f"manifest lists more than {MAX_FILES} files")

        files: list[PackageFile] = []
        for entry in raw_files:
            if not isinstance(entry, dict):
                raise PackageError("manifest file entry is not an object")
            file_name = _require_str(entry, "name")
            sha = _require_str(entry, "sha256").lower()
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise PackageError(f"file {file_name!r} has an invalid sha256")
            if Path(file_name).name != file_name or file_name in (".", ".."):
                raise PackageError(f"file {file_name!r} must be a plain name, not a path")
            size = entry.get("bytes", 0)
            words = entry.get("words", 0)
            files.append(
                PackageFile(
                    name=file_name,
                    sha256=sha,
                    bytes=size if isinstance(size, int) and not isinstance(size, bool) else 0,
                    words=words if isinstance(words, int) and not isinstance(words, bool) else 0,
                )
            )

        return cls(
            name=name,
            language=language.lower(),
            kind=kind,
            version=str(data.get("version", "0.0.0")),
            format=raw_format,
            license=str(data.get("license", "")),
            source=str(data.get("source", "")),
            created=str(data.get("created", "")),
            files=files,
        )


def _require_str(data: dict[str, Any], key: str) -> str:
    """Return ``data[key]`` as a non-empty string, or raise ``PackageError``."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PackageError(f"manifest field {key!r} is required and must be a string")
    return value.strip()


def sha256_bytes(payload: bytes) -> str:
    """Return the hex SHA-256 of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_words(payload: bytes) -> int:
    """Count non-comment, non-blank lines in a word-list payload."""
    count = 0
    for raw in payload.decode("utf-8", errors="replace").splitlines():
        entry = raw.strip()
        if entry and not entry.startswith("#"):
            count += 1
    return count


def build_package(
    files: list[Path],
    destination: Path,
    *,
    name: str,
    language: str,
    kind: str = "frequency",
    version: str = "1.0.0",
    license: str = "",
    source: str = "",
    created: str = "",
) -> Manifest:
    """Write a ``.tar.gz`` language package and return its manifest.

    Args:
        files: The word-list (or n-gram) files to include.
        destination: The ``.tar.gz`` path to write.
        name: Package name (``ru-50k``, ``medicine``, ...).
        language: Language code the package is for.
        kind: One of :data:`VALID_KINDS`.
        version: The package's own version.
        license: SPDX id or a short licence note.
        source: Where the data came from (for provenance).
        created: An ISO-8601 timestamp; the caller supplies it so a build is
            reproducible when the input is.

    Returns:
        The manifest that was embedded.

    Raises:
        PackageError: No files, an unknown kind, or a file that is missing.
    """
    if kind not in VALID_KINDS:
        raise PackageError(f"unknown package kind {kind!r}; expected one of {VALID_KINDS}")
    if not files:
        raise PackageError("a package must contain at least one file")

    entries: list[PackageFile] = []
    seen: set[str] = set()
    for path in files:
        if not path.is_file():
            raise PackageError(f"package member {path} does not exist")
        member = path.name
        if member == MANIFEST_NAME or member in seen:
            raise PackageError(f"duplicate or reserved member name {member!r}")
        seen.add(member)
        payload = path.read_bytes()
        entries.append(
            PackageFile(
                name=member,
                sha256=sha256_bytes(payload),
                bytes=len(payload),
                words=_count_words(payload),
            )
        )

    manifest = Manifest(
        name=name,
        language=language.lower(),
        kind=kind,
        version=version,
        license=license,
        source=source,
        created=created,
        files=entries,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    # ``mtime=0`` on the gzip wrapper and a fixed member ordering make the
    # archive byte-reproducible for a fixed input, which is what lets a test
    # assert on its checksum (plain ``tarfile`` "w:gz" stamps the wall clock).
    with (
        _open_reproducible_gzip(destination) as raw,
        tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive,
    ):
        manifest_payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True).encode("utf-8")
        _add_bytes(archive, MANIFEST_NAME, manifest_payload)
        for path in sorted(files, key=lambda p: p.name):
            _add_bytes(archive, path.name, path.read_bytes())
    logger.info("Built language package %s (%d files)", destination, len(entries))
    return manifest


@contextlib.contextmanager
def _open_reproducible_gzip(destination: Path) -> Iterator[io.BufferedIOBase]:
    """Open ``destination`` as a gzip stream with a fixed mtime and no name.

    ``GzipFile`` writes the source file's name into the header (the ``FNAME``
    field) unless it is given an empty ``filename``, which would make the output
    depend on the destination path; ``mtime=0`` removes the timestamp.
    """
    with (
        destination.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz,
    ):
        yield gz


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    """Add an in-memory member to ``archive`` with a fixed mtime and mode."""
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, io.BytesIO(payload))


def read_manifest(archive_path: Path) -> Manifest:
    """Return the manifest embedded in ``archive_path``.

    Raises:
        PackageError: The archive cannot be read or has no valid manifest.
    """
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            handle = archive.extractfile(MANIFEST_NAME)
            if handle is None:
                raise PackageError(f"{archive_path} has no {MANIFEST_NAME}")
            raw = handle.read()
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"cannot read package {archive_path}: {exc}") from exc
    try:
        data: object = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PackageError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
    return Manifest.from_dict(data)


def verify_package(archive_path: Path, manifest: Manifest | None = None) -> list[str]:
    """Check a package's integrity, returning a list of problems (empty = ok).

    Verifies that every file the manifest lists is present, that its size and
    SHA-256 match, and that the archive carries no member the manifest does not
    describe (an unexpected member would be written unverified).
    """
    problems: list[str] = []
    try:
        manifest = manifest if manifest is not None else read_manifest(archive_path)
    except PackageError as exc:
        return [str(exc)]

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = {m.name: m for m in archive.getmembers() if m.isfile()}
            declared = {f.name for f in manifest.files}
            for extra in sorted(set(members) - declared - {MANIFEST_NAME}):
                problems.append(f"archive contains undeclared member {extra!r}")
            for entry in manifest.files:
                member = members.get(entry.name)
                if member is None:
                    problems.append(f"missing member {entry.name!r}")
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    problems.append(f"member {entry.name!r} is too large ({member.size} bytes)")
                    continue
                handle = archive.extractfile(member)
                payload = handle.read() if handle is not None else b""
                actual = sha256_bytes(payload)
                if actual != entry.sha256:
                    problems.append(
                        f"checksum mismatch for {entry.name!r}: "
                        f"expected {entry.sha256[:12]}…, got {actual[:12]}…"
                    )
                elif entry.bytes and len(payload) != entry.bytes:
                    problems.append(
                        f"size mismatch for {entry.name!r}: "
                        f"expected {entry.bytes}, got {len(payload)}"
                    )
    except (tarfile.TarError, OSError) as exc:
        problems.append(f"cannot read package: {exc}")
    return problems


def install_dir(kind: str, language: str, base: Path) -> Path:
    """Return the directory ``kind``/``language`` installs into under ``base``.

    ``frequency`` lists land at the top level (``<base>/ru.txt``, matching
    ``dictionary.extended_dictionary_path``); ``thematic`` and ``ngrams`` are
    namespaced per language (``<base>/thematic/<lang>/``), matching
    ``thematic.thematic_dir``.
    """
    sub = _KIND_DIRS.get(kind)
    if sub is None:
        raise PackageError(f"unknown package kind {kind!r}")
    if not sub:
        return base
    return base / sub / language.lower()


@dataclass
class InstallResult:
    """What an install did, for the caller to report."""

    manifest: Manifest
    installed: list[Path] = field(default_factory=list)
    replaced: list[Path] = field(default_factory=list)


def install_package(
    archive_path: Path,
    base: Path,
    *,
    manifest: Manifest | None = None,
    verify: bool = True,
) -> InstallResult:
    """Install ``archive_path`` under ``base`` atomically, with rollback.

    Every member is staged in a temporary directory, checksum-verified, then
    moved into place. The previous file at each destination is moved aside
    first and restored if any later step fails, so a partial install cannot
    leave a half-updated dictionary set behind.

    Args:
        archive_path: The ``.tar.gz`` package.
        base: The extended-dictionary directory to install into.
        manifest: A pre-read manifest (avoids reading the archive twice).
        verify: Check the checksums before installing.

    Returns:
        An :class:`InstallResult` naming the files written and replaced.

    Raises:
        PackageError: The package is invalid or fails its integrity check.
    """
    manifest = manifest if manifest is not None else read_manifest(archive_path)
    if verify:
        problems = verify_package(archive_path, manifest)
        if problems:
            raise PackageError("package failed its integrity check: " + "; ".join(problems))

    target_dir = install_dir(manifest.kind, manifest.language, base)
    target_dir.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[Path, Path]] = []
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    replaced: list[Path] = []
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for entry in manifest.files:
                handle = archive.extractfile(entry.name)
                if handle is None:
                    raise PackageError(f"member {entry.name!r} vanished during install")
                payload = handle.read()
                if verify and sha256_bytes(payload) != entry.sha256:
                    raise PackageError(f"member {entry.name!r} changed during install")
                with tempfile.NamedTemporaryFile(
                    dir=target_dir, prefix=f".{entry.name}.", delete=False
                ) as tmp:
                    tmp.write(payload)
                    staged.append((Path(tmp.name), target_dir / entry.name))

        # Commit phase: swap each staged file in, backing up the previous one.
        for staged_path, final in staged:
            if final.exists():
                backup = final.with_name(final.name + ".bak")
                shutil.move(str(final), str(backup))
                backups.append((backup, final))
                replaced.append(final)
            os.replace(staged_path, final)
            installed.append(final)
    except Exception:
        # Roll back: restore backups, drop anything we already installed.
        for final in installed:
            final.unlink(missing_ok=True)
        for backup, final in backups:
            if backup.exists():
                os.replace(backup, final)
        for staged_path, _final in staged:
            staged_path.unlink(missing_ok=True)
        raise
    else:
        # Success: drop the backups.
        for backup, _final in backups:
            backup.unlink(missing_ok=True)

    logger.info(
        "Installed language package %s (%s/%s): %d files",
        manifest.name,
        manifest.kind,
        manifest.language,
        len(installed),
    )
    return InstallResult(manifest=manifest, installed=installed, replaced=replaced)


def uninstall_package(kind: str, language: str, names: list[str], base: Path) -> list[Path]:
    """Remove ``names`` from the install directory for ``kind``/``language``.

    Returns the paths actually removed. Missing files are not an error: the
    caller is usually removing what a package installed, and a partial state is
    still a state the user asked to clear.
    """
    target_dir = install_dir(kind, language, base)
    removed: list[Path] = []
    for name in names:
        path = target_dir / Path(name).name
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.debug("Could not remove %s", path, exc_info=True)
            continue
        removed.append(path)
    return removed
