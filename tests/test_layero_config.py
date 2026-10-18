"""The Layero build must pin a Node line that Astro can actually run on.

Astro 7 refuses to build below Node ``22.22.0`` (``site/package.json``
``engines.node``). Layero's build image offers the majors 20, 22 and 24, and
each major is a *single* build whose patch the platform updates on its own: the
docs' own example shows ``[config] node=22.18.0 (.nvmrc)`` when ``.nvmrc`` says
``22``. Requesting the patch ``22.22.0`` therefore does not buy that patch -- the
22 line is ``22.18.0``, which is exactly the version the failed deploy reported.

The pin must name a major whose *whole* range clears the floor: the smallest
version a major ``M`` can resolve to is ``M.0.0``, so ``22`` (i.e. ``22.0.0``)
is unusable even though ``22.22.0`` would be fine, while ``24`` is safe because
``24.0.0 >= 22.22.0``. ``test_pinned_major_clears_the_engines_floor`` enforces
that rule, so a future ``.nvmrc``/``layero.json`` edit cannot quietly reintroduce
a line the platform would build below Astro's floor.
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

# The majors Layero's build image offers (docs.layero.ru/deploys/runtime-versions).
# Pinning anything else does not fail the build -- Layero warns and falls back to
# its default 22 line, which is below Astro's floor -- so the set is checked too.
_SUPPORTED_MAJORS = frozenset({20, 22, 24})
# ``engines.node`` uses a range (``>=22.22.0``); the pin is a bare major (``24``).
_BARE_MAJOR = re.compile(r"^\d+$")
_LOWER_BOUND = re.compile(r">=\s*(\d+\.\d+\.\d+)")


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _layero_config() -> dict[str, object]:
    data: dict[str, object] = json.loads(LAYERO_JSON.read_text(encoding="utf-8"))
    return data


def _pinned_node_major() -> int:
    version = _layero_config().get("nodeVersion")
    assert isinstance(version, str), "site/layero.json must pin nodeVersion"
    assert _BARE_MAJOR.match(
        version
    ), f"nodeVersion must be a bare major (Layero owns the patch), got {version!r}"
    return int(version)


def _engines_floor() -> tuple[int, int, int]:
    engines = json.loads(SITE_PACKAGE_JSON.read_text(encoding="utf-8"))["engines"]
    floor = _LOWER_BOUND.search(engines["node"])
    assert floor is not None, f"unexpected engines.node: {engines['node']!r}"
    return _version_tuple(floor.group(1))


def test_layero_pins_a_supported_node_major() -> None:
    """A bare major, and one Layero actually builds: the platform owns the patch."""
    major = _pinned_node_major()
    assert major in _SUPPORTED_MAJORS, (
        f"Node {major} is not one of Layero's build majors "
        f"{sorted(_SUPPORTED_MAJORS)}; an unsupported pin falls back to the 22 line"
    )


def test_pinned_major_clears_the_engines_floor() -> None:
    """The whole range of the pinned major must be at or above Astro's floor.

    ``M.0.0`` is the oldest build a major ``M`` can resolve to; if that is below
    the floor, the deploy can land under Astro's minimum and fail before Astro
    runs. This is the rule that rejects the ``22`` line (its floor is
    ``22.0.0``) and accepts ``24``.
    """
    major = _pinned_node_major()
    assert (major, 0, 0) >= _engines_floor(), (
        f"Node major {major} can resolve below the engines floor "
        f"{'.'.join(map(str, _engines_floor()))}; pick a higher major"
    )


def test_nvmrc_agrees_with_layero_json() -> None:
    """Local dev must build on the same Node line the deploy uses."""
    pinned = _pinned_node_major()
    nvmrc = _version_tuple(NODE_VERSION_FILE.read_text(encoding="utf-8").strip())
    assert (
        nvmrc[0] == pinned
    ), f".nvmrc ({nvmrc[0]}) and layero.json ({pinned}) must name the same major"


def test_ci_builds_on_the_pinned_major() -> None:
    """The landing-page CI job must not run on a different major than the deploy."""
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    versions = re.findall(r'node-version:\s*"([^"]+)"', workflow)
    assert versions, "ci.yml must set up Node"
    majors = {_version_tuple(v)[0] for v in versions}
    assert majors == {_pinned_node_major()}, (
        f"ci.yml Node majors {sorted(majors)} must match the pinned major "
        f"{_pinned_node_major()}"
    )


def test_layero_json_declares_the_astro_build() -> None:
    """The build command and output directory stay explicit and consistent."""
    config = _layero_config()
    assert config["framework"] == "astro"
    assert config["buildCommand"] == "npm run build"
    assert config["outputDirectory"] == "dist"
