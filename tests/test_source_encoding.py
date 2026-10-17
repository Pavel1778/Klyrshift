"""The repository's text sources must be valid UTF-8, with no mojibake.

A single mis-encoded save (an editor writing UTF-8 bytes through a
single-byte pipeline) doubles the encoding of every non-ASCII character, turning
Cyrillic comments, punctuation and — worse — user-facing notification strings
into garbage.
The resulting file still imports and the test suite still passes, so the
corruption ships silently and only the end user sees it.

This guard scans every tracked text source and fails on the byte sequences a
double-encoded save produces. The bundled frequency dictionaries are excluded:
they legitimately contain accented Latin words that overlap the signature set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Suffixes that are code or prose: the files where an English/Cyrillic mix is
# expected. Data files (``.json`` corpora, ``.txt`` word lists) legitimately
# contain accented Latin words, so they are outside the scan.
TEXT_SUFFIXES = (".py", ".md", ".astro", ".ts", ".sh", ".toml", ".cfg", ".ini")

# Index of the mojibake signature characters. A double-encoded *Cyrillic*
# character always surfaces at least one of these, none of which occurs in
# genuine source outside the excluded dictionaries.
_MOJIBAKE_CHARS = frozenset("\u00d0\u00d1\u0110\u0111\u0178\u015a\u0153\u017e")

# The signature set covers Cyrillic only, so a double-encoded *punctuation* mark
# slips past it: an arrow saved through CP775 becomes ``\u014c\u00e5\u00c6``
# and an em-dash through CP1252 becomes ``\u00e2\u20ac\u201d``, and both files
# still import. Every codec a single-byte pipeline plausibly uses is therefore
# round-tripped back through UTF-8; a line that decodes cleanly is a genuine
# double-encoding. (The examples stay as escapes on purpose: written literally
# they would trip this very guard.)
_MOJIBAKE_CODECS = ("cp1252", "cp775", "latin-1", "cp437", "cp850", "mac_roman")

_EXCLUDED_PREFIXES = ("dictionaries/", "site/dist/", "site/.astro/", "site/node_modules/")


def _tracked_text_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    return [
        name
        for name in output.splitlines()
        if name.endswith(TEXT_SUFFIXES) and not name.startswith(_EXCLUDED_PREFIXES)
    ]


def _double_encoded(line: str) -> str | None:
    """Return the codec if ``line`` looks like a single-byte double-encoding."""
    for codec in _MOJIBAKE_CODECS:
        try:
            raw = line.encode(codec)
        except UnicodeEncodeError:
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded != line and any(ord(ch) > 127 for ch in decoded):
            return codec
    return None


def test_the_detector_catches_a_double_encoded_arrow() -> None:
    """The round-trip detector must catch what the signature set misses."""
    assert _double_encoded("\u014c\u00e5\u00c6") == "cp775"
    assert _double_encoded("\u00e2\u20ac\u201d") == "cp1252"
    for clean in (
        "\u2014 em-dash",
        "\u2192 arrow",
        "\u043f\u0440\u0438\u0432\u0435\u0442",
        "caf\u00e9",
    ):
        assert _double_encoded(clean) is None


def test_no_mojibake_in_tracked_sources() -> None:
    """No tracked text source may contain a double-encoded byte sequence."""
    offenders: list[str] = []
    for name in _tracked_text_files():
        try:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - surfaced below
            offenders.append(f"{name}: not valid UTF-8 ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _MOJIBAKE_CHARS & set(line):
                offenders.append(f"{name}:{lineno} (signature)")
                continue
            codec = _double_encoded(line)
            if codec is not None:
                offenders.append(f"{name}:{lineno} (double-encoded via {codec})")
    assert not offenders, "Mojibake (double-encoded UTF-8) found in:\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", ["src/klyrshift/daemon.py"])
def test_notification_strings_are_recoverable(name: str) -> None:
    """The fixed notification labels must be the intended Cyrillic text.

    A regression guard narrower than the scan above: it pins the exact strings a
    user sees, so a corruption that happens to avoid the signature set (for
    example by round-tripping through a different codec) is still caught.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    assert "Раскладка исправлена" in text
    assert "Доступна версия {latest}" in text
