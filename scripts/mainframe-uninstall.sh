#!/usr/bin/env bash
# Remove the quickshell mainframe symlink when it points at any Mainframe
# checkout, or when it is dangling. A real file or a link to something else
# is left in place.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/mainframe"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
TARGET="$CONFIG_HOME/quickshell/mainframe"

is_mainframe_dir() {
  local dir="$1"
  local preview
  # No pipe: `head | grep -q` can die with SIGPIPE under pipefail when the
  # match is early, which looks like "not mainframe". Exact AppId/ShellId
  # token, optional colon or space, optional quotes. A hyphen continues the
  # token, so ShellId mainframe-other does not match. First 40 lines only.
  local ident='(^|[^[:alnum:]_])(AppId|ShellId)\b[[:space:]]*:?[[:space:]]*["'\'']?mainframe\b["'\'']?([^[:alnum:]_-]|$)'
  [[ -d "$dir" && -f "$dir/shell.qml" ]] || return 1
  preview="$(sed -n '1,40p' -- "$dir/shell.qml")" || return 1
  grep -E "$ident" <<<"$preview" >/dev/null
}

if [[ -L "$TARGET" ]]; then
  current="$(readlink "$TARGET")"
  if [[ ! -e "$TARGET" ]]; then
    rm -- "$TARGET"
    echo "removing broken link $TARGET -> $current"
    echo "mainframe uninstall: removed dangling symlink $TARGET"
    exit 0
  fi
  resolved="$(readlink -f "$TARGET" || true)"
  src_resolved="$(readlink -f "$SRC")"
  if [[ "$current" == "$SRC" || ( -n "$resolved" && "$resolved" == "$src_resolved" ) ]] || is_mainframe_dir "$resolved"; then
    rm -- "$TARGET"
    echo "mainframe uninstall: removed symlink $TARGET"
    exit 0
  fi
  echo "mainframe uninstall: $TARGET points at $current, not a Mainframe checkout; left in place" >&2
  exit 1
fi

if [[ -e "$TARGET" ]]; then
  echo "mainframe uninstall: $TARGET is not a symlink; left in place" >&2
  exit 1
fi

echo "mainframe uninstall: nothing to remove ($TARGET)"
