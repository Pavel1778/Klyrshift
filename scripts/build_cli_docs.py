"""Generate the CLI reference from the argument parser itself.

The command line has twenty-plus subcommands, and each one carries a help
string. Documenting them by hand guarantees drift: the man page and the shell
completion would describe a command that no longer exists, or miss one that was
just added. Like the handbook, these files are generated, not edited.

Three artefacts are written, all derived from ``klyrshift.cli.build_parser()``:

* ``data/klyrshift.1`` -- the man page. Debian Policy 12.1 expects every binary
  to ship one and ``lintian`` reports ``no-manual-page`` without it.
* ``data/completions/klyrshift.bash`` -- bash completion (``/usr/share/bash-
  completion/completions``).
* ``data/completions/_klyrshift`` -- zsh completion (``/usr/share/zsh/vendor-
  completions``).

The output is deterministic: it depends on the parser, the version and the
latest dated changelog entry, never on the clock, so a rebuild in CI produces
the same bytes. ``--check`` renders in memory and compares against the committed
files, which is what the test suite calls.

Usage: ``python scripts/build_cli_docs.py [--check]``.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
COMPLETIONS = DATA / "completions"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

MAN = DATA / "klyrshift.1"
BASH = COMPLETIONS / "klyrshift.bash"
ZSH = COMPLETIONS / "_klyrshift"

# The source package path, so the parser can be imported without installing.
sys.path.insert(0, str(REPO_ROOT / "src"))

# Help actions that every parser adds; they are documented once, globally.
HELP_OPTIONS: tuple[str, ...] = ("-h", "--help")


@dataclass
class Option:
    flags: tuple[str, ...]
    metavar: str
    help: str
    choices: tuple[str, ...] = ()
    positional: bool = False

    @property
    def key(self) -> str:
        return self.flags[0] if self.flags else self.metavar


@dataclass
class Command:
    name: str
    help: str
    options: list[Option] = field(default_factory=list)
    positionals: list[Option] = field(default_factory=list)


@dataclass
class Cli:
    version: str
    description: str
    global_options: list[Option]
    commands: list[Command]


def _clean_help(text: str | None) -> str:
    """Collapse a help string to one line for roff and shell use."""
    return " ".join((text or "").split())


def _introspect() -> Cli:
    from klyrshift import __version__
    from klyrshift.cli import build_parser
    from klyrshift.i18n import set_locale

    # Help strings are translated at parser-build time, so the output would
    # otherwise follow the build machine's locale and stop being reproducible.
    # The reference is shipped in English, the upstream documentation language.
    # ``set_locale("")`` restores environment detection afterwards: the switch
    # is process-global, and a generator that leaves it changed would translate
    # everything the caller does next.
    set_locale("en")
    try:
        parser = build_parser()
        commands = _collect_commands(parser)
        global_options = _collect_globals(parser)
    finally:
        set_locale("")

    return Cli(
        version=__version__,
        description=_clean_help(parser.description),
        global_options=global_options,
        commands=commands,
    )


def _locale_choices() -> tuple[str, ...]:
    """The values ``--lang`` accepts, for the completions.

    ``auto`` is included because ``--lang auto`` is documented and means
    "follow the environment"; the rest come from the one registry the CLI
    validates against, so a locale added there appears here too.
    """
    from klyrshift.i18n import SUPPORTED_LOCALES

    return ("auto", *SUPPORTED_LOCALES)


def _collect_globals(parser: argparse.ArgumentParser) -> list[Option]:
    options: list[Option] = []
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._SubParsersAction):
            options.append(
                Option(
                    flags=tuple(action.option_strings),
                    metavar=action.metavar or "",
                    help=_clean_help(action.help),
                )
            )
    return options


def _collect_commands(parser: argparse.ArgumentParser) -> list[Command]:
    commands: list[Command] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {choice.dest: _clean_help(choice.help) for choice in action._choices_actions}
        for name, sub in action.choices.items():
            command = Command(name=name, help=helps.get(name, ""))
            _collect_options(sub, command)
            commands.append(command)
    commands.sort(key=lambda c: c.name)
    return commands


def _collect_options(parser: argparse.ArgumentParser, command: Command) -> None:
    for action in parser._actions:
        choices = tuple(str(c) for c in action.choices) if action.choices else ()
        if action.option_strings:
            if set(action.option_strings) == set(HELP_OPTIONS):
                continue
            command.options.append(
                Option(
                    flags=tuple(action.option_strings),
                    metavar=action.metavar or "",
                    help=_clean_help(action.help),
                    choices=choices,
                )
            )
        else:
            command.positionals.append(
                Option(
                    flags=(),
                    metavar=action.metavar or action.dest,
                    help=_clean_help(action.help),
                    choices=choices,
                    positional=True,
                )
            )


def _release_date() -> str:
    """The date of the newest released version, for the man page header."""
    match = re.search(
        r"^## \[[0-9][^\]]*\] - (\d{4}-\d{2}-\d{2})", CHANGELOG.read_text("utf-8"), re.M
    )
    return match.group(1) if match else "1970-01-01"


# --- roff rendering ---------------------------------------------------------


def _roff(text: str) -> str:
    """Escape a string for roff.

    A literal hyphen becomes ``\\-`` (lintian's ``hyphen-used-as-minus-sign``),
    a backslash is doubled, and a line that would start with ``.`` or ``'`` is
    protected with ``\\&`` so it is not read as a request.
    """
    escaped = text.replace("\\", "\\\\").replace("-", "\\-")
    if escaped[:1] in (".", "'"):
        escaped = "\\&" + escaped
    return escaped


def _option_tag(option: Option) -> str:
    """Return the synopsis fragment for an option, e.g. ``\\-\\-lang LOCALE``."""
    parts = "\\fR, \\fB".join(_roff(flag) for flag in option.flags)
    if option.metavar:
        parts += " \\fI" + _roff(option.metavar) + "\\fR"
    return parts


def _render_man(cli: Cli) -> str:
    lines: list[str] = [
        f'.TH KLYRSHIFT 1 "{_release_date()}" "klyrshift {cli.version}" "User Commands"',
        ".SH NAME",
        "klyrshift \\- automatic keyboard layout switcher",
        ".SH SYNOPSIS",
        ".B klyrshift",
        "[\\fI\\-\\-lang LOCALE\\fR]",
        "\\fIcommand\\fR",
        "[\\fIoptions\\fR]",
        ".SH DESCRIPTION",
        _roff(cli.description),
        ".PP",
        _roff(
            "Klyrshift is a background daemon: it watches what you type and, when "
            "a word was typed in the wrong layout, rewrites it and switches the "
            "layout. The command line starts, stops and configures that daemon and "
            "inspects its dictionaries. Appending --help to a command prints its "
            "reference; klyrshift gui opens the settings window."
        ),
        ".SH OPTIONS",
        ".TP",
    ]
    for option in cli.global_options:
        lines.append(".B " + _option_tag(option))
        lines.append(_roff(option.help) or "")
        lines.append(".TP")
    # The trailing .TP would dangle; drop it and close the section.
    if lines[-1] == ".TP":
        lines.pop()

    lines.append(".SH COMMANDS")
    for command in cli.commands:
        lines.append(f".SS {_roff(command.name)}")
        lines.append(_roff(command.help) or "")
        for positional in command.positionals:
            lines.append(".PP")
            choices = " {" + ", ".join(positional.choices) + "}" if positional.choices else ""
            lines.append(f".B {_roff(positional.metavar + choices)}")
            if positional.help:
                lines.append(".br")
                lines.append(_roff(positional.help))
        if command.options:
            lines.append(".PP")
            lines.append(".RS")
            for option in command.options:
                lines.append(".TP")
                lines.append(".B " + _option_tag(option))
                lines.append(_roff(option.help) or "")
            lines.append(".RE")

    lines += [
        ".SH EXIT STATUS",
        ".TP",
        ".B 0",
        "Success.",
        ".TP",
        ".B 1",
        "A command failed, or the requested action was not possible.",
        ".SH FILES",
        ".TP",
        ".I ~/.config/klyrshift/config.toml",
        "User configuration.",
        ".TP",
        ".I ~/.local/share/klyrshift/",
        "Dictionaries, backups and the log.",
        ".SH SEE ALSO",
        "Full documentation: \\fBhttps://github.com/Pavel1778/Klyrshift\\fR",
        "",
    ]
    return "\n".join(lines)


# --- shell completion -------------------------------------------------------


def _bash_completion(cli: Cli) -> str:
    command_names = " ".join(c.name for c in cli.commands)
    global_flags = " ".join(flag for option in cli.global_options for flag in option.flags)
    locales = " ".join(_locale_choices())
    lines = [
        "# Bash completion for klyrshift. Generated by scripts/build_cli_docs.py.",
        "# Install as /usr/share/bash-completion/completions/klyrshift.",
        "",
        "_klyrshift() {",
        "    local cur cmd i",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        "",
        "    # ``--lang`` takes a locale, not a command or a flag, so it is handled",
        "    # before the command is worked out: otherwise the locale would be",
        "    # mistaken for the command name. Both the separated (``--lang ru``)",
        "    # and the joined (``--lang=ru``) spelling are offered.",
        '    if (( COMP_CWORD > 0 )) && [[ "${COMP_WORDS[COMP_CWORD-1]}" == "--lang" ]]; then',
        f'        COMPREPLY=( $(compgen -W "{locales}" -- "$cur") )',
        "        return 0",
        "    fi",
        '    if [[ "$cur" == --lang=* ]]; then',
        f'        COMPREPLY=( $(compgen -P "--lang=" -W "{locales}" -- "${{cur#--lang=}}") )',
        "        return 0",
        "    fi",
        "",
        "    # The first word that is not an option is the command. Options come",
        "    # before or after it; the ones with a value are skipped by matching",
        "    # the value that follows them.",
        '    cmd=""',
        "    for ((i = 1; i < COMP_CWORD; i++)); do",
        '        case "${COMP_WORDS[i]}" in',
        "            --lang) ((i++)) ;;",
        "            -*) ;;",
        '            *) cmd="${COMP_WORDS[i]}"; break ;;',
        "        esac",
        "    done",
        "",
        '    if [[ -z "$cmd" ]]; then',
        f'        COMPREPLY=( $(compgen -W "{command_names} {global_flags}" -- "$cur") )',
        "        return 0",
        "    fi",
        "",
        '    case "$cmd" in',
    ]
    for command in cli.commands:
        words = " ".join(
            [flag for option in command.options for flag in option.flags] + ["-h --help"]
        )
        choices = [p for p in command.positionals if p.choices]
        if choices:
            # Offer the positional choices while the user is still filling the
            # required arguments (a bare word, not an option).
            choice_words = " ".join(choices[0].choices)
            lines += [
                f"        {command.name})",
                '            if [[ "$cur" != -* ]] && (( COMP_CWORD == i + 1 )); then',
                f'                COMPREPLY=( $(compgen -W "{choice_words}" -- "$cur") )',
                "            else",
                f'                COMPREPLY=( $(compgen -W "{words}" -- "$cur") )',
                "            fi",
                "            ;;",
            ]
        else:
            lines += [
                f"        {command.name})",
                f'            COMPREPLY=( $(compgen -W "{words}" -- "$cur") )',
                "            ;;",
            ]
    lines += [
        "        *)",
        f'            COMPREPLY=( $(compgen -W "{global_flags}" -- "$cur") )',
        "            ;;",
        "    esac",
        "    return 0",
        "}",
        "",
        "complete -F _klyrshift klyrshift",
        "",
    ]
    return "\n".join(lines)


def _zsh_completion(cli: Cli) -> str:
    command_descriptions = "\n".join(f"        '{c.name}:{c.help}'" for c in cli.commands)
    locales = " ".join(_locale_choices())
    per_command = []
    for command in cli.commands:
        specs = []
        for option in command.options:
            flags = " ".join(option.flags)
            spec = f"{flags}[{option.help}]"
            if "--lang" in option.flags:
                spec += f":locale:({locales})"
            elif option.metavar:
                spec += f":{option.metavar}:"
            specs.append(f"                '{spec}'")
        choices = [p for p in command.positionals if p.choices]
        if choices:
            specs.append(f"                '1: :({' '.join(choices[0].choices)})'")
        if not specs:
            specs = ["                '*: :_default'"]
        per_command.append(
            f"            {command.name})\n"
            "                _arguments \\\n" + " \\\n".join(specs) + "\n                ;;"
        )
    return "\n".join(
        [
            "#compdef klyrshift",
            "# Zsh completion for klyrshift. Generated by scripts/build_cli_docs.py.",
            "# Install as /usr/share/zsh/vendor-completions/_klyrshift.",
            "",
            "_klyrshift() {",
            "    local -a commands",
            "    commands=(",
            command_descriptions,
            "    )",
            "    _arguments -C \\",
            "        '--version[print the version]' \\",
            f"        '--lang[output language]:locale:({locales})' \\",
            "        '1: :->cmd' \\",
            "        '*:: :->args'",
            "    case $state in",
            "        cmd)",
            "            _describe 'command' commands",
            "            ;;",
            "        args)",
            "            case $words[1] in",
            "\n".join(per_command),
            "            esac",
            "            ;;",
            "    esac",
            "}",
            "",
            '_klyrshift "$@"',
            "",
        ]
    )


def build() -> dict[Path, str]:
    """Render every artefact in memory, keyed by its destination path."""
    cli = _introspect()
    return {
        MAN: _render_man(cli),
        BASH: _bash_completion(cli),
        ZSH: _zsh_completion(cli),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if a committed file differs from a fresh render",
    )
    args = parser.parse_args(argv)

    artefacts = build()
    if args.check:
        drifted = [
            path
            for path, text in artefacts.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != text
        ]
        if drifted:
            for path in drifted:
                print(f"drift: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            print("run: python scripts/build_cli_docs.py", file=sys.stderr)
            return 1
        print("CLI reference is up to date")
        return 0

    COMPLETIONS.mkdir(parents=True, exist_ok=True)
    for path, text in artefacts.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
