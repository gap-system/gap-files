#!/usr/bin/env python3

"""
Sort the package archives on files.gap-system.org into per-package directories.

Historically every archive sat directly in `pkg/`, which by now holds close to a
thousand files. This moves each one into `pkg/<package>/` and leaves a symlink
behind at the old location, so that every URL ever published keeps working
exactly as before -- same path, same bytes, no redirect.

The move is done by hardlinking the archive into its new home and then swapping
the old path to a symlink in a single rename, so the old path is never missing,
not even briefly, and no data is copied.

Run it again at any time: archives that have already been sorted are left alone.
It is meant to run after `mirror-packages.sh` has downloaded new archives.
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

# Archive names are mostly "<package>-<version>.<ext>", but by no means always:
# there are names like "transgrp3.5.tar.gz" and "classicpres1.21.tar.gz" with no
# separator, "smallantimagmas-v0.6.0.tar.gz" with a "v", and
# "ToricVarieties.tar.gz" with no version at all. Rather than trying to parse
# them, match each name against the list of packages we know about, longest
# first, so that e.g. "polycyclic-..." cannot be mistaken for "poly...".
VERSION_SUFFIX = re.compile(r"^(.*?)-?v?\d[\d._-]*$")


def package_names(distro: str) -> Tuple[List[str], Dict[str, str]]:
    """Every prefix an archive may start with, and the package it belongs to.

    Usually the archive is named after the package, but not always: the package
    `sl2reps` ships `sl2-reps-1.1.tar.gz`. Rather than hard-coding such cases,
    derive the prefix from the archive name recorded in the package metadata.

    Returns the prefixes ordered longest first, and the prefix -> package map.
    """
    packages = os.path.join(distro, "packages")
    names: Dict[str, str] = {}
    for name in sorted(os.listdir(packages)):
        meta = os.path.join(packages, name, "meta.json")
        if not os.path.isfile(meta):
            continue
        names[name.lower()] = name
        with open(meta, "r", encoding="utf-8") as f:
            url = json.load(f)["ArchiveURL"]
        stem = url.split("/")[-1]
        match = VERSION_SUFFIX.match(stem)
        prefix = (match.group(1) if match else stem).lower()
        if prefix:
            names[prefix] = name
    # Longest first, so the most specific prefix wins.
    return sorted(names, key=len, reverse=True), names


def resolve(fname: str, ordered: List[str], names: Dict[str, str]) -> Optional[str]:
    low = fname.lower()
    for prefix in ordered:
        if low.startswith(prefix):
            return names[prefix]
    return None


def sort_archive(pkg_dir: str, fname: str, package: str, dry_run: bool) -> None:
    """Move `fname` into its package directory, leaving a symlink behind."""
    flat = os.path.join(pkg_dir, fname)
    subdir = os.path.join(pkg_dir, package)
    target = os.path.join(subdir, fname)

    if dry_run:
        print(f"would move {fname} -> {package}/{fname}")
        return

    os.makedirs(subdir, exist_ok=True)

    if os.path.exists(target):
        if os.path.samefile(flat, target):
            # A previous run was interrupted between linking and swapping.
            pass
        else:
            raise FileExistsError(f"{target} already exists and differs from {flat}")
    else:
        # Hardlink rather than copy: same filesystem, no data movement, and the
        # archive is reachable under its new name before anything else changes.
        os.link(flat, target)

    # Swap the old path to a symlink atomically, so it is never absent.
    tmp = os.path.join(pkg_dir, f".{fname}.symlink")
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(os.path.join(package, fname), tmp)
    os.replace(tmp, flat)
    print(f"moved {fname} -> {package}/{fname}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pkg-dir",
        default=os.path.expanduser("~/http/pkg"),
        help="the served package archive directory (default: ~/http/pkg)",
    )
    parser.add_argument(
        "--distro",
        default=os.path.expanduser("~/data/PackageDistro"),
        help="PackageDistro clone, used to recognise package names",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be done"
    )
    args = parser.parse_args(argv)

    for path in (args.pkg_dir, os.path.join(args.distro, "packages")):
        if not os.path.isdir(path):
            print(f"error: {path} is not a directory", file=sys.stderr)
            return 1

    os.umask(0o022)
    ordered, names = package_names(args.distro)

    todo = []
    for entry in sorted(os.listdir(args.pkg_dir)):
        path = os.path.join(args.pkg_dir, entry)
        # Symlinks are archives sorted by an earlier run; directories are the
        # per-package directories themselves.
        if os.path.islink(path) or os.path.isdir(path):
            continue
        todo.append(entry)

    if not todo:
        print("all archives are already sorted into package directories")
        return 0

    unresolved, failures = [], []
    for fname in todo:
        package = resolve(fname, ordered, names)
        if package is None:
            unresolved.append(fname)
            continue
        try:
            sort_archive(args.pkg_dir, fname, package, args.dry_run)
        except OSError as e:
            print(f"warning: {fname}: {e}", file=sys.stderr)
            failures.append(fname)

    print(f"\n{len(todo) - len(unresolved) - len(failures)} archive(s) sorted")
    if unresolved:
        # Not an error: an archive left in place is still served from its old
        # path, exactly as it was before. Report it so the name can be dealt
        # with, but do not fail the job that called us over it.
        print(
            f"warning: {len(unresolved)} archive(s) could not be assigned to a package "
            "and were left in place:",
            file=sys.stderr,
        )
        for fname in unresolved:
            print(f"  {fname}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
