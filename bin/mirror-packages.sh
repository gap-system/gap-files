#!/bin/sh
#
# Update the local PackageDistro clone and download any package archives that
# are missing from the mirror served at https://files.gap-system.org/pkg/.
#
# Run periodically by gap-mirror-packages.timer. Pass --force to re-check every
# archive even when the package distribution has not changed.

set -eu

# Archives are served over HTTP, so they must be world readable.
umask 022

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

# Downloading exits non-zero if any archive failed, which aborts the script
# before the stamp is updated, so that the next run tries again.
tools/download_packages.py

printf '%s\n' "$head" >"$STAMP"
echo "mirrored package archives for $head"
