#!/usr/bin/env bash
# Install Mainframe: links ~/.config/quickshell/mainframe to this checkout.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/mainframe-install.sh" "$@"
