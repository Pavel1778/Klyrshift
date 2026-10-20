"""The generated CLI reference stays in step with the argument parser.

``scripts/build_cli_docs.py`` renders the man page and the two completion files
from ``klyrshift.cli.build_parser()``. These tests are the guard that keeps that
true: a command added to the parser without regenerating would otherwise ship a
man page and a completion that silently omit it, which is exactly the drift the
generator exists to prevent. The same pattern ``test_docs_handbook`` uses for the
handbook.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from klyrshift import i18n

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_cli_docs.py"
MAN = REPO_ROOT / "data" / "klyrshift.1"
BASH = REPO_ROOT / "data" / "completions" / "klyrshift.bash"
ZSH = REPO_ROOT / "data" / "completions" / "_klyrshift"
BUILD_DEB = REPO_ROOT / "scripts" / "build_deb.sh"
INSTALL_SH = REPO_ROOT / "install.sh"


def _load() -> object:
    name = "build_cli_docs"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.fixture(scope="module")
def generator() -> object:
    return _load()


@pytest.fixture(autouse=True)
def _reset_locale() -> Iterator[None]:
    """The generator forces English; do not leak it into the rest of the run."""
    i18n.set_locale("")
    yield
    i18n.set_locale("")


def test_committed_files_match_a_fresh_render(generator: object) -> None:
    """Editing the parser without running ``make cli-docs`` fails here."""
    artefacts = generator.build()
    assert set(artefacts) == {MAN, BASH, ZSH}
    for path, text in artefacts.items():
        assert path.is_file(), f"missing {path}; run: make cli-docs"
        assert path.read_text(encoding="utf-8") == text, f"drift in {path}; run: make cli-docs"


def test_man_page_documents_every_command(generator: object) -> None:
    """A command without a man entry is invisible to ``man klyrshift``."""
    man = MAN.read_text(encoding="utf-8")
    for command in generator._introspect().commands:
        # The heading is roff-escaped, so a hyphen in a name is ``\-``.
        assert f".SS {generator._roff(command.name)}" in man, command.name


def test_bash_completion_knows_every_command(generator: object) -> None:
    bash = BASH.read_text(encoding="utf-8")
    for command in generator._introspect().commands:
        # Each command appears in the top-level word list and as a case label.
        assert re.search(rf"\b{re.escape(command.name)}\b", bash), command.name
        assert f"        {command.name})" in bash, command.name


def test_man_page_has_no_unrendered_placeholder() -> None:
    man = MAN.read_text(encoding="utf-8")
    assert "@BIN@" not in man
    assert "{0}" not in man
    # The roff header is the lintian-visible signature of a real man page.
    assert man.startswith(".TH KLYRSHIFT 1 ")


def test_man_page_renders_without_warnings() -> None:
    """``man --warnings`` must stay silent: a stray escape is user-visible."""
    man = shutil.which("man")
    if man is None:
        pytest.skip("man (groff) is not installed")
    result = subprocess.run(
        [man, "--warnings=all", "-l", str(MAN)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", result.stderr


def test_deb_and_installer_ship_the_reference() -> None:
    """The generated files are useless if the package does not carry them."""
    for script in (BUILD_DEB, INSTALL_SH):
        text = script.read_text(encoding="utf-8")
        assert "man/man1" in text, script
        assert "completions" in text, script
        assert ".1" in text, script
    # The .deb must compress the man page, or lintian fails the package.
    assert 'gzip -9n "${BUILD_DIR}/usr/share/man/man1/${PKG}.1"' in BUILD_DEB.read_text(
        encoding="utf-8"
    )
