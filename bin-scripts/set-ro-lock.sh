#!/bin/zsh
#
# Lock a directory as root-owned, read-only, and immutable.
#
# Usage:
#   sudo set-ro-lock.sh "/path/to/directory"
#   sudo set-ro-lock.sh --unlock "/path/to/directory"

set -eu

script_name="${0:t}"

usage() {
  echo "Usage: sudo $script_name [--unlock] \"/path/to/directory\"" >&2
}

mode="lock"

if [[ "${1:-}" == "--unlock" ]]; then
  mode="unlock"
  shift
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

input_path="$1"

if [[ ! -d "$input_path" ]]; then
  echo "Error: Not a directory: $input_path" >&2
  exit 1
fi

if [[ -L "$input_path" ]]; then
  echo "Error: Refusing to operate on a symbolic link: $input_path" >&2
  exit 1
fi

target_path="${input_path:A}"

if [[ "$target_path" == "/" ]]; then
  echo "Error: Refusing to operate on the filesystem root." >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Error: Run this script with sudo:" >&2
  if [[ "$mode" == "unlock" ]]; then
    echo "  sudo $script_name --unlock \"$target_path\"" >&2
  else
    echo "  sudo $script_name \"$target_path\"" >&2
  fi
  exit 1
fi

if [[ "$mode" == "unlock" ]]; then
  if [[ -z "${SUDO_USER:-}" || "$SUDO_USER" == "root" ]]; then
    echo "Error: Run with sudo from the user who should own the unlocked directory." >&2
    exit 1
  fi

  owner="$SUDO_USER"
  group="$(id -gn "$owner")"

  chflags -R nouchg "$target_path"
  chown -R "$owner:$group" "$target_path"
  chmod -R u+w "$target_path"

  echo "Unlocked: $target_path"
  echo "Owner: $owner:$group"
else
  chown -R root:wheel "$target_path"
  chmod -R a-w "$target_path"
  chflags -R uchg "$target_path"

  echo "Locked read-only: $target_path"
  echo "Owner: root:wheel"
fi
