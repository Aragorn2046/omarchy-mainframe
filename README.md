# Mainframe

**A beautiful, theme-aware system monitor for [Omarchy](https://omarchy.org).** Every core, memory, GPU, disk,
network, battery and your busiest apps, on one screen, at once. No tabs. No 1991 terminal look.

![Mainframe on Omarchy](docs/screenshot.png)

## Why

Omarchy ships `btop`, which is powerful but looks like a terminal from another era. Task-manager style apps make you
click between CPU, memory and GPU pages. Mainframe shows everything you care about in equal tiles on a single
screen, and it wears your Omarchy theme: switch themes and Mainframe follows within two seconds.

## Features

- **Every logical core** as its own meter with its percentage (compact heat-map mode on 32+ core machines)
- **CPU** total, package temperature, frequency and history
- **Memory** used / available / cached and swap, with history
- **GPU** busy % and frequency: Intel Arc (`xe`), Intel (`i915`) and AMD (`amdgpu`); NVIDIA shows "not supported"
  rather than polling `nvidia-smi` every second
- **Disk** read / write rates, root filesystem usage, drive temperature
- **Network** download / upload with history, per interface
- **Battery** charge, state and power draw (hidden gracefully on desktops)
- **Top apps** by live CPU and by memory, grouped by name (`chromium ×42`)
- **Follows your Omarchy theme live**, dark and light, using your Omarchy font
- **Light**: about 1.3% of one CPU core and ~180 MB RAM while open on a real Wayland session; nothing runs when it is
  closed. No root, no daemons, no compiled code: plain QML, JavaScript and Python.

## Requirements

- Omarchy (Arch Linux + Hyprland), which already includes Quickshell (`qs`) and Python 3
- Linux `/proc` and `/sys` (that's it)

## Install

```bash
git clone https://github.com/Aragorn2046/omarchy-mainframe.git ~/.local/share/omarchy-mainframe
~/.local/share/omarchy-mainframe/install.sh
```

The installer links `~/.config/quickshell/mainframe` to the cloned `mainframe/` folder. It replaces only an older
Mainframe link or a broken link at that path, and refuses anything else (a real folder, a file, or a link to another
app). Run it:

```bash
qs -c mainframe
```

### Put it on a key

Add this to `~/.config/hypr/bindings.lua` (this example replaces Omarchy's btop key, Super+Ctrl+T):

```lua
hl.unbind("SUPER + CTRL + T")
o.bind("SUPER + CTRL + T", "Activity", "omarchy-launch-or-focus mainframe 'uwsm-app -- qs -c mainframe'")
```

Press the key again to bring an open Mainframe window to the front instead of opening a second one.

### Update

```bash
git -C ~/.local/share/omarchy-mainframe pull --ff-only
```

Close and reopen Mainframe to load the new version.

### Uninstall

```bash
~/.local/share/omarchy-mainframe/uninstall.sh && rm -rf ~/.local/share/omarchy-mainframe
```

The uninstaller removes only the Mainframe link (or a broken link at that path); the folder is deleted only if that
succeeds. Remove the key binding from `bindings.lua` if you added one.

## Keys

| Key | Action |
|---|---|
| `Esc` / `q` | Close |
| `r` | Restart the data collector if it stopped |

## How it works

`mainframe/shell.qml` is a Quickshell app that opens one normal Hyprland window. A small Python sampler
(`mainframe/collect.py`) reads `/proc` and `/sys` once per second and streams compact JSON to the window. It exits
with the window (parent-death signal plus end-of-input), so nothing is left running. Colours come from
`~/.local/state/omarchy/current/theme/colors.toml`, the same file the Omarchy shell uses.

## Development

```bash
node --test mainframe/tests/        # unit tests for the metrics logic
scripts/mainframe-smoke.sh                    # headless load, layout, CPU and cleanup checks
MAINFRAME_SMOKE_LIVE=1 scripts/mainframe-smoke.sh   # also measures CPU on a real window (opens it for ~40 s)
```

## Roadmap

- Bar widget: a small monochrome icon for the Omarchy bar with the key numbers on hover
- Remote tabs: monitor your other machines (Linux and macOS) over SSH, one tab each

## License

MIT
