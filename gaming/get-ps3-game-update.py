#!/usr/bin/env python3
"""Download the newest PS3 game update .pkg for a given title ID.

Usage:
  gaming/get-ps3-game-update.py BCUS98114
  gaming/get-ps3-game-update.py BCUS98114 -o ~/Downloads
"""

from __future__ import annotations

import argparse
import hashlib
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Manifest itself requires HTTPS; package URLs inside are usually plain HTTP.
MANIFEST_URL = "https://a0.ww.np.dl.playstation.net/tpl/np/{game_id}/{game_id}-ver.xml"
USER_AGENT = "Mozilla/5.0 (compatible; ps3-game-update/1.0)"


def ssl_context() -> ssl.SSLContext:
    # Sony's update CDN historically uses certs that fail strict verification.
    return ssl._create_unverified_context()


def parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60, context=ssl_context()) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to fetch {url}: {exc.reason}") from exc


def find_newest_package(root: ET.Element) -> ET.Element:
    packages = [pkg for pkg in root.findall(".//package") if "version" in pkg.attrib and "url" in pkg.attrib]
    if not packages:
        raise SystemExit("No <package> entries with version/url found in the update manifest.")
    return max(packages, key=lambda pkg: parse_version(pkg.attrib["version"]))


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def download_pkg(url: str, dest: Path, expected_size: int | None, expected_sha1: str | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Only pass an SSL context for https package URLs.
    open_kwargs: dict = {"timeout": 60}
    if url.startswith("https://"):
        open_kwargs["context"] = ssl_context()
    try:
        response = urllib.request.urlopen(request, **open_kwargs)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} downloading {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to download {url}: {exc.reason}") from exc

    total = expected_size
    if total is None:
        length = response.headers.get("Content-Length")
        total = int(length) if length and length.isdigit() else None

    hasher = hashlib.sha1()
    downloaded = 0

    try:
        with dest.open("wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
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
    finally:
        response.close()

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
    parser.add_argument(
        "game_id",
        help="PS3 title ID, e.g. BCUS98114 or BCUS98232",
    )
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

    xml_bytes = fetch_bytes(manifest_url)
    try:
        root = ET.fromstring(xml_bytes)
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
        if sha1sum:
            hasher = hashlib.sha1()
            with dest.open("rb") as existing:
                while True:
                    chunk = existing.read(1024 * 256)
                    if not chunk:
                        break
                    hasher.update(chunk)
            if hasher.hexdigest().lower() == sha1sum.lower():
                print(f"Already downloaded (SHA1 ok): {dest}", file=sys.stderr)
                print(dest)
                return
        else:
            print(f"Already downloaded: {dest}", file=sys.stderr)
            print(dest)
            return

    print(f"Saving to: {dest}", file=sys.stderr)
    download_pkg(url, dest, expected_size, sha1sum)
    print(f"Done: {dest}", file=sys.stderr)
    print(dest)


if __name__ == "__main__":
    main()
