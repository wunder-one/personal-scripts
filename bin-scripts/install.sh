#!/usr/bin/env bash
#
# Symlink bin-scripts into a user-local bin directory on PATH.
#
# Usage:
#   ./install.sh
#   BIN_DIR=/custom/bin ./install.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_script_name="$(basename "${BASH_SOURCE[0]}")"

# Standard user-local bin dirs (XDG + common convention), checked in order.
standard_bins=(
  "${HOME}/.local/bin"
  "${HOME}/bin"
)

path_contains() {
  local dir="$1"
  local entry
  local normalized_dir
  normalized_dir="$(cd "$dir" 2>/dev/null && pwd -P)" || return 1

  IFS=':' read -r -a path_entries <<< "${PATH:-}"
  for entry in "${path_entries[@]}"; do
    [[ -n "$entry" ]] || continue
    if [[ -d "$entry" ]]; then
      entry="$(cd "$entry" && pwd -P)"
      if [[ "$entry" == "$normalized_dir" ]]; then
        return 0
      fi
    elif [[ "$entry" == "$dir" || "$entry" == "$normalized_dir" ]]; then
      return 0
    fi
  done
  return 1
}

ensure_writable_bin() {
  local dir="$1"
  mkdir -p "$dir"
  [[ -w "$dir" ]]
}

pick_bin_dir() {
  local dir
  for dir in "${standard_bins[@]}"; do
    if ensure_writable_bin "$dir" && path_contains "$dir"; then
      printf '%s\n' "$dir"
      return 0
    fi
  done

  # Nothing standard is on PATH yet — default to XDG user bin.
  dir="${standard_bins[0]}"
  ensure_writable_bin "$dir"
  printf '%s\n' "$dir"
}

shell_rc_hint() {
  case "${SHELL:-}" in
    */zsh) printf '%s\n' "${HOME}/.zshrc" ;;
    */bash)
      if [[ "$(uname -s)" == "Darwin" ]]; then
        printf '%s\n' "${HOME}/.bash_profile"
      else
        printf '%s\n' "${HOME}/.bashrc"
      fi
      ;;
    *) printf '%s\n' "your shell rc file" ;;
  esac
}

target_bin="${BIN_DIR:-$(pick_bin_dir)}"
ensure_writable_bin "$target_bin"
on_path=true
path_contains "$target_bin" || on_path=false

linked=0
for script in "$script_dir"/*; do
  [[ -f "$script" ]] || continue
  name="$(basename "$script")"
  [[ "$name" == "$install_script_name" || "$name" == "README.md" ]] && continue

  link_name="${name%.*}"
  [[ -n "$link_name" ]] || link_name="$name"
  ln -sf "$script" "$target_bin/$link_name"
  chmod +x "$script"
  echo "linked $link_name -> $script"
  linked=$((linked + 1))
done

if [[ "$linked" -eq 0 ]]; then
  echo "No scripts to install in $script_dir"
  exit 0
fi

echo
echo "Installed $linked command(s) to $target_bin"

if [[ "$on_path" == false ]]; then
  rc_file="$(shell_rc_hint)"
  echo
  echo "That directory is not on your PATH yet. Add it once, then restart your shell:"
  echo
  echo "  echo 'export PATH=\"${target_bin}:\$PATH\"' >> ${rc_file}"
  echo "  source ${rc_file}"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "Warning: uv was not found on PATH."
  echo "Some scripts (like get-ps3-game-update) use a uv shebang and will not run without it."
  echo "Install uv, then re-open your shell:"
  echo
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo
  echo "Docs: https://docs.astral.sh/uv/getting-started/installation/"
fi
