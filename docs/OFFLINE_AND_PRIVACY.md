# Offline operation and privacy

Klyrshift reads everything you type, so it is built to work with no network and
to keep the typed text off disk. This document states the guarantees, the two
places where a network connection is *possible*, and how the guarantees are
enforced.

## Offline guarantee

**No core function needs a network connection.** Correction, detection,
learning, dictionaries, the GUI, diagnostics, history, backup and restore all
run locally. The daemon never opens a socket during normal operation.

| Function | Network needed? | Fallback when offline |
|---|---|---|
| Layout detection | No | — |
| Text replacement | No | — |
| Learning (kept / corrected / rejected words) | No | — |
| User dictionary | No | — |
| Bundled frequency dictionaries | No | Ship inside the package |
| Thematic (professional) dictionaries | No, once installed | Bundled copy is used |
| GUI, diagnostics, history | No | — |
| Backup / restore | No | Local JSON file |
| Update check | Optional, **off by default** | Nothing happens |
| `dict download` | Optional | Falls back to the bundled copy, then to upstream |

## The two network touch points

Both are explicit and both are bounded.

### 1. Update check — opt-in, off by default

`update_check_enabled` defaults to `False`. When a user turns it on, the daemon
asks the GitHub releases API for the latest tag at most once per day and shows a
desktop notification if a newer version exists. It sends no user data — the
request is an unauthenticated `GET` of a public URL. The fetch refuses any
non-`https` scheme before opening a socket, so a caller-supplied URL cannot make
it read `file:` or `ftp:`.

### 2. Dictionary download — explicit command

`klyrshift dict download` and the thematic-dictionary install fetch word lists.
They try, in order: the project mirror, the upstream FrequencyWords source, then
the copy bundled in the package. The command works with no network at all
because of the bundled copy.

## Data locations

All paths honour the XDG base-directory variables.

| Data | Path | Contains typed text? |
|---|---|---|
| Configuration | `$XDG_CONFIG_HOME/klyrshift/config.toml` | No |
| User dictionary | `$XDG_CONFIG_HOME/klyrshift/` | Words the user added deliberately |
| Learning profile | `$XDG_STATE_HOME/klyrshift/` | **Counters only, never a word** |
| Correction history | `$XDG_STATE_HOME/klyrshift/history.json` | Metadata only: length, layouts, timestamp |
| Log | `$XDG_STATE_HOME/klyrshift/klyrshift.log` | Metadata only |
| Cache | `$XDG_CACHE_HOME/klyrshift/` | Downloaded lists |

## What is never persisted

- **The word being typed.** It lives in memory as a buffer of physical keys and
  is discarded at the word boundary or on the idle timeout.
- **The original text of a correction.** It is kept only in the in-memory undo
  tuple, so it can be restored while its word is under the caret, and is never
  written to the history file or the log.
- **Learned words.** The learning profile stores counters (kept / corrected /
  rejected), never the words themselves. Learned words live in the daemon's
  memory for the session only.

The log records the buffer *length*, the source and target layout, and the
action taken. It rotates at 5 MB with three backups.

## Other surfaces

- **Notifications** carry a fixed label, never the corrected text.
- **Subprocess arguments** never contain the typed text (argv is world-readable
  through `/proc`).
- **Tracebacks** replace the buffer with `<redacted>` before formatting, so an
  exception message that embeds the text cannot leak it.

## How this is enforced

`tests/test_privacy_audit.py` runs a session with a distinctive secret string,
then searches the log, cache, state directory, config file, the user journal and
every subprocess argv for any trace of it. A regression that leaks the text into
any of those surfaces fails the test.

`tests/test_learning.py` asserts the learning profile holds counters only and no
typed word.

## Enforcing it with systemd

The user unit (`klyrshift.service`) also sandboxes the daemon, so the
guarantees above do not rest on the code alone: it runs with
`NoNewPrivileges=yes`, `LockPersonality=yes`, `RestrictRealtime=yes`,
`RestrictNamespaces=yes` and `SystemCallArchitectures=native`, and may only open
Unix, netlink and IPv4/IPv6 sockets. IPv4/IPv6 stay allowed only for the opt-in
update check.

If you never enable the update check, you can take the network away from the
daemon entirely. Create a drop-in:

```bash
mkdir -p ~/.config/systemd/user/klyrshift.service.d
cat > ~/.config/systemd/user/klyrshift.service.d/offline.conf <<'UNIT'
[Service]
RestrictAddressFamilies=
RestrictAddressFamilies=AF_UNIX AF_NETLINK
IPAddressDeny=any
UNIT
systemctl --user daemon-reload
systemctl --user restart klyrshift.service
```

The empty `RestrictAddressFamilies=` line matters: systemd *merges* repeated
allow-lists, so without it the unit's `AF_INET AF_INET6` would stay allowed.
Check the result with
`systemctl --user show -p RestrictAddressFamilies klyrshift.service`; it must
list only `AF_NETLINK AF_UNIX`.

Any attempt by the daemon to open an internet socket then fails with
`EAFNOSUPPORT`; D-Bus, the tray, notifications and the control socket keep
working. `klyrshift dict download` and the GUI run outside the unit, so they
are not affected. To undo, delete `offline.conf` and run the last two commands
again.

## What would break the guarantee

Adding any of the following would violate this document and must not be merged:

- telemetry or analytics;
- cloud learning or an account system;
- a required online API for correction, dictionaries or diagnostics;
- persisting typed text, or a word, anywhere on disk.
