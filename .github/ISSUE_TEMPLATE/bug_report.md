---
name: Bug report
about: Report something that does not work on your system
title: "[bug] "
labels: bug, needs-testing
---

## Environment

- Distribution: <!-- Debian 12 / Ubuntu 22.04 / other -->
- GNOME version (`gnome-shell --version`):
- Session type (`echo $XDG_SESSION_TYPE`): <!-- wayland / x11 -->
- `lingvix version`:
- Injector backend (`lingvix status`):
- Layout switcher backend (`lingvix status`):

## What happened

<!-- A clear description of the problem. -->

## Expected behaviour

## Steps to reproduce

1.
2.
3.

## Where it fails

- [ ] gnome-terminal
- [ ] Firefox
- [ ] Chrome / Chromium
- [ ] VS Code
- [ ] Gedit
- [ ] Game / other app (name):

## Logs

<!--
Attach the relevant lines from `~/.local/state/lingvix/lingvix.log` and
`journalctl --user -u lingvix.service`. The log contains only metadata (buffer
length, layouts), never the typed text.
-->

```
```

## Diagnostics

Run the collector and **drag the resulting tarball into this issue**:

```bash
lingvix collect-logs
# -> ~/lingvix-logs-YYYYMMDD-HHMMSS.tar.gz
```

It contains the `doctor` output, your configuration, the log tail, the user
journal, environment details, device permissions and package versions. The
daemon logs only metadata, so it never contains the text you typed.

If you prefer to paste text instead, include the output of:

```
lingvix doctor
lingvix status
groups | grep input
ls -l /dev/input/event*
```
