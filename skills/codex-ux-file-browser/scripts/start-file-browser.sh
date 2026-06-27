#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
launcher="$script_dir/launch.py"

workspace=$PWD
if [ "$#" -gt 0 ]; then
  case "$1" in
    --*) ;;
    *)
      workspace=$1
      shift
      ;;
  esac
fi

foreground=0
if [ "${1:-}" = "--foreground" ]; then
  foreground=1
  shift
fi

find_python() {
  for candidate in "${CODEX_UX_PYTHON:-}" \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3 \
    python3
  do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -f "$launcher" ]; then
  printf "Missing File Browser launcher: %s\n" "$launcher" >&2
  exit 1
fi

python_bin=$(find_python) || {
  printf "Could not find a working python3 for Codex UX File Browser\n" >&2
  exit 1
}

if [ "$foreground" -eq 1 ]; then
  exec "$python_bin" "$launcher" "$workspace" "$@"
fi

exec "$python_bin" "$launcher" "$workspace" --reuse --detach --json "$@"
