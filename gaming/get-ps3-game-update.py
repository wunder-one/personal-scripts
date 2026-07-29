#!/usr/bin/env python3
"""Download the newest PS3 game update .pkg for a given title ID.

Usage:
  gaming/get-ps3-game-update.py BCUS98114
  gaming/get-ps3-game-update.py BCUS98114 -o ~/Downloads
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

# Manifest itself requires HTTPS; package URLs inside are usually plain HTTP.
MANIFEST_URL = "https://a0.ww.np.dl.playstation.net/tpl/np/{game_id}/{game_id}-ver.xml"
USER_AGENT = "Mozilla/5.0 (compatible; ps3-game-update/1.0)"


def parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def find_newest_package(root: ET.Element) -> ET.Element:
    packages = [pkg for pkg in root.findall(".//package") if "version" in pkg.attrib and "url" in pkg.attrib]
    if not packages:
        raise SystemExit("No <package> entries with version/url found in the update manifest.")
    return max(packages, key=lambda pkg: parse_version(pkg.attrib["version"]))


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def file_sha1(path: Path) -> str:
    hasher = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_pkg(
    client: httpx.Client,
    url: str,
    dest: Path,
    expected_size: int | None,
    expected_sha1: str | None,
) -> None:
    hasher = hashlib.sha1()
    downloaded = 0

    with client.stream("GET", url) as response:
        response.raise_for_status()
        total = expected_size or int(response.headers.get("Content-Length") or 0) or None

        with dest.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(
                        f"\rDownloading… {format_bytes(downloaded)} / {format_bytes(total)} ({pct}%)",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        f"\rDownloading… {format_bytes(downloaded)}",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )

    print(file=sys.stderr)

    if expected_size is not None and downloaded != expected_size:
        dest.unlink(missing_ok=True)
        raise SystemExit(f"Size mismatch: got {downloaded} bytes, expected {expected_size}")

    digest = hasher.hexdigest()
    if expected_sha1 and digest.lower() != expected_sha1.lower():
        dest.unlink(missing_ok=True)
        raise SystemExit(f"SHA1 mismatch: got {digest}, expected {expected_sha1}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the newest PS3 game update .pkg from Sony's update manifest.",
    )
    parser.add_argument("game_id", help="PS3 title ID, e.g. BCUS98114 or BCUS98232")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory to save the .pkg into (default: current directory)",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the newest .pkg URL and exit without downloading",
    )
    args = parser.parse_args()

    game_id = args.game_id.strip().upper()
    manifest_url = MANIFEST_URL.format(game_id=game_id)
    print(f"Fetching manifest: {manifest_url}", file=sys.stderr)

    # Sony's update CDN historically uses certs that fail strict verification.
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=60.0,
        verify=False,
        follow_redirects=True,
    ) as client:
        try:
            response = client.get(manifest_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"Failed to fetch manifest: {exc}") from exc

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise SystemExit(f"Failed to parse update manifest XML: {exc}") from exc

        status = root.attrib.get("status")
        if status and status != "alive":
            print(f"Warning: titlepatch status is {status!r}", file=sys.stderr)

        package = find_newest_package(root)
        version = package.attrib["version"]
        url = package.attrib["url"]
        size_raw = package.attrib.get("size")
        sha1sum = package.attrib.get("sha1sum")
        expected_size = int(size_raw) if size_raw and size_raw.isdigit() else None

        print(f"Newest version: {version}", file=sys.stderr)
        if expected_size is not None:
            print(f"Package size:  {format_bytes(expected_size)}", file=sys.stderr)
        print(f"Package URL:   {url}", file=sys.stderr)

        if args.print_url:
            print(url)
            return

        filename = url.rsplit("/", 1)[-1]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        dest = args.output_dir / filename

        if dest.exists() and expected_size is not None and dest.stat().st_size == expected_size:
            if not sha1sum or file_sha1(dest).lower() == sha1sum.lower():
                print(f"Already downloaded: {dest}", file=sys.stderr)
                print(dest)
                return

        print(f"Saving to: {dest}", file=sys.stderr)
        try:
            download_pkg(client, url, dest, expected_size, sha1sum)
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"Failed to download package: {exc}") from exc

    print(f"Done: {dest}", file=sys.stderr)
    print(dest)


if __name__ == "__main__":
    main()
