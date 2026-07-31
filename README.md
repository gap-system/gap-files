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

This is one of three GAP sites on that machine, the others being
<https://www.gap-system.org> and <https://docs.gap-system.org>. They follow the
same conventions — directory layout, systemd user units, lingering — which are
described once in
[`etc/README.server.md`](https://github.com/gap-system/GapWWW/blob/master/etc/README.server.md)
in the GapWWW repository. Start there if you are rebuilding the hosting rather
than just this site.

The machine is run by the central IT department of RPTU Kaiserslautern-Landau,
and Apache is configured centrally by them. The vhost nevertheless supports
everything needed to extend the site: PHP is enabled (8.4 at the time of
writing) and `.htaccess` files are honoured, so redirects and CGI-style
endpoints can be added without involving them, exactly as
<https://www.gap-system.org> does.

The mirrors nevertheless poll on a timer rather than being driven by a GitHub
webhook the way that site is (see `etc/README.server.md` in the
[GapWWW](https://github.com/gap-system/GapWWW) repository). That is a
deliberate choice, not a limitation: a timer needs no shared secret, and a run
that fails or is missed is retried on the next tick instead of leaving the
mirror silently stale — which is the exact failure this setup exists to prevent.
The cost is up to 15 minutes of latency, which does not matter for an archive.
A webhook could be added on top for lower latency, with the timer kept as the
safety net.

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
| `gap-files-packages` | every 15 min | Update the PackageDistro clone; download any new package archives |
| `gap-files-releases` | hourly | Mirror any newly published stable GAP release |

The 15 minute run is cheap: it does a `git fetch` and, if `origin/main` has not
moved since the last successful run, exits immediately. It deliberately
compares against `~/data/.mirror-packages.ok` rather than the checked out
commit, so a run that failed part-way through is retried instead of being
skipped as already up to date.

There is deliberately no periodic re-verification job. Running
`mirror-packages.sh --force` re-hashes only the archives of the *currently*
distributed packages — about 0.5 GiB of the 2.5 GiB mirror, and precisely the
files that were most recently downloaded and checksummed. The roughly 730
historical archives, which are the reason this mirror exists and the ones with
years of exposure to bit rot, cannot be checked that way at all, because their
checksums are no longer recorded in any `meta.json`. A worthwhile integrity
check would need a manifest of checksums covering every file ever published
here; until that exists, a weekly `--force` run would be NFS churn over the
least interesting part of the archive. (`--force` remains available for running
by hand.)

## Installation

No root access is needed; `loginctl enable-linger www-gap-files` is already set,
which is what allows systemd *user* units to run without an active login
session. As `www-gap-files`:

```sh
git clone https://github.com/gap-system/gap-files ~/data/gap-files
mkdir -p ~/.config/systemd/user
cp ~/data/gap-files/etc/gap-files-*.service ~/.config/systemd/user/
cp ~/data/gap-files/etc/gap-files-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gap-files-packages.timer gap-files-releases.timer
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
systemctl --user status gap-files-packages.service
journalctl --user -u 'gap-files-*' -n 100
journalctl --user -f -u gap-files-packages.service   # follow a running job
```

To force a run immediately, without waiting for the timer:

```sh
systemctl --user start gap-files-packages.service
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
