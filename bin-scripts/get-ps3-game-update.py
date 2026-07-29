#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.28.1",
# ]
# ///
"""Download and install PS3 game updates for a title ID via Sony + RPCS3.

Reads the installed APP_VER from RPCS3's PARAM.SFO, downloads only newer
update .pkg files from Sony's CDN, then installs them in order with:
  rpcs3 --headless --installpkg <file.pkg>

In download+install mode, packages are staged under a temp directory and
removed after every install succeeds. With --download-only, they are kept
under <output-dir>/<title-id>/ with version-prefixed filenames, e.g.:
  ~/Downloads/BCUS98232/01.04-UP9000-….pkg

Usage:
  get-ps3-game-update BCUS98232
  get-ps3-game-update BCUS98232 --download-only -o ~/Downloads
  get-ps3-game-update BCUS98232 --print-url
"""

from __future__ import annotations

import argparse
import hashlib
import resource
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

# Manifest itself requires HTTPS; package URLs inside are usually plain HTTP.
MANIFEST_URL = "https://a0.ww.np.dl.playstation.net/tpl/np/{game_id}/{game_id}-ver.xml"
USER_AGENT = "Mozilla/5.0 (compatible; ps3-game-update/1.0)"
DEFAULT_INSTALLED_VERSION = "01.00"

# Sony PackageDigest: SHA-1 of the .pkg excluding the last 0x20 bytes
# (those bytes store the digest itself plus 12 zero bytes of padding).
PKG_DIGEST_FOOTER_SIZE = 0x20

# PARAM.SFO data formats
SFO_FMT_UTF8_SPECIAL = 0x0004
SFO_FMT_UTF8 = 0x0204
SFO_FMT_INT32 = 0x0404


def parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def list_packages(root: ET.Element) -> list[ET.Element]:
    packages = [pkg for pkg in root.findall(".//package") if "version" in pkg.attrib and "url" in pkg.attrib]
    if not packages:
        raise SystemExit("No <package> entries with version/url found in the update manifest.")
    return sorted(packages, key=lambda pkg: parse_version(pkg.attrib["version"]))


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def pkg_digest_sha1(path: Path) -> str:
    size = path.stat().st_size
    if size < PKG_DIGEST_FOOTER_SIZE:
        raise SystemExit(f"Package too small to verify ({size} bytes): {path}")

    hasher = hashlib.sha1()
    remaining = size - PKG_DIGEST_FOOTER_SIZE
    with path.open("rb") as f:
        while remaining:
            chunk = f.read(min(1024 * 256, remaining))
            if not chunk:
                break
            hasher.update(chunk)
            remaining -= len(chunk)
    return hasher.hexdigest()


def download_pkg(
    client: httpx.Client,
    url: str,
    dest: Path,
    expected_size: int | None,
    expected_sha1: str | None,
) -> None:
    downloaded = 0

    with client.stream("GET", url) as response:
        response.raise_for_status()
        total = expected_size or int(response.headers.get("Content-Length") or 0) or None

        with dest.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
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

    if expected_sha1:
        digest = pkg_digest_sha1(dest)
        if digest.lower() != expected_sha1.lower():
            dest.unlink(missing_ok=True)
            raise SystemExit(f"SHA1 mismatch: got {digest}, expected {expected_sha1}")


def package_meta(package: ET.Element) -> tuple[str, str, int | None, str | None]:
    version = package.attrib["version"]
    url = package.attrib["url"]
    size_raw = package.attrib.get("size")
    sha1sum = package.attrib.get("sha1sum")
    expected_size = int(size_raw) if size_raw and size_raw.isdigit() else None
    return version, url, expected_size, sha1sum


def parse_sfo(path: Path) -> dict[str, str | int]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"\x00PSF":
        raise ValueError(f"Not a PARAM.SFO file: {path}")

    _magic, _version, key_table_start, data_table_start, entry_count = struct.unpack_from("<4sIIII", data, 0)
    result: dict[str, str | int] = {}

    for i in range(entry_count):
        key_off, data_fmt, data_len, _data_max, data_off = struct.unpack_from("<HHIII", data, 20 + i * 16)
        key_start = key_table_start + key_off
        key_end = data.find(b"\x00", key_start)
        key = data[key_start:key_end].decode("ascii")
        raw = data[data_table_start + data_off : data_table_start + data_off + data_len]

        if data_fmt in (SFO_FMT_UTF8_SPECIAL, SFO_FMT_UTF8):
            result[key] = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        elif data_fmt == SFO_FMT_INT32:
            result[key] = struct.unpack_from("<I", raw, 0)[0]

    return result


def find_rpcs3_dir(explicit: Path | None) -> Path | None:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_dir():
            raise SystemExit(f"RPCS3 dir not found: {path}")
        return path

    candidates = [
        Path.home() / ".var/app/net.rpcs3.RPCS3/config/rpcs3",
        Path.home() / ".config/rpcs3",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def parse_vfs_mapping(vfs_yml: Path, key: str) -> str | None:
    """Parse a simple key: value line from RPCS3 vfs.yml (not full YAML)."""
    try:
        text = vfs_yml.read_text(encoding="utf-8")
    except OSError:
        return None

    prefix = f"{key}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip().strip('"').strip("'")
            return value or None
    return None


def resolve_hdd0(rpcs3_dir: Path) -> Path:
    vfs_yml = rpcs3_dir / "vfs.yml"
    mapped = parse_vfs_mapping(vfs_yml, "/dev_hdd0/") if vfs_yml.is_file() else None
    if mapped:
        mapped = mapped.replace("$(EmulatorDir)", str(rpcs3_dir) + "/")
        path = Path(mapped).expanduser()
        if path.is_dir():
            return path.resolve()
        print(f"Warning: vfs.yml /dev_hdd0/ path missing: {path}", file=sys.stderr)

    fallback = rpcs3_dir / "dev_hdd0"
    if fallback.is_dir():
        return fallback.resolve()
    raise SystemExit(f"Could not resolve RPCS3 /dev_hdd0 (checked vfs.yml and {fallback})")


def installed_version(hdd0: Path, game_id: str) -> tuple[str, Path | None]:
    """Return (version, sfo_path). Prefer APP_VER, else VERSION, else 01.00."""
    sfo_path = hdd0 / "game" / game_id / "PARAM.SFO"
    if not sfo_path.is_file():
        return DEFAULT_INSTALLED_VERSION, None

    try:
        fields = parse_sfo(sfo_path)
    except (OSError, ValueError, struct.error) as exc:
        print(f"Warning: failed to parse {sfo_path}: {exc}", file=sys.stderr)
        return DEFAULT_INSTALLED_VERSION, sfo_path

    app_ver = fields.get("APP_VER")
    version = fields.get("VERSION")
    if isinstance(app_ver, str) and app_ver.strip():
        return app_ver.strip(), sfo_path
    if isinstance(version, str) and version.strip():
        return version.strip(), sfo_path
    return DEFAULT_INSTALLED_VERSION, sfo_path


def find_rpcs3_command(explicit: str | None) -> list[str]:
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.exists():
            return [str(explicit_path.resolve())]
        return shlex.split(explicit)

    on_path = shutil.which("rpcs3")
    if on_path:
        return [on_path]

    appimage = Path.home() / "Applications" / "rpcs3.AppImage"
    if appimage.is_file():
        return [str(appimage.resolve())]

    if shutil.which("flatpak"):
        probe = subprocess.run(
            ["flatpak", "info", "net.rpcs3.RPCS3"],
            check=False,
            capture_output=True,
        )
        if probe.returncode == 0:
            return ["flatpak", "run", "--command=rpcs3", "net.rpcs3.RPCS3"]

    raise SystemExit(
        "RPCS3 executable not found. Install RPCS3, put it on PATH, place "
        "~/Applications/rpcs3.AppImage, or pass --rpcs3-bin."
    )


def rpcs3_lock_path() -> Path:
    return Path.home() / ".cache/rpcs3/RPCS3.buf"


def clear_stale_rpcs3_lock() -> None:
    """Remove RPCS3.buf when no rpcs3 process is running (leftover from crashes)."""
    lock = rpcs3_lock_path()
    if not lock.exists():
        return
    probe = subprocess.run(
        ["pgrep", "-fi", "rpcs3"],
        check=False,
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    try:
        lock.unlink()
        print(f"Removed stale RPCS3 lock: {lock}", file=sys.stderr)
    except OSError as exc:
        print(f"Warning: could not remove stale RPCS3 lock {lock}: {exc}", file=sys.stderr)


def _disable_core_dumps() -> None:
    """Prevent systemd-coredump desktop notifications from headless teardown aborts."""
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def install_pkg(
    rpcs3_cmd: list[str],
    pkg_path: Path,
    *,
    expected_version: str,
    hdd0: Path | None,
    game_id: str,
) -> None:
    # --no-gui is rejected for installs ("Cannot perform installation in no-gui
    # mode!"); --headless is the supported non-interactive path (RPCS3 #18719).
    clear_stale_rpcs3_lock()
    cmd = [*rpcs3_cmd, "--headless", "--installpkg", str(pkg_path)]
    print(f"Installing: {' '.join(cmd)}", file=sys.stderr)
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            preexec_fn=_disable_core_dumps,
        )
    except OSError as exc:
        raise SystemExit(f"Failed to launch RPCS3: {exc}") from exc

    # Headless --installpkg often succeeds then aborts during teardown (exit 143 /
    # typemap assert). Trust the on-disk APP_VER when we can read it.
    if hdd0 is not None:
        current, _ = installed_version(hdd0, game_id)
        if parse_version(current) >= parse_version(expected_version):
            if result.returncode != 0:
                print(
                    f"Warning: RPCS3 exited {result.returncode} after installing "
                    f"{expected_version} (teardown abort suppressed); "
                    f"PARAM.SFO is {current}.",
                    file=sys.stderr,
                )
            return
        details = (result.stderr or result.stdout or "").strip()
        if details:
            print(details, file=sys.stderr)
        raise SystemExit(
            f"RPCS3 install failed (exit {result.returncode}) for {pkg_path}. "
            f"Expected APP_VER >= {expected_version}, still at {current}."
        )

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if details:
            print(details, file=sys.stderr)
        raise SystemExit(
            f"RPCS3 install failed (exit {result.returncode}) for {pkg_path}. "
            "Close any running RPCS3 instance, remove a stale "
            "~/.cache/rpcs3/RPCS3.buf lock if present, or install via the GUI."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download PS3 game updates newer than the installed version and install them with RPCS3."
        ),
    )
    parser.add_argument("game_id", help="PS3 title ID, e.g. BCUS98114 or BCUS98232")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("."),
        help="With --download-only: parent dir for packages (<output-dir>/<title-id>/). Ignored when installing (uses a temp dir).",
    )
    parser.add_argument(
        "--rpcs3-dir",
        type=Path,
        default=None,
        help="RPCS3 config/data root (default: auto-detect Flatpak or ~/.config/rpcs3)",
    )
    parser.add_argument(
        "--rpcs3-bin",
        default=None,
        help="RPCS3 executable, AppImage path, or command string (default: auto-detect)",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download and verify packages without installing",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print package URLs newer than the installed version and exit",
    )
    args = parser.parse_args()

    game_id = args.game_id.strip().upper()

    rpcs3_dir = find_rpcs3_dir(args.rpcs3_dir)
    hdd0: Path | None = None
    if rpcs3_dir is None:
        print(
            "Warning: RPCS3 dir not found; assuming installed version "
            f"{DEFAULT_INSTALLED_VERSION}. Pass --rpcs3-dir if needed.",
            file=sys.stderr,
        )
        current_version = DEFAULT_INSTALLED_VERSION
    else:
        print(f"RPCS3 dir: {rpcs3_dir}", file=sys.stderr)
        hdd0 = resolve_hdd0(rpcs3_dir)
        print(f"HDD0: {hdd0}", file=sys.stderr)
        current_version, sfo_path = installed_version(hdd0, game_id)
        if sfo_path:
            print(f"Installed version: {current_version} ({sfo_path})", file=sys.stderr)
        else:
            print(
                f"Installed version: {current_version} "
                f"(no game/{game_id}/PARAM.SFO; treating as base)",
                file=sys.stderr,
            )

    current_parsed = parse_version(current_version)
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

        all_packages = list_packages(root)
        packages = [
            pkg for pkg in all_packages if parse_version(pkg.attrib["version"]) > current_parsed
        ]

        print(
            f"Manifest has {len(all_packages)} package(s): "
            f"{', '.join(pkg.attrib['version'] for pkg in all_packages)}",
            file=sys.stderr,
        )
        print(
            f"Newer than {current_version}: {len(packages)} package(s)"
            + (f": {', '.join(pkg.attrib['version'] for pkg in packages)}" if packages else ""),
            file=sys.stderr,
        )

        if not packages:
            print("Nothing to do.", file=sys.stderr)
            return

        total_size = 0
        for package in packages:
            _, _, expected_size, _ = package_meta(package)
            if expected_size is not None:
                total_size += expected_size
        if total_size:
            print(f"Download size: {format_bytes(total_size)}", file=sys.stderr)

        if args.print_url:
            for package in packages:
                print(package.attrib["url"])
            return

        cleanup_dir: Path | None = None
        if args.download_only:
            dest_dir = args.output_dir.expanduser().resolve() / game_id
            dest_dir.mkdir(parents=True, exist_ok=True)
        else:
            cleanup_dir = Path(tempfile.mkdtemp(prefix=f"ps3-updates-{game_id}-"))
            dest_dir = cleanup_dir / game_id
            dest_dir.mkdir(parents=True, exist_ok=True)

        print(f"Output directory: {dest_dir}", file=sys.stderr)
        saved: list[tuple[str, Path]] = []

        try:
            for index, package in enumerate(packages, start=1):
                version, url, expected_size, sha1sum = package_meta(package)
                filename = f"{version}-{url.rsplit('/', 1)[-1]}"
                dest = dest_dir / filename

                size_note = f", {format_bytes(expected_size)}" if expected_size is not None else ""
                print(f"[{index}/{len(packages)}] version {version}{size_note}", file=sys.stderr)

                if dest.exists() and expected_size is not None and dest.stat().st_size == expected_size:
                    if not sha1sum or pkg_digest_sha1(dest).lower() == sha1sum.lower():
                        print(f"Already downloaded: {dest}", file=sys.stderr)
                        print(dest)
                        saved.append((version, dest))
                        continue

                print(f"Saving to: {dest}", file=sys.stderr)
                try:
                    download_pkg(client, url, dest, expected_size, sha1sum)
                except httpx.HTTPError as exc:
                    dest.unlink(missing_ok=True)
                    raise SystemExit(f"Failed to download package {version}: {exc}") from exc

                print(f"Done: {dest}", file=sys.stderr)
                print(dest)
                saved.append((version, dest))

            print(f"Downloaded {len(saved)} package(s).", file=sys.stderr)

            if args.download_only:
                return

            rpcs3_cmd = find_rpcs3_command(args.rpcs3_bin)
            print(f"RPCS3: {' '.join(rpcs3_cmd)}", file=sys.stderr)
            for index, (version, pkg_path) in enumerate(saved, start=1):
                print(f"Install [{index}/{len(saved)}] version {version}", file=sys.stderr)
                install_pkg(
                    rpcs3_cmd,
                    pkg_path,
                    expected_version=version,
                    hdd0=hdd0,
                    game_id=game_id,
                )

            print(f"Installed {len(saved)} package(s).", file=sys.stderr)
        except BaseException:
            if cleanup_dir is not None:
                print(
                    f"Leaving staged packages in {cleanup_dir} after failure.",
                    file=sys.stderr,
                )
            raise
        else:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
                print(f"Removed staging directory: {cleanup_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
