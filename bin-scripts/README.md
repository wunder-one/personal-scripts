# bin-scripts

Scripts meant to live on your `$PATH` (shell or Python).

## Install

```bash
./install.sh
```

That symlinks every script here into a user-local bin directory (without the `.sh` / `.py` suffix). Override the target with `BIN_DIR` if you want:

```bash
BIN_DIR="$HOME/bin" ./install.sh
```

### Where scripts go

The installer picks the first directory that is both **writable** and **already on your PATH**:

1. `~/.local/bin` (XDG default — works on macOS and Linux)
2. `~/bin`

If neither is on `PATH` yet, it uses `~/.local/bin` and prints the exact line to add to your shell rc file.

Re-run `./install.sh` any time you add scripts — it's safe to run again.

### sudo scripts

Some commands (like `set-ro-lock`) need `sudo`. Root often has a minimal `PATH`, so `sudo set-ro-lock` may not find `~/.local/bin`. Use the full path or install those to a system bin:

```bash
BIN_DIR=/usr/local/bin sudo ./install.sh
```

## Scripts

- **`set-ro-lock`** — Lock a directory as root-owned, read-only, and immutable. Pass `--unlock` to reverse. Needs `sudo`.
- **`get-ps3-game-update`** — Download Sony PS3 title updates newer than the version installed in RPCS3, then install them headlessly. Uses `uv run --script` (needs [`uv`](https://docs.astral.sh/uv/) on `PATH`); pulls `httpx` automatically.

### get-ps3-game-update

Reads `APP_VER` from `dev_hdd0/game/<TITLE_ID>/PARAM.SFO` (via RPCS3 `vfs.yml`), fetches Sony's update manifest, downloads only newer `.pkg` files, and runs:

```bash
rpcs3 --no-gui --installpkg <file.pkg>
```

once per package in version order.

```bash
# Download + install (pkgs staged in a temp dir, removed after success)
get-ps3-game-update BCUS98232

# Download only (keep pkgs under -o)
get-ps3-game-update BCUS98232 -o ~/Downloads/ps3-updates --download-only

# List URLs that would be downloaded
get-ps3-game-update BCUS98232 --print-url

# Overrides for non-default layouts
get-ps3-game-update BCUS98232 \
  --rpcs3-dir ~/.config/rpcs3 \
  --rpcs3-bin ~/Applications/rpcs3.AppImage
```

On Bazzite / EmuDeck, HDD0 often lives under `~/Emulation/storage/rpcs3/dev_hdd0` (mapped in `vfs.yml`). Headless install needs a recent RPCS3 build that supports `--no-gui --installpkg`. Requires `uv` on `PATH` (the script shebang runs via `uv run --script`). If install fails mid-run, the temp staging directory is left in place for retry.
