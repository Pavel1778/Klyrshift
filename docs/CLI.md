# Command-line reference

`klyrshift` is one binary with a subcommand for each action. Running it with no
subcommand prints an error and the usage summary; `klyrshift --help` lists every
command, and `klyrshift <command> --help` documents one.

This page is the prose reference. The man page (`man klyrshift`) and the shell
completion are generated from the same argument parser by
`scripts/build_cli_docs.py`, so all three describe the same commands; the test
suite fails if any of them drifts.

```text
klyrshift [--lang LOCALE] <command> [options]
```

## Global options

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show the usage summary and exit. |
| `--version` | Print the version and exit. |
| `--lang LOCALE` | Language of the output. `auto` (the default) follows the environment; otherwise one of `ru`, `en`, `de`, `fr`, `uk`. |

The output language only affects the messages this tool prints. It is separate
from the dictionary language and from the interface language of the GUI; see
[Interface languages](INTERFACE_LANGUAGES.md).

## Daemon control

| Command | What it does |
| --- | --- |
| `start` | Start the daemon. `--foreground` keeps it attached to the terminal; `--dry-run` analyses without ever switching the layout or replacing text. |
| `stop` | Stop the daemon (the service is not disabled; it returns at next login). |
| `kill` | Stop the daemon immediately, without the graceful shutdown `stop` performs. |
| `restart` | Stop and start again. |
| `status` | Show whether the daemon is running and a one-line summary of its state. |

## Correction behaviour

| Command | What it does |
| --- | --- |
| `mode [auto\|manual\|hybrid]` | Show or set the global correction mode. `auto` corrects on its own, `manual` only on the hotkey, `hybrid` corrects on its own when it is confident and otherwise waits for the hotkey. |
| `app-mode [APP] [MODE]` | Show or set the mode for one application. `--clear` removes the override. An application without an override uses the global mode. |
| `undo` | Revert the last correction. See [Undo contract](UNDO_CONTRACT.md). |
| `hotkeys` | Print the configured hotkeys. |
| `fix [--text TEXT] [--apply] [--dry-run]` | Correct a string. With no `--text` it reads from standard input; with `--apply` it also rewrites the text on screen. |
| `explain [--text TEXT] [--layout LAYOUT]` | Explain what would be decided for a string and why, without changing anything. `--layout` states the current layout instead of detecting it. |

## Learning

| Command | What it does |
| --- | --- |
| `learn [list\|promote\|forget] [WORD]` | Inspect and adjust learned words. `list` shows them; `promote` pins a word so it is never rewritten; `forget` removes it. |
| `learn --on` / `--off` | Enable or disable learning. |
| `learn --reset` | Reset the learning counters. |

## Dictionaries

| Command | What it does |
| --- | --- |
| `dict list` | List the installed dictionaries. |
| `dict add WORD` / `dict remove WORD` | Add or remove a word in the user dictionary. |
| `dict download LANG` / `dict import-file PATH` | Fetch or import a base dictionary. `--lang` names the language when the file name does not. |
| `dict categories` | List the available thematic categories. |
| `dict install CATEGORY` / `dict remove-category CATEGORY` | Install or remove a thematic dictionary. |
| `dict list-installed` | List the installed thematic dictionaries. |
| `dict pack` | Build a versioned language package (manifest + sha256). Options: `--lang`, `--file`, `--name`, `--kind`, `--output`, `--package-version`, `--license`. |
| `dict verify PATH` | Check a package against its manifest and checksums. |
| `dict install-file PATH` / `dict uninstall-file PATH` | Install or remove a package from a file. |

See [Language packages](LANGUAGE_PACKAGES.md) for the package format.

## Configuration and data

| Command | What it does |
| --- | --- |
| `config show` / `edit` / `reset` / `path` / `migrate` | Show, edit, reset or locate the configuration, or migrate it to the current schema. `migrate --dry-run` shows the changes without writing them. |
| `export [FILE]` | Write a backup (dictionaries and configuration) to `FILE`. |
| `import SOURCE` | Restore from a backup. |

## Diagnostics

| Command | What it does |
| --- | --- |
| `doctor` | Run the self-diagnosis and print what is wrong and how to fix it. |
| `verify` | Verify the installed files against the package manifest. |
| `collect-logs [--output DIR]` | Collect a diagnostic archive for a bug report. |
| `logs [-n N] [-f] [--level LEVEL]` | Show the log. `-f` follows it in real time; `--level` filters to `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `version` | Print the version. |

## Desktop integration

| Command | What it does |
| --- | --- |
| `gui` | Open the settings window. |
| `install-autostart` / `uninstall-autostart` | Start the daemon at login, or stop doing so. |

## Shell completion

Bash and zsh completions ship with the package. For a manual install they live
under `data/completions/`; `install.sh` copies them into
`~/.local/share/bash-completion/completions/klyrshift` and
`~/.local/share/zsh/site-functions/_klyrshift`.

```bash
# bash: no configuration needed once the file is in place
klyrshift dic<Tab>          # -> dict
klyrshift dict <Tab>        # -> the dict actions
klyrshift mode <Tab>        # -> auto manual hybrid
klyrshift --lang <Tab>      # -> auto ru en de fr uk
klyrshift --lang=e<Tab>     # -> --lang=en

# zsh: make sure the site-functions directory is on $fpath
fpath=(~/.local/share/zsh/site-functions $fpath)
```

## Exit status

`0` on success, `1` when a command failed or the requested action was not
possible. A diagnostic command such as `doctor` exits non-zero when it finds a
problem, so it can be used in scripts.
