# bin-scripts

Shell scripts meant to live on your `$PATH`.

## Install

```bash
./install.sh
```

That symlinks every script here into a user-local bin directory (without the `.sh` suffix). Override the target with `BIN_DIR` if you want:

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
