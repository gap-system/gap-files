#!/usr/bin/env python3

"""
Mirror GAP release archives from GitHub onto files.gap-system.org.

This automates what used to be the manual last step of a GAP release,
`ssh gap-files; ./download_release.sh X.Y.Z`, as described in
https://github.com/gap-system/gap/blob/master/dev/releases/README.md

Stable releases are mirrored into `<dest>/gap-<major>.<minor>/<format>/`, so
for example

    https://files.gap-system.org/gap-4.16/tar.gz/gap-4.16.0.tar.gz

Each archive is accompanied by the `.sha256` file published alongside it, and
is verified against that checksum before being moved into place. Pre-releases
(betas and release candidates) are not mirrored.

By default an archive that is already present is left alone without being read
back; pass --verify to re-check the checksums of everything that is already
mirrored, which is worth doing periodically but is expensive.
"""

import argparse
import hashlib
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

REPO = "gap-system/gap"
API_URL = f"https://api.github.com/repos/{REPO}/releases"

# (connect, read) timeouts in seconds. Generous on purpose: the point is to
# bound a hang, not to enforce a fast connection.
TIMEOUT = (30, 60)
ATTEMPTS = 3

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Releases older than this predate the current naming and directory layout:
# 4.9 has no per-format subdirectories at all, while 4.10 and 4.11 shipped
# .tar.bz2 archives and differently named Windows installers. They are already
# mirrored in their historical layout, so we leave them alone rather than
# retroactively publishing files that never existed for them.
MIN_VERSION = (4, 12, 0)

# Which release assets to mirror, and the subdirectory each one goes into.
# Everything else in a release -- notably packages-*.zip, package-infos.json.gz
# and help-links.json.gz -- is deliberately not mirrored, matching what
# download_release.sh has always copied.
ASSET_SUFFIXES = {
    ".tar.gz": "tar.gz",
    "-core.tar.gz": "tar.gz",
    ".zip": "zip",
    "-core.zip": "zip",
    "-x86_64.exe": "exe",
}


def notice(msg: str) -> None:
    print(msg, flush=True)


def warning(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr, flush=True)


def session() -> requests.Session:
    s = requests.Session()
    # A token is not required for a public repository, but raises the API rate
    # limit and is useful if this ever runs somewhere busier.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    s.headers["Accept"] = "application/vnd.github+json"
    return s


def get(s: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """GET `url`, retrying transient failures."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = s.get(url, timeout=TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            transient = isinstance(e, (requests.ConnectionError, requests.Timeout)) or (
                isinstance(e, requests.HTTPError)
                and e.response is not None
                and (e.response.status_code == 429 or e.response.status_code >= 500)
            )
            if attempt == ATTEMPTS or not transient:
                raise
            warning(f"{url} failed ({e}), retrying")
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def stable_releases(s: requests.Session) -> List[Dict[str, Any]]:
    """Return all published, non-prerelease releases with a vX.Y.Z tag."""
    result = []
    page = 1
    while True:
        response = get(s, API_URL, params={"per_page": 100, "page": page})
        batch = response.json()
        if not batch:
            break
        for release in batch:
            if release["draft"] or release["prerelease"]:
                continue
            if TAG_RE.match(release["tag_name"]):
                result.append(release)
        page += 1
    return result


def version_of(release: Dict[str, Any]) -> Tuple[int, int, int]:
    match = TAG_RE.match(release["tag_name"])
    assert match is not None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def sha256_of_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256(data: bytes) -> str:
    """Extract the digest from the contents of a .sha256 file.

    GAP publishes these as a bare digest with no trailing newline, but accept
    the `sha256sum` format (digest followed by a filename) as well.
    """
    text = data.decode("ascii", errors="replace").strip()
    token = text.split()[0] if text.split() else ""
    if len(token) != 64 or not all(c in "0123456789abcdefABCDEF" for c in token):
        raise ValueError(f"not a sha256 digest: {text[:80]!r}")
    return token.lower()


def download_verified(s: requests.Session, url: str, dst: str, expected: str) -> None:
    """Download `url` to `dst`, but only put it in place if it verifies.

    The destination directory is served directly over HTTP, so a partially
    downloaded archive must never be visible there, and an existing good
    archive must survive a failed download.
    """
    tmp = dst + ".part"
    try:
        with get(s, url, stream=True) as response:
            with open(tmp, "wb") as f:
                for chunk in response.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
        actual = sha256_of_file(tmp)
        if actual != expected:
            raise ValueError(f"{url} has SHA256 {actual}, expected {expected}")
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def classify(name: str, version: str) -> Optional[str]:
    """Return the subdirectory `name` belongs in, or None if not mirrored."""
    for suffix, subdir in ASSET_SUFFIXES.items():
        if name == f"gap-{version}{suffix}":
            return subdir
    return None


def mirror_release(
    s: requests.Session,
    release: Dict[str, Any],
    dest: str,
    verify: bool,
    dry_run: bool,
) -> List[str]:
    """Mirror one release. Returns a list of human readable failures."""
    major, minor, patch = version_of(release)
    version = f"{major}.{minor}.{patch}"
    series_dir = os.path.join(dest, f"gap-{major}.{minor}")

    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    failures = []

    for name, url in sorted(assets.items()):
        subdir = classify(name, version)
        if subdir is None:
            continue

        target = os.path.join(series_dir, subdir, name)
        sha_target = target + ".sha256"
        sha_url = assets.get(name + ".sha256")

        if os.path.exists(target) and os.path.exists(sha_target):
            if not verify:
                continue
            try:
                with open(sha_target, "rb") as f:
                    expected = parse_sha256(f.read())
                actual = sha256_of_file(target)
                if actual == expected:
                    continue
                warning(f"{target} has SHA256 {actual}, expected {expected}")
            except (OSError, ValueError) as e:
                warning(f"{target}: {e}")

        if sha_url is None:
            failures.append(f"{version}: {name} has no .sha256 asset")
            continue

        if dry_run:
            notice(f"would mirror {name} to {os.path.dirname(target)}")
            continue

        try:
            sha_data = get(s, sha_url).content
            expected = parse_sha256(sha_data)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            notice(f"mirroring {name} to {os.path.dirname(target)}")
            download_verified(s, url, target, expected)
            # Write the checksum only once the archive is in place: if we are
            # interrupted in between, the missing .sha256 makes the next run
            # fetch the archive again rather than trust it.
            with open(sha_target, "wb") as f:
                f.write(sha_data)
        except (requests.RequestException, OSError, ValueError) as e:
            failures.append(f"{version}: {name}: {e}")

    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        default=os.path.expanduser("~/http"),
        help="directory served by the web server (default: ~/http)",
    )
    parser.add_argument(
        "--since",
        default=".".join(str(n) for n in MIN_VERSION),
        help="oldest release to consider, as X.Y.Z (default: %(default)s)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-check the checksums of already mirrored archives",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be mirrored, without downloading",
    )
    args = parser.parse_args(argv)

    try:
        since = tuple(int(n) for n in args.since.split("."))
        if len(since) != 3:
            raise ValueError
    except ValueError:
        parser.error(f"--since must be of the form X.Y.Z, not {args.since!r}")

    if not os.path.isdir(args.dest):
        print(f"error: {args.dest} is not a directory", file=sys.stderr)
        return 1

    # Archives are served over HTTP, so they must be world readable.
    os.umask(0o022)

    s = session()
    try:
        releases = stable_releases(s)
    except requests.RequestException as e:
        print(f"error: could not list releases: {e}", file=sys.stderr)
        return 1

    considered = [r for r in releases if version_of(r) >= since]
    skipped = len(releases) - len(considered)
    notice(
        f"found {len(releases)} stable releases, considering {len(considered)}"
        + (f" (skipping {skipped} older than {args.since})" if skipped else "")
    )

    failures = []
    for release in sorted(considered, key=version_of):
        failures += mirror_release(s, release, args.dest, args.verify, args.dry_run)

    if failures:
        for failure in failures:
            warning(failure)
        print(f"error: {len(failures)} asset(s) could not be mirrored", file=sys.stderr)
        return 1

    notice("all release archives are mirrored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
