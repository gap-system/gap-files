# gap-files

Scripts and systemd units that maintain <https://files.gap-system.org>, the
archive server for the [GAP computer algebra system](https://www.gap-system.org).

The server keeps permanent copies of

- **every GAP package archive** ever distributed, under `/pkg/`, mirrored from
  the [PackageDistro](https://github.com/gap-system/PackageDistro) repository;
- **every GAP release**, under `/gap-<major>.<minor>/`, mirrored from the
  [GitHub releases of GAP](https://github.com/gap-system/gap/releases).

The point of the mirror is that these URLs keep working even when an upstream
package host disappears or a release asset is retagged. Nothing here is ever
deleted; old versions are kept deliberately.

Both mirrors used to be updated by hand and both fell behind as a result. They
are now updated automatically by systemd timers.

## The server

Everything runs on `www-admin13.rz.rptu.de` as the user `www-gap-files`, which
serves `files.gap-system.org`. Assuming the `gap-files` host alias is set up in
`~/.ssh/config`:

```sh
ssh gap-files
```

Apache is managed centrally by the RZ; the vhost configuration is not readable
or writable by `www-gap-files`. That is why the mirrors poll on a timer instead
of being driven by a GitHub webhook the way <https://www.gap-system.org> is (see
`etc/README.server.md` in the [GapWWW](https://github.com/gap-system/GapWWW)
repository): a timer needs no web server change and no shared secret, and a run
that fails or is missed is simply retried on the next tick, rather than leaving
the mirror silently stale.

### Directory layout

```
/srv/www/www-gap-files/data/     (== ~/data, and ~/http -> ~/data/http)
├── http/                        document root of files.gap-system.org
│   ├── pkg/                     all package archives, flat
│   ├── gap-4.16/{tar.gz,zip,exe}/   release archives, one dir per series
│   ├── gap-4.15/...
│   └── ...                      older series, in their historical layouts
├── PackageDistro/               git clone; _archives -> ../http/pkg/
├── gap-files/                   git clone of this repository
└── .mirror-packages.ok          last successfully mirrored commit
~/.config/systemd/user/          the units from etc/
```

`~/data/PackageDistro/_archives` is a symlink to `~/data/http/pkg/`, so
downloading an archive publishes it directly. `bin/mirror-packages.sh` refuses
to run if that symlink is missing, since otherwise it would quietly fill a
directory inside the git clone instead of updating the mirror.

## What runs when

| Unit | Schedule | What it does |
| --- | --- | --- |
| `gap-mirror-packages` | every 15 min | Update the PackageDistro clone; download any new package archives |
| `gap-mirror-packages-verify` | Sundays 04:00 | Same, but re-checks every archive's checksum |
| `gap-mirror-releases` | hourly | Mirror any newly published stable GAP release |

The 15 minute run is cheap: it does a `git fetch` and, if `origin/main` has not
moved since the last successful run, exits immediately. It deliberately
compares against `~/data/.mirror-packages.ok` rather than the checked out
commit, so a run that failed part-way through is retried instead of being
skipped as already up to date.

Verifying is separated out because it re-reads every archive — well over a
gigabyte across an NFS mount — which is far too expensive to do every quarter
of an hour but well worth doing weekly.

## Installation

No root access is needed; `loginctl enable-linger www-gap-files` is already set,
which is what allows systemd *user* units to run without an active login
session. As `www-gap-files`:

```sh
git clone https://github.com/gap-system/gap-files ~/data/gap-files
mkdir -p ~/.config/systemd/user
cp ~/data/gap-files/etc/gap-mirror-*.service ~/.config/systemd/user/
cp ~/data/gap-files/etc/gap-mirror-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now \
    gap-mirror-packages.timer \
    gap-mirror-packages-verify.timer \
    gap-mirror-releases.timer
```

The units are copied rather than symlinked, so remember to copy them again
after pulling changes to `etc/`.

Before enabling the timers on a fresh setup it is worth running both scripts by
hand once, to see what they do:

```sh
~/data/gap-files/bin/mirror-packages.sh
~/data/gap-files/bin/mirror-gap-releases.py --dry-run
```

## Operating

```sh
systemctl --user list-timers
systemctl --user status gap-mirror-packages.service
journalctl --user -u 'gap-mirror-*' -n 100
journalctl --user -f -u gap-mirror-packages.service   # follow a running job
```

To force a run immediately, without waiting for the timer:

```sh
systemctl --user start gap-mirror-packages.service
```

A failed run leaves the service in a failed state and the stamp file untouched;
the next timer tick retries it. There is no email notification, so failures are
found by looking at `systemctl --user list-units --failed` or the journal.

> **Never run `tools/cleanup_archives.py` from the PackageDistro clone on this
> server.** It deletes every archive not referenced by a current `meta.json` —
> that is, the entire historical mirror, which is the whole reason this server
> exists. It is meant for pruning the CI cache, nothing else.

## The scripts

### `bin/mirror-packages.sh`

Updates `~/data/PackageDistro` to `origin/main` and runs its
`tools/download_packages.py`, which downloads any archive listed in
`packages/*/meta.json` that is not already present, verifies it against the
`ArchiveSHA256` recorded there, and writes it atomically. Pass `--force` to
re-check archives even when the distribution has not changed.

### `bin/mirror-gap-releases.py`

Mirrors stable GAP releases, replacing the manual
`ssh gap-files; ./download_release.sh X.Y.Z` step described in
[`dev/releases/README.md`](https://github.com/gap-system/gap/blob/master/dev/releases/README.md)
in the GAP repository. For each release `vX.Y.Z` it mirrors

- `gap-X.Y.Z.tar.gz` and `gap-X.Y.Z-core.tar.gz` into `gap-X.Y/tar.gz/`
- `gap-X.Y.Z.zip` and `gap-X.Y.Z-core.zip` into `gap-X.Y/zip/`
- `gap-X.Y.Z-x86_64.exe` into `gap-X.Y/exe/`

together with the `.sha256` file published beside each one, and verifies every
download against it before putting it in place. This is one thing the old
script did not do: it fetched the `.sha256` files but never checked them.

Pre-releases are skipped, as are the `packages-*` archives, `package-infos.json.gz`
and `help-links.json.gz`, matching what has always been mirrored.

Releases before 4.12.0 are skipped by default (`--since` overrides this). They
predate the current conventions — 4.9 has no per-format subdirectories at all,
and 4.10 and 4.11 shipped `.tar.bz2` archives and differently named Windows
installers — and are already mirrored in their historical layout. Considering
them would mean retroactively publishing files that were never released for
those versions.

An already mirrored archive is skipped without being read back, so the hourly
run is cheap. Pass `--verify` to re-check the checksums of everything, and
`--dry-run` to see what would happen.

### `bin/import-gap-releases.py`

Unrelated to mirroring: a one-off tool that builds a git history out of old GAP
release tarballs using `git fast-import`. Kept here because it lived untracked
in the home directory of `www-gap-files` and would otherwise be lost.
