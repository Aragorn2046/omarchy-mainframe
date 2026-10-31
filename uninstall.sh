#!/usr/bin/env bash
# Uninstall Mainframe: removes only the Mainframe link.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/mainframe-uninstall.sh" "$@"
