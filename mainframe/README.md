# Mainframe

Single-screen system dashboard for [Quickshell](https://quickshell.org/) 0.3.2.
One floating window with seven cards and an on-demand storage view. Colours follow Omarchy by default, or use a theme you choose for Mainframe.

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
`r` restarts the collector after it has stopped. Press `t` or the theme button to choose a theme. Click the Disk card to open Storage; Escape or Back returns to the dashboard.

## Install

From the repo root:

```sh
scripts/mainframe-install.sh
scripts/mainframe-uninstall.sh
```

Install symlinks `~/.config/quickshell/mainframe` (or `$XDG_CONFIG_HOME/quickshell/mainframe`) at this `mainframe/` directory. It replaces a symlink that is dangling or that already points at a Mainframe checkout (`shell.qml` names `AppId` or `ShellId` `mainframe`), and it prints what it replaced. It refuses a real file, a real directory, or a link to something that is not Mainframe. Uninstall removes the link when it points at any Mainframe checkout or when it is dangling.

## What the cards show

`collect.py` samples on its own once a second and prints one parsed JSON line. The shell publishes every sample. The process table is included every 3 seconds, or every 6 seconds when a sweep takes longer than 40 ms. `procs.sweep_ms` is that sweep's measured cost. Each history graph keeps 60 samples and redraws when a new point arrives. The shell only watches stdin for EOF or `quit`, and restarts the collector if it goes quiet.

`--remote` is the same program sent over SSH. It does not watch stdin, because that stream is the script and closes as soon as it has been read. Samples stay at 1 Hz and the process table is every 5 seconds. Each line adds `host`, `os` (`linux` or `darwin`) and `kernel`. A Linux kernel that contains `microsoft` or `WSL` also sets `wsl`. macOS fills CPU, memory, disk, network, battery and processes without root; GPU and temperatures are `n/a`. The remote process exits on SIGHUP, SIGTERM or a broken pipe, and it does not arm the parent-death signal.

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

## Storage

Click Disk to see root filesystem usage by category. Storage uses allocated blocks, counts hard links once, skips symbolic links and other devices or subvolumes, and scans readable parts of the home directory and system Flatpak and `/opt` directories. Unrecognised home files appear under Other. System & other is the remaining used space; system files are not scanned without admin rights. Filesystem snapshots and compressed or shared blocks can make category estimates approximate.

The scan runs on demand at low CPU and I/O priority. It shows progress and stops after ten minutes with partial results. Close Storage to cancel it, or select Rescan to start again. Results are cached for one hour in `$XDG_CACHE_HOME/mainframe/storage.json`. Remote tabs display a local-only notice. Select a category to open its folder in Baobab, or in the file manager if Baobab is unavailable.

## Theme

Choose a theme with `t` or the button in the window. Mainframe opens Omarchy's image picker, using previews from your Omarchy themes and the installed themes. Select `follow-omarchy` to track the system theme. If Omarchy's picker is unavailable, Mainframe shows a message and keeps working.

The choice is saved in `$XDG_CONFIG_HOME/mainframe/settings.json` (normally `~/.config/mainframe/settings.json`). Preview links are kept under `$XDG_CACHE_HOME/mainframe/theme-previews/`. If a selected theme is removed, Mainframe follows Omarchy and shows a hint. Mainframe watches the chosen `colors.toml` and reloads it when it changes.

Text uses foreground ink. Graphs use theme colours, with a dashed line for outgoing traffic. Hover over a graph for a sample. Rate graphs show their peak and the history window. Flat histories show `steady`. Meters use warning colours above 70% and a visible outline at 90%; battery warnings use low charge instead. The font is the `monospace` fontconfig alias.

## Checks

```sh
node --test mainframe/tests/
python3 -m unittest discover -s mainframe/tests -p 'test_*.py'
python3 mainframe/tests/storage-smoke.py
scripts/mainframe-smoke.sh
```

`mainframe/lib/metrics.js` holds the parsing and delta math. The node tests feed it fixture numbers and theme formats. The smoke script runs those tests, asks `collect.py` for live samples, and loads the QML under `QT_QPA_PLATFORM=offscreen` at 1800×1125 and 900×1125. `qmllint` is used when it is installed. The offscreen run does not show a window. Software rendering overstates the cost, so that regression gate is under 3.0% of one core at both sizes. It cannot prove how the compositor will tile the real Wayland surface.

On a real Wayland session, `MAINFRAME_SMOKE_LIVE=1 scripts/mainframe-smoke.sh` launches `qs -p mainframe` with no offscreen platform, waits 5 seconds, and measures that process tree for 30 seconds. The gate there is under 2% of one core. The app quits itself and the check then confirms the collector is gone. That mode is skipped otherwise.
