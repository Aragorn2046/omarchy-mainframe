#!/usr/bin/env python3
"""Self-driving host sampler for Mainframe.

Emits one compact JSON object per second on a monotonic schedule. Numbers are
parsed here; the shell does not see raw /proc text. The process table is
included every 3 seconds. A sweep longer than 40 ms stretches the next gap to
6 seconds, and the sample reports that sweep's measured time. Stdin is watched
only for EOF or "quit".

--once prints one sample (with a process sweep) and exits. --selftest runs
the pure parser checks.
"""

import ctypes
import glob
import json
import math
import os
import re
import select
import signal
import sys
import time

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


def collect_sample(include_procs):
    """One parsed sample. Counter files are read before the monotonic stamp."""
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


def emit_sample(sample):
    sys.stdout.write(json.dumps(sample, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit(include_procs):
    emit_sample(collect_sample(include_procs))


def selftest():
    """Pure checks for the hardware parsers. No sysfs and no nvidia-smi."""
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

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
        os._exit(1)
    if os.getppid() != ppid:
        os._exit(0)


def _die_term(_signum, _frame):
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


def serve():
    """One sample per second, phase-locked to the start.

    The process table is on the first sample and then every 3 s. A sweep
    slower than 40 ms stretches that to 6 s.
    """
    period = 1.0
    next_at = time.monotonic()
    every = int(_PROC_INTERVAL_S)
    since = every
    while True:
        if wait_until(next_at):
            return 0
        include = proc_due(since, every)
        try:
            sample = collect_sample(include)
        except Exception as exc:  # noqa: BLE001 — still one line, never {"error": ...} alone
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
        sweep_ms = None
        if include and isinstance(sample, dict):
            procs = sample.get("procs")
            if isinstance(procs, dict):
                sweep_ms = procs.get("sweep_ms")
        emit_sample(sample)
        next_at += period
        now = time.monotonic()
        skipped = 0
        if next_at < now:
            # Drop missed slots instead of bursting, and keep the original phase.
            skipped = int((now - next_at) / period) + 1
            next_at += skipped * period
        since, every = advance_proc_clock(since, every, include, sweep_ms, skipped)
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--once" in sys.argv:
        emit(True)
        return 0
    arm_parent_death()
    signal.signal(signal.SIGTERM, _die_term)
    return serve()


if __name__ == "__main__":
    sys.exit(main())
