# Releasing

This is the checklist to run before publishing a release. It is written for
`v0.2.8.3`, the first release under the new name, but the same steps apply to
any version.

Nothing here is executed automatically. A release is published by pushing a tag
(`git push origin v0.2.8.3`), which triggers
[`.github/workflows/release.yml`](../.github/workflows/release.yml). Read the
whole list before pushing the tag: the tag is the point of no return.

## 0. Decide what the version is

- [ ] The version is **one** value, in four places that a test compares:
  `pyproject.toml`, `src/klyrshift/__init__.py`, `site/src/consts.ts` and the
  landing page JSON-LD (which reads `VERSION` from `consts.ts`).
  `python3 scripts/release_consistency.py --source` must print `ok`.
- [ ] The `CHANGELOG.md` section for this version exists and is not still under
  `## [Unreleased]`. A released version must have its own `## [x.y.z] - date`
  heading, or the tree claims a version the changelog does not describe.
- [ ] The version is not already used. `git ls-remote --tags origin` must not
  list it. `0.2.8.2` has a **changelog heading from 2026-10-08** that was never
  tagged; `0.2.8.3` is the next number and does not reuse it.

## 1. Local checks

- [ ] `make check` — lint (ruff, isort, black), `mypy --strict`, and the test
  suite with coverage. The suite must stay above **80 %**.
- [ ] `bash scripts/build_deb.sh` builds `dist/klyrshift_<version>_all.deb`.
- [ ] `python3 scripts/release_consistency.py --source` — the tree agrees with
  itself and the asset names match what the workflow uploads.
- [ ] `python3 scripts/release_consistency.py --latest` — the newest published
  release matches the tree. **This is expected to fail while the version is
  bumped but not yet released**; it must pass once the tag is published.

## 2. The package on clean Debian images

These need Docker. Run both on **Debian 12 and Debian 13**, since the layout
backend and the `tomli`/`tomllib` split differ between them.

- [ ] `bash scripts/smoke_test.sh` — the installed CLI starts and answers
  `version`, `--help`, `status` and `doctor`.
- [ ] `bash scripts/deb_selfsufficiency_test.sh` — `apt install ./…` needs no
  `usermod`, no re-login and no manual `systemctl enable`; `apt remove --purge`
  leaves nothing behind.
- [ ] `SMOKE_IMAGE=debian:13 bash scripts/deb_selfsufficiency_test.sh` — same on
  Debian 13.

## 3. Upgrade from the old `linguafix` package

`bash scripts/upgrade_test.sh` automates this on a clean `debian:13` image
(`UPGRADE_IMAGE=debian:12` for the other release): it installs a stand-in for the
old package, installs the new `.deb` over it with apt, and checks the three
conditions below plus the config migration. The manual steps, for a real machine:

- [ ] Install the previous `linguafix_0.2.8_all.deb`, then install the new
  `klyrshift_<version>_all.deb` over it. After the upgrade:
  - `dpkg -l | grep -E 'linguafix|lingvix|klyrshift'` shows only `ii  klyrshift`;
  - `ls /etc/systemd/user/default.target.wants/` lists only `klyrshift.service`;
  - `pgrep -af 'klyrshift start' | wc -l` is `1` — two daemons must never run.
- [ ] The configuration **is** migrated on first load: `~/.config/lingvix` (or
  `~/.config/linguafix`) is copied into `~/.config/klyrshift`, and the old file is
  left in place. Confirm the manual copy still works (see
  [INSTALL.md](INSTALL.md#upgrading-from-the-old-linguafix-package)).

## 4. On a real keyboard (this cannot be done in CI)

The daemon reads `/dev/input/event*` through `evdev` and injects through
`uinput`. No container in this project has those nodes, so this section is the
only place the kernel boundary is exercised. Run `bash scripts/acceptance_check.sh`
on a real GNOME session and complete the manual steps it prints:

- [ ] In **both** session types (Wayland and X11): type `ghbdtn`, press Space,
  and confirm it becomes `привет`; type `привет`, press Space, and confirm it is
  left alone.
- [ ] The fix hotkey (SHIFT+SHIFT) corrects a word with no Space;
  SHIFT+BACKSPACE undoes the last fix.
- [ ] Each mode behaves as documented: `auto` corrects on its own, `hybrid`
  withholds a borderline word until the hotkey, `manual` waits for the hotkey.
- [ ] A word added to the exceptions list is left alone.
- [ ] `https://example.com/a_b` and `/usr/lib/klyrshift/x.py` are never rewritten.
- [ ] The log holds no typed text:
  `grep -c привет ~/.local/state/klyrshift/klyrshift.log` is `0`.
- [ ] Exactly one daemon runs: `pgrep -af 'klyrshift start' | wc -l` is `1`.

Record the session type, the distribution and the result for each line. A
release may not claim the input path works until this section is done.

## 5. Documentation and the landing page

- [ ] `CHANGELOG.md` describes every user-visible change since the last release,
  including the breaking rename and the config-directory migration.
- [ ] `README.md` and `docs/*` show the current version in every
  `apt install ./klyrshift_<version>_all.deb` example. A test enforces this.
- [ ] The landing page builds (`cd site && npm run build`) and the JSON-LD
  `softwareVersion`, the hero version and the download links agree.
- [ ] The canonical origin, `og:url` and the `hreflang` alternates point at the
  hosts that resolve (`linguafix.layero.app`, `linguafix.vercel.app`), not at
  the `klyrshift.*` names, which are still 404. A test enforces this.

## 6. The release assets

The release workflow attaches, and `klyrshift dict install` depends on:

- [ ] `klyrshift_<version>_all.deb` — the package.
- [ ] `klyrshift-<version>.tar.gz` — the source distribution.
- [ ] `<lang>-50k.txt` for every frequency list (`ru`, `en`, `uk`, `de`, `fr`).
- [ ] `klyrshift-dict-<slug>.tar.gz` for **every** thematic category that has a
  `README.md` in `dictionaries/` (twelve today), each containing
  `<lang>-<slug>-1k.txt` for `ru` and `en`.
- [ ] `SHA256SUMS.txt`.

`python3 scripts/release_consistency.py --tag v<version>` lists the expected
names; the workflow runs the same check against the staged files before it
publishes.

## 7. Publish, then verify

- [ ] CI is green on the **exact commit** the tag will point at. Do not tag a
  commit whose checks have not finished.
- [ ] Tag and push: `git tag -a v<version> -m '...' && git push origin v<version>`.
- [ ] Watch the release workflow: the consistency gate, the smoke test, the
  zero-config test and the post-publish link check must all pass.
- [ ] `python3 scripts/release_consistency.py --latest` passes — the newest
  published release now matches the tree.
- [ ] The download links on the landing page resolve. Redeploy the Layero host
  if it still serves the previous version.

## Known blockers for `v0.2.8.3`

One thing is outside this repository and cannot be fixed from a commit:

- `linguafix.layero.app` serves a stale build (old name, `0.2.8.1`, a 404
  download link). It needs a redeploy with Layero credentials.

The GitHub repository rename is done: the repository is `Pavel1778/Klyrshift`
and GitHub redirects the old `Pavel1778/LinguaFix` slug.

The Layero host does not block *cutting* the tag, but it should be settled
before announcing the release, because the site advertises the version.

