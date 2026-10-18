"""The Layero build must pin the Node version the site actually needs.

Astro 7 refuses to build below Node ``22.22.0`` (``site/package.json``
``engines.node``). Layero reads the pin from ``site/layero.json`` first and only
then from ``site/.nvmrc`` / ``engines.node``, and its own default for the 22
major is an older patch (``22.18.0``). A deploy therefore failed before the
first line of Astro ran. The three declarations are kept in lockstep here so a
future bump of one cannot silently leave the others behind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
LAYERO_JSON = SITE / "layero.json"
NODE_VERSION_FILE = SITE / ".nvmrc"
SITE_PACKAGE_JSON = SITE / "package.json"

# ``engines.node`` uses a range (``>=22.22.0``); ``layero.json``/``.nvmrc`` a
# bare ``X.Y.Z``. Compare the numeric triple instead of the raw strings.
_FULL_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_LOWER_BOUND = re.compile(r">=\s*(\d+\.\d+\.\d+)")


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def _layero_config() -> dict[str, object]:
    data: dict[str, object] = json.loads(LAYERO_JSON.read_text(encoding="utf-8"))
    return data


def _pinned_node_version() -> str:
    version = _layero_config().get("nodeVersion")
    assert isinstance(version, str), "site/layero.json must pin nodeVersion"
    assert _FULL_VERSION.match(version), f"nodeVersion must be X.Y.Z, got {version!r}"
    return version


def test_layero_pins_an_exact_node_version() -> None:
    """A bare major would ride Layero's default, which is below Astro's floor."""
    assert _pinned_node_version() == "22.22.0"


def test_nvmrc_agrees_with_layero_json() -> None:
    """Local dev must build on the same Node the deploy uses."""
    assert NODE_VERSION_FILE.read_text(encoding="utf-8").strip() == _pinned_node_version()


def test_pinned_node_satisfies_the_package_engines_floor() -> None:
    """The pin must not be older than what ``engines.node`` demands."""
    engines = json.loads(SITE_PACKAGE_JSON.read_text(encoding="utf-8"))["engines"]
    floor = _LOWER_BOUND.search(engines["node"])
    assert floor is not None, f"unexpected engines.node: {engines['node']!r}"
    assert _version_tuple(_pinned_node_version()) >= _version_tuple(floor.group(1))


def test_layero_json_declares_the_astro_build() -> None:
    """The build command and output directory stay explicit and consistent."""
    config = _layero_config()
    assert config["framework"] == "astro"
    assert config["buildCommand"] == "npm run build"
    assert config["outputDirectory"] == "dist"
