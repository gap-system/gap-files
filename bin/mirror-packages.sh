#!/bin/sh
#
# Update the local PackageDistro clone and download any package archives that
# are missing from the mirror served at https://files.gap-system.org/pkg/.
#
# Run periodically by gap-files-packages.timer. Pass --force to re-check every
# archive even when the package distribution has not changed.

set -eu

# Archives are served over HTTP, so they must be world readable.
umask 022

# Resolve our own directory before changing into the clone.
BINDIR=$(cd "$(dirname "$0")" && pwd)

REPO="${PACKAGEDISTRO_DIR:-$HOME/data/PackageDistro}"
STAMP="$HOME/data/.mirror-packages.ok"

force=false
if [ "${1:-}" = "--force" ]; then
    force=true
fi

cd "$REPO"

# download_packages.py writes into `_archives`, which here is a symlink to the
# directory served by the web server. Without it we would silently fill up a
# fresh directory inside the git clone instead of updating the mirror.
if [ ! -d _archives ]; then
    echo "error: $REPO/_archives is missing; it should be a symlink to the served pkg directory" >&2
    exit 1
fi

git fetch --quiet --prune origin
head=$(git rev-parse origin/main)

# The stamp file records the commit for which downloading last completed
# without errors. Comparing against it, rather than against the checked out
# commit, means a run that failed part-way through is retried on the next tick
# instead of being skipped as "already up to date".
if ! $force && [ "$head" = "$(cat "$STAMP" 2>/dev/null || true)" ]; then
    echo "PackageDistro unchanged at $head, nothing to do"
    exit 0
fi

git checkout --quiet --force -B main origin/main

# List the packages explicitly rather than relying on download_packages.py to
# default to all of them: older versions of that script simply do nothing when
# given no arguments, which would make this whole job a silent no-op.
set -- packages/*/meta.json
if [ ! -f "$1" ]; then
    echo "error: no packages/*/meta.json found in $REPO" >&2
    exit 1
fi

# Downloading exits non-zero if any archive failed, which aborts the script
# before the stamp is updated, so that the next run tries again.
tools/download_packages.py "$@"

# Newly downloaded archives land directly in pkg/; sort them into their package
# directory, leaving a symlink behind at the flat path. Doing this here rather
# than in download_packages.py keeps the layout a concern of this server alone,
# and that script still finds an already sorted archive through its symlink.
"$BINDIR/reorganise-pkg.py"

printf '%s\n' "$head" >"$STAMP"
echo "mirrored package archives for $head"
