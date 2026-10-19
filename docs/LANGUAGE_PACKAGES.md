# Language packages

A *language package* is how a dictionary or an n-gram model travels between
machines. It is a single `.tar.gz` carrying one or more data files plus a
`manifest.json` that describes them and records a SHA-256 for each. The format
gives the dictionary layer the four properties the roadmap asks for: integrity,
provenance, version compatibility, and an atomic install that rolls back.

Nothing in a package is typed text. A package is a curated word list or a
built n-gram model, exactly like the lists the bundled dictionaries already
ship. See [OFFLINE_AND_PRIVACY.md](OFFLINE_AND_PRIVACY.md).

## Layout

```
ru-50k.tar.gz
├── manifest.json
└── ru-50k.txt
```

`manifest.json`:

```json
{
  "format": 1,
  "name": "ru-50k",
  "kind": "frequency",
  "language": "ru",
  "version": "1.0.0",
  "license": "MIT",
  "source": "klyrshift dict pack",
  "created": "2026-10-19T00:00:00Z",
  "files": [
    { "name": "ru-50k.txt", "sha256": "…", "bytes": 512345, "words": 50000 }
  ]
}
```

| Field | Meaning |
|---|---|
| `format` | The package-format version. An installer refuses a package whose `format` is newer than it understands. |
| `kind` | `frequency`, `thematic` or `ngrams`. It decides the install directory. |
| `language` | The language the data is for. |
| `version` | The package's own version, for provenance and updates. |
| `license` | SPDX id or a short licence note. A package without one can still be installed, but the field is where provenance lives. |
| `source` | Where the data came from. |
| `files[].sha256` | The member's SHA-256, checked before anything is written. |
| `files[].name` | A plain file name. A name containing a path separator is rejected, so a package cannot write outside its directory. |

## Install locations

`kind` decides where a member lands, relative to the extended-dictionary
directory (`extended_dictionary_dir`, default
`$XDG_DATA_HOME/klyrshift/dictionaries`):

| `kind` | Directory |
|---|---|
| `frequency` | `<dir>/` (for example `<dir>/ru-50k.txt`) |
| `thematic` | `<dir>/thematic/<lang>/` |
| `ngrams` | `<dir>/ngrams/<lang>/` |

## Commands

```bash
# Build a package from one or more word lists.
klyrshift dict pack ru-50k.txt --name ru-50k --lang ru --license MIT \
    --output ru-50k.tar.gz

# Check a package before trusting it.
klyrshift dict verify ru-50k.tar.gz

# Install it (verified, atomic, with rollback).
klyrshift dict install-file ru-50k.tar.gz

# Remove the files a package installed.
klyrshift dict uninstall-file ru-50k.tar.gz
```

`dict pack` accepts extra files with `--file <path>`, a package version with
`--package-version`, and a kind with `--kind`.

## What is enforced

- **Integrity.** Every member is hashed and compared to the manifest before a
  single byte is written. A truncated download or a tampered archive is refused
  with a non-zero exit code and nothing is changed on disk.
- **No undeclared members.** An archive carrying a file the manifest does not
  describe is refused: an unexpected member would otherwise be written
  unverified.
- **No path traversal.** A member name must be a plain name; `../etc/passwd` is
  rejected at manifest-parse time.
- **Bounded size.** A member larger than 64 MiB, or a manifest listing more than
  256 files, is refused, so a crafted archive cannot exhaust the disk.
- **Atomic install with rollback.** Each member is staged next to its
  destination and swapped in one at a time; the previous file is moved aside
  first. If any later step fails, every file already swapped is restored and the
  staging files are removed. A failed update leaves the previous dictionaries
  exactly as they were — this is the "rollback on a failed update" the roadmap
  asks for.
- **Reproducible archives.** A fixed input produces a byte-identical archive
  (fixed mtime, no embedded file name, sorted members), so a checksum can be
  published and verified.

## Relationship to `dict download` / `dict install`

The older commands fetch a single word list from the project mirror, the
upstream source, or the bundled copy, and are unchanged. `dict pack` /
`verify` / `install-file` are the versioned transport: they add the manifest,
the checksums, the provenance fields and the atomic rollback. A future release
can publish its bundled lists *as packages* without changing the download
order, because a package installs into the same paths.

## Tests

`tests/test_langpack.py` pins the format: round-trip build/read/verify/install,
reproducible output, a tampered member refused before any write, an undeclared
member refused, rollback restoring the previous file when a later commit fails,
a newer `format` refused, a path-traversal name refused, and the module never
importing a network client. `tests/test_cli.py` covers the four commands
end-to-end.
