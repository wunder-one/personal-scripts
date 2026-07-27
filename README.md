# personal-scripts

Random shell scripts I actually use. Nothing fancy — copy what you need.

## What's here

### `bin-scripts/`

- **`set-ro-lock.sh`** — Lock a directory as root-owned, read-only, and immutable (or unlock it). Needs `sudo`.

### `homelab/`

- **`create-stack.sh`** — Spin up Docker stack dirs under `/opt/stacks` with the right ownership and permissions. Also has a `--fix-all` mode for when things get weird.

## Usage

### `bin-scripts/`

Run `./install.sh` inside that folder to symlink everything onto your `$PATH`. See [bin-scripts/README.md](bin-scripts/README.md) for details.

## License

MIT — do whatever, no warranty.
