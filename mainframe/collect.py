#!/usr/bin/env python3
"""Self-driving host sampler for Mainframe.

Emits one compact JSON object per second on a monotonic schedule. Numbers are
parsed here; the shell does not see raw /proc text. The process table is
included every 3 seconds. A sweep longer than 40 ms stretches the next gap to
6 seconds, and the sample reports that sweep's measured time. Stdin is watched
only for EOF or "quit".

--remote is the copy sent over ssh. It does not watch stdin (that stream is
the script itself and closes immediately). It emits the same JSON plus host,
os and kernel, samples once a second, and includes the process table every
5 seconds. It does not ignore SIGPIPE. On SIGHUP, SIGTERM, SIGPIPE, a stdout
write failure, or when the parent pid becomes 1, it kills every tracked
child process group and exits.

--once prints one sample (with a process sweep) and exits. --selftest runs
the pure parser checks.
"""

import atexit
import base64
import datetime
import tempfile
import ctypes
import fcntl
import glob
import hashlib
import copy
import json
import math
import os
import pty
import plistlib
import re
import select
import signal
import struct
import stat
import subprocess
import sys
import time
import threading
import xml.parsers.expat
import shutil

_NVME_PART = re.compile(r"^(nvme\d+n\d+)p\d+$")
_NVME_DISK = re.compile(r"^nvme\d+n\d+$")
_MMC_PART = re.compile(r"^(mmcblk\d+)p\d+$")
_MMC_DISK = re.compile(r"^mmcblk\d+$")
_GENERIC_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+)$")
_GENERIC_PART = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+)\d+$")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def read_int(path):
    text = read_text(path).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def read_float_file(path):
    text = read_text(path).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_whole_disk(name):
    if not name:
        return False
    return bool(_NVME_DISK.match(name) or _MMC_DISK.match(name) or _GENERIC_DISK.match(name))


def parent_disk(name):
    """Whole disk that contains a partition. dm/LVM names have no parent here."""
    if not name:
        return None
    for pattern in (_NVME_PART, _MMC_PART, _GENERIC_PART):
        match = pattern.match(name)
        if match:
            return match.group(1)
    if is_whole_disk(name):
        return name
    return None


def resolve_disk_name(name, slaves_of):
    """Follow partition names and device-mapper slaves to a whole disk."""
    seen = set()

    def walk(node):
        if not node or node in seen:
            return None
        seen.add(node)
        for slave in slaves_of(node) or []:
            found = walk(slave)
            if found:
                return found
        if is_whole_disk(node):
            return node
        parent = parent_disk(node)
        if parent and parent != node:
            return walk(parent)
        return None

    found = walk(name)
    if found:
        return found
    return parent_disk(name) or name or None


def _slaves_of(node):
    for base in ("/sys/class/block", "/sys/block"):
        path = "%s/%s/slaves" % (base, node)
        if os.path.isdir(path):
            try:
                return sorted(os.listdir(path))
            except OSError:
                return []
    return []


_root_disk = None
_root_ready = False


def cached_root_disk():
    global _root_disk, _root_ready
    if not _root_ready:
        _root_disk = resolve_root_disk()
        _root_ready = True
    return _root_disk


def resolve_root_disk():
    source = None
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "/":
                    source = parts[0]
                    break
    except OSError:
        return None
    if not source or not source.startswith("/dev/"):
        return None
    try:
        name = os.path.basename(os.path.realpath(source))
    except OSError:
        name = os.path.basename(source)

    return resolve_disk_name(name, _slaves_of)


def virtual_ifaces():
    names = []
    base = "/sys/class/net"
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return names
    for name in entries:
        if name == "lo":
            continue
        if not os.path.exists(os.path.join(base, name, "device")):
            names.append(name)
    return names


# Existing cpufreq files, keyed by the real cpu id. Offline ids and cpus
# with no scaling file are absent: nothing is read for them, and the id
# space is not assumed to equal the online count (SMT-off safe).
_cpu_freq_paths = None


def cpu_freq_paths():
    global _cpu_freq_paths
    if _cpu_freq_paths is not None:
        return _cpu_freq_paths
    base = "/sys/devices/system/cpu"
    paths = {}
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    for name in names:
        match = re.fullmatch(r"cpu(\d+)", name)
        if not match:
            continue
        cpu_id = int(match.group(1))
        freq = os.path.join(base, name, "cpufreq", "scaling_cur_freq")
        if os.path.exists(freq):
            paths[cpu_id] = freq
    _cpu_freq_paths = paths
    return paths


def cpuinfo_mhz_by_id():
    vals = {}
    current = None
    for line in read_text("/proc/cpuinfo").split("\n"):
        if line.startswith("processor"):
            try:
                current = int(line.split(":", 1)[1])
            except (IndexError, ValueError):
                current = None
        elif line.startswith("cpu MHz") and current is not None:
            try:
                vals[current] = float(line.split(":", 1)[1])
            except (IndexError, ValueError):
                pass
            current = None
    return vals


def cpu_core_mhz(core_count):
    """MHz list indexed by cpu id. Missing files stay None. Not packed by online count."""
    paths = cpu_freq_paths()
    count = core_count if core_count and core_count > 0 else 0
    if paths:
        count = max(count, max(paths) + 1)
    freqs = [None] * count
    any_freq = False
    for cpu_id, path in paths.items():
        if cpu_id < 0 or cpu_id >= len(freqs):
            continue
        khz = read_int(path)
        if khz is None:
            continue
        any_freq = True
        freqs[cpu_id] = khz / 1000.0
    if any_freq:
        return freqs
    info = cpuinfo_mhz_by_id()
    if info:
        count = max(len(freqs), max(info) + 1)
        if len(freqs) < count:
            freqs.extend([None] * (count - len(freqs)))
        for cpu_id, mhz in info.items():
            if 0 <= cpu_id < len(freqs):
                freqs[cpu_id] = mhz
    return freqs


def cpu_mhz(freqs):
    nums = [value for value in (freqs or []) if isinstance(value, (int, float))]
    if not nums:
        return None
    return sum(nums) / float(len(nums))


def _numeric_suffix(path):
    match = re.search(r"(\d+)$", str(path or "").rstrip("/"))
    if not match:
        return 10 ** 9
    return int(match.group(1))


def hwmon_dirs():
    # hwmon10 must sort after hwmon2. Lexical order gets this wrong.
    return sorted(glob.glob("/sys/class/hwmon/hwmon*"), key=_numeric_suffix)


# False until the first scan. None means the last scan found nothing, or the
# last read failed. Either way we try again after _PKG_RETRY_S, not forever.
_pkg_temp_path = False
_pkg_temp_at = 0.0
_PKG_RETRY_S = 30.0


def choose_package_sensor(found):
    """Prefer Package id 0, then Tctl, then Tdie, then x86_pkg_temp."""
    best = None
    best_key = None
    for item in found or []:
        label = (item.get("label") or "").strip().lower()
        driver = item.get("driver") or ""
        score = None
        if item.get("kind") == "hwmon" and driver == "coretemp" and label == "package id 0":
            score = 0
        elif item.get("kind") == "hwmon" and driver in ("k10temp", "zenpower") and label == "tctl":
            score = 1
        elif item.get("kind") == "hwmon" and driver in ("k10temp", "zenpower") and label == "tdie":
            score = 2
        elif item.get("kind") == "zone" and driver == "x86_pkg_temp":
            score = 3
        if score is None:
            continue
        order = item.get("order")
        if order is None:
            order = 10 ** 9
        key = (score, order)
        if best_key is None or key < best_key:
            best_key = key
            best = item
    return best


def find_package_temp_path():
    found = []
    for hwmon in hwmon_dirs():
        driver = read_text(os.path.join(hwmon, "name")).strip()
        if driver not in ("coretemp", "k10temp", "zenpower"):
            continue
        order = _numeric_suffix(hwmon)
        labels = sorted(glob.glob(os.path.join(hwmon, "temp*_label")), key=_numeric_suffix)
        for label_path in labels:
            input_path = label_path.replace("_label", "_input")
            if not os.path.exists(input_path):
                continue
            found.append({
                "kind": "hwmon",
                "driver": driver,
                "label": read_text(label_path).strip(),
                "path": input_path,
                "order": order,
            })
    zones = sorted(glob.glob("/sys/class/thermal/thermal_zone*"), key=_numeric_suffix)
    for zone in zones:
        kind = read_text(os.path.join(zone, "type")).strip()
        temp = os.path.join(zone, "temp")
        if kind != "x86_pkg_temp" or not os.path.exists(temp):
            continue
        found.append({
            "kind": "zone",
            "driver": kind,
            "label": kind,
            "path": temp,
            "order": _numeric_suffix(zone),
        })
    chosen = choose_package_sensor(found)
    return chosen["path"] if chosen else None


def package_temp_c():
    global _pkg_temp_path, _pkg_temp_at
    now = time.monotonic()
    missing = _pkg_temp_path is None or _pkg_temp_path == ""
    if _pkg_temp_path is False or (missing and (now - _pkg_temp_at) >= _PKG_RETRY_S):
        _pkg_temp_path = find_package_temp_path()
        _pkg_temp_at = now
    if not _pkg_temp_path:
        return None
    raw = read_int(_pkg_temp_path)
    if raw is None:
        # Don't latch off. The next try is a fresh discovery, 30s from now.
        _pkg_temp_path = None
        _pkg_temp_at = now
        return None
    return raw / 1000.0


def nvme_controller(disk):
    if not disk:
        return None
    match = re.match(r"(nvme\d+)", disk)
    return match.group(1) if match else None


def hwmon_matches_controller(hwmon, controller):
    try:
        target = os.path.realpath(os.path.join(hwmon, "device"))
    except OSError:
        return False
    return controller in target.split("/")


def _first_temp_input(directory):
    labels = sorted(glob.glob(os.path.join(directory, "temp*_label")), key=_numeric_suffix)
    first = None
    for label_path in labels:
        input_path = label_path.replace("_label", "_input")
        if not os.path.exists(input_path):
            continue
        if first is None:
            first = input_path
        if read_text(label_path).strip().lower() == "composite":
            return input_path
    if first:
        return first
    inputs = sorted(glob.glob(os.path.join(directory, "temp*_input")), key=_numeric_suffix)
    return inputs[0] if inputs else None


def nvme_input_path(disk_name):
    """NVMe hwmon for this disk. Never used unless the root disk is that NVMe.

    The composite input is an admin command and costs tens of milliseconds,
    so callers cache the path and poll it slowly.
    """
    if not disk_name or not _NVME_DISK.match(disk_name):
        return None
    controller = nvme_controller(disk_name)
    nvme_hwmons = []
    for hwmon in hwmon_dirs():
        if read_text(os.path.join(hwmon, "name")).strip() != "nvme":
            continue
        nvme_hwmons.append(hwmon)
    chosen = None
    if controller:
        for hwmon in nvme_hwmons:
            if hwmon_matches_controller(hwmon, controller):
                chosen = hwmon
                break
    if chosen is None:
        # The root disk is NVMe. One controller sensor is that disk. Several
        # with no link back to it would be a guess.
        if len(nvme_hwmons) == 1:
            chosen = nvme_hwmons[0]
        else:
            return None
    return _first_temp_input(chosen)


def disk_hwmon_input(disk_name):
    """hwmon temperature for a non-NVMe root disk. None when there isn't one."""
    if not disk_name or _NVME_DISK.match(disk_name):
        return None
    device = "/sys/block/%s/device" % disk_name
    for directory in sorted(glob.glob(device + "/hwmon/hwmon*"), key=_numeric_suffix):
        found = _first_temp_input(directory)
        if found:
            return found
    try:
        dev_real = os.path.realpath(device)
    except OSError:
        dev_real = ""
    for hwmon in hwmon_dirs():
        if read_text(os.path.join(hwmon, "name")).strip() == "nvme":
            continue
        try:
            target = os.path.realpath(os.path.join(hwmon, "device"))
        except OSError:
            continue
        parts = target.split("/")
        if disk_name not in parts and (not dev_real or not target.startswith(dev_real)):
            continue
        found = _first_temp_input(hwmon)
        if found:
            return found
    return None


def select_disk_temp_path(disk_name, nvme_path, other_path):
    """NVMe temperature only when the root disk is that NVMe; else its hwmon."""
    if not disk_name:
        return None
    if _NVME_DISK.match(disk_name):
        return nvme_path or None
    return other_path or None


# A successful NVMe composite read is cached for 10s (it is an admin command).
# A failure is not cached as a temperature: the path is dropped and discovery
# waits 30s, same as a missing package sensor.
_DISK_TEMP_OK_S = 10.0
_DISK_TEMP_FAIL_S = 30.0
_disk_temp_key = None
_disk_temp_path = False
_disk_temp_c = None
_disk_temp_at = 0.0


def disk_temp_c(disk_name):
    global _disk_temp_key, _disk_temp_path, _disk_temp_c, _disk_temp_at
    now = time.monotonic()
    if disk_name != _disk_temp_key:
        _disk_temp_key = disk_name
        _disk_temp_path = False
        _disk_temp_c = None
        _disk_temp_at = 0.0
    have_value = _disk_temp_c is not None
    interval = _DISK_TEMP_OK_S if have_value else _DISK_TEMP_FAIL_S
    if _disk_temp_at and (now - _disk_temp_at) < interval:
        return _disk_temp_c
    if _disk_temp_path is False or _disk_temp_path is None:
        nvme_path = nvme_input_path(disk_name)
        other_path = None if (disk_name and _NVME_DISK.match(disk_name)) else disk_hwmon_input(disk_name)
        _disk_temp_path = select_disk_temp_path(disk_name, nvme_path, other_path)
    value = None
    if _disk_temp_path:
        raw = read_int(_disk_temp_path)
        if raw is None:
            _disk_temp_path = None
        else:
            value = raw / 1000.0
    _disk_temp_c = value
    _disk_temp_at = now
    return value


def nvme_temp_c(disk_name):
    """Root-disk temperature. The JSON key stays nvme_temp_c for the UI."""
    return disk_temp_c(disk_name)


# Render-GT sysfs paths. Rediscovered every 30 s while no GT has been found.
# A measurement on this machine (xe, runtime_status already "active", suspended
# time stuck at 0) showed that reading idle residency and act_freq does not
# change PCI runtime PM: active time advanced with wall clock during a quiet
# gap and during a read burst.
_gpu_paths = False
_gpu_discover_at = 0.0
_GPU_DISCOVER_S = 30.0


def parse_dpm_mhz(text):
    """Current sclk from pp_dpm_sclk. The active line is marked with *."""
    current = None
    first = None
    for line in str(text or "").splitlines():
        match = re.search(r"(\d+)\s*Mhz", line, re.IGNORECASE)
        if not match:
            continue
        mhz = int(match.group(1))
        if first is None:
            first = mhz
        if "*" in line:
            current = mhz
    if current is not None:
        return current
    return first


def rank_gpu_candidates(cands):
    """Readable devices outrank 'not supported'. Among those, discrete wins."""
    def key(item):
        readable = not item.get("unsupported")
        discrete = bool(item.get("discrete"))
        return (0 if readable else 1, 0 if discrete else 1, item.get("card") or "")
    return sorted(list(cands or []), key=key)


def _card_entries():
    found = []
    for path in glob.glob("/sys/class/drm/card[0-9]*"):
        name = os.path.basename(path)
        if re.fullmatch(r"card\d+", name):
            found.append(name)
    found.sort(key=lambda name: int(name[4:]))
    return found


def _driver_of(card):
    link = "/sys/class/drm/%s/device/driver" % card
    try:
        return os.path.basename(os.path.realpath(link))
    except OSError:
        return ""


def _is_boot_vga(card):
    return read_int("/sys/class/drm/%s/device/boot_vga" % card) == 1


def _first_existing(paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def _xe_candidate(card):
    best = None
    pattern = "/sys/class/drm/%s/device/tile*/gt*/gtidle" % card
    for gt_idle in sorted(glob.glob(pattern)):
        idle = os.path.join(gt_idle, "idle_residency_ms")
        if not os.path.exists(idle):
            continue
        gt_name = read_text(os.path.join(gt_idle, "name")).strip()
        gt_dir = os.path.dirname(gt_idle)
        freq = os.path.join(gt_dir, "freq0", "act_freq")
        cand = {
            "driver": "xe",
            "name": gt_name or "xe",
            "idle": idle,
            "freq": freq if os.path.exists(freq) else None,
            "freq_kind": "mhz",
            "card": card,
        }
        if gt_name.endswith("-rc"):
            return cand
        if best is None:
            best = cand
    return best


def _i915_candidate(card):
    base = "/sys/class/drm/%s" % card
    idles = sorted(glob.glob(base + "/gt/gt*/rc6_residency_ms"))
    if not idles:
        idles = sorted(glob.glob(base + "/gt/gt*/gtidle/idle_residency_ms"))
    if not idles:
        idles = sorted(glob.glob(base + "/gt/gt*/gtidle/*/idle_residency_ms"))
    if not idles:
        idles = sorted(glob.glob(base + "/device/gt/gt*/rc6_residency_ms"))
    if not idles:
        idles = sorted(glob.glob(base + "/device/gt/gt*/gtidle/idle_residency_ms"))
    if not idles:
        return None
    gt_dir = os.path.dirname(idles[0])
    freq = _first_existing([
        os.path.join(base, "gt_act_freq_mhz"),
        os.path.join(base, "gt_cur_freq_mhz"),
        os.path.join(base, "device", "gt_act_freq_mhz"),
        os.path.join(base, "device", "gt_cur_freq_mhz"),
        os.path.join(gt_dir, "gt_act_freq_mhz"),
        os.path.join(gt_dir, "gt_cur_freq_mhz"),
    ])
    return {
        "driver": "i915",
        "name": "i915",
        "idle": idles[0],
        "freq": freq,
        "freq_kind": "mhz",
        "card": card,
    }


def _amd_candidate(card):
    dev = "/sys/class/drm/%s/device" % card
    busy = os.path.join(dev, "gpu_busy_percent")
    if not os.path.exists(busy):
        return None
    freq = None
    kind = None
    dpm = os.path.join(dev, "pp_dpm_sclk")
    if os.path.exists(dpm):
        freq = dpm
        kind = "dpm"
    else:
        hw = sorted(glob.glob(dev + "/hwmon/hwmon*/freq1_input"))
        if hw:
            freq = hw[0]
            kind = "hz"
    return {
        "driver": "amdgpu",
        "name": "amdgpu",
        "busy": busy,
        "idle": None,
        "freq": freq,
        "freq_kind": kind,
        "card": card,
    }


def _nvidia_candidate(card):
    # Sysfs only. nvidia-smi is not spawned; a 1 Hz sampler cannot afford it.
    return {
        "driver": "nvidia",
        "name": "nvidia",
        "unsupported": True,
        "idle": None,
        "freq": None,
        "card": card,
    }


def discover_gpu():
    ranked = []
    for card in _card_entries():
        driver = _driver_of(card)
        cand = None
        if driver == "xe":
            cand = _xe_candidate(card)
        elif driver == "i915":
            cand = _i915_candidate(card)
        elif driver == "amdgpu":
            cand = _amd_candidate(card)
        elif driver == "nvidia":
            cand = _nvidia_candidate(card)
        else:
            cand = _xe_candidate(card) or _i915_candidate(card) or _amd_candidate(card)
        if not cand:
            continue
        # boot_vga is the firmware primary, usually the integrated GPU.
        cand["discrete"] = (not _is_boot_vga(card)) or driver == "nvidia"
        cand["card"] = card
        ranked.append(cand)
    if not ranked:
        return None
    return rank_gpu_candidates(ranked)[0]


def gpu_absent():
    return {"present": False, "name": None, "driver": None, "idle_ms": None, "mhz": None}


def gpu_paths_gone(info, exists=None):
    """True when a discovered GPU's card or counter file has disappeared.

    An unsupported device with its card node still present is kept. A missing
    counter path (driver reload, hot-unplug) is gone and must be rediscovered.
    """
    if exists is None:
        exists = os.path.exists
    if not isinstance(info, dict):
        return False
    card = info.get("card")
    if card and not exists("/sys/class/drm/%s" % card):
        return True
    if info.get("unsupported"):
        return False
    watched = []
    if info.get("idle"):
        watched.append(info["idle"])
    if info.get("busy"):
        watched.append(info["busy"])
    if not watched:
        return False
    for path in watched:
        if exists(path):
            return False
    return True


def gpu_runtime_status(info, read=None):
    """runtime_status text, or None. Never raises."""
    if not isinstance(info, dict):
        return None
    card = info.get("card")
    if not card:
        return None
    if read is None:
        read = read_text
    path = "/sys/class/drm/%s/device/power/runtime_status" % card
    try:
        text = read(path)
    except Exception:  # noqa: BLE001 — status is optional
        return None
    value = str(text or "").strip().lower()
    return value or None


def _read_gpu_mhz(info):
    path = info.get("freq") if info else None
    if not path:
        return None
    kind = info.get("freq_kind")
    if kind == "dpm":
        return parse_dpm_mhz(read_text(path))
    raw = read_int(path)
    if raw is None:
        return None
    if kind == "hz":
        return raw / 1000000.0
    return raw


def gpu_sample():
    global _gpu_paths, _gpu_discover_at
    now = time.monotonic()
    # A vanished card or counter is rediscovered immediately. If that search
    # also comes up empty, the 30 s backoff applies so a missing GPU is not
    # globbed on every sample.
    gone = gpu_paths_gone(_gpu_paths) if isinstance(_gpu_paths, dict) else False
    due = _gpu_paths is None and (now - _gpu_discover_at) >= _GPU_DISCOVER_S
    if _gpu_paths is False or gone or due:
        found = discover_gpu()
        _gpu_discover_at = now
        if isinstance(found, dict) and gpu_paths_gone(found):
            _gpu_paths = None
        else:
            _gpu_paths = found
    info = _gpu_paths
    if not info:
        return gpu_absent()
    driver = info.get("driver")
    name = info.get("name")
    try:
        runtime = gpu_runtime_status(info)
    except Exception:  # noqa: BLE001 — status is optional
        runtime = None
    if info.get("unsupported"):
        return {
            "present": True,
            "name": name or "nvidia",
            "driver": driver or "nvidia",
            "unsupported": True,
            "idle_ms": None,
            "mhz": None,
            "runtime_status": runtime,
        }
    # Read the counter now. Never replay a previous cumulative sample: a
    # repeated idle value looks like a GPU that is fully busy.
    idle = read_int(info["idle"]) if info.get("idle") else None
    freq = _read_gpu_mhz(info)
    sample = {
        "present": True,
        "name": name,
        "driver": driver,
        "idle_ms": idle,
        "mhz": freq,
        "runtime_status": runtime,
    }
    if info.get("busy"):
        busy = read_int(info["busy"])
        sample["busy_pct"] = busy
    return sample


_bat_dir = None
_bat_checked = 0.0


def battery_sample():
    global _bat_dir, _bat_checked
    now = time.monotonic()
    if _bat_dir and not os.path.isdir(_bat_dir):
        _bat_dir = None
    if _bat_dir is None and _bat_checked > 0 and (now - _bat_checked) < 30:
        return None
    if _bat_dir is None:
        _bat_checked = now
        bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
        _bat_dir = bats[0] if bats else None
    if not _bat_dir:
        return None
    bat = _bat_dir
    # The first of these sysfs reads can take ~10 ms of CPU (embedded-controller
    # refresh). Callers cache the result and skip the files between refreshes.
    status = read_text(os.path.join(bat, "status")).strip() or None
    power_path = os.path.join(bat, "power_now")
    power = read_int(power_path) if os.path.exists(power_path) else None
    current = None
    voltage = None
    if power is None:
        current_path = os.path.join(bat, "current_now")
        voltage_path = os.path.join(bat, "voltage_now")
        if os.path.exists(current_path):
            current = read_int(current_path)
        if os.path.exists(voltage_path):
            voltage = read_int(voltage_path)
    return {
        "capacity": read_int(os.path.join(bat, "capacity")),
        "status": status,
        "power_now_uw": power,
        "current_now_ua": current,
        "voltage_now_uv": voltage,
    }


# Fresh battery numbers are not worth an EC transaction every second.
_BAT_INTERVAL_S = 5.0
_bat_read_at = 0.0


def battery_hot():
    """Return (sample_or_none, skip). skip keeps the previous dashboard reading."""
    global _bat_read_at
    now = time.monotonic()
    if _bat_read_at and (now - _bat_read_at) < _BAT_INTERVAL_S:
        return None, True
    sample = battery_sample()
    _bat_read_at = now
    return sample, False


def root_fs():
    try:
        st = os.statvfs("/")
    except OSError:
        return None, None
    fr = st.f_frsize or st.f_bsize or 1
    total = int(st.f_blocks) * int(fr)
    used = (int(st.f_blocks) - int(st.f_bfree)) * int(fr)
    if used < 0:
        used = 0
    return used, total


def read_bytes(path, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return b""
    try:
        return os.read(fd, limit)
    except OSError:
        return b""
    finally:
        os.close(fd)


def cmdline_argv0(pid):
    raw = read_bytes("/proc/%s/cmdline" % pid, 4096)
    if not raw:
        return ""
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def _parse_stat(data):
    """comm, utime+stime, starttime, rss pages. None when the line is short.

    comm is the bytes between the first '(' and the last ')'. RSS is stat
    field 24 (pages). The ranker multiplies it by the page size.
    """
    rpar = data.rfind(b")")
    lpar = data.find(b"(")
    if lpar < 0 or rpar <= lpar:
        return None
    parts = data[rpar + 2:].split()
    if len(parts) < 22:
        return None
    try:
        # After comm: utime field 14 (index 11), stime 15, starttime field 22
        # (index 19), rss field 24 (index 21).
        ticks = int(parts[11]) + int(parts[12])
        start = int(parts[19])
        rss = int(parts[21])
    except ValueError:
        return None
    comm = data[lpar + 1:rpar].decode("utf-8", "replace")
    return comm, ticks, start, rss


def _read_proc_stat(name):
    """One read of /proc/<pid>/stat. Empty when the pid has already exited."""
    try:
        fd = os.open("/proc/%s/stat" % name, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return b""
    try:
        return os.read(fd, 4096)
    except OSError:
        return b""
    finally:
        os.close(fd)


# cmdline for truncated or generic comms, keyed by (pid, starttime). Replaced
# each sweep so a reused pid does not keep the previous argv0.
_argv_cache = {}

_GENERIC_THREAD_EXACT = {"mainthread", "thread", "main", "geckomain"}
_GENERIC_THREAD_PREFIXES = ("threadpool", "kworker", "ksoftirqd", "migration", "kswapd", "rcu_")
# Kernel helpers have an empty cmdline. Opening it on every sweep is wasted IO.
_KERNEL_THREAD_PREFIXES = ("kworker", "ksoftirqd", "migration", "kswapd", "rcu_")


def generic_thread_name(comm):
    name = "" if comm is None else str(comm)
    if not name:
        return False
    low = name.lower()
    if low in _GENERIC_THREAD_EXACT:
        return True
    for prefix in _GENERIC_THREAD_PREFIXES:
        if low.startswith(prefix):
            return True
    return False


def _kernel_thread_name(comm):
    low = ("" if comm is None else str(comm)).lower()
    for prefix in _KERNEL_THREAD_PREFIXES:
        if low.startswith(prefix):
            return True
    return False


def needs_cmdline(comm):
    """Userspace generic comms and the 15-byte kernel cap need argv0."""
    name = "" if comm is None else str(comm)
    if generic_thread_name(name):
        return not _kernel_thread_name(name)
    return len(name) == 15


def sweep_processes():
    """One complete pass over /proc. Returns (rows, sweep_ms). Never resumes.

    Each row is (pid, comm, ticks, rss, start, read_s, argv0). read_s is the
    monotonic time of that pid's stat read, not the time the sweep finished.
    cmdline is opened when comm is a userspace generic thread name or 15
    characters (the kernel cap). Kernel workers have no cmdline.
    """
    global _argv_cache
    started = time.monotonic()
    rows = []
    cache = _argv_cache
    fresh = {}
    try:
        entries = os.scandir("/proc")
    except OSError:
        return [], (time.monotonic() - started) * 1000.0
    try:
        for entry in entries:
            name = entry.name
            # Digit check only. is_dir() would stat, and /proc has no numeric files.
            if not name.isdigit():
                continue
            # Stamp the read itself. CPU% uses this time.
            read_s = time.monotonic()
            data = _read_proc_stat(name)
            if not data:
                continue
            parsed = _parse_stat(data)
            if not parsed:
                continue
            comm, ticks, start, rss = parsed
            try:
                pid = int(name)
            except ValueError:
                continue
            argv0 = None
            if needs_cmdline(comm):
                key = (pid, start)
                if key in cache:
                    argv0 = cache[key]
                else:
                    argv0 = cmdline_argv0(name) or ""
                fresh[key] = argv0
            rows.append((pid, comm, ticks, rss, start, read_s, argv0 or None))
    finally:
        entries.close()
    _argv_cache = fresh
    return rows, (time.monotonic() - started) * 1000.0


def clk_page():
    try:
        clk = int(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
        page = int(os.sysconf(os.sysconf_names["SC_PAGE_SIZE"]))
    except (OSError, ValueError, KeyError):
        clk = 100
        page = 4096
    return clk, page


def basename_path(path):
    s = "" if path is None else str(path)
    cut = -1
    for index, ch in enumerate(s):
        if ch == "/" or ch == "\\":
            cut = index
    if cut >= 0:
        return s[cut + 1:]
    return s


def program_from_cmdline(text):
    """Basename of the program token. Arguments after the first space are dropped."""
    s = "" if text is None else str(text)
    if not s:
        return ""
    token = s.split(" ", 1)[0]
    return basename_path(token)


def cmdline_has_args(text):
    """A rewritten title such as 'mcp 6276 --auth-timeout 60', not 'Web Content'."""
    parts = ("" if text is None else str(text)).split(" ")
    if len(parts) < 2:
        return False
    for token in parts[1:]:
        if not token:
            continue
        if token.startswith("-") or token.isdigit():
            return True
    return False


def proc_display_name(comm, argv0):
    name = "" if comm is None else str(comm)
    if len(name) == 15 or generic_thread_name(name):
        base = program_from_cmdline(argv0)
        if base:
            return base
    if cmdline_has_args(name):
        titled = program_from_cmdline(name)
        if titled:
            return titled
    return name


def format_percent_precise(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number or number == float("inf") or number == float("-inf"):
        return "—"
    if abs(number) >= 100:
        return "%d%%" % int(math.floor(number + 0.5))
    return "%.1f%%" % number


def _row_tuple(row):
    """(pid, comm, ticks, rss, start, read_s, argv0). Dict rows stay valid for tests."""
    if isinstance(row, tuple):
        return row
    if not row:
        return None
    return (
        row.get("pid"),
        row.get("comm"),
        row.get("ticks"),
        row.get("rss"),
        row.get("start"),
        row.get("read_s"),
        row.get("argv0"),
    )


def _prev_pair(before):
    """(ticks, read_s) from a hot-path tuple or a test dict."""
    if isinstance(before, dict):
        return before.get("ticks") or 0, before.get("read_s") or 0
    return before[0] or 0, before[1] or 0


def proc_key(row):
    """(pid, starttime). A recycled pid does not inherit the previous ticks."""
    fields = _row_tuple(row)
    if not fields or fields[0] is None or fields[4] is None:
        return None
    return "%s:%s" % (fields[0], fields[4])


def build_presented(rows, prev, mem_total, clk, page):
    """Group by display name. Cap 8 CPU rows and 8 memory rows.

    CPU% = Δticks / (CLK_TCK × Δread_s) for that pid. `prev` maps proc_key to
    {"ticks", "read_s"}. A pid with no previous sighting has no CPU% yet.
    Memory% = RSS pages × page size / MemTotal.
    """
    order = []
    groups = {}
    prev = prev or {}
    clk = float(clk or 100)
    page = float(page or 4096)
    mem_total = float(mem_total or 0)
    for row in rows or []:
        fields = _row_tuple(row)
        if not fields:
            continue
        pid, comm, ticks, rss, start, read_s, argv0 = fields
        name = proc_display_name(comm, argv0)
        mem = 0.0
        if page > 0 and mem_total > 0 and rss is not None:
            try:
                rss_pages = float(rss)
            except (TypeError, ValueError):
                rss_pages = -1
            if rss_pages >= 0:
                mem = 100.0 * (rss_pages * page) / mem_total
        cpu = None
        if pid is not None and start is not None:
            before = prev.get("%s:%s" % (pid, start))
        else:
            before = None
        if before is not None and clk > 0:
            try:
                old_ticks, old_read = _prev_pair(before)
                delta = float(ticks or 0) - float(old_ticks or 0)
                dt = float(read_s or 0) - float(old_read or 0)
            except (TypeError, ValueError):
                delta = 0.0
                dt = 0.0
            if delta < 0:
                delta = 0.0
            if dt > 0:
                cpu = 100.0 * delta / (clk * dt)
        group = groups.get(name)
        if group is None:
            group = {"name": name, "cpu": 0.0, "mem": 0.0, "count": 0, "cpu_known": False}
            groups[name] = group
            order.append(name)
        if cpu is not None:
            group["cpu"] += cpu
            group["cpu_known"] = True
        group["mem"] += mem
        group["count"] += 1
    items = []
    for name in order:
        group = groups[name]
        label = group["name"] if group["count"] <= 1 else "%s ×%d" % (group["name"], group["count"])
        items.append((label, group["cpu"], group["mem"], group["cpu_known"]))

    def top(index, known_only):
        ranked = [item for item in items if item[3] or not known_only]
        ranked.sort(key=lambda item: (-item[index], item[0]))
        return [{"name": item[0], "text": format_percent_precise(item[index])} for item in ranked[:8]]

    return {
        "byCpu": top(1, True),
        "byMem": top(2, False),
    }


# Previous sighting: key -> {"ticks", "read_s"}. The hot path sends only the top rows.
_proc_prev = {}


def rank_processes(rows, mem_total):
    """Rank this complete sweep, then store each row's ticks and read time."""
    global _proc_prev
    clk, page = clk_page()
    presented = build_presented(rows, _proc_prev, mem_total, clk, page)
    nxt = {}
    for row in rows or []:
        fields = _row_tuple(row)
        if not fields or fields[0] is None or fields[4] is None:
            continue
        try:
            ticks = float(fields[2] or 0)
        except (TypeError, ValueError):
            ticks = 0.0
        nxt["%s:%s" % (fields[0], fields[4])] = (ticks, fields[5])
    _proc_prev = nxt
    return presented


def mem_total_bytes(text):
    for line in text.split("\n"):
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1]) * 1024
                except ValueError:
                    return 0
    return 0


_MEM_KEYS = (
    "MemTotal:",
    "MemFree:",
    "MemAvailable:",
    "Buffers:",
    "Cached:",
    "SReclaimable:",
    "SwapTotal:",
    "SwapFree:",
)


def cpu_lines(text):
    # Drop the huge `intr` line. The parser only reads cpu / cpuN.
    lines = [line for line in text.split("\n") if line.startswith("cpu")]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def short_meminfo(text):
    lines = []
    for line in text.split("\n"):
        for key in _MEM_KEYS:
            if line.startswith(key):
                lines.append(line.strip())
                break
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def disk_line(text, device):
    if not device:
        return ""
    for line in text.split("\n"):
        parts = line.split()
        if len(parts) >= 3 and parts[2] == device:
            return line.strip() + "\n"
    return ""


# RTF_UP. Point-to-point default routes are up and have no RTF_GATEWAY bit.
_RTF_UP = 0x1


def _route_flags_ok(text):
    try:
        flags = int(text, 16)
    except ValueError:
        return False
    return (flags & _RTF_UP) == _RTF_UP


def parse_ipv4_default(text):
    best = None
    best_metric = None
    for line in str(text or "").split("\n"):
        parts = line.split()
        if len(parts) < 8 or parts[1] != "00000000" or parts[7] != "00000000":
            continue
        if not parts[0] or parts[0] == "Iface":
            continue
        if not _route_flags_ok(parts[3]):
            continue
        try:
            metric = int(parts[6])
        except ValueError:
            metric = 0
        if best_metric is None or metric < best_metric:
            best_metric = metric
            best = parts[0]
    return best


def parse_ipv6_default(text):
    best = None
    best_metric = None
    for line in str(text or "").split("\n"):
        parts = line.split()
        if len(parts) < 10:
            continue
        if parts[0] != "00000000000000000000000000000000":
            continue
        try:
            prefix = int(parts[1], 16)
        except ValueError:
            continue
        if prefix != 0 or not _route_flags_ok(parts[8]):
            continue
        iface = parts[-1]
        if not iface or iface == "lo":
            continue
        try:
            metric = int(parts[5], 16)
        except ValueError:
            metric = 0
        if best_metric is None or metric < best_metric:
            best_metric = metric
            best = iface
    return best


def default_route_iface(route_v4, route_v6):
    return parse_ipv4_default(route_v4) or parse_ipv6_default(route_v6) or None


def read_rate_snapshot(read_fn=None, clock=None):
    """Read the three rate files, then take one monotonic timestamp.

    The stamp has to sit with the counters. Reading it after the slow sensors
    stretches the byte/s window by however long those sensors took.
    """
    read = read_fn or read_text
    clock = clock or time.monotonic
    proc_text = read("/proc/stat")
    disk_text = read("/proc/diskstats")
    net_text = read("/proc/net/dev")
    stamp = clock() * 1000.0
    return proc_text, disk_text, net_text, stamp


_CPU_FIELDS = (
    "user", "nice", "system", "idle", "iowait",
    "irq", "softirq", "steal", "guest", "guestNice",
)


def _cpu_fields(parts):
    nums = []
    for item in parts[1:11]:
        try:
            nums.append(int(item))
        except ValueError:
            nums.append(0)
    while len(nums) < 10:
        nums.append(0)
    return {name: nums[index] for index, name in enumerate(_CPU_FIELDS)}


def parse_cpu_stat(text):
    total = None
    cores = []
    for line in str(text or "").split("\n"):
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        if not parts:
            continue
        label = parts[0]
        if label == "cpu":
            total = _cpu_fields(parts)
            continue
        if len(label) > 3 and label.startswith("cpu") and label[3:].isdigit():
            index = int(label[3:])
            while len(cores) <= index:
                cores.append(None)
            cores[index] = _cpu_fields(parts)
    if total is None:
        total = {name: 0 for name in _CPU_FIELDS}
    return total, cores


def parse_meminfo_bytes(text):
    raw = {}
    for line in str(text or "").split("\n"):
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        bits = rest.split()
        if not bits:
            continue
        try:
            raw[key] = int(bits[0])
        except ValueError:
            continue

    def bytes_of(key):
        if key not in raw:
            return None
        return raw[key] * 1024

    total = bytes_of("MemTotal")
    available = bytes_of("MemAvailable")
    cached = bytes_of("Cached")
    reclaimable = bytes_of("SReclaimable")
    buffers = bytes_of("Buffers")
    swap_total = bytes_of("SwapTotal")
    swap_free = bytes_of("SwapFree")
    used = None
    if total is not None and available is not None:
        used = total - available
        if used < 0:
            used = 0
    cached_display = None
    if cached is not None or reclaimable is not None or buffers is not None:
        cached_display = (cached or 0) + (reclaimable or 0) + (buffers or 0)
    swap_used = None
    if swap_total is not None and swap_free is not None:
        swap_used = swap_total - swap_free
        if swap_used < 0:
            swap_used = 0
    return {
        "total": total,
        "free": bytes_of("MemFree"),
        "available": available,
        "cached": cached_display,
        "buffers": buffers,
        "swapTotal": swap_total,
        "swapFree": swap_free,
        "used": used,
        "swapUsed": swap_used,
    }


def parse_net_ifaces(text):
    rows = []
    for line in str(text or "").split("\n"):
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        if not name or name in ("Inter-", "face"):
            continue
        nums = rest.split()
        if len(nums) < 9:
            continue
        try:
            rx = int(nums[0])
            tx = int(nums[8])
        except ValueError:
            continue
        rows.append({"name": name, "rx": rx, "tx": tx})
    return rows


def disk_counters(text, device):
    if not device:
        return None, None
    for line in str(text or "").split("\n"):
        parts = line.split()
        if len(parts) >= 14 and parts[2] == device:
            try:
                return int(parts[5]), int(parts[9])
            except ValueError:
                return None, None
    return None, None


def sensor_cpu(text):
    """CPU counters always return. A frequency-probe failure only nulls MHz."""
    total, cores = parse_cpu_stat(text)
    freqs = None
    try:
        freqs = cpu_core_mhz(len(cores))
    except Exception:  # noqa: BLE001 — optional probe
        freqs = None
    mhz = None
    if freqs is not None:
        try:
            mhz = cpu_mhz(freqs)
        except Exception:  # noqa: BLE001 — optional probe
            mhz = None
    return {
        "total": total,
        "cores": cores,
        "mhz": mhz,
        "core_mhz": freqs,
    }


def sensor_mem():
    return parse_meminfo_bytes(read_text("/proc/meminfo"))


def sensor_disk(text):
    disk = cached_root_disk()
    sectors_read, sectors_written = disk_counters(text, disk)
    root_used, root_total = root_fs()
    return {
        "device": disk,
        "sectors_read": sectors_read,
        "sectors_written": sectors_written,
        "root_used": root_used,
        "root_total": root_total,
    }


def sensor_net(text):
    """Interface byte counters always return. Route and virtual class are optional."""
    ifaces = parse_net_ifaces(text)
    virtual = None
    try:
        virtual = virtual_ifaces()
    except Exception:  # noqa: BLE001 — optional probe
        virtual = None
    default_iface = None
    try:
        default_iface = default_route_iface(
            read_text("/proc/net/route"),
            read_text("/proc/net/ipv6_route"),
        )
    except Exception:  # noqa: BLE001 — optional probe
        default_iface = None
    return {
        "ifaces": ifaces,
        "virtual": virtual,
        "default_iface": default_iface,
    }


def sensor_temps():
    disk = cached_root_disk()
    return {
        "package_c": package_temp_c(),
        "disk_c": disk_temp_c(disk),
    }


def sensor_procs():
    """One Python pass over /proc. sweep_ms is the measured cost of that pass."""
    rows, sweep_ms = sweep_processes()
    mem = parse_meminfo_bytes(read_text("/proc/meminfo"))
    presented = rank_processes(rows, mem.get("total") or 0)
    return {
        "presented": presented,
        "sweep_ms": round(sweep_ms, 3),
        "count": len(rows),
    }


def _error_text(exc, name):
    msg = str(exc).replace("\n", " ").strip() or name
    return msg[:200]


def take_sensor(sample, errors, name, fn):
    """One sensor. A failure is null plus errors[name]; it does not abort the sample."""
    try:
        sample[name] = fn()
    except Exception as exc:  # noqa: BLE001 — isolation is the point
        sample[name] = None
        errors[name] = _error_text(exc, name)


# --- host identity, darwin parsers, and the --remote loop ---

_DARWIN_IFACE = re.compile(r"^(?:disk\d+|en\d+|lo\d*|[a-zA-Z][a-zA-Z0-9]*)$")
_DARWIN_DISK = re.compile(r"^(?:disk\d+|nvme\d+|ada\d+|da\d+)$")
_DARWIN_VIRTUAL = re.compile(
    r"^(?:lo\d*|gif\d*|stf\d*|awdl\d*|llw\d*|utun\d*|bridge\d*|ap\d*|"
    r"ipsec\d*|pktap\d*|anpi\d*|XHC\d*|awdl|llw)$"
)
_DISK_NODE = re.compile(r"(disk\d+)")
_ROUTE_IFACE = re.compile(r"^\s*interface:\s*(\S+)", re.MULTILINE)
_SWAP_TOTAL = re.compile(r"total\s*=\s*([0-9.]+)\s*([KMGT]?)")
_SWAP_USED = re.compile(r"used\s*=\s*([0-9.]+)\s*([KMGT]?)")
_PMSET_PCT = re.compile(r"(\d+)%;\s*([^;\n]+)")
_NET_IFACE_HEADER = re.compile(r"\(([^)\s]+)\)")

# `-K` prints KB/t, tps and combined MB/s. There is no read/write split.
IOSTAT_ARGV = ["iostat", "-d", "-w", "1", "-K"]
_IOSTAT_MIB = 1048576
NETSTAT_ARGV = ["netstat", "-ib", "-w", "1"]


def netstat_argv(iface):
    """Pin counters to the default interface. Unscoped netstat reports Total."""
    name = str(iface or "")
    if name and _DARWIN_IFACE.match(name) and not _DARWIN_VIRTUAL.match(name):
        return ["netstat", "-I", name, "-b", "-w", "1"]
    return list(NETSTAT_ARGV)
_REMOTE_PROC_EVERY = 5

_child_procs = []
_children_stopped = False
_children_lock = threading.RLock()


def host_name():
    try:
        return os.uname().nodename
    except OSError:
        return ""


def kernel_release():
    try:
        return os.uname().release
    except OSError:
        return ""


def host_os_name():
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def kernel_is_wsl(release):
    text = str(release or "").lower()
    return "microsoft" in text or "wsl" in text


def valid_temperature(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and -20 <= value <= 150 else None
    except (TypeError, ValueError, OverflowError):
        return None


def select_mac_cpu_temperature(sensors):
    tdie, mtr = [], []
    for name, raw in sensors.items():
        value = valid_temperature(raw)
        if value is None:
            continue
        if "tdie" in name.lower():
            tdie.append(value)
        elif re.search(r"^\s*(?:pacc|eacc|acc).*mtr temp sensor", name, re.IGNORECASE):
            mtr.append(value)
    return max(tdie or mtr) if tdie or mtr else None


class MacTemperatureReader:
    """Own one HID client and cache its temperature events for two seconds."""

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.client = None
        self.init_at = None
        self.at = None
        self.sensors = {}
        self.cf = None
        self.io = None

    def _initialize(self):
        if sys.platform != "darwin" or os.uname().machine.lower() != "arm64":
            return
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        io = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        ptr, integer = ctypes.c_void_p, ctypes.c_long
        def bind(lib, name, result, args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            return fn
        bind(cf, 'CFRelease', None, [ptr])
        bind(cf, 'CFGetTypeID', ctypes.c_ulong, [ptr])
        bind(cf, 'CFStringGetTypeID', ctypes.c_ulong, [])
        bind(cf, 'CFStringCreateWithCString', ptr, [ptr, ctypes.c_char_p, ctypes.c_uint32])
        bind(cf, 'CFStringGetLength', integer, [ptr])
        bind(cf, 'CFStringGetMaximumSizeForEncoding', integer, [integer, ctypes.c_uint32])
        bind(cf, 'CFStringGetCString', ctypes.c_bool, [ptr, ctypes.c_char_p, integer, ctypes.c_uint32])
        bind(cf, 'CFNumberCreate', ptr, [ptr, ctypes.c_int, ptr])
        bind(cf, 'CFDictionaryCreate', ptr, [ptr, ctypes.POINTER(ptr), ctypes.POINTER(ptr), integer, ptr, ptr])
        bind(cf, 'CFArrayGetCount', integer, [ptr])
        bind(cf, 'CFArrayGetValueAtIndex', ptr, [ptr, integer])
        bind(io, 'IOHIDEventSystemClientCreate', ptr, [ptr])
        bind(io, 'IOHIDEventSystemClientSetMatching', None, [ptr, ptr])
        bind(io, 'IOHIDEventSystemClientCopyServices', ptr, [ptr])
        bind(io, 'IOHIDServiceClientCopyProperty', ptr, [ptr, ptr])
        bind(io, 'IOHIDServiceClientCopyEvent', ptr, [ptr, ctypes.c_int64, ctypes.c_int32, ctypes.c_int64])
        bind(io, 'IOHIDEventGetFloatValue', ctypes.c_double, [ptr, ctypes.c_int])
        self.cf, self.io = cf, io
        owned = []
        client = None
        try:
            client = io.IOHIDEventSystemClientCreate(None)
            if not client:
                return
            for text in (b'PrimaryUsagePage', b'PrimaryUsage'):
                obj = cf.CFStringCreateWithCString(None, text, 0x08000100)
                if not obj:
                    return
                owned.append(obj)
            for number in (0xff00, 5):
                raw = ctypes.c_int(number)
                obj = cf.CFNumberCreate(None, 9, ctypes.byref(raw))  # kCFNumberIntType
                if not obj:
                    return
                owned.append(obj)
            keys = (ptr * 2)(*owned[:2])
            values = (ptr * 2)(*owned[2:])
            key_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryKeyCallBacks'))
            value_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryValueCallBacks'))
            matching = cf.CFDictionaryCreate(None, keys, values, 2, key_callbacks, value_callbacks)
            if not matching:
                return
            owned.append(matching)
            io.IOHIDEventSystemClientSetMatching(client, matching)
            atexit.register(self.close)
            self.client, client = client, None
        finally:
            for obj in reversed(owned):
                cf.CFRelease(obj)
            if client:
                cf.CFRelease(client)

    def close(self):
        if self.client:
            self.cf.CFRelease(self.client)
            self.client = None

    def read(self):
        now = self.clock()
        retry_due = not self.client and (self.init_at is None or now - self.init_at >= 60)
        if self.at is not None and now - self.at < 2 and not retry_due:
            return self.sensors
        self.at, self.sensors = now, {}
        try:
            if retry_due:
                self.init_at = now
                self._initialize()
            if not self.client:
                return self.sensors
            cf, io = self.cf, self.io
            services = io.IOHIDEventSystemClientCopyServices(self.client)
            if not services:
                return self.sensors
            try:
                key = cf.CFStringCreateWithCString(None, b'Product', 0x08000100)
                if not key:
                    return self.sensors
                try:
                    for index in range(cf.CFArrayGetCount(services)):
                        service = cf.CFArrayGetValueAtIndex(services, index)
                        name = io.IOHIDServiceClientCopyProperty(service, key)
                        if not name:
                            continue
                        try:
                            if cf.CFGetTypeID(name) != cf.CFStringGetTypeID():
                                continue
                            length = cf.CFStringGetLength(name)
                            size = cf.CFStringGetMaximumSizeForEncoding(length, 0x08000100) + 1
                            if size <= 0 or size > 65536:
                                continue
                            buf = ctypes.create_string_buffer(size)
                            if not cf.CFStringGetCString(name, buf, size, 0x08000100):
                                continue
                            event = io.IOHIDServiceClientCopyEvent(service, 15, 0, 0)
                            if event:
                                try:
                                    value = valid_temperature(io.IOHIDEventGetFloatValue(event, 15 << 16))
                                    if value is not None:
                                        sensor_name = buf.value.decode('utf-8', errors='replace')
                                        self.sensors[sensor_name] = max(value, self.sensors.get(sensor_name, value))
                                finally:
                                    cf.CFRelease(event)
                        finally:
                            cf.CFRelease(name)
                finally:
                    cf.CFRelease(key)
            finally:
                cf.CFRelease(services)
        except Exception:  # noqa: BLE001 — optional platform sensor
            self.sensors = {}
        return self.sensors


_mac_temperature_reader = MacTemperatureReader()


def mac_temperature_c():
    return select_mac_cpu_temperature(_mac_temperature_reader.read())


_HWiNFO_LABELS = ('CPU Package', 'CPU (Tctl/Tdie)', 'CPU Die (average)',
                  'CPU (Tctl)', 'CPU (Tdie)', 'Core Max', 'CPU')
_HWiNFO_REG = '/mnt/c/Windows/System32/reg.exe'
_HWiNFO_KEY = r'HKCU\Software\HWiNFO64\VSB'
_HWiNFO_OUTPUT_LIMIT = 256 * 1024
_HWiNFO_TIMEOUT = 2


def parse_hwinfo_temperatures(data):
    data = data[:256 * 1024] if isinstance(data, (bytes, str)) else ''
    if isinstance(data, bytes):
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = data.decode('utf-16', errors='replace')
        elif b'\x00' in data:
            text = data.decode('utf-16le', errors='replace')
        else:
            try:
                text = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = data.decode('latin-1')
    else:
        text = str(data or '')
    entries = {}
    for line in text.splitlines():
        if len(line) > 1024:
            continue
        line = line.strip()
        key, separator, _ = line.upper().partition(' REG_SZ ')
        if not separator:
            continue
        shown = line[len(key) + len(separator):].strip()
        key = key.strip().lower()
        for prefix in ('sensor', 'label', 'valueraw', 'value'):
            index = key[len(prefix):]
            if key.startswith(prefix) and index and index.isascii() and index.isdigit():
                entries.setdefault(index, {})[prefix] = shown
                break
    sensors = {}
    for entry in entries.values():
        label, shown = entry.get('label', ''), entry.get('value', '')
        raw = entry.get('valueraw', '')
        if raw.count(',') == 1 and '.' not in raw:
            raw = raw.replace(',', '.')
        value = valid_temperature(raw)
        shown = shown.strip()
        if not shown.lower().endswith('c'):
            continue
        number = shown[:-1].rstrip()
        end = len(number)
        while (end and not number[end - 1].isspace() and
               not (number[end - 1].isascii() and number[end - 1].isalnum())):
            end -= 1
        number = number[:end].rstrip()
        unsigned = number.lstrip('+-')
        parts = unsigned.replace(',', '.').split('.')
        numeric = (len(number) <= 64 and len(parts) <= 2 and
                   all(part and part.isascii() and part.isdigit() for part in parts) and
                   number.count('+') + number.count('-') <= 1)
        if label and numeric and value is not None:
            sensors.setdefault(label, value)
    return sensors


def select_hwinfo_cpu_temperature(sensors):
    for wanted in _HWiNFO_LABELS:
        for label, value in sensors.items():
            if label.casefold() == wanted.casefold():
                return value
    return None


class WslTemperatureReader:
    def __init__(self, clock=None, runner=None):
        self.clock = clock or time.monotonic
        self.runner = runner or subprocess.Popen
        self.at = None
        self.interval = 0
        self.sensors = {}

    def read(self, release):
        if not kernel_is_wsl(release):
            return {}
        now = self.clock()
        if self.at is not None and now - self.at < self.interval:
            return self.sensors
        self.at, self.sensors, self.interval = now, {}, 60
        try:
            deadline = time.monotonic() + _HWiNFO_TIMEOUT
            child = self.runner([_HWiNFO_REG, 'query', _HWiNFO_KEY],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
            try:
                output = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                        raise subprocess.TimeoutExpired(child.args, _HWiNFO_TIMEOUT)
                    chunk = os.read(child.stdout.fileno(), min(65536, _HWiNFO_OUTPUT_LIMIT + 1 - len(output)))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > _HWiNFO_OUTPUT_LIMIT:
                        raise ValueError('registry output exceeds limit')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(child.args, _HWiNFO_TIMEOUT)
                if child.wait(timeout=remaining) != 0:
                    raise ValueError('registry query failed')
            finally:
                try:
                    if child.poll() is None:
                        child.kill()
                finally:
                    try:
                        child.wait()
                    finally:
                        child.stdout.close()
            self.sensors = parse_hwinfo_temperatures(bytes(output))
            if select_hwinfo_cpu_temperature(self.sensors) is not None:
                self.interval = 5
        except Exception:  # noqa: BLE001 — Windows interop is optional
            pass
        return self.sensors


_wsl_temperature_reader = WslTemperatureReader()


def wsl_temperature_c(release):
    return select_hwinfo_cpu_temperature(_wsl_temperature_reader.read(release))


def diagnostic_temperature_sensors():
    if host_os_name() == 'darwin':
        return _mac_temperature_reader.read()
    return _wsl_temperature_reader.read(kernel_release())


def remote_includes(index):
    """Process table on sample 0, 5, 10, ... in --remote mode."""
    try:
        slot = int(index)
    except (TypeError, ValueError):
        return False
    return slot % _REMOTE_PROC_EVERY == 0


def use_pdeathsig(remote):
    """The local collector arms PDEATHSIG. The ssh copy does not."""
    return not remote


def gpu_na():
    return {"present": False, "na": True, "name": None, "driver": None, "idle_ms": None, "mhz": None}


def temps_na():
    return {"na": True, "package_c": None, "disk_c": None}


def apply_host_meta(sample, name, os_name, kernel, mac_reader=None, wsl_reader=None):
    """Add host identity and optional platform sensor values."""
    if not isinstance(sample, dict):
        sample = {}
    sample["host"] = name or ""
    sample["os"] = os_name if os_name in ("linux", "darwin") else "linux"
    sample["kernel"] = kernel or ""
    errors = sample.get("errors")
    if not isinstance(errors, dict):
        errors = None
    if sample["os"] == "linux" and kernel_is_wsl(sample["kernel"]):
        sample["wsl"] = True
        temps = sample.get("temps")
        if kernel_is_wsl(kernel_release()) and isinstance(temps, dict) and temps.get("package_c") is None:
            try:
                value = (wsl_reader or wsl_temperature_c)(sample["kernel"])
                if value is not None:
                    sample["temps"] = temps.copy()
                    sample["temps"]["package_c"] = value
                    sample["temps"].pop("na", None)
                    if errors is not None:
                        errors.pop("temps", None)
            except Exception:  # noqa: BLE001 — optional platform sensor
                pass
        gpu = sample.get("gpu")
        if not isinstance(gpu, dict) or gpu.get("present") is not True:
            sample["gpu"] = gpu_na()
            if errors is not None:
                errors.pop("gpu", None)
    if sample["os"] == "darwin":
        sample["gpu"] = gpu_na()
        value = None
        if sys.platform == "darwin":
            try:
                value = (mac_reader or mac_temperature_c)()
            except Exception:  # noqa: BLE001 — optional platform sensor
                pass
        sample["temps"] = {"package_c": value, "disk_c": None} if value is not None else temps_na()
        if errors is not None:
            errors.pop("gpu", None)
            errors.pop("temps", None)
    if errors is not None:
        if errors:
            sample["errors"] = errors
        elif "errors" in sample:
            del sample["errors"]
    return sample


def _blank_ticks(user, nice, system, idle):
    return {
        "user": int(user),
        "nice": int(nice),
        "system": int(system),
        "idle": int(idle),
        "iowait": 0,
        "irq": 0,
        "softirq": 0,
        "steal": 0,
        "guest": 0,
        "guestNice": 0,
    }


def parse_mach_cpu_blob(blob):
    """Little-endian Mach PROCESSOR_CPU_LOAD_INFO: user, system, idle, nice per core."""
    data = bytes(blob or b"")
    cores = []
    offset = 0
    width = 16
    while offset + width <= len(data):
        user, system, idle, nice = struct.unpack_from("<4I", data, offset)
        cores.append(_blank_ticks(user, nice, system, idle))
        offset += width
    return cores


def sum_cpu_ticks(cores):
    total = {name: 0 for name in _CPU_FIELDS}
    for core in cores or []:
        for name in _CPU_FIELDS:
            total[name] += int(core.get(name) or 0)
    return total


def darwin_memory_from_counts(free, inactive, speculative, pagesize, memsize, swap_total, swap_used):
    """available = (free + inactive + speculative) pages, clamped to physical RAM."""
    try:
        page = int(pagesize or 0)
    except (TypeError, ValueError):
        page = 0
    if page <= 0:
        page = 4096
    try:
        available = (int(free) + int(inactive) + int(speculative)) * page
    except (TypeError, ValueError):
        available = 0
    if available < 0:
        available = 0
    try:
        total = int(memsize or 0)
    except (TypeError, ValueError):
        total = 0
    if total < 0:
        total = 0
    if total > 0 and available > total:
        available = total
    used = None
    if total > 0:
        used = total - available
        if used < 0:
            used = 0
    try:
        cached = (int(inactive) + int(speculative)) * page
    except (TypeError, ValueError):
        cached = 0
    if cached < 0:
        cached = 0
    swap_free = None
    if swap_total is not None and swap_used is not None:
        try:
            swap_free = int(swap_total) - int(swap_used)
        except (TypeError, ValueError):
            swap_free = None
        if swap_free is not None and swap_free < 0:
            swap_free = 0
    return {
        "total": total or None,
        "free": int(free or 0) * page,
        "available": available,
        "cached": cached,
        "buffers": 0,
        "swapTotal": swap_total,
        "swapFree": swap_free,
        "used": used,
        "swapUsed": swap_used,
    }


def _swap_bytes(number, unit):
    value = float(number)
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    scale = mult.get(str(unit or "").upper(), 1)
    return int(round(value * scale))


def parse_swapusage_text(text):
    """`sysctl vm.swapusage` text: total = 2048.00M  used = 512.50M."""
    blob = str(text or "")
    total_m = _SWAP_TOTAL.search(blob)
    used_m = _SWAP_USED.search(blob)
    if not total_m or not used_m:
        return None, None
    try:
        return _swap_bytes(total_m.group(1), total_m.group(2)), _swap_bytes(used_m.group(1), used_m.group(2))
    except (TypeError, ValueError):
        return None, None


def parse_xsw_usage(blob):
    """Packed xsw_usage: total, avail, used, pagesize, encrypted."""
    data = bytes(blob or b"")
    if len(data) < 32:
        return None, None
    total, _avail, used, _pagesize, _encrypted = struct.unpack_from("<QQQII", data)
    return int(total), int(used)


def parse_route_default(text):
    match = _ROUTE_IFACE.search(str(text or ""))
    if not match:
        return None
    return match.group(1)


_PART_OF_WHOLE = re.compile(r"Part of Whole:\s*(\S+)")
_APFS_STORE = re.compile(r"APFS Physical Store:\s*(\S+)")


def apfs_whole_disk(text):
    """`diskutil info /` field `Part of Whole: disk4`."""
    match = _PART_OF_WHOLE.search(str(text or ""))
    if not match:
        return None
    name = match.group(1)
    if not _DARWIN_DISK.match(name):
        return None
    return name


def apfs_physical_disk(text):
    """`APFS Physical Store: disk0s2` reduced to the whole disk, disk0."""
    match = _APFS_STORE.search(str(text or ""))
    if not match:
        return None
    node = _DISK_NODE.search(match.group(1))
    if not node:
        return None
    name = node.group(1)
    if not _DARWIN_DISK.match(name):
        return None
    return name


def darwin_physical_from_diskutil(root_info, whole_info):
    """Physical store behind the APFS volume at /. None when it is unnamed."""
    if not apfs_whole_disk(root_info):
        return None
    return apfs_physical_disk(whole_info)


def fallback_physical_disk(name):
    if name and _DARWIN_DISK.match(str(name)):
        return str(name)
    return "disk0"


def resolve_darwin_physical_disk():
    """Once, at collector start. disk0 when diskutil does not name a store."""
    root_info = _run_text(["diskutil", "info", "/"], 2)
    whole = apfs_whole_disk(root_info)
    store = None
    if whole:
        store = apfs_physical_disk(_run_text(["diskutil", "info", whole], 2))
    return fallback_physical_disk(store)


def feed_iostat_line(state, line):
    """One line of `iostat -d -w 1 -K`.

    A device line names the columns. Each data line is KB/t, tps, MB/s per
    device. The first data line is the since-boot average and is ignored.
    MB/s is combined throughput for that one-second interval.
    """
    text = str(line or "").strip()
    if not text:
        return False
    parts = text.split()
    if parts and all(_DARWIN_DISK.match(part) for part in parts):
        state["devices"] = parts
        return False
    if "KB/t" in parts or "MB/s" in parts or parts[0] in ("KB/t", "tps"):
        return False
    devices = state.get("devices") or []
    width = 3 * len(devices)
    if not devices or len(parts) < width:
        return False
    values = []
    for part in parts[:width]:
        try:
            values.append(float(part))
        except ValueError:
            return False
    if not state.get("boot_skipped"):
        state["boot_skipped"] = True
        return False
    root = state.get("root") or state.get("device") or "disk0"
    try:
        index = devices.index(root)
    except ValueError:
        return False
    mb_s = values[index * 3 + 2]
    if mb_s < 0:
        mb_s = 0.0
    state["device"] = root
    state["io_bytes_per_s"] = int(mb_s * _IOSTAT_MIB)
    state["rows"] = int(state.get("rows") or 0) + 1
    return True


def darwin_disk_sample(state, root_used, root_total):
    """Combined bytes/s for the physical disk. Read and write stay null."""
    device = state.get("root") or state.get("device") or "disk0"
    io = state.get("io_bytes_per_s")
    if io is not None:
        try:
            io = int(io)
        except (TypeError, ValueError):
            io = None
        if io is not None and io < 0:
            io = 0
    return {
        "device": device,
        "io_bytes_per_s": io,
        "sectors_read": None,
        "sectors_written": None,
        "root_used": root_used,
        "root_total": root_total,
    }


def darwin_virtual(name):
    return bool(_DARWIN_VIRTUAL.match(str(name or "")))


def _net_slot(state, name):
    ifaces = state.setdefault("ifaces", {})
    slot = ifaces.get(name)
    if slot is None:
        slot = {"abs_rx": 0, "abs_tx": 0, "last_rx": None, "last_tx": None, "mode": "unknown"}
        ifaces[name] = slot
    return slot


def _note_net_reading(state, name, ibytes, obytes, kind):
    """kind is 'absolute' (replace) or 'interval' (absolute until a drop, then deltas)."""
    slot = _net_slot(state, name)
    ibytes = int(ibytes)
    obytes = int(obytes)
    if kind == "absolute":
        slot["mode"] = "absolute"
        slot["abs_rx"] = ibytes
        slot["abs_tx"] = obytes
    elif slot["last_rx"] is None:
        slot["abs_rx"] = ibytes
        slot["abs_tx"] = obytes
    elif ibytes < slot["last_rx"] or obytes < slot["last_tx"] or slot["mode"] == "delta":
        slot["mode"] = "delta"
        slot["abs_rx"] = int(slot["abs_rx"]) + ibytes
        slot["abs_tx"] = int(slot["abs_tx"]) + obytes
    else:
        slot["mode"] = "absolute"
        slot["abs_rx"] = ibytes
        slot["abs_tx"] = obytes
    slot["last_rx"] = ibytes
    slot["last_tx"] = obytes
    state["rows"] = int(state.get("rows") or 0) + 1


def feed_netstat_line(state, line):
    """One line of `netstat -ib` or `netstat -ib -w 1`."""
    text = str(line or "").strip()
    if not text:
        return False
    header = _NET_IFACE_HEADER.search(text)
    if header and not text[0].isdigit():
        state["current"] = header.group(1)
        return False
    lowered = text.lower()
    if lowered.startswith("name ") or lowered.startswith("packets ") or lowered.startswith("input "):
        return False
    parts = text.split()
    if not parts:
        return False
    if "<Link" in text or "<link" in lowered:
        name = parts[0]
        nums = []
        for part in parts:
            if part.isdigit():
                nums.append(int(part))
        # Mtu sits in front of the packet counters. The last 7 are the link row.
        if len(nums) >= 8:
            nums = nums[-7:]
        if len(nums) >= 6:
            obytes = nums[5]
            _note_net_reading(state, name, nums[2], obytes, "absolute")
            return True
        return False
    if all(part.isdigit() for part in parts) and len(parts) >= 6:
        name = state.get("current") or ""
        if not name:
            return False
        # `netstat -ib -w 1` with no -I labels the row Total. Pin it to the default.
        if name == "Total" and state.get("default"):
            name = state["default"]
        ibytes = int(parts[2])
        obytes = int(parts[5])
        _note_net_reading(state, name, ibytes, obytes, "interval")
        return True
    return False


def publish_darwin_disk(box, root_used, root_total):
    """While iostat is dead the last interval must not go out with a new stamp."""
    if box.iostat.dead:
        box.disk["io_bytes_per_s"] = None
    return darwin_disk_sample(box.disk, root_used, root_total)


def publish_darwin_net(box):
    """While netstat is dead the last counters are not a fresh rate."""
    if box.netstat.dead:
        box.net["ifaces"] = {}
        box.net["rows"] = 0
        box.net["current"] = ""
        return {"na": True}
    return net_sample_from_state(box.net, box.route_iface)


def net_sample_from_state(state, default_iface):
    rows = []
    virtual = []
    ifaces = state.get("ifaces") or {}
    for name in sorted(ifaces):
        slot = ifaces[name]
        rows.append({"name": name, "rx": int(slot["abs_rx"]), "tx": int(slot["abs_tx"])})
        if darwin_virtual(name):
            virtual.append(name)
    if "lo0" not in virtual:
        virtual.append("lo0")
    return {"ifaces": rows, "virtual": virtual, "default_iface": default_iface}


def parse_pmset_batt(text):
    """pmset -g batt. No InternalBattery and no percent hides the card."""
    blob = str(text or "")
    if "InternalBattery" not in blob and "Battery" not in blob:
        return None
    match = _PMSET_PCT.search(blob)
    if not match:
        return None
    status = match.group(2).strip().lower()
    if status:
        status = status.split()[0]
    else:
        status = None
    try:
        capacity = int(match.group(1))
    except ValueError:
        return None
    return {
        "capacity": capacity,
        "status": status,
        "power_now_uw": None,
        "current_now_ua": None,
        "voltage_now_uv": None,
    }


def present_darwin_ps(text, mem_total):
    """Group `ps -axo pid=,pcpu=,rss=,comm=` by basename. pcpu is already a percent."""
    order = []
    groups = {}
    count = 0
    try:
        total = float(mem_total or 0)
    except (TypeError, ValueError):
        total = 0.0
    for line in str(text or "").split("\n"):
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pcpu = float(parts[1])
            rss_kb = float(parts[2])
        except ValueError:
            continue
        if pcpu < 0:
            pcpu = 0.0
        if rss_kb < 0:
            rss_kb = 0.0
        comm = parts[3].strip()
        base = os.path.basename(comm) or comm or "?"
        count += 1
        mem = 0.0
        if total > 0:
            mem = 100.0 * (rss_kb * 1024.0) / total
        group = groups.get(base)
        if group is None:
            group = {"cpu": 0.0, "mem": 0.0, "count": 0}
            groups[base] = group
            order.append(base)
        group["cpu"] += pcpu
        group["mem"] += mem
        group["count"] += 1
    items = []
    for name in order:
        group = groups[name]
        label = name if group["count"] <= 1 else "%s ×%d" % (name, group["count"])
        items.append((label, group["cpu"], group["mem"]))

    def top(index):
        ranked = sorted(items, key=lambda item: (-item[index], item[0]))
        return [{"name": item[0], "text": format_percent_precise(item[index])} for item in ranked[:8]]

    return {"byCpu": top(1), "byMem": top(2)}, count


def _track_child(proc):
    if proc is not None:
        with _children_lock:
            _child_procs.append(proc)


def stop_children():
    """SIGTERM, then SIGKILL after 0.5 s, every long-lived child process group."""
    global _children_stopped
    with _children_lock:
        _children_stopped = True
        children = list(_child_procs)
    for child in list(_line_children):
        child.stop()
    for proc in children:
        _stop_group(proc)


def _stop_group(proc):
    if proc is None:
        return
    def send(sig):
        try:
            os.killpg(proc.pid, sig)
            return True
        except ProcessLookupError:
            return False
    alive = send(signal.SIGTERM)
    deadline = time.monotonic() + 0.5
    while alive and time.monotonic() < deadline:
        proc.poll()  # Reap the leader even if other group members remain.
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            alive = False
            break
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    if alive:
        send(signal.SIGKILL)
    proc.wait()
    with _children_lock:
        if proc in _child_procs:
            _child_procs.remove(proc)


def _run_tracked(args, timeout, **kwargs):
    input_data = kwargs.pop("input", None)
    with _children_lock:
        if _children_stopped:
            raise subprocess.SubprocessError('collector is stopping')
        proc = subprocess.Popen(args, start_new_session=True, **kwargs)
        _track_child(proc)
    try:
        try:
            stdout, stderr = proc.communicate(input=input_data, timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_group(proc)
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args, output=stdout, stderr=stderr)
        return stdout
    finally:
        with _children_lock:
            if proc in _child_procs:
                _child_procs.remove(proc)


def finalize():
    stop_children()


atexit.register(finalize)


_line_children = []


class LineChild(object):
    """One long-lived stdout producer. A pty makes iostat flush each line.

    The child is its own session, same as the macOS iostat and netstat
    helpers. When it dies, proc and the pty are cleared and the next start
    waits 30 s. While it is dead the sensor must not republish the last rate.
    """

    def __init__(self, argv):
        self.argv = list(argv)
        self.proc = None
        self.master = None
        self.buf = b""
        self.dead = False
        self.fresh = False
        self.generation = 0
        self.next_start = 0.0
        _line_children.append(self)

    def close_master(self):
        if self.master is None:
            return
        try:
            os.close(self.master)
        except OSError:
            pass
        self.master = None

    def _mark_dead(self):
        if not self.dead:
            self.next_start = time.monotonic() + 30.0
        self.stop()

    def stop(self):
        proc = self.proc
        self.dead = True
        self.fresh = False
        try:
            _stop_group(proc)
        finally:
            self.close_master()
            self.proc = None
            if self in _line_children:
                _line_children.remove(self)

    def ensure(self):
        if _children_stopped:
            self._mark_dead()
            return
        if self.proc is not None and self.proc.poll() is None:
            self.dead = False
            return
        if self.proc is not None:
            self._mark_dead()
            return
        now = time.monotonic()
        if now < self.next_start:
            self.dead = True
            return
        if self not in _line_children:
            _line_children.append(self)
        self.close_master()
        master = None
        slave = None
        try:
            master, slave = pty.openpty()
            self.proc = subprocess.Popen(
                self.argv,
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            self.proc = None
            self.dead = True
            self.fresh = False
            self.next_start = now + 30.0
            if master is not None:
                try:
                    os.close(master)
                except OSError:
                    pass
            if slave is not None:
                try:
                    os.close(slave)
                except OSError:
                    pass
            return
        try:
            os.close(slave)
        except OSError:
            pass
        self.master = master
        try:
            flags = fcntl.fcntl(master, fcntl.F_GETFL)
            fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        except OSError:
            pass
        self.buf = b""
        self.dead = False
        self.fresh = True
        self.generation += 1
        _track_child(self.proc)

    def read_ready(self):
        if self.proc is None or self.master is None:
            return []
        lines = []
        while True:
            try:
                ready, _, _ = select.select([self.master], [], [], 0)
            except (OSError, ValueError):
                break
            if not ready:
                break
            try:
                chunk = os.read(self.master, 65536)
            except BlockingIOError:
                break
            except OSError:
                self._mark_dead()
                break
            if not chunk:
                self._mark_dead()
                break
            self.buf += chunk
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                lines.append(raw.decode("utf-8", "replace"))
        if self.proc is not None and self.proc.poll() is not None:
            self._mark_dead()
        return lines

    def drain(self):
        self.ensure()
        return self.read_ready()


def _run_text(argv, timeout):
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return ""
    _track_child(proc)
    try:
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return ""
        return stdout.decode("utf-8", "replace")
    finally:
        _stop_group(proc)
        if proc.stdout is not None:
            proc.stdout.close()


_darwin_libc = None
_mach_host = None


def _libc():
    global _darwin_libc
    if _darwin_libc is None:
        _darwin_libc = ctypes.CDLL(None, use_errno=True)
    return _darwin_libc


def _host_port(libc):
    global _mach_host
    if _mach_host is None:
        libc.mach_host_self.restype = ctypes.c_uint
        _mach_host = libc.mach_host_self()
    return _mach_host


class VMStatistics64(ctypes.Structure):
    _fields_ = [
        ("free_count", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("inactive_count", ctypes.c_uint32),
        ("wire_count", ctypes.c_uint32),
        ("zero_fill_count", ctypes.c_uint64),
        ("reactivations", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("pageouts", ctypes.c_uint64),
        ("faults", ctypes.c_uint64),
        ("cow_faults", ctypes.c_uint64),
        ("lookups", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("purges", ctypes.c_uint64),
        ("purgeable_count", ctypes.c_uint32),
        ("speculative_count", ctypes.c_uint32),
        ("decompressions", ctypes.c_uint64),
        ("compressions", ctypes.c_uint64),
        ("swapins", ctypes.c_uint64),
        ("swapouts", ctypes.c_uint64),
        ("compressor_page_count", ctypes.c_uint32),
        ("throttled_count", ctypes.c_uint32),
        ("external_page_count", ctypes.c_uint32),
        ("internal_page_count", ctypes.c_uint32),
        ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
    ]


class XSWUsage(ctypes.Structure):
    _fields_ = [
        ("xsu_total", ctypes.c_uint64),
        ("xsu_avail", ctypes.c_uint64),
        ("xsu_used", ctypes.c_uint64),
        ("xsu_pagesize", ctypes.c_uint32),
        ("xsu_encrypted", ctypes.c_uint32),
    ]


def darwin_cpu_cores():
    """Per-core Mach ticks. Caller maps a failure to n/a."""
    libc = _libc()
    libc.mach_task_self.restype = ctypes.c_uint
    libc.host_processor_info.argtypes = [
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint),
    ]
    libc.host_processor_info.restype = ctypes.c_int
    libc.vm_deallocate.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t]
    libc.vm_deallocate.restype = ctypes.c_int
    host = _host_port(libc)
    cpu_count = ctypes.c_uint(0)
    info = ctypes.c_void_p()
    info_count = ctypes.c_uint(0)
    kr = libc.host_processor_info(host, 2, ctypes.byref(cpu_count), ctypes.byref(info), ctypes.byref(info_count))
    try:
        if kr != 0 or not info.value or info_count.value <= 0:
            raise OSError("host_processor_info %s" % kr)
        blob = ctypes.string_at(info.value, int(info_count.value) * 4)
    finally:
        if info.value:
            libc.vm_deallocate(libc.mach_task_self(), info, int(info_count.value) * 4)
    cores = parse_mach_cpu_blob(blob)
    if not cores:
        raise OSError("host_processor_info returned no cpus")
    return cores


def darwin_page_size():
    libc = _libc()
    page = ctypes.c_ulong(0)
    libc.host_page_size.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_ulong)]
    libc.host_page_size.restype = ctypes.c_int
    kr = libc.host_page_size(_host_port(libc), ctypes.byref(page))
    if kr != 0 or page.value <= 0:
        return 4096
    return int(page.value)


def _c_void(buf):
    """Address as c_void_p. byref() is rejected when the argtype is c_void_p."""
    return ctypes.c_void_p(ctypes.addressof(buf))


def darwin_vm_stats():
    libc = _libc()
    stats = VMStatistics64()
    count = ctypes.c_uint(ctypes.sizeof(stats) // 4)
    libc.host_statistics64.argtypes = [
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.POINTER(VMStatistics64),
        ctypes.POINTER(ctypes.c_uint),
    ]
    libc.host_statistics64.restype = ctypes.c_int
    kr = libc.host_statistics64(_host_port(libc), 4, ctypes.byref(stats), ctypes.byref(count))
    if kr != 0:
        raise OSError("host_statistics64 %s" % kr)
    return stats


def _sysctl_prepare(libc):
    libc.sysctlbyname.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    libc.sysctlbyname.restype = ctypes.c_int


def darwin_memsize():
    libc = _libc()
    _sysctl_prepare(libc)
    size = ctypes.c_size_t(8)
    value = ctypes.c_uint64(0)
    if libc.sysctlbyname(b"hw.memsize", _c_void(value), ctypes.byref(size), None, 0) != 0:
        raise OSError("hw.memsize")
    return int(value.value)


def darwin_swap_pair():
    libc = _libc()
    _sysctl_prepare(libc)
    usage = XSWUsage()
    size = ctypes.c_size_t(ctypes.sizeof(usage))
    if libc.sysctlbyname(b"vm.swapusage", _c_void(usage), ctypes.byref(size), None, 0) != 0:
        return None, None
    return int(usage.xsu_total), int(usage.xsu_used)


def darwin_hw_mhz():
    """Apple Silicon often reports 0. Leave MHz null rather than invent a number."""
    libc = _libc()
    _sysctl_prepare(libc)
    for key in (b"hw.cpufrequency", b"hw.cpufrequency_max"):
        size = ctypes.c_size_t(8)
        value = ctypes.c_uint64(0)
        if libc.sysctlbyname(key, _c_void(value), ctypes.byref(size), None, 0) != 0:
            continue
        hz = int(value.value)
        if hz > 0:
            return int(hz / 1000000)
    return None


class DarwinCollector(object):
    def __init__(self):
        physical = resolve_darwin_physical_disk()
        self.disk = {
            "io_bytes_per_s": None,
            "device": physical,
            "root": physical,
            "devices": None,
            "boot_skipped": False,
            "rows": 0,
        }
        self.net = {"ifaces": {}, "current": "", "rows": 0}
        self.iostat = LineChild(IOSTAT_ARGV)
        self.netstat = LineChild(netstat_argv(None))
        self.route_at = 0.0
        self.route_iface = None
        self.batt_at = 0.0
        self.memsize = None
        self.page = None

    def _reset_disk_parser(self):
        self.disk["boot_skipped"] = False
        self.disk["io_bytes_per_s"] = None
        self.disk["devices"] = None
        self.disk["rows"] = 0

    def _reset_net_parser(self):
        self.net = {"ifaces": {}, "current": "", "rows": 0, "default": self.route_iface or ""}

    def poll_rates(self):
        now = time.monotonic()
        if self.route_at <= 0 or (now - self.route_at) >= 60:
            self.route_iface = parse_route_default(_run_text(["route", "-n", "get", "default"], 2))
            self.route_at = now
            want = netstat_argv(self.route_iface)
            if self.netstat.argv != want:
                self.netstat.stop()
                self.netstat = LineChild(want)
        self.iostat.ensure()
        self.netstat.ensure()
        if self.iostat.fresh:
            self._reset_disk_parser()
            self.iostat.fresh = False
        if self.netstat.fresh:
            self._reset_net_parser()
            self.netstat.fresh = False
        self.net["default"] = self.route_iface or ""
        for line in self.iostat.read_ready():
            feed_iostat_line(self.disk, line)
        for line in self.netstat.read_ready():
            feed_netstat_line(self.net, line)


_darwin_collector = None


def darwin_collector():
    global _darwin_collector
    if _darwin_collector is None:
        _darwin_collector = DarwinCollector()
    return _darwin_collector


def collect_darwin(include_procs):
    """macOS sample. GPU is n/a without root."""
    errors = {}
    sample = {"t_ms": int(time.time() * 1000)}
    box = darwin_collector()
    try:
        box.poll_rates()
    except Exception as exc:  # noqa: BLE001
        errors["collector"] = _error_text(exc, "collector")
    sample["mono_ms"] = time.monotonic() * 1000.0

    try:
        cores = darwin_cpu_cores()
        mhz = None
        try:
            mhz = darwin_hw_mhz()
        except Exception:  # noqa: BLE001 — frequency is optional
            mhz = None
        core_mhz = []
        for _core in cores:
            core_mhz.append(mhz)
        sample["cpu"] = {
            "total": sum_cpu_ticks(cores),
            "cores": cores,
            "mhz": mhz,
            "core_mhz": core_mhz,
        }
    except Exception:  # noqa: BLE001 — no Mach counters on this host
        sample["cpu"] = {"na": True}

    try:
        if box.page is None:
            box.page = darwin_page_size()
        if box.memsize is None:
            box.memsize = darwin_memsize()
        stats = darwin_vm_stats()
        swap_total, swap_used = darwin_swap_pair()
        sample["mem"] = darwin_memory_from_counts(
            stats.free_count,
            stats.inactive_count,
            stats.speculative_count,
            box.page,
            box.memsize,
            swap_total,
            swap_used,
        )
    except Exception:  # noqa: BLE001
        sample["mem"] = {"na": True}

    root_used, root_total = root_fs()
    sample["disk"] = publish_darwin_disk(box, root_used, root_total)
    sample["net"] = publish_darwin_net(box)

    sample["gpu"] = gpu_na()
    sample["temps"] = temps_na()

    now = time.monotonic()
    if box.batt_at and (now - box.batt_at) < 30.0:
        sample["battery_skip"] = True
        sample["battery"] = None
    else:
        sample["battery"] = parse_pmset_batt(_run_text(["pmset", "-g", "batt"], 2))
        box.batt_at = now

    if include_procs:
        started = time.monotonic()
        mem_total = 0
        mem = sample.get("mem")
        if isinstance(mem, dict) and mem.get("total"):
            mem_total = mem.get("total") or 0
        text = _run_text(["ps", "-axo", "pid=,pcpu=,rss=,comm="], 4)
        presented, count = present_darwin_ps(text, mem_total)
        sample["procs"] = {
            "presented": presented,
            "sweep_ms": round((time.monotonic() - started) * 1000.0, 3),
            "count": count,
        }
    else:
        sample["procs"] = None
    if errors:
        sample["errors"] = errors
    return sample


def safe_sample(include_procs):
    try:
        return collect_sample(include_procs)
    except Exception as exc:  # noqa: BLE001
        sample = {
            "t_ms": int(time.time() * 1000),
            "mono_ms": time.monotonic() * 1000.0,
            "cpu": None,
            "mem": None,
            "disk": None,
            "net": None,
            "gpu": None,
            "temps": None,
            "battery": None,
            "procs": None,
            "errors": {"collector": _error_text(exc, "collector")},
        }
        return apply_host_meta(sample, host_name(), host_os_name(), kernel_release())


def remote_shutdown():
    """Kill every tracked child process group, then the caller exits."""
    finalize()


def remote_parent_gone(ppid=None):
    """sshd is gone when this process has been reparented to pid 1."""
    if ppid is None:
        try:
            ppid = os.getppid()
        except OSError:
            return True
    try:
        return int(ppid) == 1
    except (TypeError, ValueError):
        return True


def _die_remote(_signum, _frame):
    _die_term(_signum, _frame)


def install_remote_signals():
    """Handle SIGHUP, SIGTERM and SIGPIPE. Do not ignore SIGPIPE."""
    signal.signal(signal.SIGHUP, _die_remote)
    signal.signal(signal.SIGTERM, _die_remote)
    try:
        signal.signal(signal.SIGPIPE, _die_remote)
    except (OSError, ValueError):
        pass


def serve_remote():
    """1 Hz, no stdin. Process table every 5 samples. Children die with us."""
    period = 1.0
    next_at = time.monotonic()
    index = 0
    usage_emitter = _UsageEmitter()
    while True:
        if remote_parent_gone():
            return 0
        now = time.monotonic()
        delay = next_at - now
        if delay > 0:
            time.sleep(delay if delay < 0.25 else 0.25)
            continue
        if remote_parent_gone():
            return 0
        sample = usage_emitter.filter(safe_sample(remote_includes(index)))
        try:
            emit_sample(sample)
        except BrokenPipeError:
            return 0
        except OSError:
            return 0
        except ValueError as exc:
            if "closed" in str(exc).lower():
                return 0
            raise
        index += 1
        next_at += period
        now = time.monotonic()
        if next_at < now:
            skipped = int((now - next_at) / period)
            if skipped > 0:
                index += skipped
                next_at += skipped * period
    return 0


def remote_shutdown_fixture():
    """One session child, then wait until the remote shutdown path runs.

    The child is started the same way as iostat: pty, new session. The test
    signals this process. This process must reap the child itself.
    """
    install_remote_signals()
    child = LineChild(["sleep", "60"])
    child.ensure()
    proc = child.proc
    if proc is None or proc.poll() is not None:
        sys.stderr.write("fixture: helper child did not start\n")
        return 2
    sys.stdout.write("ready %s\n" % proc.pid)
    sys.stdout.flush()
    while True:
        if remote_parent_gone():
            remote_shutdown()
            return 0
        if proc.poll() is not None:
            sys.stderr.write("fixture: helper exited on its own\n")
            return 3
        time.sleep(0.05)
    return 0


def remote_shutdown_selftest():
    """SIGTERM the fixture only. The sleep child must die without us signaling it."""
    try:
        source_path = __file__
    except NameError:
        return "remote shutdown selftest has no script path"
    proc = subprocess.Popen(
        [sys.executable, "-u", source_path, "--remote-shutdown-selftest"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sleep_pid = None
    try:
        deadline = time.monotonic() + 5.0
        buf = b""
        while time.monotonic() < deadline and b"\n" not in buf:
            if proc.poll() is not None and not buf:
                err = b""
                if proc.stderr is not None:
                    try:
                        err = proc.stderr.read()
                    except OSError:
                        err = b""
                return "remote shutdown fixture exited early %s %s" % (
                    proc.returncode, err.decode("utf-8", "replace").strip(),
                )
            try:
                ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(proc.stdout.fileno(), 256)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        if not line.startswith("ready "):
            return "remote shutdown fixture did not report ready: %s" % line
        try:
            sleep_pid = int(line.split()[1])
        except (IndexError, ValueError):
            return "remote shutdown fixture pid unreadable"
        try:
            with open("/proc/%s/stat" % sleep_pid, "r", encoding="utf-8") as handle:
                stat = handle.read()
            fields = stat[stat.rfind(")") + 2:].split()
            pgrp = int(fields[2])
        except (OSError, ValueError, IndexError):
            return "helper is not a session leader"
        if pgrp != sleep_pid:
            return "helper pgrp %s is not its pid" % pgrp
        try:
            os.kill(sleep_pid, 0)
        except OSError:
            return "helper was already gone"
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return "remote shutdown fixture ignored SIGTERM"
        if code != 0:
            err = b""
            if proc.stderr is not None:
                try:
                    err = proc.stderr.read()
                except OSError:
                    err = b""
            return "remote shutdown fixture exit %s %s" % (code, err.decode("utf-8", "replace").strip())
        try:
            os.kill(sleep_pid, 0)
        except ProcessLookupError:
            sleep_pid = None
            return None
        except OSError as exc:
            if getattr(exc, "errno", None) == 3:
                sleep_pid = None
                return None
            return "helper still signalable: %s" % exc
        return "helper still alive after remote shutdown"
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

        if sleep_pid is not None:
            try:
                os.kill(-sleep_pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(sleep_pid, signal.SIGKILL)
                except OSError:
                    pass


def remote_loopback():
    """Run this file under --remote locally. Three samples, then SIGHUP."""
    try:
        source_path = __file__
    except NameError:
        return "remote loopback has no script path"
    try:
        with open(source_path, "rb") as handle:
            source = handle.read()
    except OSError as exc:
        return "remote loopback could not read the script: %s" % exc
    proc = subprocess.Popen(
        [sys.executable, "-u", "-", "--remote"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.stdin.write(source)
        proc.stdin.close()
        lines = []
        deadline = time.monotonic() + 12.0
        buf = b""
        while len(lines) < 3 and time.monotonic() < deadline:
            if proc.poll() is not None and not buf:
                break
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                ready, _, _ = select.select([proc.stdout], [], [], min(timeout, 1.0))
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(proc.stdout.fileno(), 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if raw.strip():
                    lines.append(raw)
        if len(lines) < 3:
            return "remote loopback got %d samples" % len(lines)
        samples = []
        for raw in lines[:3]:
            try:
                samples.append(json.loads(raw.decode("utf-8")))
            except (ValueError, UnicodeError):
                return "remote loopback line was not json"
        for sample in samples:
            if "host" not in sample or sample.get("os") not in ("linux", "darwin"):
                return "remote sample missing host or os"
            if "kernel" not in sample:
                return "remote sample missing kernel"
            if "error" in sample:
                return "remote sample has a top-level error"
        if not isinstance(samples[0].get("procs"), dict):
            return "remote sample 0 missing procs"
        if samples[1].get("procs") is not None or samples[2].get("procs") is not None:
            return "remote samples 1-2 included procs"
        proc.send_signal(signal.SIGHUP)
        try:
            code = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            return "remote ignored SIGHUP"
        if code != 0:
            return "remote exit %s" % code
        return None
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass


def darwin_parser_checks(check):
    """Recorded iostat, netstat, ps, pmset, route, swap and Mach fixtures."""
    check(IOSTAT_ARGV == ["iostat", "-d", "-w", "1", "-K"], "one iostat child, one second interval")
    check(NETSTAT_ARGV == ["netstat", "-ib", "-w", "1"], "one netstat child, one second interval")
    check(netstat_argv(None) == NETSTAT_ARGV, "netstat fallback has no interface")
    check(netstat_argv("en0") == ["netstat", "-I", "en0", "-b", "-w", "1"], "netstat pins the default interface")
    check(netstat_argv("lo0") == NETSTAT_ARGV, "netstat does not pin loopback")
    check(remote_includes(0) and remote_includes(5) and not remote_includes(1), "remote procs every 5 s")
    check(use_pdeathsig(False) is True and use_pdeathsig(True) is False, "no pdeathsig in --remote")
    check(kernel_is_wsl("5.15.153.1-microsoft-standard-WSL2"), "wsl kernel")
    check(kernel_is_wsl("6.6.87.2-microsoft-standard-WSL2"), "microsoft kernel")
    check(not kernel_is_wsl("6.8.0-arch1-1"), "linux kernel is not wsl")
    check(not kernel_is_wsl("24.5.0"), "darwin kernel is not wsl")

    blob = struct.pack("<4I", 100, 10, 900, 5) + struct.pack("<4I", 50, 20, 400, 1)
    cores = parse_mach_cpu_blob(blob)
    check(len(cores) == 2, "mach blob has two cores")
    check(cores[0]["user"] == 100 and cores[0]["system"] == 10, "mach user and system")
    check(cores[0]["idle"] == 900 and cores[0]["nice"] == 5, "mach idle and nice")
    check(cores[0]["iowait"] == 0 and cores[1]["user"] == 50, "mach second core")
    total = sum_cpu_ticks(cores)
    check(total["user"] == 150 and total["idle"] == 1300 and total["nice"] == 6, "mach total")

    stats = VMStatistics64()
    stats.free_count = 100
    stats.inactive_count = 50
    stats.speculative_count = 25
    mem = darwin_memory_from_counts(
        stats.free_count, stats.inactive_count, stats.speculative_count,
        4096, 1000 * 4096, 2048 * 1024 * 1024, int(round(512.5 * 1024 * 1024)),
    )
    check(mem["available"] == 175 * 4096, "darwin available pages")
    check(mem["used"] == (1000 - 175) * 4096, "darwin used is physical minus available")
    check(mem["cached"] == 75 * 4096, "darwin cached")
    check(mem["total"] == 1000 * 4096, "darwin memsize")
    packed = struct.pack("<QQQII", 2048 * 1024 * 1024, 100, int(round(512.5 * 1024 * 1024)), 4096, 1)
    swap_total, swap_used = parse_xsw_usage(packed)
    check(swap_total == 2048 * 1024 * 1024 and swap_used == int(round(512.5 * 1024 * 1024)), "xsw_usage")
    text_total, text_used = parse_swapusage_text("total = 2048.00M  used = 512.50M  free = 1535.50M")
    check(text_total == 2048 * 1024 * 1024, "swapusage total")
    check(text_used == int(round(512.5 * 1024 * 1024)), "swapusage used")

    root_info = (
        "   Device Identifier:         disk4s1s1\n"
        "   Device Node:               /dev/disk4s1s1\n"
        "   Whole:                     No\n"
        "   Part of Whole:             disk4\n"
    )
    whole_info = (
        "   Device Identifier:         disk4\n"
        "   Part of Whole:             disk4\n"
        "   APFS Physical Store:       disk0s2\n"
    )
    check(apfs_whole_disk(root_info) == "disk4", "diskutil part of whole")
    check(apfs_physical_disk(whole_info) == "disk0", "apfs physical store disk0s2")
    check(apfs_physical_disk("   APFS Physical Store:       disk10s2\n") == "disk10", "slice reduces to the whole disk")
    check(darwin_physical_from_diskutil(root_info, whole_info) == "disk0", "synthesized volume maps to the physical store")
    check(darwin_physical_from_diskutil("no disk", whole_info) is None, "missing whole disk")
    check(darwin_physical_from_diskutil(root_info, "no store") is None, "missing physical store")
    check(fallback_physical_disk(None) == "disk0", "diskutil fallback is disk0")
    check(fallback_physical_disk("disk0s2") == "disk0", "a slice name is not a whole disk")

    def blank_disk(root):
        return {
            "io_bytes_per_s": None,
            "device": root,
            "root": root,
            "devices": None,
            "boot_skipped": False,
            "rows": 0,
        }

    disk = blank_disk("disk0")
    feed_iostat_line(disk, "              disk0               disk3               disk6               disk7 ")
    feed_iostat_line(disk, "    KB/t  tps  MB/s     KB/t  tps  MB/s     KB/t  tps  MB/s     KB/t  tps  MB/s ")
    feed_iostat_line(disk, "   16.00   10  9.00    32.00    2  8.00     8.00    1  0.50     4.00    1  0.25 ")
    check(disk["io_bytes_per_s"] is None and disk["rows"] == 0, "iostat ignores the since-boot average")
    feed_iostat_line(disk, "   20.00    4  1.00    10.00    1  3.00    12.00    2  0.50    12.00    3  2.00 ")
    check(disk["device"] == "disk0", "iostat uses the physical disk")
    check(disk["io_bytes_per_s"] == int(1.00 * _IOSTAT_MIB), "iostat MB/s is combined bytes per second")
    check(disk["rows"] == 1, "one interval row")
    shaped = darwin_disk_sample(disk, 10, 100)
    check(shaped["device"] == "disk0", "darwin disk device")
    check(shaped["io_bytes_per_s"] == int(1.00 * _IOSTAT_MIB), "darwin io_bytes_per_s")
    check(shaped["sectors_read"] is None and shaped["sectors_written"] is None, "darwin read/write split is null")
    check(shaped["root_used"] == 10 and shaped["root_total"] == 100, "root usage passed through")
    feed_iostat_line(disk, "    8.00    2  2.00     0.00    0  0.00     0.00    0  0.00     0.00    0  0.00 ")
    check(disk["io_bytes_per_s"] == int(2.00 * _IOSTAT_MIB), "iostat keeps the latest interval")
    feed_iostat_line(disk, "disk0 disk3 disk6 disk7")
    feed_iostat_line(disk, "KB/t tps MB/s KB/t tps MB/s KB/t tps MB/s KB/t tps MB/s")
    feed_iostat_line(disk, "8.00 2 0.25 0.00 0 0.00 0.00 0 0.00 0.00 0 0.00")
    check(disk["io_bytes_per_s"] == int(0.25 * _IOSTAT_MIB), "a repeated header does not skip the next interval")

    other = blank_disk("disk6")
    feed_iostat_line(other, "disk0 disk3 disk6 disk7")
    feed_iostat_line(other, "KB/t  tps  MB/s  KB/t  tps  MB/s  KB/t  tps  MB/s  KB/t  tps  MB/s")
    feed_iostat_line(other, "16.00 10 9.00 32.00 2 8.00 8.00 1 0.50 4.00 1 0.25")
    feed_iostat_line(other, "20.00 4 1.00 10.00 1 3.00 12.00 2 0.50 12.00 3 2.00")
    check(other["io_bytes_per_s"] == int(0.50 * _IOSTAT_MIB), "iostat reads the physical disk column")
    absent = blank_disk("disk9")
    feed_iostat_line(absent, "disk0 disk3 disk6 disk7")
    feed_iostat_line(absent, "KB/t tps MB/s KB/t tps MB/s KB/t tps MB/s KB/t tps MB/s")
    feed_iostat_line(absent, "16.00 10 9.00 32.00 2 8.00 8.00 1 0.50 4.00 1 0.25")
    feed_iostat_line(absent, "20.00 4 1.00 10.00 1 3.00 12.00 2 0.50 12.00 3 2.00")
    check(absent["io_bytes_per_s"] is None and absent["rows"] == 0, "a missing column stays null")
    missed = darwin_disk_sample(absent, 1, 2)
    check(missed["device"] == "disk9" and missed["sectors_read"] is None, "device stays the resolved disk")

    net = {"ifaces": {}, "current": "", "rows": 0}
    feed_netstat_line(net, "            input          (en0)           output")
    feed_netstat_line(net, "   packets  errs      bytes    packets  errs      bytes colls")
    feed_netstat_line(net, "       10     0     1000000         1     0        2000     0")
    feed_netstat_line(net, "        4     0        5000         1     0         100     0")
    check(net["ifaces"]["en0"]["abs_rx"] == 1005000, "netstat absolute then delta")
    check(net["ifaces"]["en0"]["abs_tx"] == 2100, "netstat tx delta")
    check(net["ifaces"]["en0"]["mode"] == "delta", "a drop switches netstat to deltas")
    classic = {"ifaces": {}, "current": "", "rows": 0}
    table = "\n".join([
        "Name  Mtu   Network     Address   Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll",
        "en0   1500  <Link#14>   aa:bb     10 0 5000 80 0 3000 0",
        "en0   1500  192.0.2.5 192.0.2.5 10 0 9999 80 0 9999 0",
        "lo0   16384 <Link#1>    1 0 100 1 0 100 0",
    ])
    for row in table.split("\n"):
        feed_netstat_line(classic, row)
    check(classic["ifaces"]["en0"]["abs_rx"] == 5000, "link row bytes, not the address row")
    check(classic["ifaces"]["en0"]["abs_tx"] == 3000, "link row obytes")
    check(classic["ifaces"]["lo0"]["abs_rx"] == 100, "lo0 link row")
    shaped_net = net_sample_from_state(classic, "en0")
    check("lo0" in shaped_net["virtual"] and shaped_net["default_iface"] == "en0", "lo0 is virtual")
    check(parse_route_default("   route to: default\ndestination: default\n  interface: en0\n") == "en0", "route interface")
    total_net = {"ifaces": {}, "current": "", "rows": 0, "default": "en0"}
    feed_netstat_line(total_net, "            input          (Total)           output")
    feed_netstat_line(total_net, "       10     0        4000         1     0         250     0")
    check(total_net["ifaces"]["en0"]["abs_rx"] == 4000, "Total row is pinned to the default interface")
    unresolved = darwin_disk_sample(blank_disk(None), 1, 2)
    check(unresolved["device"] == "disk0" and unresolved["io_bytes_per_s"] is None, "sample falls back to disk0")

    ps_text = "\n".join([
        "  101  12.5  20480 Safari",
        "  102   1.0   1024 Safari",
        "  103   0.5    512 /usr/libexec/trustd",
    ])
    presented, count = present_darwin_ps(ps_text, 8 * 1024 * 1024 * 1024)
    check(count == 3, "ps row count")
    check(presented["byCpu"][0]["name"] == "Safari ×2", "ps groups basename")
    check(presented["byCpu"][0]["text"] == "13.5%", "ps sums pcpu")
    check(presented["byMem"][0]["name"] == "Safari ×2", "ps memory leader")

    batt = parse_pmset_batt(
        "Now drawing from 'Battery Power'\n"
        " -InternalBattery-0 (id=1)\t76%; discharging; 3:12 remaining present: true\n"
    )
    check(batt and batt["capacity"] == 76 and batt["status"] == "discharging", "pmset percent")
    check(parse_pmset_batt("Now drawing from 'AC Power'\n") is None, "pmset without a battery hides")

    wsl = {"gpu": {"present": False}, "temps": {"package_c": None, "disk_c": None}, "errors": {"gpu": "no card"}}
    apply_host_meta(wsl, "host-b", "linux", "5.15.153.1-microsoft-standard-WSL2", wsl_reader=lambda _release: None)
    check(wsl.get("wsl") is True and wsl["gpu"].get("na") is True, "wsl gpu is n/a")
    check("errors" not in wsl or "gpu" not in wsl.get("errors", {}), "wsl drops the gpu error")
    plain_linux = {"gpu": {"present": False, "name": None}}
    apply_host_meta(plain_linux, "box", "linux", "6.8.0-arch1-1")
    check(plain_linux.get("wsl") is not True and plain_linux["gpu"].get("na") is not True, "linux keeps gpu absent")
    mac = {"gpu": {"present": True}, "temps": {"package_c": 40}, "errors": {"temps": "denied", "cpu": "no"}}
    apply_host_meta(mac, "host-a", "darwin", "24.5.0", mac_reader=lambda: None)
    check(mac["gpu"].get("na") is True and mac["temps"].get("na") is True, "darwin gpu and temps are n/a")
    check("temps" not in mac["errors"] and mac["errors"].get("cpu") == "no", "darwin keeps unrelated errors")

    dead_box = type("Box", (), {})()
    dead_box.iostat = LineChild(["true"])
    dead_box.iostat.dead = True
    dead_box.disk = {
        "io_bytes_per_s": 999,
        "device": "disk0",
        "root": "disk0",
        "rows": 4,
    }
    dead_box.netstat = LineChild(["true"])
    dead_box.netstat.dead = True
    dead_box.net = {
        "ifaces": {"en0": {"abs_rx": 10, "abs_tx": 4, "last_rx": 10, "last_tx": 4, "mode": "absolute"}},
        "rows": 3,
        "current": "en0",
    }
    dead_box.route_iface = "en0"
    dead_disk = publish_darwin_disk(dead_box, 1, 2)
    check(dead_disk["io_bytes_per_s"] is None, "dead iostat publishes null, not the last rate")
    check(dead_box.disk["io_bytes_per_s"] is None, "dead iostat clears the stored rate")
    check("t_ms" not in dead_disk, "the disk value itself is not restamped")
    dead_net = publish_darwin_net(dead_box)
    check(dead_net.get("na") is True and "ifaces" not in dead_net, "dead netstat is unavailable")
    check(dead_box.net.get("rows") == 0, "dead netstat drops the last counters")

    quick = None
    restarted = None
    try:
        quick = LineChild([sys.executable, "-c", "import time; time.sleep(0.05)"])
        quick.ensure()
        deadline = time.monotonic() + 3.0
        while quick.proc is not None and quick.proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        quick.drain()
        check(quick.dead is True, "exited helper is dead")
        check(quick.proc is None, "dead helper clears proc")
        check(quick.master is None, "dead helper clears master")
        held_until = quick.next_start
        quick.drain()
        check(quick.proc is None, "backoff does not restart the helper")
        check(quick.next_start == held_until, "backoff is not pushed while the helper stays dead")
        quick.next_start = 0
        quick.ensure()
        restarted = quick.proc
        check(restarted is not None and restarted.poll() is None, "helper restarts after the backoff")
        check(quick.fresh is True, "a restarted helper is a new sample generation")
    finally:
        if restarted is not None and restarted.poll() is None:
            try:
                os.kill(-restarted.pid, signal.SIGKILL)
            except OSError:
                try:
                    restarted.kill()
                except OSError:
                    pass
            try:
                restarted.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


    stubborn = LineChild([sys.executable, "-u", "-c",
                          "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"])
    stubborn.ensure()
    deadline = time.monotonic() + 3
    ready = False
    while time.monotonic() < deadline and not ready:
        ready = any(line.strip() == "ready" for line in stubborn.read_ready())
        if not ready:
            time.sleep(0.01)
    old_proc = stubborn.proc
    check(ready and old_proc is not None, "stubborn helper started")
    stubborn.stop()
    check(old_proc is not None and old_proc.returncode == -signal.SIGKILL, "stubborn helper killed and reaped")
    check(stubborn.master is None and stubborn not in _line_children and old_proc not in _child_procs,
          "stopped helper releases pty and tracking")


def collect_linux(include_procs):
    """Linux sample. Counter files are read before the monotonic stamp."""
    errors = {}
    sample = {"t_ms": int(time.time() * 1000)}
    texts = {}

    def slurp(name, path):
        try:
            texts[name] = read_text(path)
        except Exception as exc:  # noqa: BLE001
            texts[name] = None
            errors[name] = _error_text(exc, name)

    slurp("cpu", "/proc/stat")
    slurp("disk", "/proc/diskstats")
    slurp("net", "/proc/net/dev")
    sample["mono_ms"] = time.monotonic() * 1000.0

    if "cpu" in errors and texts.get("cpu") is None:
        sample["cpu"] = None
    else:
        take_sensor(sample, errors, "cpu", lambda: sensor_cpu(texts.get("cpu") or ""))
    take_sensor(sample, errors, "mem", sensor_mem)
    if "disk" in errors and texts.get("disk") is None:
        sample["disk"] = None
    else:
        take_sensor(sample, errors, "disk", lambda: sensor_disk(texts.get("disk") or ""))
    if "net" in errors and texts.get("net") is None:
        sample["net"] = None
    else:
        take_sensor(sample, errors, "net", lambda: sensor_net(texts.get("net") or ""))
    take_sensor(sample, errors, "gpu", gpu_sample)
    take_sensor(sample, errors, "temps", sensor_temps)
    try:
        battery, skip = battery_hot()
        if skip:
            sample["battery_skip"] = True
            sample["battery"] = None
        else:
            sample["battery"] = battery
    except Exception as exc:  # noqa: BLE001
        sample["battery"] = None
        errors["battery"] = _error_text(exc, "battery")
    if include_procs:
        take_sensor(sample, errors, "procs", sensor_procs)
    else:
        sample["procs"] = None
    if errors:
        sample["errors"] = errors
    return sample


# Transcript usage is indexed on each machine; only token counts leave it.
_USAGE_FIELDS = ('input', 'output', 'cache_read', 'cache_write_5m', 'cache_write_1h', 'cached_input')
_USAGE_LIMIT = 1024 * 1024 * 1024
_USAGE_LINE_LIMIT = 2 * 1024 * 1024
_USAGE_JSON_DEPTH_LIMIT = 128
_USAGE_CHECKPOINT_BYTES = 64 * 1024 * 1024
_USAGE_SEEN_LIMIT = 200000
_USAGE_INDEX_LIMIT = 64 * 1024 * 1024
_USAGE_FILE_LIMIT = 200000


def _usage_json_depth_ok(text):
    # Nesting cannot exceed the number of openers; count them cheaply in C.
    if text.count('[') + text.count('{') <= _USAGE_JSON_DEPTH_LIMIT:
        return True
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in '[{':
            depth += 1
            if depth > _USAGE_JSON_DEPTH_LIMIT:
                return False
        elif char in ']}':
            depth = max(0, depth - 1)
    return True


def _usage_hour(timestamp):
    try:
        value = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        value = value.astimezone(datetime.timezone.utc)
        return value.replace(minute=(value.minute // 15) * 15).strftime('%Y-%m-%dT%H:%M')
    except (AttributeError, ValueError, OverflowError):
        return None


def _usage_number(value):
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage_record(state, provider, data, seen, sessions, hours, counted_day):
    payload = data.get('payload') or {}
    if not isinstance(payload, dict):
        return
    if provider == 'codex':
        if data.get('type') == 'session_meta' and (payload.get('id') or payload.get('session_id')):
            session_id = str(payload.get('id') or payload['session_id'])
            parent_id = str(payload.get('forked_from_id') or '')
            state['session'] = session_id if len(session_id) <= 128 else ''
            state['forked_from_id'] = parent_id if len(parent_id) <= 128 else ''
        cursor = sessions.setdefault(state['path'], {})
        if data.get('type') in ('turn_context', 'session_meta'):
            if isinstance(payload.get('model'), str) and payload['model']:
                state['model'] = payload['model'][:64]
            return
        if data.get('type') != 'event_msg' or payload.get('type') != 'token_count':
            return
        info = payload.get('info') or {}
        totals = info.get('total_token_usage') if isinstance(info, dict) else None
        if not isinstance(totals, dict) or not _usage_hour(data.get('timestamp')):
            return
        keys = ('input_tokens', 'output_tokens', 'cached_input_tokens')
        current = {key: _usage_number(totals.get(key)) for key in keys}
        delta = {key: max(0, current[key] - cursor.get(key, 0)) for key in keys}
        sessions[state['path']] = {key: max(current[key], cursor.get(key, 0)) for key in keys}
        sessions[state['path']]['day'] = max(cursor.get('day', ''), _usage_hour(data.get('timestamp'))[:10])
        state['has_usage_cursor'] = True
        last = info.get('last_token_usage')
        last = last if isinstance(last, dict) else {}
        key = hashlib.sha1(json.dumps(['codex', sorted(totals.items()), sorted(last.items())]).encode()).hexdigest()[:12]
        if key in seen:
            return
        seen[key] = counted_day
        tokens = {'input': delta['input_tokens'], 'output': delta['output_tokens'], 'cached_input': delta['cached_input_tokens']}
        model = state.get('model') or 'unknown'
    else:
        message = data.get('message') or {}
        if data.get('type') != 'assistant' or not isinstance(message, dict) or not isinstance(message.get('usage'), dict):
            return
        hour = _usage_hour(data.get('timestamp'))
        if not hour:
            return
        ident = message.get('id')
        key = None
        if ident:
            key = hashlib.sha1(json.dumps([str(ident), str(data.get('requestId') or '')], separators=(',', ':')).encode()).hexdigest()[:12]
        usage = message['usage']
        creation = usage.get('cache_creation')
        if isinstance(creation, dict) and ('ephemeral_5m_input_tokens' in creation or 'ephemeral_1h_input_tokens' in creation):
            five = _usage_number(creation.get('ephemeral_5m_input_tokens'))
            hour_tokens = _usage_number(creation.get('ephemeral_1h_input_tokens'))
        else:
            five, hour_tokens = _usage_number(usage.get('cache_creation_input_tokens')), 0
        tokens = {'input': _usage_number(usage.get('input_tokens')), 'output': _usage_number(usage.get('output_tokens')),
                  'cache_read': _usage_number(usage.get('cache_read_input_tokens')), 'cache_write_5m': five, 'cache_write_1h': hour_tokens}
        model = message.get('model') or 'unknown'
        if key:
            previous = seen.get(key)
            counted = dict(zip(_USAGE_FIELDS[:5], previous[1:])) if isinstance(previous, list) else {}
            maximum = {field: max(count, counted.get(field, 0)) for field, count in tokens.items()}
            tokens = {field: maximum[field] - counted.get(field, 0) for field in tokens}
            if any(tokens.values()):
                seen[key] = [counted_day] + [maximum[field] for field in _USAGE_FIELDS[:5]]
    hour = _usage_hour(data.get('timestamp'))
    if not hour or not any(tokens.values()):
        return
    target = hours.setdefault(hour, {}).setdefault(provider + '/' + str(model)[:64], {})
    for field, count in tokens.items():
        target[field] = target.get(field, 0) + count


def _usage_empty():
    return {'version': 8, 'files': {}, 'seen': {}, 'sessions': {}, 'hours': {}}


def _usage_seen_day(value):
    if isinstance(value, dict): return value.get('day', '')
    if isinstance(value, list): return value[0] if value else ''
    return value


def _usage_write(path, index):
    if os.path.islink(path):
        raise ValueError('usage index is a symbolic link')
    encoded = json.dumps(index, separators=(',', ':')).encode()
    evicted = False
    if len(encoded) > _USAGE_INDEX_LIMIT and index['seen']:
        index['dedupe_evicted_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        encoded = json.dumps(index, separators=(',', ':')).encode()
        excess = len(encoded) - _USAGE_INDEX_LIMIT
        for key, value in sorted(index['seen'].items(), key=lambda item: _usage_seen_day(item[1])):
            excess -= len(json.dumps(key).encode()) + len(json.dumps(value, separators=(',', ':')).encode()) + (2 if len(index['seen']) > 1 else 1)
            del index['seen'][key]
            evicted = True
            if excess <= 0:
                break
        encoded = json.dumps(index, separators=(',', ':')).encode()
    reset = len(encoded) > _USAGE_INDEX_LIMIT
    if reset:
        empty = _usage_empty()
        if evicted:
            empty['dedupe_evicted_at'] = index['dedupe_evicted_at']
        encoded = json.dumps(empty, separators=(',', ':')).encode()
        if len(encoded) > _USAGE_INDEX_LIMIT:
            raise ValueError('empty usage index exceeds limit')
    fd, tmp = tempfile.mkstemp(prefix='.usage-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        if os.path.islink(path):
            raise ValueError('usage index is a symbolic link')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return 'reset' if reset else 'evicted' if evicted else 'ok'


def _usage_int(value, maximum=(1 << 63) - 1):
    return type(value) is int and 0 <= value <= maximum


def _usage_valid_cursor(value):
    return (isinstance(value, dict) and isinstance(value.get('day', ''), str) and
            all(_usage_int(value.get(k, 0)) for k in ('input_tokens', 'output_tokens', 'cached_input_tokens')))


def usage_scan(home=None, cache=None, limit=_USAGE_LIMIT, now=None):
    """Incrementally scan recent transcripts and checkpoint consistent cursors."""
    home = os.path.expanduser('~') if home is None else str(home)
    cache = cache or os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.join(home, '.cache'), 'mainframe')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    utc_now = now.astimezone(datetime.timezone.utc)
    cutoff = (utc_now.date() - datetime.timedelta(days=34)).isoformat()
    skip_cutoff = (utc_now.date() - datetime.timedelta(days=29)).isoformat()
    os.makedirs(cache, mode=0o700, exist_ok=True)
    path = os.path.join(cache, 'usage-index.json')
    if os.path.islink(path):
        raise ValueError('usage index is a symbolic link')
    index = _usage_empty()
    dirty = False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('index is not a regular file')
            if info.st_size > _USAGE_INDEX_LIMIT:
                raise ValueError('oversized index')
            text = stream.read().decode('utf-8-sig')
            if not _usage_json_depth_ok(text):
                raise ValueError('index nesting too deep')
            loaded = json.loads(text)
        if (not isinstance(loaded, dict) or loaded.get('version') != 8 or
                any(not isinstance(loaded.get(k), dict) for k in ('files', 'seen', 'sessions', 'hours')) or
                any(not _usage_valid_cursor(value) for value in loaded['sessions'].values()) or
                any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:(00|15|30|45)', k) or
                    not isinstance(models, dict) or any(not isinstance(counts, dict) or
                    any(type(value) is not int or value < 0 for value in counts.values()) for counts in models.values())
                    for k, models in loaded['hours'].items())):
            raise ValueError('invalid index')
        index = loaded
    except FileNotFoundError:
        pass
    except (ValueError, TypeError, OSError, RecursionError, MemoryError, UnicodeError):
        if os.path.islink(path):
            raise ValueError('usage index is a symbolic link')
        dirty = True
    hours = {k: v for k, v in index['hours'].items() if k[:10] >= cutoff}
    if len(hours) != len(index['hours']):
        index['hours'] = hours
        dirty = True
    seen = {}
    for key, value in index['seen'].items():
        day = _usage_seen_day(value)
        if not isinstance(day, str) or day < cutoff:
            continue
        if isinstance(value, dict):
            tokens = value.get('tokens')
            if not isinstance(tokens, dict) or not all(k in _USAGE_FIELDS[:5] and _usage_int(n) for k, n in tokens.items()):
                continue
            value = [day] + [tokens.get(field, 0) for field in _USAGE_FIELDS[:5]]
            dirty = True
        if isinstance(value, str) or (isinstance(value, list) and len(value) == 6 and all(_usage_int(n) for n in value[1:])):
            seen[key] = value
    if len(seen) != len(index['seen']) or dirty:
        index['seen'] = seen
        dirty = True
    evicted_at = index.get('dedupe_evicted_at', '')
    dedupe_full = isinstance(evicted_at, str) and len(evicted_at) >= 10 and evicted_at[:10] >= skip_cutoff
    if len(index['seen']) * 10 > _USAGE_SEEN_LIMIT * 11:
        index['seen'] = dict(sorted(index['seen'].items(), key=lambda item: _usage_seen_day(item[1]))[-_USAGE_SEEN_LIMIT:]) if _USAGE_SEEN_LIMIT else {}
        index['dedupe_evicted_at'] = utc_now.isoformat()
        dedupe_full = dirty = True
    files = index['files']
    for entry in files.values():
        if isinstance(entry, dict) and 'header_scan' in entry:
            del entry['header_scan']
            dirty = True
    skipped = 0
    roots = [('claude', os.path.join(home, '.claude', 'projects'))]
    roots += [('claude', p) for p in sorted(glob.glob(os.path.join(home, '.claude-accounts', '*', 'projects')))]
    if os.environ.get('CLAUDE_CONFIG_DIR'):
        roots.append(('claude', os.path.join(os.environ['CLAUDE_CONFIG_DIR'], 'projects')))
    roots.append(('claude', os.path.join(home, '.config', 'claude', 'projects')))
    roots.append(('codex', os.path.join(home, '.codex', 'sessions')))
    if os.environ.get('CODEX_HOME'):
        roots.append(('codex', os.path.join(os.environ['CODEX_HOME'], 'sessions')))
    root_paths, candidates, present = set(), [], set()
    entry_count, too_many_files = 0, False
    for provider, root in roots:
        try:
            os.lstat(root)
            real_root = os.path.realpath(root)
            if real_root in root_paths:
                continue
            root_paths.add(real_root)
        except FileNotFoundError:
            continue
        except OSError:
            skipped += 1
            continue
        directories = [root]
        while directories and not too_many_files:
            directory = directories.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry_count >= _USAGE_FILE_LIMIT:
                            too_many_files = True
                            break
                        entry_count += 1
                        if entry.is_dir(follow_symlinks=False):
                            directories.append(entry.path)
                        elif entry.name.endswith('.jsonl'):
                            file = os.path.realpath(entry.path)
                            present.add(file)
                            try:
                                info = os.stat(file)
                                if not stat.S_ISREG(info.st_mode):
                                    present.discard(file)
                                elif info.st_mtime >= now.timestamp() - 31 * 86400:
                                    candidates.append((provider, file, info))
                                else:
                                    present.discard(file)
                            except OSError:
                                skipped += 1
            except OSError:
                skipped += 1
        if too_many_files:
            break
    candidates.sort(key=lambda item: item[1])
    if not skipped and not too_many_files:
        for file in list(files):
            if file not in present:
                del files[file]
                dirty = True
    invalid_sessions = {k for k, v in index['sessions'].items() if not _usage_valid_cursor(v)}
    sessions = {k: v for k, v in index['sessions'].items() if k in files and k not in invalid_sessions and v.get('day', '') >= cutoff}
    if len(sessions) != len(index['sessions']):
        index['sessions'] = sessions
        dirty = True
    read_bytes, checkpoint_bytes, limited = 0, 0, False
    checkpoint_at = time.monotonic()
    write_failed, reset_index = False, False
    def write_checkpoint():
        nonlocal dirty, checkpoint_bytes, checkpoint_at, write_failed, reset_index, dedupe_full
        if not dirty or write_failed or reset_index:
            return
        try:
            result = _usage_write(path, index)
            dedupe_full |= result == 'evicted'
            reset_index = result == 'reset'
            dirty = False
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            write_failed = True
        checkpoint_bytes = 0
        checkpoint_at = time.monotonic()

    def validate_previous(previous, provider, file, info):
        pending = tail = b''
        valid = isinstance(previous, dict) and previous.get('provider') == provider
        valid = valid and all(_usage_int(previous.get(k)) for k in ('offset', 'size', 'mtime_ns', 'ino', 'dev', 'head_len'))
        valid = valid and previous['head_len'] <= 4096 and previous['offset'] <= info.st_size and previous['offset'] <= previous['size']
        valid = valid and isinstance(previous.get('pending'), str) and len(previous.get('pending', '')) <= ((_USAGE_LINE_LIMIT + 2) // 3) * 4
        valid = valid and previous.get('path') == file and isinstance(previous.get('head'), str)
        valid = valid and previous['head_len'] <= previous['size']
        valid = valid and isinstance(previous.get('session'), str) and len(previous['session']) <= 128 and file not in invalid_sessions
        valid = valid and isinstance(previous.get('forked_from_id'), str) and len(previous['forked_from_id']) <= 128
        valid = valid and type(previous.get('has_usage_cursor')) is bool
        valid = valid and (provider != 'codex' or not previous['offset'] or not previous.get('has_usage_cursor') or file in index['sessions'])
        valid = valid and isinstance(previous.get('model'), str) and type(previous.get('skip_line')) is bool
        valid = valid and type(previous.get('skip_mark')) is bool and isinstance(previous.get('skip_tail'), str) and len(previous.get('skip_tail', '')) <= ((65536 + 2) // 3) * 4
        skip_days = previous.get('skip_days') if valid else {}
        valid = valid and isinstance(skip_days, dict) and all(isinstance(k, str) and _usage_int(v) for k, v in skip_days.items())
        if valid:
            try:
                pending = base64.b64decode(previous.get('pending', ''), validate=True)
                tail = base64.b64decode(previous.get('skip_tail', ''), validate=True)
                valid = len(pending) <= _USAGE_LINE_LIMIT and len(tail) <= 65536
            except (ValueError, TypeError):
                valid = False
        return valid, pending, tail

    for provider, file, info in candidates:
        previous = files.get(file, {})
        valid, _, _ = validate_previous(previous, provider, file, info)
        if (valid and previous['offset'] == info.st_size and previous['size'] == info.st_size and
                previous['mtime_ns'] == info.st_mtime_ns and previous['ino'] == info.st_ino and previous['dev'] == info.st_dev):
            continue
        try:
            fd = os.open(file, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                stat_info = os.fstat(stream.fileno())
                if not stat.S_ISREG(stat_info.st_mode):
                    continue
                info = stat_info
                previous = files.get(file, {})
                valid, pending, tail = validate_previous(previous, provider, file, info)
                unchanged = (valid and previous['size'] == info.st_size and previous['mtime_ns'] == info.st_mtime_ns and
                             previous['ino'] == info.st_ino and previous['dev'] == info.st_dev)
                if unchanged:
                    head = previous['head']
                    head_len = previous['head_len']
                    reset_cursor = False
                else:
                    stream.seek(0)
                    if valid:
                        if read_bytes >= limit:
                            limited = True
                            break
                        old_head_data = stream.read(previous['head_len'])
                        read_bytes += len(old_head_data)
                    else:
                        old_head_data = b''
                    old_head = hashlib.sha1(old_head_data).hexdigest()
                    stream.seek(0)
                    if read_bytes >= limit:
                        limited = True
                        break
                    head_data = stream.read(4096)
                    read_bytes += len(head_data)
                    head = hashlib.sha1(head_data).hexdigest()
                    reset_cursor = (not valid or info.st_size < previous['size'] or info.st_mtime_ns < previous['mtime_ns'] or
                                    previous['ino'] != info.st_ino or previous['dev'] != info.st_dev or previous.get('head') != old_head)
                    head_len = len(head_data)
                if reset_cursor:
                    previous = {'provider': provider, 'path': file, 'offset': 0, 'skip_days': {},
                                'session': '', 'forked_from_id': '', 'model': '', 'has_usage_cursor': False,
                                'skip_line': False, 'skip_mark': False}
                    pending = b''
                    tail = b''
                state = copy.deepcopy(previous)
                state['skip_days'] = {k: v for k, v in state.get('skip_days', {}).items() if k >= skip_cutoff}
                stream.seek(state['offset'])
                staged_seen, staged_hours = {}, {}
                class Seen:
                    def __contains__(self, key): return key in index['seen'] or key in staged_seen
                    def __setitem__(self, key, value): staged_seen[key] = value
                    def get(self, key, default=None): return staged_seen.get(key, index['seen'].get(key, default))
                class Sessions(dict):
                    def setdefault(self, key, default):
                        if key not in self: self[key] = copy.deepcopy(default if reset_cursor else index['sessions'].get(key, default))
                        return self[key]
                staged_sessions = Sessions()
                def commit():
                    nonlocal staged_seen, staged_sessions, staged_hours, dirty, dedupe_full, reset_cursor
                    state['offset'] = stream.tell()
                    state['pending'] = base64.b64encode(pending).decode('ascii')
                    state['skip_tail'] = base64.b64encode(tail).decode('ascii')
                    state.update(size=info.st_size, mtime_ns=info.st_mtime_ns, ino=info.st_ino, dev=info.st_dev,
                                 head=head, head_len=head_len)
                    if files.get(file) != state or staged_seen or staged_sessions or staged_hours:
                        dirty = True
                    files[file] = copy.deepcopy(state)
                    index['seen'].update(staged_seen)
                    if len(index['seen']) * 10 > _USAGE_SEEN_LIMIT * 11:
                        dedupe_full = True
                        index['dedupe_evicted_at'] = utc_now.isoformat()
                        index['seen'] = dict(sorted(index['seen'].items(), key=lambda item: _usage_seen_day(item[1]))[-_USAGE_SEEN_LIMIT:]) if _USAGE_SEEN_LIMIT else {}
                    if reset_cursor and file in index['sessions']:
                        del index['sessions'][file]
                        dirty = True
                    index['sessions'].update(staged_sessions)
                    reset_cursor = False
                    for hour, models in staged_hours.items():
                        if hour[:10] < cutoff: continue
                        for model, counts in models.items():
                            target = index['hours'].setdefault(hour, {}).setdefault(model, {})
                            for field, count in counts.items(): target[field] = target.get(field, 0) + count
                    staged_seen, staged_sessions, staged_hours = {}, Sessions(), {}
                while stream.tell() < info.st_size:
                    remaining = min(limit - read_bytes, _USAGE_CHECKPOINT_BYTES - checkpoint_bytes,
                                    info.st_size - stream.tell())
                    if remaining <= 0:
                        if read_bytes >= limit:
                            limited = True
                            break
                        commit(); write_checkpoint()
                        if write_failed or reset_index: break
                        continue
                    chunk = stream.readline(min(remaining, _USAGE_LINE_LIMIT + 1))
                    if not chunk:
                        skipped += 1
                        break
                    read_bytes += len(chunk)
                    checkpoint_bytes += len(chunk)
                    if state.get('skip_line'):
                        tail = (tail + chunk)[-65536:]
                        if chunk.endswith(b'\n'):
                            if not state.get('skip_mark') and (b'"usage"' in tail or b'token_count' in tail):
                                day = utc_now.date().isoformat()
                                state['skip_days'][day] = state['skip_days'].get(day, 0) + 1
                            state['skip_line'] = state['skip_mark'] = False
                            tail = b''
                    else:
                        pending += chunk
                        if len(pending) > _USAGE_LINE_LIMIT:
                            prefix = pending[:65536]
                            tail = pending[-65536:]
                            state['skip_mark'] = b'"usage"' in prefix or b'token_count' in prefix
                            if state['skip_mark'] or (chunk.endswith(b'\n') and (b'"usage"' in tail or b'token_count' in tail)):
                                day = utc_now.date().isoformat()
                                state['skip_days'][day] = state['skip_days'].get(day, 0) + 1
                            pending = b''
                            state['skip_line'] = not chunk.endswith(b'\n')
                            if not state['skip_line']:
                                state['skip_mark'], tail = False, b''
                        elif chunk.endswith(b'\n'):
                            if (b'"usage"' in pending or b'token_count' in pending or
                                    (provider == 'codex' and any(x in pending for x in (b'turn_context', b'session_meta')))):
                                try:
                                    text = pending.decode('utf-8-sig')
                                    if not _usage_json_depth_ok(text):
                                        raise ValueError('usage nesting too deep')
                                    data = json.loads(text)
                                    if isinstance(data, dict): _usage_record(state, provider, data, Seen(), staged_sessions, staged_hours, utc_now.date().isoformat())
                                except (ValueError, UnicodeError, TypeError, RecursionError):
                                    if b'"usage"' in pending or b'token_count' in pending:
                                        day = utc_now.date().isoformat()
                                        state['skip_days'][day] = state['skip_days'].get(day, 0) + 1
                            pending = b''
                    if checkpoint_bytes >= _USAGE_CHECKPOINT_BYTES or time.monotonic() - checkpoint_at >= 30:
                        commit(); write_checkpoint()
                        if write_failed or reset_index: break
                if not write_failed and not reset_index:
                    commit()
                    if time.monotonic() - checkpoint_at >= 30:
                        write_checkpoint()
        except (OSError, ValueError, TypeError, OverflowError):
            skipped += 1
        if limited or write_failed or reset_index:
            break
    skipped += sum(sum(v for k, v in state.get('skip_days', {}).items() if k >= skip_cutoff) for state in files.values() if isinstance(state, dict) and isinstance(state.get('skip_days', {}), dict) and all(isinstance(k, str) and _usage_int(v) for k, v in state.get('skip_days', {}).items()))
    write_checkpoint()
    model_names, bounded_hours = set(), {}
    for hour, models in index['hours'].items():
        for key, counts in models.items():
            provider, _, model = key.partition('/')
            if model != 'other' and model not in model_names:
                if len(model_names) < 24:
                    model_names.add(model)
                else:
                    model = 'other'
            target = bounded_hours.setdefault(hour, {}).setdefault(provider + '/' + model, {})
            for field, count in counts.items():
                target[field] = target.get(field, 0) + count
    result = {'days': bounded_hours, 'partial': bool(skipped or limited or write_failed or reset_index or dedupe_full or too_many_files), 'skipped': skipped, 'scanned_at': utc_now.isoformat()}
    if too_many_files: result['reason'] = 'too many files'
    elif dedupe_full: result['reason'] = 'dedupe window full'
    elif write_failed: result['reason'] = 'index write failed'
    elif reset_index: result['reason'] = 'index too large'
    return result


def usage_probe():
    source = globals().get('_SCRIPT_SOURCE')
    if source is None:
        with open(__file__, encoding='utf-8') as stream:
            source = stream.read()
    command = [sys.executable, '-u', '-', '--usage-scan']
    if sys.platform.startswith('linux') and shutil.which('ionice'):
        command = ['ionice', '-c', '3'] + command
    result = _run_tracked(command, timeout=570, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, input=source)
    return json.loads(result)


# Each rule names one CLI and its interpreter package entry points.
AGENT_RULES = [
    {'provider': 'claude', 'names': ('claude',), 'package': 'node_modules/@anthropic-ai/claude-code/'},
    {'provider': 'codex', 'names': ('codex',), 'package': 'node_modules/@openai/codex/'},
    {'provider': 'gemini', 'names': ('gemini',), 'package': 'node_modules/@google/gemini-cli/'},
    {'provider': 'qwen', 'names': ('qwen', 'qwen-code'), 'package': 'node_modules/@qwen-code/qwen-code/'},
    {'provider': 'grok', 'names': ('grok',), 'scripts': ('grok',)},
    {'provider': 'cursor-agent', 'names': ('cursor-agent',), 'scripts': ('cursor-agent',)},
    {'provider': 'opencode', 'names': ('opencode',), 'scripts': ('opencode',)},
    {'provider': 'aider', 'names': ('aider',), 'scripts': ('aider',)},
    {'provider': 'crush', 'names': ('crush',), 'scripts': ('crush',)},
]
_AGENT_INTERPRETERS = {'node', 'nodejs', 'bun', 'deno', 'python'}
_AGENT_SHELLS = {'sh', 'bash', 'dash', 'zsh'}


def _agent_interpreter(name):
    return name in _AGENT_INTERPRETERS or bool(re.fullmatch(r'python3(?:\.\d+)?', name))
_AGENT_KEYS = {'claude': (b'ANTHROPIC_API_KEY', b'ANTHROPIC_AUTH_TOKEN'),
               'codex': (b'OPENAI_API_KEY', b'CODEX_API_KEY'),
               'gemini': (b'GEMINI_API_KEY', b'GOOGLE_API_KEY'), 'grok': (b'XAI_API_KEY',),
               'qwen': (b'OPENAI_API_KEY', b'DASHSCOPE_API_KEY', b'QWEN_API_KEY')}
_AGENT_MULTI_KEYS = (b'ANTHROPIC_API_KEY', b'OPENAI_API_KEY', b'GEMINI_API_KEY',
                     b'GOOGLE_API_KEY', b'XAI_API_KEY', b'OPENROUTER_API_KEY')
for _provider in ('aider', 'opencode', 'crush'):
    _AGENT_KEYS[_provider] = _AGENT_MULTI_KEYS
_AGENT_DIRS = {'claude': (b'CLAUDE_CONFIG_DIR', '.claude'), 'codex': (b'CODEX_HOME', '.codex')}


def _agent_match(comm, argv, executable='', raw_args=''):
    if not argv:
        return None
    exe = os.path.basename(argv[0])
    executable_name = os.path.basename(executable)
    executable_lower = executable.lower()
    if (os.path.basename(executable_lower) == 'electron' or '/electron' in executable_lower or
            'claude-desktop' in executable_lower or '.app/contents/macos/' in executable_lower):
        return None
    if '.app/contents/' in argv[0].lower():
        return None
    if comm == 'codex-linux-sandbox' or exe == 'codex-linux-sandbox':
        return None
    interpreter = _agent_interpreter(comm) or _agent_interpreter(exe) or _agent_interpreter(executable_name)
    shell = exe in _AGENT_SHELLS
    python = any(name.startswith('python') for name in (comm, exe, executable_name))
    node = any(name in ('node', 'nodejs') for name in (comm, exe, executable_name))
    operands = {'-W', '-X'} if python else ({'-r', '--require', '--import', '--loader', '--experimental-loader'} if node else set())
    claude_operands = {'-p', '--print', '--mcp-config', '--model', '--settings', '--system-prompt',
                       '--append-system-prompt', '--permission-mode', '--output-format', '--input-format',
                       '--allowed-tools', '--disallowed-tools', '--add-dir', '--agent', '--resume'}
    i = 1
    while i < len(argv) and argv[i].startswith('-'):
        if argv[i].startswith('--type='):
            return None
        if argv[i] in operands or argv[i] in claude_operands:
            if i + 1 < len(argv) and not argv[i + 1].startswith('-'):
                break
            i += 2
        else:
            i += 1
    rule_match, script_index = None, 0
    if interpreter:
        if len(argv) == 1:
            rule_match = next((r for r in AGENT_RULES if argv[0] in r['names']), None)
        i = 1
        subcommand = False
        while i < len(argv):
            arg = argv[i]
            if arg in ('-c', '-e', '--eval', '-p', '--print'):
                return None
            if arg in operands:
                i += 2
                continue
            if python and arg == '-m':
                if i + 1 < len(argv) and argv[i + 1] == 'aider':
                    rule_match, script_index = next(r for r in AGENT_RULES if r['provider'] == 'aider'), i + 1
                break
            if arg.startswith('-'):
                i += 1
                continue
            if not subcommand and ((comm == 'bun' or exe == 'bun') and arg in ('run', 'x') or
                                   (comm == 'deno' or exe == 'deno') and arg == 'run'):
                subcommand = True
                i += 1
                continue
            path = arg.replace('\\', '/')
            if 'mcp-server' in path or 'mcp_server' in path:
                return None
            rule_match = next((r for r in AGENT_RULES if os.path.basename(path) in r.get('scripts', r['names']) or
                               (r.get('package') and '/' + r['package'] in '/' + path) or
                               (r['provider'] == 'cursor-agent' and '/cursor-agent/' in path)), None)
            if not rule_match and raw_args:
                span = arg
                if not os.path.splitext(arg)[1]:
                    candidate = arg
                    for fragment in argv[i + 1:]:
                        if fragment.startswith(('/', '-')):
                            break
                        candidate += ' ' + fragment
                        if re.search(r'\.(?:mjs|cjs|js)$', fragment):
                            span = candidate
                            break
                rule_match = next((r for r in AGENT_RULES if
                                   (r.get('package') and '/' + r['package'] in span) or
                                   (r['provider'] == 'cursor-agent' and '/cursor-agent/' in span)), None)
            script_index = i
            break
        if not rule_match:
            return None
    if shell and not interpreter and len(argv) > 1:
        rule_match = next((r for r in AGENT_RULES if os.path.basename(argv[1]) in r['names']), None)
        if rule_match:
            script_index = 1
    args = argv[script_index + 1:] if script_index else argv[1:]
    if args and all(arg in ('--version', '-v', '-V', 'version', '--help', '-h', 'help') for arg in args):
        return None
    for rule in AGENT_RULES:
        matched = not interpreter and (comm in rule['names'] or exe in rule['names'] or rule is rule_match)
        if interpreter:
            matched = rule is rule_match
        if matched:
            if rule['provider'] == 'claude':
                options_and_args = []
                i = 0
                while i < len(args):
                    options_and_args.append(args[i])
                    if args[i] in claude_operands and i + 1 < len(args):
                        options_and_args.append(None)
                        i += 2
                    else:
                        i += 1
                if any(arg in ('--claude-in-chrome-mcp', '--chrome-native-host') for arg in options_and_args):
                    return None
                if any(options_and_args[i] == 'mcp' and options_and_args[i + 1] == 'serve'
                       for i in range(len(options_and_args) - 1)):
                    return None
                i = 0
                while i < len(args) and args[i].startswith('-'):
                    i += 2 if args[i] in claude_operands else 1
                if i < len(args) and args[i] in ('mcp', 'daemon'):
                    return None
            elif any(arg in ('mcp-server', 'mcp_server') for arg in args):
                return None
            elif any(args[i] == 'mcp' and args[i + 1] in ('serve', 'server') for i in range(len(args) - 1)):
                return None
            if rule['provider'] == 'codex':
                if '/app-server-daemon/' in executable or '/app-server-daemon/' in argv[0] or any(arg in ('app-server', 'app-server-daemon') for arg in argv):
                    return None
            return rule['provider']
    return None


def _agent_environment(path, provider, home):
    try:
        with open(path, 'rb') as source:
            raw = source.read()
    except OSError:
        return None, None
    wanted = set(_AGENT_KEYS.get(provider, ()))
    directory = _AGENT_DIRS.get(provider)
    if directory:
        wanted.add(directory[0])
    values = {}
    for entry in raw.split(b'\0'):
        key, sep, value = entry.partition(b'=')
        if sep and key in wanted:
            values[key] = value
    billing = 'api' if any(values.get(key) for key in _AGENT_KEYS.get(provider, ())) else None
    result = None
    if directory:
        value = (values.get(directory[0]) or b'').decode('utf-8', 'replace')
        path = os.path.normpath(os.path.expanduser(value)) if value else os.path.join(home, directory[1])
        if os.path.isabs(path):
            home = os.path.normpath(home)
            result = '~' + path[len(home):] if path == home or path.startswith(home.rstrip('/') + '/') else path
            result = result.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')
            if len(result) > 200:
                result = None
    return result, billing


def _agent_finish(processes, now):
    matched = {pid: row for pid, row in processes.items() if row.get('provider')}
    counted = {pid: row for pid, row in matched.items()
               if row['ppid'] not in matched or matched[row['ppid']]['provider'] != row['provider']}
    sessions = []
    for pid, row in sorted(counted.items()):
        parent, seen = row['ppid'], {pid}
        while parent in processes and parent not in seen and parent not in counted:
            seen.add(parent)
            parent = processes[parent]['ppid']
        session = {key: row.get(key) for key in ('pid', 'provider', 'interactive', 'dir', 'billing', 'project', 'age_s', 'rss')}
        session['parent_pid'] = parent if parent in counted and parent not in seen else None
        sessions.append(session)
    return {'at': int(now), 'sessions': sessions[:256], 'truncated': len(sessions) > 256, 'supported': True}


def _agent_linux(proc_root, home, now):
    processes = {}
    try:
        own_namespace = os.readlink(os.path.join(proc_root, 'self', 'ns', 'pid'))
    except OSError:
        own_namespace = None
    with open(os.path.join(proc_root, 'uptime'), encoding='ascii') as source:
        uptime = float(source.read().split()[0])
    ticks, page = os.sysconf('SC_CLK_TCK'), os.sysconf('SC_PAGE_SIZE')
    candidates = {name for rule in AGENT_RULES for name in rule['names']} | _AGENT_INTERPRETERS | _AGENT_SHELLS
    with os.scandir(proc_root) as entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                with open(os.path.join(entry.path, 'stat'), encoding='utf-8', errors='replace') as source:
                    statline = source.read()
                start, end = statline.find('('), statline.rfind(')')
                comm, fields = statline[start + 1:end], statline[end + 2:].split()
                pid, ppid = int(entry.name), int(fields[1])
                row = {'pid': pid, 'ppid': ppid}
                processes[pid] = row
                if own_namespace is not None:
                    try:
                        if os.readlink(os.path.join(entry.path, 'ns', 'pid')) != own_namespace:
                            continue
                    except OSError:
                        pass
                # Some native launchers resolve to version-named binaries.
                if comm not in candidates and not _agent_interpreter(comm) and not generic_thread_name(comm) and not (comm.startswith('node-') and generic_thread_name(comm[5:])) and not re.fullmatch(r'\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*', comm):
                    continue
                try:
                    with open(os.path.join(entry.path, 'cmdline'), 'rb') as source:
                        argv = [os.fsdecode(x) for x in source.read().split(b'\0') if x]
                except OSError:
                    argv = [comm] if not _agent_interpreter(comm) else []
                try:
                    executable = os.readlink(os.path.join(entry.path, 'exe'))
                except OSError:
                    executable = ''
                provider = _agent_match(comm, argv, executable)
                if not provider:
                    continue
                row.update(provider=provider, age_s=max(0, int(uptime - int(fields[19]) / ticks)), rss=max(0, int(fields[21]) * page))
                try:
                    tty = os.readlink(os.path.join(entry.path, 'fd', '0'))
                    row['interactive'] = tty.startswith('/dev/pts/') or tty.startswith('/dev/tty')
                except OSError:
                    row['interactive'] = None
                try:
                    cwd = os.readlink(os.path.join(entry.path, 'cwd'))
                    row['project'] = os.path.basename(cwd.rstrip('/')).encode('utf-8', 'surrogateescape').decode('utf-8', 'replace') or None
                except OSError:
                    row['project'] = None
                try:
                    owned = entry.stat().st_uid == os.getuid()
                except OSError:
                    owned = False
                row['dir'], row['billing'] = _agent_environment(os.path.join(entry.path, 'environ'), provider, home) if owned else (None, None)
            except (OSError, ValueError, IndexError):
                continue
    return _agent_finish(processes, now)


def _agent_elapsed(value):
    try:
        days, sep, rest = value.partition('-')
        if not sep:
            rest, days = days, '0'
        parts = [int(part) for part in rest.split(':')]
        if len(parts) not in (2, 3):
            return None
        return int(days) * 86400 + sum(part * 60 ** i for i, part in enumerate(reversed(parts)))
    except ValueError:
        return None


def _agent_darwin(text, args_text, now):
    processes = {}
    arguments = {}
    for line in args_text.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0].isdigit():
            arguments[int(fields[0])] = fields[1]
    for line in text.splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        try:
            pid, ppid, tty, elapsed, rss, comm = fields
            pid, ppid = int(pid), int(ppid)
            row = {'pid': pid, 'ppid': ppid}
            processes[pid] = row
            raw_args = arguments.get(pid, '')
            argv = raw_args.split() or [comm]
            provider = _agent_match(os.path.basename(comm), argv, comm, raw_args)
            if not provider and ' ' in comm and argv[0] != comm and not _agent_interpreter(os.path.basename(comm)):
                provider = _agent_match(os.path.basename(comm), [comm], comm)
            if provider:
                row.update(provider=provider, interactive=tty != '??', dir=None, billing=None, project=None,
                           age_s=_agent_elapsed(elapsed), rss=max(0, int(rss) * 1024))
        except (ValueError, IndexError):
            continue
    return _agent_finish(processes, now)


def agents_probe(proc_root='/proc', home=None, platform=None):
    now = time.time()
    failure = {'at': int(now), 'sessions': [], 'truncated': False, 'supported': False}
    if os.environ.get('MAINFRAME_AGENTS_SCAN') == '0':
        return failure
    try:
        platform = platform or sys.platform
        if platform.startswith('linux'):
            return _agent_linux(proc_root, home or os.path.expanduser('~'), now)
        if platform == 'darwin':
            output = _run_tracked(['ps', '-ww', '-axo', 'pid=,ppid=,tty=,etime=,rss=,ucomm='], 4, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
            args = _run_tracked(['ps', '-axww', '-o', 'pid=,args='], 4, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
            return _agent_darwin(output, args, now) if output and args and output.strip() and args.strip() else failure
    except Exception:
        return failure
    return failure


# Slow host probes run independently of the one-second sampling clock.
_probe = {"windows": None, "storage": [], "windows_at": 0.0, "storage_at": 0.0,
          "windows_busy": False, "storage_busy": False, "usage": None, "usage_at": 0.0, "usage_busy": False,
          "usage_snapshot": (None, 0), "usage_generation": 0, "agents_live": None, "agents_live_at": 0.0, "agents_live_busy": False}
_probe_started = time.monotonic()
_PS_QUERY = r"""$o=Get-CimInstance Win32_OperatingSystem; $p=Get-CimInstance Win32_Processor; $d=Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'; @{total=$o.TotalVisibleMemorySize;free=$o.FreePhysicalMemory;cpu=@($p | ForEach-Object {$_.LoadPercentage});disks=@($d | ForEach-Object {@{name=$_.DeviceID;size=$_.Size;free=$_.FreeSpace}})} | ConvertTo-Json -Compress -Depth 4"""


def parse_windows(text):
    try:
        data = json.loads(text.lstrip('\ufeff').strip())
        total, free = int(data['total']) * 1024, int(data['free']) * 1024
        if total <= 0 or free < 0 or free > total:
            return None
        cpus = [float(x) for x in data.get('cpu', []) if x is not None and 0 <= float(x) <= 100]
        disks = []
        for d in data.get('disks', []):
            size, avail = int(d['size']), int(d['free'])
            if size > 0 and 0 <= avail <= size:
                disks.append({'device': str(d['name']), 'mount': str(d['name']), 'total': size, 'used': size - avail})
        return {'total': total, 'used': total - free, 'cpu': sum(cpus) / len(cpus) if cpus else None, 'disks': disks}
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def windows_probe():
    exe = shutil.which('powershell.exe')
    if not exe:
        suffix = 'Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        candidates = ['/mnt/c/' + suffix] + sorted(glob.glob('/mnt/[a-zA-Z]/' + suffix))
        exe = next((path for path in candidates if os.path.isfile(path)), None)
    if not exe:
        return None
    try:
        result = _run_tracked([exe, '-NoProfile', '-NonInteractive', '-Command', _PS_QUERY],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        return parse_windows(result.decode('utf-8-sig', 'replace').replace('\x00', ''))
    except (OSError, subprocess.SubprocessError):
        return None


_network_mount_timeouts = set()
_network_mount_probes = {}
_network_mount_lock = threading.Lock()


def _network_statvfs(mount, stat_fn):
    with _network_mount_lock:
        previous = _network_mount_probes.get(mount)
        if previous and (previous[0].is_alive() or time.monotonic() - previous[1] < 600):
            return None
        outcome = []
        def probe():
            try:
                outcome.append((stat_fn(mount), None))
            except Exception as error:
                outcome.append((None, error))
        thread = threading.Thread(target=probe, daemon=True)
        _network_mount_probes[mount] = (thread, float('inf'))
        thread.start()
    thread.join(2)
    with _network_mount_lock:
        if thread.is_alive():
            _network_mount_timeouts.add(mount)
            _network_mount_probes[mount] = (thread, time.monotonic())
            return None
        _network_mount_timeouts.discard(mount)
        _network_mount_probes.pop(mount, None)
    value, error = outcome[0]
    if error:
        raise error
    return value


def parse_mounts(text, stat_fn=os.statvfs, wsl=False):
    result, seen = [], set()
    excluded = {'tmpfs', 'devtmpfs', 'overlay', 'squashfs', 'proc', 'sysfs', 'cgroup', 'cgroup2', 'devpts', 'securityfs', 'debugfs', 'tracefs', 'pstore', 'configfs', 'fusectl', 'mqueue', 'hugetlbfs', 'autofs', 'binfmt_misc', 'nsfs'}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        device, mount, fs, opts = fields[:4]
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), mount)
        options = opts.split(',')
        drive = wsl and fs in ('9p', 'drvfs') and re.fullmatch(r'/mnt/[a-zA-Z]', mount)
        if (fs in excluded or device.startswith('/dev/loop') or 'ro' in options or 'bind' in options
                or device in seen or any(mount == p or mount.startswith(p + '/')
                                         for p in ('/usr/lib/wsl', '/usr/src', '/mnt/wsl', '/init', '/snap'))):
            continue
        if fs in ('9p', 'drvfs') and not drive:
            continue
        if wsl and mount != '/' and not drive:
            continue
        if not (device.startswith('/dev/') or drive or fs in ('fuseblk', 'nfs', 'nfs4', 'cifs', 'smb3', 'fuse.sshfs', 'btrfs', 'zfs')):
            continue
        try:
            st = _network_statvfs(mount, stat_fn) if fs in ('nfs', 'nfs4', 'cifs', 'smb3', 'fuse.sshfs') else stat_fn(mount)
            if st is None:
                continue
            total = st.f_blocks * st.f_frsize
            if total <= 0:
                continue
            seen.add(device)
            result.append({'device': device, 'mount': mount, 'total': total, 'used': total - st.f_bfree * st.f_frsize})
        except OSError:
            continue
    return result


# Cache successful lookups by device and capacity; failures by device for 60s.
_darwin_disk_info = {}
_darwin_disk_failures = {}


def darwin_disk_info(device, total):
    key = (device, total)
    if key not in _darwin_disk_info:
        if time.monotonic() < _darwin_disk_failures.get(device, 0):
            return None
        try:
            data = _run_tracked(['diskutil', 'info', '-plist', device], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=3)
            info = plistlib.loads(data)
            if not isinstance(info, dict):
                raise ValueError('invalid diskutil metadata')
            _darwin_disk_info[key] = info
            _darwin_disk_failures.pop(device, None)
        except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException, xml.parsers.expat.ExpatError, TypeError, OverflowError):
            _darwin_disk_failures[device] = time.monotonic() + 60
            return None
    return _darwin_disk_info[key]


def parse_df(text):
    candidates = []
    now = time.monotonic()
    for device, expiry in list(_darwin_disk_failures.items()):
        if expiry <= now:
            del _darwin_disk_failures[device]
    lines = text.splitlines()[1:]
    present = {}
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) >= 4:
            try:
                present.setdefault(fields[0], set()).add(int(fields[1]) * 1024)
            except ValueError:
                pass
    for key in list(_darwin_disk_info):
        if key[1] not in present.get(key[0], set()):
            del _darwin_disk_info[key]
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        device, mount = fields[0], fields[5]
        disk = re.match(r'^/dev/(disk\d+)', device)
        if not disk or mount.startswith('/System/Volumes/') or mount == '/private/var/vm' or mount.startswith('/private/var/vm/') or mount == '/Volumes/Recovery' or mount.startswith('/Volumes/Recovery/'):
            continue
        try:
            total, available = int(fields[1]) * 1024, int(fields[3]) * 1024
            if total <= 0:
                continue
        except ValueError:
            continue
        info = darwin_disk_info(device, total)
        dedupe = ('disk', disk.group(1)) if info is None else (('container', info['APFSContainerReference']) if info.get('APFSContainerReference') else ('device', device))
        info = info or {}
        protocol = info.get('Protocol') or info.get('BusProtocol') or ''
        if str(protocol).casefold() == 'disk image' or str(info.get('BusProtocol') or '').casefold() == 'disk image':
            continue
        bus = next((name for name in ('USB', 'Thunderbolt') if name.casefold() in str(protocol).casefold() or name.casefold() in str(info.get('BusProtocol') or '').casefold()), '')
        if not bus and info.get('Internal') is True:
            bus = 'Internal'
        label = 'Mac (internal)' if mount == '/' else mount[len('/Volumes/'):] if mount.startswith('/Volumes/') else mount
        candidates.append((dedupe, disk.group(1), {'device': device, 'mount': mount, 'total': total, 'used': total - available, 'label': label, 'bus': bus}))
    candidates.sort(key=lambda item: item[2]['mount'] != '/')
    result, seen, whole_seen, fallback_seen = [], set(), set(), set()
    for key, whole, row in candidates:
        fallback = key[0] == 'disk'
        if key not in seen and whole not in fallback_seen and not (fallback and whole in whole_seen):
            seen.add(key)
            whole_seen.add(whole)
            if fallback:
                fallback_seen.add(whole)
            result.append(row)
    return result


def storage_probe(wsl=False):
    if sys.platform == 'darwin':
        try:
            return parse_df(_run_tracked(['df', '-k', '-P'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, text=True))
        except (OSError, subprocess.SubprocessError):
            return []
    return parse_mounts(read_text('/proc/mounts'), wsl=wsl)


def _background_probe(name, function):
    try:
        _probe[name] = function()
    except Exception as exc:
        if name == 'usage':
            previous = _probe.get(name)
            _probe[name] = dict(previous, stale=True) if isinstance(previous, dict) else {'days': {}, 'error': _error_text(exc, 'usage scan failed'), 'stale': True}
        elif name == 'agents_live':
            _probe[name] = {'at': int(time.time()), 'sessions': [], 'truncated': False, 'supported': False}
        else:
            _probe[name] = None if name == 'windows' else []
    finally:
        if name == 'usage':
            generation = _probe.get('usage_generation', 0) + 1
            _probe['usage_generation'] = generation
            _probe['usage_snapshot'] = (_probe[name], generation)
        elif name == 'agents_live':
            generation = _probe.get('agents_live_generation', 0) + 1
            _probe['agents_live_generation'] = generation
            _probe['agents_live_snapshot'] = (_probe[name], generation)
        _probe[name + '_busy'] = False


def wsl_filesystems(storage, windows):
    result, drives = [], {}
    for disk in storage:
        mount = disk.get('mount', '')
        if mount == '/':
            result.append(dict(disk, mount='WSL (/)'))
        elif re.fullmatch(r'/mnt/[a-zA-Z]', mount):
            label = mount[-1].upper() + ':'
            drives[label] = dict(disk, device=label, mount=label)
    if windows is not None:
        for disk in windows.get('disks', []):
            label = str(disk.get('mount', '')).upper()
            drives[label] = disk
    return result + [drives[label] for label in sorted(drives)]


def usage_scan_enabled():
    return os.environ.get('MAINFRAME_USAGE_SCAN') != '0'


def slow_probes(sample):
    now = time.monotonic()
    for name, interval, enabled, fn in (('agents_live', 10, os.environ.get('MAINFRAME_AGENTS_SCAN') != '0', agents_probe), ('storage', 30, True, lambda: storage_probe(sample.get('wsl') is True)), ('windows', 15, sample.get('wsl') is True, windows_probe)):
        if enabled and not _probe.get(name + '_busy', False) and (not _probe.get(name + '_at', 0) or now - _probe[name + '_at'] >= interval):
            _probe[name + '_busy'] = True
            _probe[name + '_at'] = now
            threading.Thread(target=_background_probe, args=(name, fn), daemon=True).start()
    if usage_scan_enabled() and now - _probe_started >= 20 and not _probe.get('usage_busy', False) and (not _probe.get('usage_at', 0) or now - _probe['usage_at'] >= 600):
        _probe['usage_busy'] = True
        _probe['usage_at'] = now
        threading.Thread(target=_background_probe, args=('usage', usage_probe), daemon=True).start()
    usage, generation = _probe.get('usage_snapshot', (_probe.get('usage'), _probe.get('usage_generation', 0)))
    live, live_generation = _probe.get('agents_live_snapshot', (None, 0))
    sample['agents_live'] = live if os.environ.get('MAINFRAME_AGENTS_SCAN') != '0' else None
    sample['_agents_live_generation'] = live_generation
    sample['usage'] = usage
    sample['_usage_generation'] = generation
    sample['windows'] = _probe['windows'] if sample.get('wsl') else None
    sample['filesystems'] = list(_probe['storage'] or [])
    if sample.get('wsl') is True:
        sample['filesystems'] = wsl_filesystems(sample['filesystems'], sample['windows'])
    return sample


def collect_sample(include_procs):
    """One sample for this machine. Linux reads /proc; macOS uses the darwin backend."""
    if sys.platform == "darwin":
        sample = collect_darwin(include_procs)
    else:
        sample = collect_linux(include_procs)
    return slow_probes(apply_host_meta(sample, host_name(), host_os_name(), kernel_release()))


class _UsageEmitter:
    def __init__(self):
        self.last = object()
        self.last_live = object()

    def filter(self, sample):
        if not isinstance(sample, dict):
            return sample
        sample = dict(sample)
        usage = sample.get('usage')
        generation = sample.pop('_usage_generation', None)
        if usage is None or generation == self.last:
            sample.pop('usage', None)
        else:
            self.last = generation
        live = sample.get('agents_live')
        generation = sample.pop('_agents_live_generation', None)
        if live is None or generation == self.last_live:
            sample.pop('agents_live', None)
        else:
            self.last_live = generation
        return sample


def emit_sample(sample):
    try:
        payload = json.dumps(sample, separators=(",", ":")) + "\n"
    except (TypeError, ValueError):
        raise
    try:
        sys.stdout.write(payload)
        sys.stdout.flush()
    except BrokenPipeError:
        raise
    except OSError as exc:
        raise BrokenPipeError(str(exc))
    except ValueError as exc:
        if "closed" in str(exc).lower():
            raise BrokenPipeError(str(exc))
        raise


def emit(include_procs):
    emit_sample(collect_sample(include_procs))


class _CheckedFunc(object):
    """Stand-in for a ctypes function. c_void_p rejects byref (CArgObject)."""

    def __init__(self, impl):
        self.argtypes = []
        self.restype = None
        self._impl = impl

    def __call__(self, *args):
        specs = list(self.argtypes or [])
        paired = min(len(specs), len(args))
        index = 0
        while index < paired:
            spec = specs[index]
            arg = args[index]
            if spec == ctypes.c_void_p and arg is not None and type(arg).__name__ == "CArgObject":
                raise ctypes.ArgumentError("c_void_p does not accept byref")
            index += 1
        return self._impl(*args)


class _StubLibc(object):
    """Enough of libSystem for the darwin sysctl and vm_stat call shapes."""

    def __init__(self):
        self.sysctlbyname = _CheckedFunc(self._sysctl)
        self.host_statistics64 = _CheckedFunc(self._host_stats)
        self.host_calls = 0
        self.freed = []
        self.cpu_blob = (ctypes.c_int * 4)(1, 2, 3, 4)
        self.mach_host_self = _CheckedFunc(self._host)
        self.mach_task_self = _CheckedFunc(lambda: 7)
        self.host_processor_info = _CheckedFunc(self._cpu_info)
        self.vm_deallocate = _CheckedFunc(self._free)
        self.host_page_size = _CheckedFunc(self._page)

    def _host(self):
        self.host_calls += 1
        return 1

    def _cpu_info(self, host, flavor, cpus, info, count):
        assert host == 1 and flavor == 2
        cpus._obj.value = 1
        info._obj.value = ctypes.addressof(self.cpu_blob)
        count._obj.value = 4
        return 0

    def _free(self, task, address, size):
        self.freed.append((task, address.value, size))
        return 0

    def _page(self, host, page):
        assert host == 1
        page._obj.value = 4096
        return 0

    def _sysctl(self, name, oldp, _oldlenp, _newp, _newlen):
        addr = None
        if isinstance(oldp, ctypes.c_void_p):
            addr = oldp.value
        elif isinstance(oldp, int):
            addr = oldp
        else:
            raise ctypes.ArgumentError("oldp is %s" % type(oldp).__name__)
        if name == b"hw.memsize":
            ctypes.cast(addr, ctypes.POINTER(ctypes.c_uint64))[0] = 8 * 1024 * 1024 * 1024
            return 0
        if name == b"vm.swapusage":
            usage = ctypes.cast(addr, ctypes.POINTER(XSWUsage)).contents
            usage.xsu_total = 2 * 1024 * 1024 * 1024
            usage.xsu_used = 512 * 1024 * 1024
            usage.xsu_avail = usage.xsu_total - usage.xsu_used
            usage.xsu_pagesize = 4096
            usage.xsu_encrypted = 1
            return 0
        if name in (b"hw.cpufrequency", b"hw.cpufrequency_max"):
            ctypes.cast(addr, ctypes.POINTER(ctypes.c_uint64))[0] = 3200000000
            return 0
        return 1

    def _host_stats(self, _host, flavor, stats, _count):
        if int(flavor) != 4:
            return 1
        target = stats
        if type(stats).__name__ == "CArgObject":
            target = stats._obj
        if hasattr(target, "contents"):
            target = target.contents
        target.free_count = 100
        target.inactive_count = 40
        target.speculative_count = 10
        return 0


def ctypes_call_checks(check):
    """Call the real darwin helpers against a stub that rejects byref-as-c_void_p."""
    saved = globals().get("_darwin_libc")
    saved_host = globals().get("_mach_host")
    libc = _StubLibc()
    globals()["_darwin_libc"] = libc
    globals()["_mach_host"] = None
    try:
        _sysctl_prepare(libc)
        rejected = False
        try:
            libc.sysctlbyname(
                b"hw.memsize",
                ctypes.byref(ctypes.c_uint64(0)),
                ctypes.byref(ctypes.c_size_t(8)),
                None,
                0,
            )
        except (ctypes.ArgumentError, TypeError):
            rejected = True
        check(rejected, "sysctlbyname rejects byref for c_void_p")
        try:
            mem = darwin_memsize()
        except Exception as exc:  # noqa: BLE001
            check(False, "darwin_memsize stub: %s" % exc)
            mem = None
        check(mem == 8 * 1024 * 1024 * 1024, "stub memsize")
        try:
            swap_total, swap_used = darwin_swap_pair()
        except Exception as exc:  # noqa: BLE001
            check(False, "darwin_swap_pair stub: %s" % exc)
            swap_total, swap_used = None, None
        check(swap_total == 2 * 1024 * 1024 * 1024 and swap_used == 512 * 1024 * 1024, "stub swap")
        try:
            mhz = darwin_hw_mhz()
        except Exception as exc:  # noqa: BLE001
            check(False, "darwin_hw_mhz stub: %s" % exc)
            mhz = None
        check(mhz == 3200, "stub mhz")
        try:
            stats = darwin_vm_stats()
        except Exception as exc:  # noqa: BLE001
            check(False, "darwin_vm_stats stub: %s" % exc)
            stats = None
        check(
            stats is not None
            and stats.free_count == 100
            and stats.inactive_count == 40
            and stats.speculative_count == 10,
            "stub vm stats",
        )
        cores = darwin_cpu_cores()
        check(len(cores) == 1, "stub mach cpu info")
        check(darwin_page_size() == 4096, "stub mach page size")
        check(libc.host_calls == 1, "mach host send right reused")
        check(libc.freed == [(7, ctypes.addressof(libc.cpu_blob), 16)], "mach cpu allocation freed")
    finally:
        globals()["_darwin_libc"] = saved
        globals()["_mach_host"] = saved_host


def selftest():
    """Pure checks for the hardware parsers. No sysfs and no nvidia-smi."""
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    # Observed on the real WSL hosts. The second excerpt was truncated in the report.
    real_wsl_lines = [
        '{"device":"/dev/sdb","mount":"/usr/src/linux-headers-6.18.54.1-microsoft-standard-WSL2","total":101089280,"used":101089280}',
        '{"device":"drivers","mount":"/usr/lib/wsl/drivers","total":994553696256,...}',
    ]
    real_wsl_rows = [json.loads(real_wsl_lines[0]),
                     json.loads(real_wsl_lines[1].replace(',...}', ',"used":0}'))]
    root_row = {'device': '/dev/sdc', 'mount': '/', 'total': 100, 'used': 20}
    fallback_row = {'device': 'C:', 'mount': '/mnt/c', 'total': 200, 'used': 50}
    disks = wsl_filesystems(real_wsl_rows + [root_row, fallback_row], None)
    check([row['mount'] for row in disks] == ['WSL (/)', 'C:'], "WSL excludes observed internal mounts and labels fallback")
    fixed = {'disks': [{'device': 'D:', 'mount': 'D:', 'total': 300, 'used': 100}]}
    check([row['mount'] for row in wsl_filesystems(real_wsl_rows + [root_row, fallback_row], fixed)]
          == ['WSL (/)', 'C:', 'D:'], "WSL merges Windows fixed disks")

    saved_finalize = globals()["finalize"]
    saved_signal = signal.signal
    saved_exit = os._exit
    calls = []
    class ExitCalled(BaseException):
        pass
    try:
        globals()["finalize"] = lambda: calls.append("finalize")
        check(_finalized(lambda: 42)() == 42 and calls == ["finalize"], "normal return finalizes")
        calls.clear()
        def fail():
            raise ValueError("test")
        try:
            _finalized(fail)()
        except ValueError:
            pass
        check(calls == ["finalize"], "exception finalizes")
        def failing_finalize():
            raise RuntimeError("cleanup failure")
        def fake_exit(code):
            calls.append(code)
            raise ExitCalled()
        globals()["finalize"] = failing_finalize
        signal.signal = lambda *_args: None
        os._exit = fake_exit
        try:
            _die_term(signal.SIGTERM, None)
        except ExitCalled:
            pass
        check(calls[-1:] == [0], "signal exits even when finalizer fails")
    finally:
        globals()["finalize"] = saved_finalize
        signal.signal = saved_signal
        os._exit = saved_exit

    check(_run_text([sys.executable, "-c", "print('ok')"], 2).strip() == "ok", "short helper output")
    before_helpers = list(_child_procs)
    check(_run_text([sys.executable, "-c", "import time; time.sleep(5)"], 0.1) == "",
          "timed-out short helper stops")
    check(_child_procs == before_helpers, "short helper is reaped and untracked")

    check(parent_disk("nvme0n1p1") == "nvme0n1", "nvme partition")
    check(parent_disk("nvme1n2p12") == "nvme1n2", "nvme multi-digit partition")
    check(parent_disk("mmcblk0p1") == "mmcblk0", "mmc partition")
    check(parent_disk("sda1") == "sda", "sd partition")
    check(parent_disk("vda2") == "vda", "vd partition")
    check(parent_disk("dm-0") is None, "dm has no name parent")
    check(is_whole_disk("nvme0n1") and is_whole_disk("mmcblk0") and is_whole_disk("sda"), "whole disks")
    check(not is_whole_disk("mmcblk0p1") and not is_whole_disk("dm-0"), "not whole")
    check(resolve_disk_name("dm-0", lambda node: ["nvme0n1p2"] if node == "dm-0" else []) == "nvme0n1", "lvm slave")
    check(resolve_disk_name("mmcblk0p1", lambda node: []) == "mmcblk0", "mmc resolve")
    check(resolve_disk_name("sda3", lambda node: []) == "sda", "sd resolve")

    check(parse_ipv4_default("ppp0 00000000 00000000 0001 0 0 0 00000000 0 0 0\n") == "ppp0", "ipv4 point to point")
    check(parse_ipv4_default("wlo1 00000000 0101A8C0 0003 0 0 100 00000000 0 0 0\n") == "wlo1", "ipv4 gateway")
    check(parse_ipv4_default("wlo1 00000000 0101A8C0 0000 0 0 100 00000000 0 0 0\n") is None, "ipv4 down")
    check(parse_ipv4_default("wlo1 00000000 0101A8C0 0003 0 0 100 FFFFFFFF 0 0 0\n") is None, "ipv4 mask")
    v6_up = "00000000000000000000000000000000 00 a b c 00000064 d e 00000001 f eth0\n"
    v6_down = "00000000000000000000000000000000 00 a b c 00000064 d e 00000000 f eth0\n"
    check(parse_ipv6_default(v6_up) == "eth0", "ipv6 up without gateway")
    check(parse_ipv6_default(v6_down) is None, "ipv6 down")

    check(parse_dpm_mhz("0: 300Mhz\n1: 1200Mhz *\n") == 1200, "dpm current")
    check(parse_dpm_mhz("0: 300Mhz\n") == 300, "dpm fallback")

    ranked = rank_gpu_candidates([
        {"card": "card0", "driver": "i915", "discrete": False},
        {"card": "card1", "driver": "amdgpu", "discrete": True},
    ])
    check(ranked[0]["driver"] == "amdgpu", "discrete readable wins")
    hybrid = rank_gpu_candidates([
        {"card": "card0", "driver": "i915", "discrete": False},
        {"card": "card1", "driver": "nvidia", "discrete": True, "unsupported": True},
    ])
    check(hybrid[0]["driver"] == "i915", "readable integrated beats unsupported discrete")
    only_nv = rank_gpu_candidates([
        {"card": "card0", "driver": "nvidia", "discrete": True, "unsupported": True},
    ])
    check(only_nv[0]["unsupported"] is True, "nvidia-only stays unsupported")

    chosen = choose_package_sensor([
        {"kind": "hwmon", "driver": "k10temp", "label": "Tctl", "path": "tctl", "order": 1},
        {"kind": "hwmon", "driver": "coretemp", "label": "Package id 0", "path": "pkg", "order": 3},
        {"kind": "hwmon", "driver": "k10temp", "label": "Tdie", "path": "tdie", "order": 0},
        {"kind": "zone", "driver": "x86_pkg_temp", "label": "x86_pkg_temp", "path": "zone", "order": 0},
        {"kind": "hwmon", "driver": "coretemp", "label": "Package id 1", "path": "pkg1", "order": 0},
    ])
    check(chosen["path"] == "pkg", "package id 0 wins")
    amd = choose_package_sensor([
        {"kind": "hwmon", "driver": "zenpower", "label": "Tdie", "path": "tdie", "order": 2},
        {"kind": "hwmon", "driver": "k10temp", "label": "Tctl", "path": "tctl", "order": 4},
        {"kind": "zone", "driver": "x86_pkg_temp", "label": "x86_pkg_temp", "path": "zone", "order": 0},
    ])
    check(amd["path"] == "tctl", "tctl before tdie and zone")
    zone = choose_package_sensor([
        {"kind": "zone", "driver": "x86_pkg_temp", "label": "x86_pkg_temp", "path": "zone", "order": 1},
        {"kind": "hwmon", "driver": "coretemp", "label": "Core 0", "path": "core", "order": 0},
    ])
    check(zone["path"] == "zone", "zone when no package label")
    check(_numeric_suffix("/sys/class/hwmon/hwmon2") < _numeric_suffix("/sys/class/hwmon/hwmon10"), "hwmon numeric")

    check(select_disk_temp_path("nvme0n1", "/nvme", "/other") == "/nvme", "nvme temp")
    check(select_disk_temp_path("sda", "/nvme", "/other") == "/other", "non-nvme ignores nvme sensor")
    check(select_disk_temp_path("sda", "/nvme", None) is None, "hide missing disk temp")
    check(select_disk_temp_path("mmcblk0", None, None) is None, "mmc without hwmon hides temp")

    prev = {
        "10:1": {"ticks": 1000, "read_s": 10.0},
        "11:1": {"ticks": 0, "read_s": 10.0},
        "12:1": {"ticks": 0, "read_s": 10.0},
        "13:1": {"ticks": 0, "read_s": 10.0},
    }
    ranked_rows = [
        {"pid": 10, "start": 1, "comm": "missioncenter-m", "argv0": "/usr/bin/missioncenter", "ticks": 1000, "rss": 250, "read_s": 12.0},
        {"pid": 11, "start": 1, "comm": "worker.bin", "ticks": 100, "rss": 40, "read_s": 12.0},
        {"pid": 12, "start": 1, "comm": "worker.bin", "ticks": 100, "rss": 40, "read_s": 12.0},
        {"pid": 13, "start": 1, "comm": "Web Content", "ticks": 10, "rss": 10, "read_s": 12.0},
    ]
    presented = build_presented(ranked_rows, prev, 1000 * 1024, 100, 4096)
    check(presented["byCpu"][0]["name"] == "worker.bin ×2", "grouped cpu name")
    check(presented["byCpu"][0]["text"] == "100%", "grouped cpu percent")
    check(presented["byMem"][0]["name"] == "missioncenter", "mem leader")
    fresh = build_presented(
        [{"pid": 99, "start": 5, "comm": "new", "ticks": 50, "rss": 1, "read_s": 3.0}],
        {},
        1000 * 1024,
        100,
        4096,
    )
    check(fresh["byCpu"] == [], "new pid has no cpu percent")
    check(fresh["byMem"][0]["name"] == "new", "new pid still has memory")
    reused = build_presented(
        [{"pid": 10, "start": 9, "comm": "a", "ticks": 500, "rss": 1, "read_s": 4.0}],
        {"10:1": {"ticks": 100, "read_s": 1.0}},
        1000 * 1024,
        100,
        4096,
    )
    check(reused["byCpu"] == [], "reused pid does not keep the old baseline")

    isolated = {}
    isolated_errors = {}

    def boom():
        raise RuntimeError("disk failed")

    take_sensor(isolated, isolated_errors, "cpu", lambda: {"total": {"user": 1}})
    take_sensor(isolated, isolated_errors, "disk", boom)
    check(isolated["cpu"]["total"]["user"] == 1, "sibling sensor kept")
    check(isolated["disk"] is None, "failed sensor is null")
    check(isolated_errors.get("disk") == "disk failed", "error map entry")
    check("error" not in isolated, "no sample-wide error")

    order = []

    def fake_read(path):
        order.append(path)
        return path

    def fake_clock():
        order.append("clock")
        return 12.5

    proc, disk, net, stamp = read_rate_snapshot(fake_read, fake_clock)
    check(order == ["/proc/stat", "/proc/diskstats", "/proc/net/dev", "clock"], "rate files before the stamp")
    check(stamp == 12500.0 and proc == "/proc/stat" and disk == "/proc/diskstats" and net == "/proc/net/dev", "stamp value")

    stat_line = b"42 (a)b)c) S 1 1 1 0 -1 0 0 0 0 0 10 5 0 0 20 0 1 0 77 999 33"
    check(_parse_stat(stat_line) == ("a)b)c", 15, 77, 33), "stat comm, ticks, starttime, rss field 24")
    check(_parse_stat(b"1 (x) R 1") is None, "short stat is ignored")
    check(adapt_proc_interval(40.0, 6.0) == 3.0, "40 ms stays on the 3 s clock")
    check(adapt_proc_interval(40.1, 3.0) == 6.0, "over 40 ms stretches to 6 s")
    check(adapt_proc_interval(None, 6.0) == 6.0, "unreadable sweep keeps the interval")
    check(scheduled_sweeps([1, 1, 1, 1, 1, 1, 1])[:5] == [0, 3, 6, 9, 12], "fast sweeps every 3 s")
    check(scheduled_sweeps([80, 80, 80, 80])[:4] == [0, 6, 12, 18], "slow sweeps every 6 s")
    check(scheduled_sweeps([80, 1, 1, 1, 1])[:5] == [0, 6, 9, 12, 15], "a fast sweep returns to 3 s")
    needle = "mf" + "proc"
    own = read_text(__file__)
    check(len(own) > 1000 and needle not in own, "no native process ranker")

    check(proc_display_name("MainThread", "/opt/foo/bar") == "bar", "mainthread uses argv basename")
    check(proc_display_name("MainThread", "mcp 6276 --auth-timeout 60") == "mcp", "mainthread cmdline drops arguments")
    check(proc_display_name("mcp 6276 --auth-timeout 60", "") == "mcp", "rewritten title drops arguments")
    check(proc_display_name("Thread", "/opt/foo/bar") == "bar", "thread uses argv basename")
    check(proc_display_name("Main", "/opt/foo/bar") == "bar", "main uses argv basename")
    check(proc_display_name("GeckoMain", "/usr/lib/firefox/firefox") == "firefox", "geckomain uses argv basename")
    check(proc_display_name("ThreadPool#3", "/usr/bin/app") == "app", "threadpool prefix uses argv basename")
    check(proc_display_name("kworker/0:1", "") == "kworker/0:1", "kworker without cmdline keeps comm")
    check(proc_display_name("Web Content", "/usr/lib/firefox/firefox") == "Web Content", "spaced comm is kept")
    check(proc_display_name("missioncenter-m", "/usr/bin/missioncenter") == "missioncenter", "15 char still uses argv")
    check(proc_display_name("a" * 15, "mcp 6276 --auth-timeout 60") == "mcp", "15 char cmdline drops arguments")
    named = build_presented(
        [{"pid": 7, "start": 1, "comm": "MainThread", "argv0": "/opt/foo/bar", "ticks": 0, "rss": 10, "read_s": 1.0}],
        {},
        1000 * 1024,
        100,
        4096,
    )
    check(named["byMem"][0]["name"] == "bar", "ranked mainthread shows argv basename")

    stat = "cpu  10 1 2 80 3 0 0 0 0 0\ncpu0 10 1 2 80 3 0 0 0 0 0\n"
    saved_freq = globals()["cpu_core_mhz"]

    def broken_freq(_count):
        raise OSError("freq probe failed")

    globals()["cpu_core_mhz"] = broken_freq
    try:
        cpu_sample = sensor_cpu(stat)
    finally:
        globals()["cpu_core_mhz"] = saved_freq
    check(cpu_sample["total"]["user"] == 10, "cpu counters survive a freq probe failure")
    check(cpu_sample["cores"][0]["user"] == 10, "core counters survive a freq probe failure")
    check(cpu_sample["mhz"] is None and cpu_sample["core_mhz"] is None, "freq failure nulls mhz only")

    net_line = "  eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n"
    saved_virtual = globals()["virtual_ifaces"]
    saved_route = globals()["default_route_iface"]

    def broken_virtual():
        raise OSError("virtual probe failed")

    def broken_route(_v4, _v6):
        raise OSError("route probe failed")

    globals()["virtual_ifaces"] = broken_virtual
    globals()["default_route_iface"] = lambda _v4, _v6: "eth0"
    try:
        virt_fail = sensor_net(net_line)
    finally:
        globals()["virtual_ifaces"] = saved_virtual
        globals()["default_route_iface"] = saved_route
    check(virt_fail["ifaces"][0]["rx"] == 100 and virt_fail["ifaces"][0]["tx"] == 200, "byte counters survive virtual failure")
    check(virt_fail["virtual"] is None, "virtual failure is null")
    check(virt_fail["default_iface"] == "eth0", "route still runs when virtual fails")

    globals()["virtual_ifaces"] = lambda: ["docker0"]
    globals()["default_route_iface"] = broken_route
    try:
        route_fail = sensor_net(net_line)
    finally:
        globals()["virtual_ifaces"] = saved_virtual
        globals()["default_route_iface"] = saved_route
    check(route_fail["ifaces"][0]["rx"] == 100, "byte counters survive a route failure")
    check(route_fail["virtual"] == ["docker0"], "virtual class survives a route failure")
    check(route_fail["default_iface"] is None, "route failure is null")

    alive = lambda path: path == "/sys/class/drm/card0" or path == "/alive"
    check(gpu_paths_gone({"card": "card0", "idle": "/alive", "driver": "xe"}, alive) is False, "live gpu paths stay")
    check(gpu_paths_gone({"card": "card1", "idle": "/alive"}, alive) is True, "missing card is gone")
    check(gpu_paths_gone({"card": "card0", "idle": "/missing"}, alive) is True, "missing counter is gone")
    check(gpu_paths_gone({"card": "card0", "unsupported": True, "driver": "nvidia"}, alive) is False, "nvidia card still present is kept")
    check(gpu_runtime_status({"card": "card0"}, lambda _path: "Suspended\n") == "suspended", "runtime status is lowered")
    check(gpu_runtime_status({"card": "card0"}, lambda _path: "") is None, "blank runtime status is null")

    saved_exists = os.path.exists
    saved_discover = globals()["discover_gpu"]
    saved_paths = globals()["_gpu_paths"]
    saved_at = globals()["_gpu_discover_at"]
    discover_calls = {"n": 0}

    def fake_discover():
        discover_calls["n"] += 1
        return {"driver": "xe", "name": "new", "idle": "/alive", "freq": None}

    try:
        globals()["discover_gpu"] = fake_discover
        globals()["_gpu_paths"] = {"driver": "xe", "name": "old", "idle": "/dead", "freq": None}
        globals()["_gpu_discover_at"] = time.monotonic()
        os.path.exists = lambda path: path == "/alive"
        found = gpu_sample()
        check(discover_calls["n"] == 1, "missing gpu path rediscovers once")
        check(found.get("present") is True and found.get("name") == "new", "rediscovery replaces the gpu")
        check(found.get("idle_ms") is None, "new idle file is read, not cached")
        gpu_sample()
        check(discover_calls["n"] == 1, "an existing gpu path is not rediscovered")
        os.path.exists = lambda path: False
        gone_sample = gpu_sample()
        check(discover_calls["n"] == 2, "a disappeared path rediscovers again")
        check(gone_sample.get("present") is False, "a still-missing discovery backs off to absent")
        held = gpu_sample()
        check(discover_calls["n"] == 2 and held.get("present") is False, "failed discovery waits 30s")
    finally:
        os.path.exists = saved_exists
        globals()["discover_gpu"] = saved_discover
        globals()["_gpu_paths"] = saved_paths
        globals()["_gpu_discover_at"] = saved_at

    darwin_parser_checks(check)
    loop_msg = remote_loopback()
    check(loop_msg is None, loop_msg or "remote loopback")
    shut_msg = remote_shutdown_selftest()
    check(shut_msg is None, shut_msg or "remote shutdown")
    ctypes_call_checks(check)

    if failures:
        for msg in failures:
            sys.stderr.write("selftest: %s\n" % msg)
        return 1
    sys.stdout.write("selftest: pass\n")
    return 0


def arm_parent_death():
    """SIGTERM when the parent dies, and exit if the parent is already gone.

    The check closes the race where the parent exits between the prctl and
    the return: the new ppid would never deliver the death signal.
    """
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong
    ]
    libc.prctl.restype = ctypes.c_int
    pr_set_pdeathsig = 1
    ppid = os.getppid()
    if libc.prctl(pr_set_pdeathsig, ctypes.c_ulong(signal.SIGTERM), 0, 0, 0) != 0:
        raise OSError("could not arm parent death signal")
    if os.getppid() != ppid:
        _die_term(signal.SIGTERM, None)


def _die_term(_signum, _frame):
    try:
        try:
            for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGPIPE):
                signal.signal(sig, signal.SIG_IGN)
        finally:
            finalize()
    finally:
        os._exit(0)


def wait_until(deadline):
    """Sleep until deadline. True when stdin hits EOF or a quit line."""
    while True:
        timeout = deadline - time.monotonic()
        if timeout < 0:
            timeout = 0
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
        except InterruptedError:
            continue
        except (OSError, ValueError):
            return False
        if not ready:
            return False
        line = sys.stdin.readline()
        if line == "" or line.strip() == "quit":
            return True


# Process sweeps ride the 1 Hz sample clock. 3 s unless one pass costs more
# than 40 ms, in which case the next gap is 6 s.
_PROC_INTERVAL_S = 3.0
_PROC_INTERVAL_SLOW_S = 6.0
_PROC_SLOW_MS = 40.0


def adapt_proc_interval(sweep_ms, current=_PROC_INTERVAL_S):
    """Seconds until the next process sweep.

    3 s while a sweep costs 40 ms or less. A slower sweep stretches the gap
    to 6 s. An unreadable cost keeps `current`.
    """
    try:
        gap = float(current)
    except (TypeError, ValueError):
        gap = _PROC_INTERVAL_S
    if gap != gap or gap < _PROC_INTERVAL_S:
        gap = _PROC_INTERVAL_S
    if gap > _PROC_INTERVAL_SLOW_S:
        gap = _PROC_INTERVAL_SLOW_S
    try:
        cost = float(sweep_ms)
    except (TypeError, ValueError):
        return gap
    if cost != cost:
        return gap
    if cost > _PROC_SLOW_MS:
        return _PROC_INTERVAL_SLOW_S
    return _PROC_INTERVAL_S


def proc_due(since, every):
    """True when this 1 Hz slot should run a process sweep."""
    return since >= every


def advance_proc_clock(since, every, include, sweep_ms, skipped=0):
    """Return (since, every) after one sample.

    `include` means this sample ran a sweep. `skipped` is extra seconds
    dropped so a late sample does not burst.
    """
    if include:
        every = int(adapt_proc_interval(sweep_ms, float(every)))
        since = 0
    try:
        skip = int(skipped or 0)
    except (TypeError, ValueError):
        skip = 0
    if skip < 0:
        skip = 0
    since += 1 + skip
    return since, every


def scheduled_sweeps(costs, samples=20):
    """Sample indexes that include a sweep, for a list of sweep costs in ms."""
    every = int(_PROC_INTERVAL_S)
    since = every
    got = []
    seen = 0
    for index in range(samples):
        include = proc_due(since, every)
        cost = None
        if include:
            got.append(index)
            cost = costs[seen] if seen < len(costs) else 1.0
            seen += 1
        since, every = advance_proc_clock(since, every, include, cost, 0)
    return got


def _serve():
    """One sample per second, phase-locked to the start.

    The process table is on the first sample and then every 3 s. A sweep
    slower than 40 ms stretches that to 6 s.
    """
    period = 1.0
    next_at = time.monotonic()
    every = int(_PROC_INTERVAL_S)
    since = every
    usage_emitter = _UsageEmitter()
    while True:
        if wait_until(next_at):
            return 0
        include = proc_due(since, every)
        sample = usage_emitter.filter(safe_sample(include))
        sweep_ms = None
        if include and isinstance(sample, dict):
            procs = sample.get("procs")
            if isinstance(procs, dict):
                sweep_ms = procs.get("sweep_ms")
        try:
            emit_sample(sample)
        except BrokenPipeError:
            return 0
        next_at += period
        now = time.monotonic()
        skipped = 0
        if next_at < now:
            # Drop missed slots instead of bursting, and keep the original phase.
            skipped = int((now - next_at) / period) + 1
            next_at += skipped * period
        since, every = advance_proc_clock(since, every, include, sweep_ms, skipped)
    return 0


def _main():
    if "--temp-sensors" in sys.argv:
        print(json.dumps(diagnostic_temperature_sensors(), allow_nan=False))
        return 0
    if '--usage-scan' in sys.argv:
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            cap = 2 * 1024 * 1024 * 1024
            if soft == resource.RLIM_INFINITY or soft > cap:
                resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
        except Exception:
            pass
        arm_parent_death()
        try:
            os.nice(19)
        except OSError:
            pass
        print(json.dumps(usage_scan(), separators=(',', ':')))
        return 0
    if "--storage" in sys.argv:
        import storage_scan
        arm_parent_death()
        signal.signal(signal.SIGTERM, _die_term)
        return storage_scan.run("--force" in sys.argv)
    if "--storage-open" in sys.argv:
        import storage_scan
        index = sys.argv.index("--storage-open")
        return storage_scan.open_category(sys.argv[index + 1] if index + 1 < len(sys.argv) else "")
    if "--selftest" in sys.argv:
        return selftest()
    if "--once" in sys.argv:
        emit(True)
        return 0
    if "--remote-shutdown-selftest" in sys.argv:
        install_remote_signals()
        return remote_shutdown_fixture()
    if "--remote" in sys.argv:
        # Stdin is the script source and is already closed. Do not watch it.
        # SIGPIPE is handled, not ignored: a dead ssh must kill the helpers.
        install_remote_signals()
        return serve_remote()
    signal.signal(signal.SIGTERM, _die_term)
    signal.signal(signal.SIGHUP, _die_term)
    arm_parent_death()
    return serve()


def _finalized(function):
    def run(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            finalize()
    return run


serve = _finalized(_serve)
serve_remote = _finalized(serve_remote)
main = _finalized(_main)


if __name__ == "__main__":
    sys.exit(main())
