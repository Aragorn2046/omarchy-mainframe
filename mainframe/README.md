# Mainframe

Single-screen system dashboard for [Quickshell](https://quickshell.org/) 0.3.2.
One floating window, seven cards, no pages. Colours follow the live Omarchy theme.

## Launch

From this directory:

```sh
qs -p /path/to/mainframe
```

After install:

```sh
qs -c mainframe
```

The Wayland app id is `mainframe` and the window title is `Mainframe`.
Escape or `q` closes the window and quits the process. Closing the window does the same.
`r` restarts the collector after it has stopped.

## Install

From the repo root:

```sh
scripts/mainframe-install.sh
scripts/mainframe-uninstall.sh
```

Install symlinks `~/.config/quickshell/mainframe` (or `$XDG_CONFIG_HOME/quickshell/mainframe`) at this `mainframe/` directory. It replaces a symlink that is dangling or that already points at a Mainframe checkout (`shell.qml` names `AppId` or `ShellId` `mainframe`), and it prints what it replaced. It refuses a real file, a real directory, or a link to something that is not Mainframe. Uninstall removes the link when it points at any Mainframe checkout or when it is dangling.

## What the cards show

`collect.py` samples on its own once a second and prints one parsed JSON line. The shell publishes every sample. The process table is included every 3 seconds, or every 6 seconds when a sweep takes longer than 40 ms. `procs.sweep_ms` is that sweep's measured cost. Each history graph keeps 60 samples and redraws when a new point arrives. The shell only watches stdin for EOF or `quit`, and restarts the collector if it goes quiet.

| Card | Source |
| --- | --- |
| CPU | `/proc/stat` busy percent for the total and each cpu id, per-core MHz from the cpufreq file for that id, package temperature from `coretemp` / `k10temp` / `zenpower` |
| Memory | `/proc/meminfo`. Used is total minus available |
| GPU | Intel `xe` idle residency against wall time, or amdgpu busy percent. Nvidia is shown as not supported |
| Disk | `/proc/diskstats` sectors × 512 for the disk that backs `/`, root used/total from `statvfs`, disk temperature when a sensor exists |
| Network | `/proc/net/dev` summed over physical interfaces, headline from the default route. Other NICs are listed under it |
| Battery | `BAT*` capacity, status, and watts. Re-read every 5 seconds |
| Processes | One full `/proc` pass every 3 seconds (6 seconds if that pass exceeds 40 ms). CPU% uses each pid's own read time. New pids wait for a second sighting. Top 8 by CPU and top 8 by memory |

A sensor that throws is `null` with an entry in `errors`. The rest of that sample is still sent. The collector exits when its parent dies, when stdin closes, or on SIGTERM.

## Theme

Colours come from `~/.local/state/omarchy/current/theme/colors.toml`.
The file is watched, and it is also re-read every 2 seconds so a theme switch that swaps the `current/theme` symlink shows up within 2 seconds.

`background` paints the window. `lighter_background` paints the cards (or background mixed 6% toward foreground). Text uses `foreground`, labels use `dark_foreground` (or `muted`). Meters and graphs use `accent`, then `yellow` from 70% and `red` from 90%. The font is the `monospace` fontconfig alias.

## Checks

```sh
node --test mainframe/tests/
scripts/mainframe-smoke.sh
```

`mainframe/lib/metrics.js` holds the parsing and delta math. The node tests feed it fixture numbers and theme formats. The smoke script runs those tests, asks `collect.py` for live samples, and loads the QML under `QT_QPA_PLATFORM=offscreen` at 1800×1125 and 900×1125. `qmllint` is used when it is installed. The offscreen run does not show a window. Software rendering overstates the cost, so that regression gate is under 3.0% of one core at both sizes. It cannot prove how the compositor will tile the real Wayland surface.

On a real Wayland session, `MAINFRAME_SMOKE_LIVE=1 scripts/mainframe-smoke.sh` launches `qs -p mainframe` with no offscreen platform, waits 5 seconds, and measures that process tree for 30 seconds. The gate there is under 2% of one core. The app quits itself and the check then confirms the collector is gone. That mode is skipped otherwise.
