#!/usr/bin/env bash
# Point $XDG_CONFIG_HOME/quickshell/mainframe at this repo's mainframe/ directory.
# Replaces a symlink that is dangling or that already points at a Mainframe
# checkout (shell.qml names AppId/ShellId mainframe). Refuses a real file,
# a real directory, or a link to something that is not Mainframe.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/mainframe"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
TARGET="$CONFIG_HOME/quickshell/mainframe"

if [[ ! -f "$SRC/shell.qml" ]]; then
  echo "mainframe install: missing $SRC/shell.qml" >&2
  exit 1
fi

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

mkdir -p "$(dirname "$TARGET")"

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo "mainframe install: refusing to overwrite non-symlink $TARGET" >&2
  exit 1
fi

if [[ -L "$TARGET" ]]; then
  current="$(readlink "$TARGET")"
  src_resolved="$(readlink -f "$SRC")"
  if [[ ! -e "$TARGET" ]]; then
    :
  else
    resolved="$(readlink -f "$TARGET" || true)"
    if [[ "$current" == "$SRC" || ( -n "$resolved" && "$resolved" == "$src_resolved" ) ]]; then
      echo "mainframe install: already linked $TARGET -> $SRC"
      exit 0
    fi
    if [[ -z "$resolved" ]] || ! is_mainframe_dir "$resolved"; then
      echo "mainframe install: refusing to replace symlink $TARGET -> $current" >&2
      exit 1
    fi
  fi
fi

# Stage the symlink under a sibling name, then rename it into place.
# `ln -s` follows an existing directory symlink and can create
# $SRC/mainframe -> $SRC. -T never dereferences, and mv -T replaces a symlink
# without following it. Same directory, so the rename is atomic.
link_tmp="${TARGET}.tmp.$$"
if ! ln -sfnT "$SRC" "$link_tmp"; then
  echo "mainframe install: failed to create $link_tmp" >&2
  exit 1
fi
replaced=""
broken_dest=""
if [[ -L "$TARGET" ]]; then
  replaced="$(readlink "$TARGET")"
  if [[ ! -e "$TARGET" ]]; then
    broken_dest="$replaced"
  fi
fi
if ! mv -T "$link_tmp" "$TARGET"; then
  rm -f "$link_tmp"
  echo "mainframe install: failed to place $TARGET" >&2
  exit 1
fi
if [[ -n "$broken_dest" ]]; then
  echo "removing broken link $TARGET -> $broken_dest"
fi
if [[ -n "$replaced" ]]; then
  if [[ ! -e "$replaced" && "$replaced" != "$SRC" ]]; then
    echo "mainframe install: replaced dangling symlink $TARGET (was $replaced)"
  else
    echo "mainframe install: replaced $TARGET -> $replaced"
  fi
else
  echo "mainframe install: linked $TARGET -> $SRC"
fi
