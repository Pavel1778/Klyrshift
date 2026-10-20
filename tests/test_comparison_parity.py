"""The landing page's comparison matrix must say exactly what the README says.

``README.md`` carries a feature table against the other Linux layout switchers,
and ``site/src/components/Comparison.astro`` renders the same table on the page a
visitor lands on. The two are written by hand in different languages (Markdown
and Astro/TypeScript), so one can be edited while the other keeps an old claim --
the drift the ``Demo`` component had against the detector. This test parses both
and fails when a row, a competitor column or a verdict disagrees, and when the
site's column order stops matching the README's.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
COMPONENT = REPO_ROOT / "site" / "src" / "components" / "Comparison.astro"

# The README writes a verdict as an emoji; the component uses a word. The mapping
# is the contract between the two files. The signs are written as escapes so an
# invisible U+FE0F variation selector cannot ride along in a dict key: the
# README's warning sign carries one, and it is stripped before the lookup.
_MARK_TO_VERDICT = {"\u2705": "yes", "\u26a0": "partial", "\u274c": "no"}


def _verdict(mark: str) -> str:
    return _MARK_TO_VERDICT.get(mark.replace("\ufe0f", ""), mark)


_ROW = re.compile(
    r'label:\s*pick\("(?P<label>[^"]+)".*?\),\s*'
    r'xneur:\s*"(?P<xneur>\w+)",\s*'
    r'gswitch:\s*"(?P<gswitch>\w+)",\s*'
    r'poltertype:\s*"(?P<poltertype>\w+)",\s*'
    r'klyrshift:\s*"(?P<klyrshift>\w+)",',
    re.S,
)
_COLUMN = re.compile(r'\{\s*key:\s*"(?P<key>\w+)",\s*name:\s*"(?P<name>[^"]+)"')
_COLUMN_ORDER = ("xneur", "gswitch", "poltertype", "klyrshift")


def _readme_rows() -> tuple[list[str], list[list[str]]]:
    """Return the comparison table's ``(header, rows)`` from the README."""
    text = README.read_text(encoding="utf-8")
    section = text.split("Сравнение с аналогами", 1)[1].split("\n## ", 1)[0]
    table = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.strip().startswith("|")
    ]
    header, _, *rows = table
    return header, rows


def _component_rows() -> list[dict[str, str]]:
    text = COMPONENT.read_text(encoding="utf-8")
    return [
        {
            "label": match.group("label"),
            "xneur": match.group("xneur"),
            "gswitch": match.group("gswitch"),
            "poltertype": match.group("poltertype"),
            "klyrshift": match.group("klyrshift"),
        }
        for match in _ROW.finditer(text)
    ]


def _component_columns() -> list[tuple[str, str]]:
    """Return the ``(key, display name)`` of every column, in source order."""
    text = COMPONENT.read_text(encoding="utf-8")
    return [(m.group("key"), m.group("name")) for m in _COLUMN.finditer(text)]


def test_both_files_describe_the_same_competitors_in_the_same_order() -> None:
    header, _ = _readme_rows()
    columns = _component_columns()
    assert columns, "Comparison.astro declares no columns"
    names = [name for _, name in columns]
    assert header[1:] == names, f"README columns {header[1:]} != {names}"
    keys = tuple(key for key, _ in columns)
    assert keys == _COLUMN_ORDER, f"unexpected column keys: {keys}"


def test_every_readme_row_is_rendered_with_the_same_verdicts() -> None:
    _, rows = _readme_rows()
    component = _component_rows()
    assert len(component) == len(
        rows
    ), f"README has {len(rows)} rows, the component renders {len(component)}"

    mismatches: list[str] = []
    for (label, *marks), entry in zip(rows, component, strict=True):
        if label != entry["label"]:
            mismatches.append(f"row label {label!r} != {entry['label']!r}")
            continue
        expected = [_verdict(mark) for mark in marks]
        actual = [entry[key] for key in _COLUMN_ORDER]
        if expected != actual:
            mismatches.append(f"{label!r}: README {expected} != site {actual}")
    assert not mismatches, "the comparison table drifted:\n" + "\n".join(mismatches)


def test_the_password_guard_is_the_row_klyrshift_alone_wins() -> None:
    """The differentiator the section advertises must still be unique to us.

    The component's closing line and the README both single out the stop-word
    password guard; if a competitor ever earns it too, the claim is wrong.
    """
    component = _component_rows()
    guard = next(row for row in component if "парол" in row["label"])
    assert guard["klyrshift"] == "yes"
    assert all(guard[key] != "yes" for key in ("xneur", "gswitch", "poltertype"))
