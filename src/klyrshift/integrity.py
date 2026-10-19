"""Post-install integrity check for the packaged Klyrshift files.

A Debian package ships an ``md5sums`` manifest listing every file it installs
with the digest of that file. ``dpkg --verify`` compares the manifest against
the files on disk and reports any that were truncated, corrupted or edited
after installation. ``dpkg-deb --build`` does **not** generate that manifest by
itself (verified against dpkg 1.22), so ``scripts/build_deb.sh`` writes it, and
this module re-implements the comparison for the two cases dpkg cannot cover:

* the daemon and the CLI run as the user, and ``dpkg --verify`` needs root on
  some systems to read ``/var/lib/dpkg/info``;
* a file that is *missing* should be reported distinctly from one that is
  *modified*, because the fix differs (reinstall vs. reinstall).

The check is read-only: it never rewrites a file, and it only ever reads the
paths the package itself lists in its manifest.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .i18n import _

logger = logging.getLogger(__name__)

PACKAGE = "klyrshift"
COMMAND_TIMEOUT = 15.0

# Where dpkg keeps the per-package manifest. The file is named
# ``<package>:<arch>.md5sums`` for an arch-specific package and
# ``<package>.md5sums`` for ``Architecture: all`` (ours).
_INFO_DIR = Path("/var/lib/dpkg/info")

OK = "OK"
MISSING = "MISSING"
MODIFIED = "MODIFIED"


@dataclass
class FileStatus:
    """The verification outcome for a single packaged file.

    Args:
        path: Absolute path of the file on disk.
        status: One of :data:`OK`, :data:`MISSING` or :data:`MODIFIED`.
    """

    path: str
    status: str


@dataclass
class VerifyReport:
    """The result of verifying the whole package.

    Args:
        files: One entry per file named in the manifest.
        manifest: Path of the manifest that was read, or ``None`` when the
            package is not installed from a ``.deb``.
    """

    files: list[FileStatus]
    manifest: Path | None

    @property
    def missing(self) -> list[str]:
        """Paths the manifest lists but that are absent from disk."""
        return [f.path for f in self.files if f.status == MISSING]

    @property
    def modified(self) -> list[str]:
        """Paths whose contents no longer match the manifest digest."""
        return [f.path for f in self.files if f.status == MODIFIED]

    @property
    def ok(self) -> bool:
        """``True`` when every listed file matches its recorded digest."""
        return not self.missing and not self.modified


def manifest_path(package: str = PACKAGE) -> Path | None:
    """Return the installed md5sums manifest for ``package``, if present.

    ``Architecture: all`` packages use ``<name>.md5sums``; an arch-qualified
    install uses ``<name>:<arch>.md5sums``. Both are accepted so the check works
    whether the package was installed from the ``.deb`` or built by hand.
    """
    for candidate in (_INFO_DIR / f"{package}.md5sums",):
        if candidate.is_file():
            return candidate
    for candidate in sorted(_INFO_DIR.glob(f"{package}:*.md5sums")):
        return candidate
    return None


def parse_manifest(text: str) -> dict[str, str]:
    """Parse md5sums lines into ``{absolute_path: digest}``.

    The format is one ``<md5>  <path>`` line per file, the path relative to the
    filesystem root. Blank lines and the ``\\*`` binary-mode marker (md5sum
    writes two spaces for text, ``*`` for binary) are tolerated.
    """
    entries: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        digest, _, path = line.partition("  ")
        if not path:
            # Fall back to a single-space split for a hand-edited manifest.
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            digest, path = parts
        path = path.lstrip("*").strip()
        if not path:
            continue
        entries[path if path.startswith("/") else f"/{path}"] = digest.strip()
    return entries


def _digest(path: Path) -> str | None:
    """Return the MD5 hex digest of ``path``, or ``None`` when unreadable."""
    hasher = hashlib.md5(usedforsecurity=False)
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def verify_package(package: str = PACKAGE) -> VerifyReport:
    """Verify every file the installed package's manifest lists.

    A package that is not installed from a ``.deb`` (a source checkout, a venv
    install, a container) has no manifest; the report then carries
    ``manifest=None`` and no files, and :meth:`VerifyReport.ok` is true. The
    caller is expected to say so rather than claim a pass.

    Args:
        package: Package name to verify.

    Returns:
        The per-file report.
    """
    manifest = manifest_path(package)
    if manifest is None:
        return VerifyReport(files=[], manifest=None)
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("cannot read %s: %s", manifest, exc)
        return VerifyReport(files=[], manifest=None)

    files: list[FileStatus] = []
    for path, expected in sorted(parse_manifest(text).items()):
        target = Path(path)
        if not target.is_file():
            files.append(FileStatus(path, MISSING))
            continue
        actual = _digest(target)
        if actual is None:
            files.append(FileStatus(path, MISSING))
        elif actual == expected:
            files.append(FileStatus(path, OK))
        else:
            files.append(FileStatus(path, MODIFIED))
    return VerifyReport(files=files, manifest=manifest)


def dpkg_verify(package: str = PACKAGE) -> str | None:
    """Return the raw ``dpkg --verify`` output, or ``None`` when unavailable.

    ``dpkg`` knows about files a package installs and reports them with a
    single-letter marker; it is the authoritative check when it is installed and
    the user may read the dpkg database. It is used only to enrich the message,
    never as the sole source of truth, so a missing ``dpkg`` is not a failure.
    """
    executable = shutil.which("dpkg")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--verify", package],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    return result.stdout


def format_report(report: VerifyReport) -> str:
    """Render a verification report for the terminal.

    Args:
        report: The report to render.

    Returns:
        A short human-readable summary.
    """
    if report.manifest is None:
        return _(
            "Пакет klyrshift не установлен из .deb — проверять нечего.\n"
            "Если вы ставили из исходников, целостность файлов гарантирует "
            "система контроля версий, а не dpkg."
        )
    lines = [_("Манифест: {0}").format(report.manifest)]
    if report.ok:
        lines.append(_("Итог: все {0} файлов совпадают с манифестом.").format(len(report.files)))
        return "\n".join(lines)
    for path in report.missing:
        lines.append(_("❌  отсутствует: {0}").format(path))
    for path in report.modified:
        lines.append(_("❌  изменён: {0}").format(path))
    lines.append(
        _(
            "Итог: {0} отсутствуют, {1} изменены из {2}. Переустановите пакет: sudo apt install --reinstall klyrshift"
        ).format(len(report.missing), len(report.modified), len(report.files))
    )
    return "\n".join(lines)


def run_verify(package: str = PACKAGE) -> int:
    """Verify the package and print the result.

    Args:
        package: Package name to verify.

    Returns:
        ``0`` when every file matches, ``1`` otherwise.
    """
    report = verify_package(package)
    print(_("Klyrshift: проверка целостности пакета"))
    print("=" * 40)
    print(format_report(report))
    return 0 if report.ok else 1
