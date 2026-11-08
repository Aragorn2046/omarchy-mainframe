#!/usr/bin/env bash
# Headless checks for mainframe: node unit tests, live samples, and a QML load.
# Install checks use a temporary XDG_CONFIG_HOME. No visible window unless
# MAINFRAME_SMOKE_LIVE=1.
# Offscreen (software) regression gate: < 3.0% of one core at both sizes.
# Live Wayland gate: < 2% of one core over 30 s, after a 5 s wait.
# MAINFRAME_SMOKE_NO_GUI=1 skips QML, graphical interaction, and SSH checks.
set -u

# Quickshell can crash without a writable runtime directory.
if [[ -z "${XDG_RUNTIME_DIR:-}" || ! -d "$XDG_RUNTIME_DIR" || ! -w "$XDG_RUNTIME_DIR" || ! -x "$XDG_RUNTIME_DIR" ]]; then
  echo "smoke: XDG_RUNTIME_DIR must be set to a writable, accessible directory" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

echo "== node tests =="
if node --test mainframe/tests/; then
  echo "node tests: pass"
else
  echo "node tests: FAIL"
  fail=1
fi

echo "== theme manager tests =="
if python3 -m unittest discover -s mainframe/tests -p 'test_theme_manager.py'; then
  echo "theme manager tests: pass"
else
  echo "theme manager tests: FAIL"
  fail=1
fi

echo "== collector selftest =="
if python3 "$ROOT/mainframe/collect.py" --selftest; then
  echo "collector selftest: pass"
else
  echo "collector selftest: FAIL"
  fail=1
fi

echo "== usage scan =="
if python3 - "$ROOT/mainframe/collect.py" <<'PY'
import datetime
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile

times = [float('nan'), float('nan')]
try:
    with tempfile.TemporaryDirectory(prefix='mainframe-usage-smoke-') as tmp:
        home = Path(tmp) / 'home'
        cache = Path(tmp) / 'cache'
        home.mkdir()
        cache.mkdir()
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for number in range(3):
            path = home / '.claude' / 'projects' / 'fixture' / ('session-%d.jsonl' % number)
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {'type': 'assistant', 'timestamp': stamp,
                      'message': {'id': 'fixture-%d' % number, 'model': 'fixture-claude',
                                  'usage': {'input_tokens': 10, 'output_tokens': 2}}}
            path.write_text(json.dumps(record) + '\n', encoding='utf-8')
        path = home / '.codex' / 'sessions' / 'fixture.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {'type': 'session_meta', 'payload': {'id': 'fixture-session', 'model': 'fixture-codex'}},
            {'type': 'event_msg', 'timestamp': stamp, 'payload': {'type': 'token_count',
             'info': {'total_token_usage': {'input_tokens': 40, 'output_tokens': 5, 'cached_input_tokens': 7}}}},
        ]
        path.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
        env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(cache))
        command = ['python3', sys.argv[1], '--usage-scan']
        if shutil.which('ionice'):
            command = ['ionice', '-c', '3'] + command
        results = []
        index_path = cache / 'mainframe' / 'usage-index.json'
        for run in range(2):
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=True, timeout=60)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            times[run] = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
            results.append(json.loads(result.stdout))
            if run == 0:
                index = json.loads(index_path.read_text(encoding='utf-8'))
                index_stat = index_path.stat()
                if len(index['files']) != 4 or any(row['offset'] != row['size'] for row in index['files'].values()):
                    raise ValueError('first scan did not index all fixture files')
        if index_path.stat().st_ino != index_stat.st_ino:
            raise ValueError('second scan rebuilt the index')
        first, second = results
        totals = next(iter(first['days'].values()))
        if (first['partial'] or second['partial'] or first['days'] != second['days'] or
                totals['claude/fixture-claude']['input'] != 30 or
                totals['codex/fixture-codex']['input'] != 40 or times[1] >= 0.5):
            raise ValueError('scan totals or CPU gate failed')
    print('usage scan: first=%.3fs second=%.3fs' % tuple(times))
    print('usage scan gate: PASS')
except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
    print('usage scan: first=%.3fs second=%.3fs' % tuple(times))
    print('usage scan gate: FAIL (%s)' % exc)
    sys.exit(1)
PY
then
  :
else
  fail=1
fi

echo "== collector --once =="
collect_log="$(mktemp)"
if python3 "$ROOT/mainframe/collect.py" --once >"$collect_log" 2>"$collect_log.err"; then
  if python3 - "$collect_log" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    sample = json.loads(handle.readline())
if "error" in sample:
    raise SystemExit("sample-wide error key")
for key in ("t_ms", "mono_ms", "cpu", "mem", "disk", "net", "gpu", "temps", "procs"):
    if key not in sample:
        raise SystemExit("missing " + key)
cpu = sample.get("cpu") or {}
cores = cpu.get("cores") or []
present = [row for row in cores if isinstance(row, dict)]
try:
    ncpu = int(os.sysconf("SC_NPROCESSORS_ONLN"))
except (OSError, ValueError):
    ncpu = 0
if ncpu < 1:
    raise SystemExit("online cpu count unavailable")
if len(present) != ncpu:
    raise SystemExit("present cores %s want %s" % (len(present), ncpu))
if not isinstance(cpu.get("core_mhz"), list):
    raise SystemExit("core_mhz missing")
procs = sample.get("procs") or {}
presented = procs.get("presented") or {}
if presented.get("byCpu"):
    raise SystemExit("first sweep invented cpu percent")
if not isinstance(presented.get("byMem"), list):
    raise SystemExit("byMem missing")
if len(presented.get("byCpu") or []) > 8 or len(presented.get("byMem") or []) > 8:
    raise SystemExit("presented list longer than 8")
sweep = procs.get("sweep_ms")
if not isinstance(sweep, (int, float)):
    raise SystemExit("sweep_ms missing")
print("sweep cost: %.3f ms" % sweep)
print("collector keys ok; disk=%s gpu_present=%s cores=%s procs=%s" % (
    (sample.get("disk") or {}).get("device"),
    bool((sample.get("gpu") or {}).get("present")),
    len(present),
    procs.get("count"),
))
PY
  then
    echo "collector: pass"
  else
    echo "collector: FAIL (bad json)"
    cat "$collect_log" "$collect_log.err"
    fail=1
  fi
else
  echo "collector: FAIL"
  cat "$collect_log" "$collect_log.err"
  fail=1
fi
rm -f "$collect_log" "$collect_log.err"

echo "== collector sample =="
if python3 - "$ROOT/mainframe/collect.py" <<'PY'
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("mainframe_collect", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mem_total = 1000 * 1024
prev = {
    "10:1": {"ticks": 1000, "read_s": 10.0},
    "11:1": {"ticks": 0, "read_s": 10.0},
    "12:1": {"ticks": 0, "read_s": 10.0},
    "13:1": {"ticks": 0, "read_s": 10.0},
}
rows = [
    {"pid": 10, "start": 1, "comm": "missioncenter-m", "argv0": "/usr/bin/missioncenter", "ticks": 1000, "rss": 250, "read_s": 12.0},
    {"pid": 11, "start": 1, "comm": "worker.bin", "ticks": 100, "rss": 40, "read_s": 12.0},
    {"pid": 12, "start": 1, "comm": "worker.bin", "ticks": 100, "rss": 40, "read_s": 12.0},
    {"pid": 13, "start": 1, "comm": "Web Content", "ticks": 10, "rss": 10, "read_s": 12.0},
]
presented = mod.build_presented(rows, prev, mem_total, 100, 4096)
if presented["byCpu"][0]["name"] != "worker.bin ×2" or presented["byCpu"][0]["text"] != "100%":
    raise SystemExit("presented cpu: %s" % presented["byCpu"])
if presented["byMem"][0]["name"] != "missioncenter":
    raise SystemExit("presented mem: %s" % presented["byMem"])
fresh = mod.build_presented(
    [{"pid": 99, "start": 5, "comm": "new", "ticks": 50, "rss": 1, "read_s": 3.0}],
    {}, mem_total, 100, 4096)
if fresh["byCpu"] != []:
    raise SystemExit("new pid invented cpu percent")
reused = mod.build_presented(
    [{"pid": 10, "start": 9, "comm": "a", "ticks": 500, "rss": 1, "read_s": 4.0}],
    {"10:1": {"ticks": 100, "read_s": 1.0}}, mem_total, 100, 4096)
if reused["byCpu"] != []:
    raise SystemExit("reused pid kept the old baseline")

mod._proc_prev = {}
tick = mod.collect_sample(False)
blob = json.dumps(tick, separators=(",", ":"))
if "error" in tick or "proc_stat" in tick or "route_v4" in tick:
    raise SystemExit("tick sample still has raw fields")
if tick.get("procs") is not None:
    raise SystemExit("tick sample included processes")
if len(blob) > 20000:
    raise SystemExit("tick sample is %d bytes" % len(blob))
try:
    ncpu = int(os.sysconf("SC_NPROCESSORS_ONLN"))
except (OSError, ValueError):
    ncpu = 0
cores = ((tick.get("cpu") or {}).get("cores")) or []
present = [row for row in cores if isinstance(row, dict)]
if len(present) != ncpu:
    raise SystemExit("tick cores %s want %s" % (len(present), ncpu))

first = mod.collect_sample(True)
second = mod.collect_sample(True)
for sample in (first, second):
    procs = sample.get("procs") or {}
    view = procs.get("presented") or {}
    if "rows" in procs:
        raise SystemExit("sample still ships raw process rows")
    if len(view.get("byCpu") or []) > 8 or len(view.get("byMem") or []) > 8:
        raise SystemExit("presented list longer than 8")
    if not isinstance(procs.get("sweep_ms"), (int, float)):
        raise SystemExit("sweep_ms missing")
if first["procs"]["presented"]["byCpu"]:
    raise SystemExit("first sweep invented cpu percent")
if not second["procs"]["presented"]["byCpu"]:
    raise SystemExit("second sweep produced no cpu rows")
print("sweep cost: second %.3f ms" % second["procs"]["sweep_ms"])

# An empty counter file exists, so discovery is not re-run, and the read is
# still not replayed from a previous sample.
idle_dir = tempfile.mkdtemp()
idle_path = os.path.join(idle_dir, "idle")
try:
    with open(idle_path, "w", encoding="utf-8") as handle:
        handle.write("")
    mod._gpu_paths = {"name": "gt0-rc", "idle": idle_path, "freq": idle_path}
    mod._gpu_discover_at = time.monotonic()
    bad_idle = mod.gpu_sample()
    if bad_idle.get("present") is not True or bad_idle.get("idle_ms") is not None:
        raise SystemExit("idle read was cached or dropped: %s" % bad_idle)
    again = mod.gpu_sample()
    if again.get("idle_ms") is not None:
        raise SystemExit("second idle read returned a cached counter")
    if mod._gpu_paths.get("idle") != idle_path:
        raise SystemExit("an existing counter path was rediscovered")
finally:
    shutil.rmtree(idle_dir, ignore_errors=True)

discoveries = {"n": 0}

def fake_discover():
    discoveries["n"] += 1
    return None

mod.discover_gpu = fake_discover
mod._gpu_paths = False
mod._gpu_discover_at = 0.0
mod.gpu_sample()
mod.gpu_sample()
if discoveries["n"] != 1:
    raise SystemExit("gpu discovery ran %s times before the 30s retry" % discoveries["n"])
mod._gpu_discover_at = time.monotonic() - 31.0
mod.gpu_sample()
if discoveries["n"] != 2:
    raise SystemExit("gpu discovery did not retry after 30s (%s)" % discoveries["n"])

v4_ok = "wlo1 00000000 0101A8C0 0003 0 0 100 00000000 0 0 0\n"
v4_flags = "wlo1 00000000 0101A8C0 0001 0 0 100 00000000 0 0 0\n"
v4_down = "wlo1 00000000 0101A8C0 0000 0 0 100 00000000 0 0 0\n"
v4_gw = "wlo1 00000000 0101A8C0 0002 0 0 100 00000000 0 0 0\n"
v4_mask = "wlo1 00000000 0101A8C0 0003 0 0 100 FFFFFFFF 0 0 0\n"
if mod.parse_ipv4_default(v4_ok) != "wlo1" or mod.parse_ipv4_default(v4_flags) != "wlo1":
    raise SystemExit("ipv4 default route not accepted")
if mod.parse_ipv4_default(v4_down) is not None or mod.parse_ipv4_default(v4_gw) is not None or mod.parse_ipv4_default(v4_mask) is not None:
    raise SystemExit("ipv4 down route or non-zero mask was accepted")
v6_ok = "00000000000000000000000000000000 00 a b c 00000064 d e 00000003 f wlo1\n"
v6_prefix = "00000000000000000000000000000000 40 a b c 00000064 d e 00000003 f wlo1\n"
v6_flags = "00000000000000000000000000000000 00 a b c 00000064 d e 00000001 f wlo1\n"
v6_down = "00000000000000000000000000000000 00 a b c 00000064 d e 00000000 f wlo1\n"
v6_lo = "00000000000000000000000000000000 00 a b c 00000064 d e 00200200 f lo\n"
if mod.parse_ipv6_default(v6_ok) != "wlo1" or mod.parse_ipv6_default(v6_flags) != "wlo1":
    raise SystemExit("ipv6 default route not accepted")
if mod.parse_ipv6_default(v6_prefix) is not None or mod.parse_ipv6_default(v6_down) is not None:
    raise SystemExit("ipv6 route with a non-zero prefix or without UP was accepted")
if mod.parse_ipv6_default(v6_lo) is not None:
    raise SystemExit("ipv6 lo prefix-0 route was accepted")
print("collector sample ok")
PY
then
  echo "collector sample: pass"
else
  echo "collector sample: FAIL"
  fail=1
fi

# Each qs run is its own session. Cleanup kills only that session, the
# collector group it spawned, or the systemd scope it was placed in.
# $4 is hold_ms. $5 is timeout_s, not a core count: layout cores come from nproc.
# $1 "selftest" checks the gate math and does not launch qs.
# $8 "live" is a real Wayland window: no offscreen platform, 5 s wait, 30 s sample, < 2%.
run_qml() {
  if python3 - "$ROOT" "$1" "${2:-}" "${3:-}" "${4:-}" "${5:-}" "${6:-}" "${7:-}" "${8:-}" <<'PY'
import atexit
import errno
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

def cpu_core_percent(before, after, elapsed, mode, clk):
    """Percent of one core. cgroup usage is microseconds; proc mode is ticks."""
    if elapsed <= 0 or before is None or after is None:
        return None
    delta = after - before
    if mode == "cgroup":
        return 100.0 * delta / (elapsed * 1e6)
    ticks = clk or 100
    if ticks <= 0:
        return None
    return 100.0 * delta / (elapsed * ticks)


def cpu_gate_limit(live):
    """Offscreen software rendering overstates cost. Live is the real bar."""
    return 2.0 if live else 3.0


def cpu_gate_verdict(pct, limit, mode=''):
    if pct is None or pct < 0:
        return "FAIL"
    return power_gate_verdict("FAIL", mode) if pct >= limit else "PASS"


def frame_gate_verdict(frame_count, elapsed, connected, saw_frame, limit=3, mode=''):
    if not connected or not saw_frame or elapsed <= 0 or frame_count < 0:
        return "FAIL"
    return power_gate_verdict("FAIL", mode) if frame_count / elapsed > limit else "PASS"


def power_gate_verdict(verdict, mode):
    return "REPORT" if mode == "report" and verdict == "FAIL" else verdict


def sample_cadence_min(window_s):
    """1 Hz samples. The floor is 90% of the window: 18 in 20 s, 27 in 30 s."""
    try:
        window = int(window_s)
    except (TypeError, ValueError):
        return 1
    if window < 1:
        return 1
    need = (window * 9) // 10
    if need < 1:
        return 1
    return need


def measure_plan(live):
    """(warmup_s, window_s). Live waits 5 s, then samples for 30 s."""
    if live:
        return 5.0, 30.0
    return 2.0, 20.0


def launch_env(base, live):
    """Normal qs launch when live. Offscreen only for the regression run."""
    env = dict(base)
    env.pop("MAINFRAME_SMOKE_LIVE", None)
    if live:
        env.pop("QT_QPA_PLATFORM", None)
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def qs_command(qs, config_path):
    """qs -p <config>. The platform is an environment variable, not an argument."""
    return [qs, "-p", config_path]


def requested_machine_tab(env, log):
    try:
        name = env.get("MAINFRAME_SMOKE_TAB_NAME")
        if name:
            matches = re.findall(r'TAB index=(\d+) status=\S+ wsl=\d+ local=\d+ name=("(?:\\.|[^"\\])*")', log)
            return next((int(index) for index, value in reversed(matches) if json.loads(value) == name), -1)
        return int(env["MAINFRAME_SMOKE_TAB"])
    except (ValueError, TypeError, KeyError):
        return -1


def gate_selftest():
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    check(cpu_gate_limit(False) == 3.0, "offscreen limit is 3.0")
    check(cpu_gate_limit(True) == 2.0, "live limit is 2.0")
    check(measure_plan(False) == (2.0, 20.0), "offscreen plan")
    check(measure_plan(True) == (5.0, 30.0), "live plan")
    check(cpu_gate_verdict(2.999, 3.0) == "PASS", "2.999 passes 3.0")
    check(cpu_gate_verdict(3.0, 3.0) == "FAIL", "3.0 fails the offscreen gate")
    check(cpu_gate_verdict(1.999, 2.0) == "PASS", "1.999 passes 2.0")
    check(cpu_gate_verdict(2.0, 2.0) == "FAIL", "2.0 fails the live gate")
    check(cpu_gate_verdict(-0.01, 3.0) == "FAIL", "negative cpu fails")
    check(cpu_gate_verdict(None, 2.0) == "FAIL", "missing cpu fails")
    check(frame_gate_verdict(60, 20, True, True) == 'PASS', '3 fps passes')
    check(frame_gate_verdict(61, 20, True, True) == 'FAIL', 'over 3 fps fails')
    check(frame_gate_verdict(160, 20, True, True, 8) == 'PASS', '8 fps passes')
    check(frame_gate_verdict(161, 20, True, True, 8) == 'FAIL', 'over 8 fps fails')
    check(frame_gate_verdict(0, 20, True, True) == 'PASS', 'idle window may render no frames')
    check(frame_gate_verdict(0, 20, False, False) == 'FAIL', 'missing frame probe fails')
    check(cpu_gate_verdict(4.0, 3.0, 'report') == 'REPORT', 'report mode reports over-limit cpu')
    check(frame_gate_verdict(61, 20, True, True, 3, 'report') == 'REPORT', 'report mode reports over-limit frames')
    check(cpu_gate_verdict(1.0, 3.0, 'report') == 'PASS', 'report mode passes cpu under limit')
    check(frame_gate_verdict(60, 20, True, True, 3, 'report') == 'PASS', 'report mode passes frames under limit')
    check(cpu_gate_verdict(None, 3.0, 'report') == 'FAIL', 'report mode fails missing cpu')
    check(cpu_gate_verdict(-0.01, 3.0, 'report') == 'FAIL', 'report mode fails negative cpu')
    check(frame_gate_verdict(0, 20, False, False, 3, 'report') == 'FAIL', 'report mode fails missing frame probe')
    check(frame_gate_verdict(0, 20, True, False, 3, 'report') == 'FAIL', 'report mode fails unseen frame probe')
    check(frame_gate_verdict(0, 0, True, True, 3, 'report') == 'FAIL', 'report mode fails invalid frame window')
    pct = cpu_core_percent(0, 1000000, 10.0, "cgroup", 100)
    check(pct is not None and abs(pct - 10.0) < 1e-9, "cgroup 10%")
    pct = cpu_core_percent(50, 150, 10.0, "proc", 100)
    check(pct is not None and abs(pct - 10.0) < 1e-9, "proc ticks 10%")
    check(cpu_core_percent(0, 1, 0, "cgroup", 100) is None, "zero elapsed")
    check(sample_cadence_min(20) == 18, "cadence over 20 s")
    check(sample_cadence_min(30) == 27, "cadence over 30 s")
    live_env = launch_env({"QT_QPA_PLATFORM": "offscreen", "MAINFRAME_SMOKE_LIVE": "1", "HOME": "/tmp"}, True)
    check("QT_QPA_PLATFORM" not in live_env, "live drops offscreen")
    check("MAINFRAME_SMOKE_LIVE" not in live_env, "live flag is not forwarded")
    check(live_env.get("HOME") == "/tmp", "live keeps the rest of the environment")
    off_env = launch_env({"HOME": "/tmp"}, False)
    check(off_env.get("QT_QPA_PLATFORM") == "offscreen", "offscreen platform")
    check(qs_command("qs", "mainframe") == ["qs", "-p", "mainframe"], "launch is qs -p mainframe")
    sample_tabs = 'TAB index=2 status=connected wsl=0 local=0 name="Work host"'
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB_NAME": "Work host"}, sample_tabs) == 2, "name-only machine tab")
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB_NAME": "Missing"}, sample_tabs) == -1, "missing machine tab")
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB": "1"}, sample_tabs) == 1, "numeric machine tab")
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB_NAME": 'Work "host"'}, 'TAB index=3 status=connected wsl=0 local=0 name="Work \\"host\\"" extra="quoted"') == 3, "quoted machine tab with trailing fields")
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB_NAME": "Work"}, 'TAB index=3 status=connected wsl=0 local=0 name="bad\\q"') == -1, "invalid tab name json")
    check(requested_machine_tab({"MAINFRAME_SMOKE_TAB": "invalid"}, sample_tabs) == -1, "invalid numeric machine tab")
    check(requested_machine_tab({}, sample_tabs) == -1, "missing numeric machine tab")
    if failures:
        for msg in failures:
            sys.stderr.write("cpu gate math: %s\n" % msg)
        return 1
    sys.stdout.write("cpu gate math: offscreen < 3.0% over 20s after 2s; live < 2.0% over 30s after 5s\n")
    return 0


if len(sys.argv) > 2 and sys.argv[2] == "selftest":
    sys.exit(gate_selftest())

root = sys.argv[1]
width = int(sys.argv[2])
height = int(sys.argv[3])
hold = int(sys.argv[4])
tmo = float(sys.argv[5])
expect_cols = int(sys.argv[6])
expect_rows = int(sys.argv[7])
measure = sys.argv[8] == "1"
mode = sys.argv[9] if len(sys.argv) > 9 else ""
live = mode == "live"
machine = mode == "machine"

def online_cpus():
    try:
        count = int(os.sysconf("SC_NPROCESSORS_ONLN"))
        if count > 0:
            return count
    except (OSError, ValueError):
        pass
    try:
        text = subprocess.check_output(["nproc"], text=True).strip()
        return int(text)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 1

nproc = online_cpus()
my_pgrp = os.getpgrp()
known = {}
pgrps = set()
cg = None

def read_stat(pid):
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    cut = text.rfind(")")
    if cut < 0:
        return None
    rest = text[cut + 2:].split()
    if len(rest) < 20:
        return None
    try:
        return {
            "ppid": int(rest[1]),
            "pgrp": int(rest[2]),
            "start": int(rest[19]),
            "ticks": int(rest[11]) + int(rest[12]),
            # Reaped children. Live children are still in their own utime/stime.
            "cutime": int(rest[13]),
            "cstime": int(rest[14]),
        }
    except ValueError:
        return None

def note(pid, st):
    if not st:
        return
    if st["pgrp"] <= 1 or st["pgrp"] == my_pgrp:
        return
    known[pid] = st["start"]
    pgrps.add(st["pgrp"])

def snapshot(root_pid):
    stats = {}
    children = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return {}
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        st = read_stat(pid)
        if not st:
            continue
        stats[pid] = st
        children.setdefault(st["ppid"], []).append(pid)
    if root_pid not in stats:
        return {}
    out = {}
    stack = [root_pid]
    seen = set()
    while stack:
        pid = stack.pop()
        if pid in seen or pid not in stats:
            continue
        seen.add(pid)
        out[pid] = stats[pid]
        for kid in children.get(pid, []):
            stack.append(kid)
    return out

def note_tree(root_pid):
    for pid, st in snapshot(root_pid).items():
        note(pid, st)

def scope_path(unit):
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", "-p", "ControlGroup", "--value", unit + ".scope"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    cg_rel = out.stdout.strip()
    if not cg_rel.startswith("/"):
        return None
    path = "/sys/fs/cgroup" + cg_rel
    if os.path.isdir(path):
        return path
    return None

def cgroup_pids(path):
    try:
        with open(os.path.join(path, "cgroup.procs"), "r", encoding="utf-8") as handle:
            return [int(line) for line in handle if line.strip().isdigit()]
    except OSError:
        return []

def note_cgroup():
    if not cg:
        return
    for pid in cgroup_pids(cg):
        note(pid, read_stat(pid))

def usage_usec(path):
    try:
        with open(os.path.join(path, "cpu.stat"), "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("usage_usec "):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None

def tree_ticks(root_pid):
    total = 0
    alive = False
    snap = snapshot(root_pid)
    for pid, st in snap.items():
        total += st["ticks"]
        alive = True
        # Reaped descendants are no longer live in the tree.
        total += st["cutime"] + st["cstime"]
    return total, alive

def component_ticks(root_pid):
    """Identify the qs and collector processes, retaining their start times."""
    found = {}
    for pid, st in snapshot(root_pid).items():
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as handle:
                args = handle.read().split(b'\0')
        except OSError:
            continue
        if args and os.path.basename(os.fsdecode(args[0])) == 'qs':
            found['qs'] = (pid, st['start'], st['ticks'])
        elif any(os.path.basename(os.fsdecode(arg)) == 'collect.py' for arg in args):
            found['collector'] = (pid, st['start'], st['ticks'])
    return found

def leftovers():
    alive = []
    for pid, start in list(known.items()):
        st = read_stat(pid)
        if st and st["start"] == start:
            alive.append(pid)
    if cg and os.path.isdir(cg):
        for pid in cgroup_pids(cg):
            if pid not in alive:
                st = read_stat(pid)
                if st:
                    note(pid, st)
                    alive.append(pid)
    return alive

def kill_recorded():
    if cg:
        try:
            with open(os.path.join(cg, "cgroup.kill"), "w", encoding="utf-8") as handle:
                handle.write("1\n")
        except OSError:
            pass
    for pgrp in list(pgrps):
        if pgrp <= 1 or pgrp == my_pgrp:
            continue
        # Signal only when the recorded leader is still that process group.
        leader_st = read_stat(pgrp)
        start = known.get(pgrp)
        if start is None or not leader_st:
            continue
        if leader_st["start"] != start or leader_st["pgrp"] != pgrp:
            continue
        try:
            os.kill(-pgrp, signal.SIGKILL)
        except OSError:
            pass

def decode(status):
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1

qs = shutil.which("qs")
if not qs:
    print("qml load: qs is not on PATH")
    sys.exit(1)

unit = "mainframe-smoke-%d-%d-%d" % (os.getpid(), width, random.randint(0, 999999))
use_scope = shutil.which("systemd-run") is not None and os.environ.get("MAINFRAME_SMOKE_NO_SCOPE") != "1"
qs_cmd = qs_command(qs, os.path.join(root, "mainframe"))
if use_scope:
    argv = [
        "systemd-run", "--user", "--scope", "--unit", unit, "--collect", "--quiet", "--",
    ] + qs_cmd
else:
    argv = list(qs_cmd)

env = launch_env(os.environ, live)
if measure:
    env["MAINFRAME_USAGE_SCAN"] = "0"
env["MAINFRAME_SMOKE"] = "1"
env["MAINFRAME_SMOKE_W"] = str(width)
env["MAINFRAME_SMOKE_H"] = str(height)
env["MAINFRAME_SMOKE_MS"] = str(hold)
if measure and not live:
    env["MAINFRAME_FRAME_DIAGNOSTIC"] = "1"
    env["QSG_RENDER_LOOP"] = "basic"
env.pop("MAINFRAME_SMOKE_TAB", None)
if machine and not env.get("MAINFRAME_SMOKE_TAB_NAME"):
    env["MAINFRAME_SMOKE_TAB"] = "1"
xdg_home = tempfile.mkdtemp(prefix="mainframe-xdg-")
env["XDG_CONFIG_HOME"] = xdg_home
if mode in ("cyber-static", "cyber-all"):
    # Boot is tested separately. Trigger ambient effects during the measurement.
    env["MAINFRAME_SMOKE_SKIP_BOOT"] = "1"
    env["MAINFRAME_SMOKE_STYLE_EXPECTED"] = mode
    if mode == "cyber-all":
        env["MAINFRAME_SMOKE_AMBIENT_NOW"] = "1"
    config_dir = os.path.join(xdg_home, "mainframe")
    os.makedirs(config_dir)
    switches = {} if mode == "cyber-all" else {key: False for key in (
        "dataAnimations", "titleGlitch", "scanlineSweep", "pulsingStatusDots", "bootSequence")}
    with open(os.path.join(config_dir, "settings.json"), "w", encoding="utf-8") as config:
        json.dump({"style": "cyberpunk", "cyber": switches}, config)
    print("style measurement: " + mode, flush=True)
atexit.register(lambda: shutil.rmtree(xdg_home, ignore_errors=True))

log_fd, log_path = tempfile.mkstemp(prefix="mainframe-smoke-")
os.close(log_fd)
leader = os.fork()
if leader == 0:
    try:
        os.setsid()
        out = os.open(log_path, os.O_WRONLY | os.O_TRUNC)
        os.dup2(out, 1)
        os.dup2(out, 2)
        inn = os.open("/dev/null", os.O_RDONLY)
        os.dup2(inn, 0)
        for fd in range(3, 64):
            try:
                os.close(fd)
            except OSError:
                pass
        os.execvpe(argv[0], argv, env)
    finally:
        os._exit(127)

fail = False
code = None
cpu_mode = None
before = after = None
components_before = components_after = None
process_baseline = {}
process_last = {}
collector_counts = []
t0 = t1 = None
window_at = None
clk = os.sysconf("SC_CLK_TCK") or 100
started = time.monotonic()
warmup_s, window_s = measure_plan(live)
deadline = started + tmo
try:
    while True:
        try:
            wpid, status = os.waitpid(leader, os.WNOHANG)
        except OSError:
            code = 1
            break
        note_tree(leader)
        if use_scope and cg is None:
            cg = scope_path(unit)
        note_cgroup()
        now = time.monotonic()
        if wpid == leader:
            code = decode(status)
            break
        if now >= deadline:
            kill_recorded()
            try:
                os.kill(leader, signal.SIGKILL)
            except OSError:
                pass
            try:
                _, status = os.waitpid(leader, 0)
                code = 124
            except OSError:
                code = 124
            break
        if measure and window_at is None and (now - started) >= warmup_s:
            components_before = component_ticks(leader)
            if use_scope and cg and usage_usec(cg) is not None:
                before = usage_usec(cg)
                cpu_mode = "cgroup"
            else:
                print("cpu sample: systemd-run unavailable, fell back to /proc ticks")
                before, alive = tree_ticks(leader)
                cpu_mode = "proc"
                if not alive:
                    print("cpu qs+collector: qs pid %s was not alive" % leader)
                    fail = True
            t0 = time.time() * 1000.0
            window_at = now
        if measure and window_at is not None and t1 is None and (now - window_at) >= window_s:
            components_after = component_ticks(leader)
            if cpu_mode == "cgroup":
                after = usage_usec(cg) if cg else None
            else:
                after, alive = tree_ticks(leader)
                if not alive:
                    print("cpu qs+collector: qs exited before the %.0fs sample ended" % window_s)
                    fail = True
            t1 = time.time() * 1000.0
        if measure and window_at is not None and t1 is None:
            current = snapshot(leader)
            count = 0
            for pid, st in current.items():
                try:
                    with open('/proc/%d/cmdline' % pid, 'rb') as handle:
                        args = [os.fsdecode(arg) for arg in handle.read().split(b'\0') if arg]
                except OSError:
                    continue
                if not args:
                    continue
                key = (pid, st['start'])
                label = os.path.basename(args[0]) + ' ' + next((os.path.basename(arg) for arg in args[1:] if arg.endswith('.py')), '')
                if any(os.path.basename(arg) == 'collect.py' for arg in args) and '--storage' not in args:
                    count += 1
                if key not in process_baseline:
                    process_baseline[key] = st['ticks'] if now == window_at else 0
                process_last[key] = (st['ticks'], label)
            collector_counts.append(count)
        # Sample frequently enough to catch most short-lived helpers.
        time.sleep(0.02 if measure and window_at is not None and t1 is None else 0.1)
finally:
    if code is None:
        kill_recorded()
        try:
            os.kill(leader, signal.SIGKILL)
        except OSError:
            pass
        try:
            os.waitpid(leader, 0)
        except OSError:
            pass
        code = 124

try:
    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        log = handle.read()
finally:
    try:
        os.remove(log_path)
    except OSError:
        pass

log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)

def tokens(line):
    found = {}
    for key, value in re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=(-?\d+)(?=\s|$)", line):
        found[key] = int(value)
    return found

def last_word(text, word):
    last = None
    pattern = re.compile(r"(?:^|\s)" + re.escape(word) + r"(?:\s|$)")
    for line in text.splitlines():
        if pattern.search(line):
            last = line
    return last

# Case-sensitive. Add a line here only after it showed up in a real qs log
# and is unrelated to our QML.
HARMLESS_SUBSTR = ()
fail_re = re.compile(r"Error|Warning|Binding loop|Cannot assign|Unable to|failed|TypeError|ReferenceError")
bad_lines = []
for line in log.splitlines():
    if not fail_re.search(line):
        continue
    if any(token and token in line for token in HARMLESS_SUBSTR):
        continue
    bad_lines.append(line)
if bad_lines:
    print("qml %dx%d: FAIL (log)" % (width, height))
    sys.stdout.write("\n".join(bad_lines) + "\n")
    fail = True

if machine:
    active_line = last_word(log, "ACTIVE")
    active = tokens(active_line or "")
    requested_tab = requested_machine_tab(env, log)
    if active.get("tab") != requested_tab or active.get("selected") != requested_tab - 1 or active.get("highlighted") != requested_tab:
        print("qml %dx%d: FAIL active tab %s, expected tab=%s selected=%s" % (width, height, active, requested_tab, requested_tab - 1))
        fail = True

layout_line = last_word(log, "LAYOUT")
gauge_line = last_word(log, "GAUGE")
for line in log.splitlines():
    if re.search(r"(?:^|\s)(LAYOUT|SMOKE|GAUGE)(?:\s|$)", line):
        print(line.strip())

if layout_line is None:
    print("qml %dx%d: FAIL (no layout, qs exit %s)" % (width, height, code))
    sys.stdout.write(log)
    fail = True
elif machine:
    if "view=machine" not in layout_line or gauge_line is None:
        print("qml %dx%d: FAIL (local machine layout or gauge missing)" % (width, height))
        fail = True
    else:
        got = tokens(layout_line)
        want = {
            "w": width,
            "h": height,
            "cols": expect_cols,
            "rows": expect_rows,
            "overflow": 0,
            "cores": nproc,
        }
        for key, value in want.items():
            if got.get(key) != value:
                print("qml %dx%d: FAIL layout %s=%s want %s" % (width, height, key, got.get(key), value))
                print(layout_line.strip())
                fail = True
                break
        gauge = tokens(gauge_line)
        for key in ("meters", "minMeterH", "minMeterW", "minLabel"):
            if key not in gauge:
                print("qml %dx%d: FAIL gauge missing %s" % (width, height, key))
                print(gauge_line.strip())
                fail = True
        meters = gauge.get("meters")
        if nproc > 32:
            if not fail and meters != 0:
                print("qml %dx%d: FAIL meters=%s want 0 (compact)" % (width, height, meters))
                fail = True
        else:
            if not fail and meters != nproc:
                print("qml %dx%d: FAIL meters=%s want %s" % (width, height, meters, nproc))
                fail = True
            if not fail and (gauge.get("minMeterH", 0) < 14 or gauge.get("minMeterW", 0) < 14):
                print("qml %dx%d: FAIL core meter below 14px" % (width, height))
                print(gauge_line.strip())
                fail = True
        if not fail and gauge.get("minLabel", 0) < 12:
            print("qml %dx%d: FAIL label below 12px" % (width, height))
            print(gauge_line.strip())
            fail = True
else:
    got = tokens(layout_line)
    for key, value in {"w": width, "h": height, "overflow": 0}.items():
        if got.get(key) != value:
            print("qml %dx%d: FAIL overview %s=%s want %s" % (width, height, key, got.get(key), value))
            fail = True
    if "view=systems" not in layout_line or got.get("rows", 0) < 1:
        print("qml %dx%d: FAIL overview systems or local row missing" % (width, height))
        fail = True

if mode in ("cyber-static", "cyber-all"):
    expected = "CYBER static=true motion=" + ("5" if mode == "cyber-all" else "0")
    if expected not in log:
        print("style measurement: FAIL (expected %s)" % expected)
        fail = True
    else:
        print("style measurement: verified " + expected)

if mode == "cyber-all":
    for effect in ("glitch", "sweep"):
        stamps = [int(match.group(1)) for match in re.finditer(r"AMBIENT " + effect + r" t=(\d+)", log)]
        if t0 is None or t1 is None or not any(t0 <= stamp <= t1 for stamp in stamps):
            print("ambient %s: FAIL (not observed during measurement)" % effect)
            fail = True
        else:
            print("ambient %s: observed during measurement" % effect)

if measure:
    if t0 is None or t1 is None or before is None or after is None:
        print("cpu qs+collector: measurement window did not complete")
        fail = True
    else:
        elapsed = (t1 - t0) / 1000.0
        if elapsed <= 0:
            print("cpu qs+collector: bad elapsed")
            fail = True
        else:
            pct = cpu_core_percent(before, after, elapsed, cpu_mode, clk)
            limit = cpu_gate_limit(live)
            verdict = cpu_gate_verdict(pct, limit, os.environ.get('MAINFRAME_SMOKE_GATES', ''))
            kind = "live" if live else "offscreen"
            if pct is None:
                print("cpu qs+collector: no reading (%s)" % kind)
            else:
                print("cpu qs+collector: %.2f%% of one core over %.1fs (%s)" % (pct, elapsed, cpu_mode))
            print("cpu process breakdown: sampled /proc ticks; short-lived processes may be missed")
            sampled = 0.0
            for key, (ticks, label) in sorted(process_last.items(), key=lambda item: item[1][0] - process_baseline[item[0]], reverse=True):
                part = cpu_core_percent(process_baseline[key], ticks, elapsed, 'proc', clk)
                sampled += part
                print("cpu pid %d: %.2f%% of one core (%s)" % (key[0], part, label))
            if pct is not None:
                print("cpu unattributed: %.2f%% of one core (sampling and tick rounding)" % max(0.0, pct - sampled))
            if not collector_counts or any(count != 1 for count in collector_counts):
                print("local collector count: FAIL (observed %s)" % sorted(set(collector_counts)))
                fail = True
            else:
                print("local collector count: 1 throughout sampled window")
            print("cpu gate: %s (< %.1f%% of one core, %s)" % (verdict, limit, kind))
            if verdict == "FAIL":
                fail = True
            if not live:
                for name in ('qs', 'collector'):
                    first = (components_before or {}).get(name)
                    last = (components_after or {}).get(name)
                    if not first or not last or first[:2] != last[:2]:
                        print('cpu %s: unavailable or process changed' % name)
                        fail = True
                    else:
                        part = cpu_core_percent(first[2], last[2], elapsed, 'proc', clk)
                        print('cpu %s: %.2f%% of one core over %.1fs (proc)' % (name, part, elapsed))
                frames = []
                for line in log.splitlines():
                    match = re.search(r'(?:^|\s)FRAME t=(\d+)(?:\s|$)', line)
                    if match and t0 <= int(match.group(1)) <= t1:
                        frames.append(int(match.group(1)))
                fps = len(frames) / elapsed
                connected = 'FRAME_DIAGNOSTIC connected' in log
                saw_frame = bool(re.search(r'(?:^|\s)FRAME t=\d+(?:\s|$)', log, re.MULTILINE))
                print('frames: %d over %.1fs = %.2f fps' % (len(frames), elapsed, fps))
                frame_limit = 8 if mode == 'cyber-all' else 3
                frame_verdict = frame_gate_verdict(
                    len(frames), elapsed, connected, saw_frame, frame_limit,
                    os.environ.get('MAINFRAME_SMOKE_GATES', ''))
                if frame_verdict == 'FAIL':
                    print('frame gate: FAIL (expected <= %d fps and a working probe)' % frame_limit)
                    fail = True
                elif frame_verdict == 'REPORT':
                    print('frame gate: REPORT (expected <= %d fps and a working probe)' % frame_limit)
                else:
                    print('frame gate: PASS (<= %d fps)' % frame_limit)
        samples = 0
        sample_re = re.compile(r"(?:^|\s)SAMPLE(?:\s|$)")
        stamp_re = re.compile(r"(?:^|\s)t=(\d+)(?=\s|$)")
        for line in log.splitlines():
            if not sample_re.search(line):
                continue
            stamp = stamp_re.search(line)
            if not stamp:
                continue
            stamp_ms = int(stamp.group(1))
            if t0 <= stamp_ms <= t1:
                samples += 1
        need = sample_cadence_min(window_s)
        print("cpu samples: %d" % samples)
        if samples < need:
            print("cpu samples: FAIL (want >= %d)" % need)
            fail = True

left_deadline = time.monotonic() + 2.0
alive = leftovers()
while alive and time.monotonic() < left_deadline:
    time.sleep(0.1)
    alive = leftovers()
if alive:
    print("leftover collect.py after quit: %s" % " ".join(str(pid) for pid in alive))
    kill_recorded()
    fail = True
else:
    print("collector gone within 2s")

if code != 0:
    print("qml %dx%d: FAIL (qs exit %s)" % (width, height, code))
    if not fail:
        sys.stdout.write(log)
    fail = True

if fail:
    sys.exit(1)
print("qml %dx%d: pass (qs exit %s)" % (width, height, code))
PY
  then
    if [[ "$1" == "selftest" ]]; then
      echo "cpu gate math: pass"
    else
      echo "qml ${1}x${2}: pass"
    fi
  else
    if [[ "$1" == "selftest" ]]; then
      echo "cpu gate math: FAIL"
    else
      echo "qml ${1}x${2}: FAIL"
    fi
    fail=1
  fi
}

echo "== install link =="
if ! grep -q 'ln -sfnT' "$ROOT/scripts/mainframe-install.sh" || ! grep -q 'mv -T' "$ROOT/scripts/mainframe-install.sh"; then
  echo "install: FAIL atomic link commands missing"
  fail=1
else
  cfg="$(mktemp -d)"
  install_out="$(mktemp)"
  # Fresh install.
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out" \
      && [[ "$(readlink "$cfg/quickshell/mainframe")" == "$ROOT/mainframe" ]] \
      && grep -q 'linked' "$install_out" && ! grep -q 'already' "$install_out"; then
    echo "install fresh: pass"
  else
    echo "install fresh: FAIL"
    cat "$install_out"
    fail=1
  fi
  # Reinstall of the same checkout.
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out" \
      && grep -q 'already linked' "$install_out" \
      && [[ "$(readlink "$cfg/quickshell/mainframe")" == "$ROOT/mainframe" ]]; then
    echo "install reinstall: pass"
  else
    echo "install reinstall: FAIL"
    cat "$install_out"
    fail=1
  fi
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-uninstall.sh" >"$install_out" \
      && [[ ! -e "$cfg/quickshell/mainframe" && ! -L "$cfg/quickshell/mainframe" ]] \
      && grep -q 'removed' "$install_out"; then
    echo "uninstall: pass"
  else
    echo "uninstall: FAIL"
    cat "$install_out"
    fail=1
  fi
  # Upgrade from another checkout that names AppId mainframe.
  old="$cfg/old-checkout"
  mkdir -p "$old"
  printf '%s\n' '//@ pragma AppId mainframe' '//@ pragma ShellId mainframe' > "$old/shell.qml"
  ln -s "$old" "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out" \
      && [[ "$(readlink "$cfg/quickshell/mainframe")" == "$ROOT/mainframe" ]] \
      && grep -q 'replaced' "$install_out" && grep -F -q "$old" "$install_out"; then
    echo "install upgrade: pass"
  else
    echo "install upgrade: FAIL"
    cat "$install_out"
    fail=1
  fi
  # Dangling symlink.
  rm -f "$cfg/quickshell/mainframe"
  ln -s "$cfg/missing-checkout" "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out" \
      && [[ "$(readlink "$cfg/quickshell/mainframe")" == "$ROOT/mainframe" ]] \
      && grep -q 'dangling' "$install_out"; then
    echo "install dangling: pass"
  else
    echo "install dangling: FAIL"
    cat "$install_out"
    fail=1
  fi
  rm -f "$cfg/quickshell/mainframe"
  ln -s "$cfg/missing-checkout" "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-uninstall.sh" >"$install_out" \
      && [[ ! -L "$cfg/quickshell/mainframe" ]] && grep -q 'dangling' "$install_out"; then
    echo "uninstall dangling: pass"
  else
    echo "uninstall dangling: FAIL"
    cat "$install_out"
    fail=1
  fi
  # A real directory is refused.
  rm -rf "$cfg/quickshell/mainframe"
  mkdir -p "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out"; then
    echo "install directory: FAIL overwrote a directory"
    fail=1
  elif [[ -d "$cfg/quickshell/mainframe" && ! -L "$cfg/quickshell/mainframe" ]]; then
    echo "install refuse directory: pass"
  else
    echo "install refuse directory: FAIL"
    fail=1
  fi
  # A real file is refused.
  rm -rf "$cfg/quickshell/mainframe"
  echo kept > "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out"; then
    echo "install file: FAIL overwrote a real file"
    fail=1
  elif [[ -f "$cfg/quickshell/mainframe" && ! -L "$cfg/quickshell/mainframe" ]]; then
    echo "install refuse file: pass"
  else
    echo "install refuse file: FAIL"
    fail=1
  fi
  # Race: TARGET is a symlink to a Mainframe directory. ln without -T would
  # create $old/mainframe. The real script must replace the symlink itself.
  rm -rf "$cfg/quickshell/mainframe"
  race_old="$cfg/race-old"
  mkdir -p "$race_old"
  printf '%s\n' '//@ pragma AppId mainframe' '//@ pragma ShellId mainframe' > "$race_old/shell.qml"
  ln -s "$race_old" "$cfg/quickshell/mainframe"
  if XDG_CONFIG_HOME="$cfg" "$ROOT/scripts/mainframe-install.sh" >"$install_out" \
      && [[ ! -e "$race_old/mainframe" && ! -L "$race_old/mainframe" ]] \
      && [[ "$(readlink "$cfg/quickshell/mainframe")" == "$ROOT/mainframe" ]]; then
    echo "install race: pass"
  else
    echo "install race: FAIL"
    cat "$install_out"
    fail=1
  fi
  rm -rf "$cfg"
  rm -f "$install_out"
fi

echo "== cpu gate math =="
run_qml selftest

if [[ "${MAINFRAME_SMOKE_NO_GUI:-}" == "1" ]]; then
  echo "GUI and SSH smoke checks: skipped (MAINFRAME_SMOKE_NO_GUI=1)"
else
echo "== qml load =="
if ! command -v qs >/dev/null 2>&1; then
  echo "qml load: qs is not on PATH; cannot verify"
  fail=1
else
  if python3 - "$ROOT" <<'PY'
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(sys.argv[1]) / 'mainframe'
qml = sorted(root.rglob('*.qml'))
sources = qml + sorted(root.rglob('*.js'))
removed = re.compile(r'\bkillGroup\b')
bad = [(path, n) for path in sources for n, line in enumerate(path.read_text().splitlines(), 1) if removed.search(line)]
if bad:
    for path, line in bad:
        print('removed helper reference: %s:%s' % (path, line))
    sys.exit(1)
lint = shutil.which('qmllint') or ('/usr/lib/qt6/bin/qmllint' if Path('/usr/lib/qt6/bin/qmllint').is_file() else None)
if not lint:
    print('qmllint: not available, skipped; removed helper source check passed')
    sys.exit(0)
result = subprocess.run([lint, '--json', '-'] + [str(p) for p in qml], capture_output=True, text=True)
try:
    data = json.loads(result.stdout)
except ValueError:
    print('qmllint JSON unavailable; checking text diagnostics')
    result = subprocess.run([lint] + [str(p) for p in qml], capture_output=True, text=True)
    if result.returncode or removed.search(result.stdout + result.stderr):
        print((result.stdout + result.stderr)[-3000:])
        sys.exit(1)
else:
    if result.returncode:
        print('qmllint failed:', result.stderr[-3000:])
        sys.exit(1)
    for item in data.get('files', []):
        lines = Path(item['filename']).read_text().splitlines()
        for warning in item.get('warnings', []):
            number = warning.get('line', 0)
            line = lines[number - 1] if 0 < number <= len(lines) else ''
            if removed.search(warning.get('message', '') + ' ' + line):
                print('removed helper diagnostic:', item['filename'], number, warning.get('message'))
                sys.exit(1)
print('qmllint: checked %d QML files; removed helper check passed' % len(qml))
PY
  then
    echo "qmllint: pass"
  else
    echo "qmllint: FAIL"
    fail=1
  fi
fi

if [[ "${MAINFRAME_SMOKE_SKIP_STORAGE:-}" == "1" ]]; then
  echo "storage shutdown: SKIP (MAINFRAME_SMOKE_SKIP_STORAGE=1: no scannable disk in this environment)"
else
  echo "== storage shutdown =="
  if python3 "$ROOT/mainframe/tests/storage-shutdown-smoke.py" && \
     python3 "$ROOT/mainframe/tests/storage-shutdown-smoke.py" --faults; then
    echo "storage shutdown: pass"
  else
    echo "storage shutdown: FAIL"
    fail=1
  fi
fi

echo "== sparkline interaction =="
qmltest="$(command -v qmltestrunner || true)"
if [[ -z "$qmltest" && -x /usr/lib/qt6/bin/qmltestrunner ]]; then
  qmltest=/usr/lib/qt6/bin/qmltestrunner
fi
if [[ -n "$qmltest" ]]; then
  if QT_QPA_PLATFORM=offscreen QSG_RENDER_LOOP=basic "$qmltest" -input "$ROOT/mainframe/tests/tst_sparkline.qml"; then
    echo "sparkline interaction: pass"
    if QT_QPA_PLATFORM=offscreen QSG_RENDER_LOOP=basic "$qmltest" -input "$ROOT/mainframe/tests/tst_overview.qml"; then
      echo "overview interaction: pass"
    else
      echo "overview interaction: FAIL"
      fail=1
    fi
  else
    echo "sparkline interaction: FAIL"
    fail=1
  fi
else
  echo "sparkline interaction: skipped (qmltestrunner unavailable)"
fi

if command -v qs >/dev/null 2>&1; then
  # timeout_s is 60. Core count is this machine's nproc, inside the checker.
  run_qml 1800 1125 26000 60 4 2 1
  run_qml 900 1125 26000 60 2 4 1
  run_qml 1800 1125 26000 60 4 2 1 cyber-static
  run_qml 1800 1125 26000 60 4 2 1 cyber-all
  run_qml 1800 1125 5000 20 4 2 0 machine
  run_qml 900 1125 5000 20 2 4 0 machine
else
  :
fi

echo "== kill -9 parent =="
if python3 - "$ROOT" <<'PY'
import atexit
import os
import shutil
import signal
import sys
import tempfile
import time

root = sys.argv[1]
qs = shutil.which("qs")
if not qs:
    print("kill -9: qs is not on PATH")
    sys.exit(1)

def read_stat(pid):
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    cut = text.rfind(")")
    if cut < 0:
        return None
    rest = text[cut + 2:].split()
    if len(rest) < 20:
        return None
    try:
        return {"state": rest[0], "ppid": int(rest[1]), "start": int(rest[19]), "pgrp": int(rest[2])}
    except ValueError:
        return None

def cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            return handle.read()
    except OSError:
        return b""

def descendants(root_pid):
    kids = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        names = []
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        st = read_stat(pid)
        if not st:
            continue
        kids.setdefault(st["ppid"], []).append(pid)
    out = []
    stack = [root_pid]
    seen = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for kid in kids.get(pid, []):
            out.append(kid)
            stack.append(kid)
    return out

env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "offscreen"
env["MAINFRAME_SMOKE"] = "1"
env["MAINFRAME_SMOKE_W"] = "900"
env["MAINFRAME_SMOKE_H"] = "700"
env["MAINFRAME_SMOKE_MS"] = "30000"
env.pop("MAINFRAME_SMOKE_LIVE", None)
env.pop("MAINFRAME_SMOKE_TAB", None)
xdg_home = tempfile.mkdtemp(prefix="mainframe-xdg-")
env["XDG_CONFIG_HOME"] = xdg_home
atexit.register(lambda: shutil.rmtree(xdg_home, ignore_errors=True))
leader = os.fork()
if leader == 0:
    try:
        os.setsid()
        devnull = os.open("/dev/null", os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.execvpe(qs, [qs, "-p", os.path.join(root, "mainframe")], env)
    finally:
        os._exit(127)

collectors = []
deadline = time.monotonic() + 8.0
try:
    while time.monotonic() < deadline:
        try:
            wpid, _status = os.waitpid(leader, os.WNOHANG)
        except OSError:
            wpid = 0
        if wpid == leader:
            print("kill -9: qs exited before collect.py started")
            sys.exit(1)
        for pid in descendants(leader):
            if b"collect.py" in cmdline(pid):
                st = read_stat(pid)
                if st:
                    collectors.append((pid, st["start"], st["ppid"]))
        if collectors:
            break
        time.sleep(0.1)
    if not collectors:
        print("kill -9: collect.py did not start")
        sys.exit(1)
    parents = {parent for _, _, parent in collectors}
    if len(parents) != 1 or not parents.issubset({leader, *descendants(leader)}):
        print("kill -9: collector parent is not a single qs descendant: %s" % parents)
        sys.exit(1)
    # Kill only the actual shell parent. A group kill would hide a missing death signal.
    os.kill(parents.pop(), signal.SIGKILL)
    left = time.monotonic() + 2.0
    still = list(collectors)
    while time.monotonic() < left:
        still = []
        for pid, start, _parent in collectors:
            st = read_stat(pid)
            if st and st["start"] == start and st["state"] != "Z":
                still.append(pid)
        if not still:
            break
        time.sleep(0.05)
    if still:
        print("kill -9: collect.py still alive: %s" % " ".join(str(pid) for pid in still))
        sys.exit(1)
    print("kill -9: collect.py gone within 2s")
finally:
    try:
        os.kill(leader, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.kill(-leader, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.waitpid(leader, 0)
    except OSError:
        pass
PY
then
  echo "kill -9: pass"
else
  echo "kill -9: FAIL"
  fail=1
fi

if [[ "${MAINFRAME_SMOKE_NO_SSH:-}" == "1" ]]; then
  echo "unreachable host: skipped (MAINFRAME_SMOKE_NO_SSH=1)"
else
echo "== unreachable host =="
# A temp hosts.json names an alias that will not resolve. Select it by name.
if python3 - "$ROOT" <<'PY'
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

root = sys.argv[1]
qs = shutil.which("qs")
if not qs:
    print("unreachable host: qs is not on PATH")
    sys.exit(1)

alias = "mf-no-such-host.invalid"
xdg = tempfile.mkdtemp(prefix="mainframe-hosts-")
log_path = ""
try:
    os.makedirs(os.path.join(xdg, "mainframe"))
    with open(os.path.join(xdg, "mainframe", "hosts.json"), "w", encoding="utf-8") as handle:
        handle.write('{"hosts":[{"name":"Away","ssh":"%s"}]}\n' % alias)
    env = dict(os.environ)
    env.pop("MAINFRAME_SMOKE_LIVE", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MAINFRAME_SMOKE"] = "1"
    env.pop("MAINFRAME_SMOKE_TAB", None)
    env["MAINFRAME_SMOKE_TAB_NAME"] = "Away"
    env["MAINFRAME_SMOKE_MS"] = "15000"
    env["MAINFRAME_SMOKE_W"] = "900"
    env["MAINFRAME_SMOKE_H"] = "700"
    env["XDG_CONFIG_HOME"] = xdg
    log_fd, log_path = tempfile.mkstemp(prefix="mainframe-unreach-")
    os.close(log_fd)
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [qs, "-p", os.path.join(root, "mainframe")],
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    deadline = time.monotonic() + 30.0
    code = None
    while time.monotonic() < deadline:
        got = proc.poll()
        if got is not None:
            code = got
            break
        time.sleep(0.2)
    if code is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            code = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            code = proc.wait(timeout=2)
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        log = handle.read()
    log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
    fail_re = re.compile(r"Error|Warning|Binding loop|Cannot assign|Unable to|failed|TypeError|ReferenceError")
    bad = [line for line in log.splitlines() if fail_re.search(line)]
    tab_re = re.compile(r'TAB index=(\d+) status=(\S+) wsl=\d+ local=\d+ name=(".*")')
    tabs = [tab_re.search(line) for line in log.splitlines()]
    reached = any(m and json.loads(m.group(3)) == "Away" and m.group(2) == "unreachable" for m in tabs)

    def ssh_leftovers(target):
        # argv0 may be an absolute path. Match the executable basename.
        found = []
        me = os.getpid()
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == me:
                continue
            try:
                with open("/proc/%s/cmdline" % name, "rb") as handle:
                    raw = handle.read()
            except OSError:
                continue
            parts = [part for part in raw.split(b"\x00") if part]
            if not parts:
                continue
            argv0 = parts[0].decode("utf-8", "replace")
            base = argv0.rsplit("/", 1)[-1]
            if base != "ssh":
                continue
            args = [part.decode("utf-8", "replace") for part in parts]
            if target in args:
                found.append(int(name))
        return found

    leftover = ssh_leftovers(alias)
    for pid in leftover:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    if bad or not reached or leftover or code != 0:
        print("unreachable host: FAIL exit=%s reached=%s leftover=%s" % (code, reached, leftover))
        if bad:
            sys.stdout.write("\n".join(bad[:30]) + "\n")
        if not reached:
            lines = [line for line in log.splitlines() if "TAB " in line or "SMOKE" in line]
            sys.stdout.write("\n".join(lines[-30:]) + "\n")
            if not lines:
                sys.stdout.write(log[-2000:])
        sys.exit(1)
    print("unreachable host: tab status=unreachable, ssh gone")
finally:
    shutil.rmtree(xdg, ignore_errors=True)
    if log_path:
        try:
            os.remove(log_path)
        except OSError:
            pass
PY
then
  echo "unreachable host: pass"
else
  echo "unreachable host: FAIL"
  fail=1
fi

fi

echo "== selected remote tab =="
if python3 - "$ROOT" <<'PYTEST'
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='mainframe-selected-') as tmp:
    config = Path(tmp) / 'mainframe'
    config.mkdir()
    (config / 'hosts.json').write_text(json.dumps({'hosts': [{'name': 'Test host', 'ssh': 'test-host'}]}))
    env = dict(os.environ, XDG_CONFIG_HOME=tmp, QT_QPA_PLATFORM='offscreen',
               MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_TAB='2', MAINFRAME_SMOKE_FAKE_REMOTE='1',
               MAINFRAME_SMOKE_MS='3000')
    env.pop('MAINFRAME_SMOKE_LIVE', None)
    env.pop('MAINFRAME_SMOKE_TAB_NAME', None)
    env.pop('MAINFRAME_SMOKE_NO_REMOTE', None)
    result = subprocess.run(['qs', '-p', str(Path(sys.argv[1]) / 'mainframe')], env=env,
                            capture_output=True, text=True, timeout=20)
    matches = re.findall(r'ACTIVE tab=(\d+) selected=(\d+) highlighted=(\d+)', result.stdout + result.stderr)
    if result.returncode != 0 or not matches or matches[-1] != ('2', '1', '2'):
        raise SystemExit('selected remote tab: FAIL exit=%s active=%s\n%s' % (result.returncode, matches, (result.stdout + result.stderr)[-3000:]))
    print('selected remote tab: tab=2 selected=1 highlighted=2')
PYTEST
then
  echo "selected remote tab: pass"
else
  echo "selected remote tab: FAIL"
  fail=1
fi

echo "== local tab with hosts =="
# hosts.json has an entry, but the local tab stays selected. Local cards must
# still sample and lay out, and that entry must not become the selected tab.
if python3 - "$ROOT" <<'PY'
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

root = sys.argv[1]
qs = shutil.which("qs")
if not qs:
    print("local tab: qs is not on PATH")
    sys.exit(1)

def online_cpus():
    try:
        text = subprocess.check_output(["nproc"], text=True).strip()
        count = int(text)
        if count > 0:
            return count
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return 1

def ssh_leftovers(target):
    found = []
    me = os.getpid()
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % name, "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        parts = [part for part in raw.split(b"\x00") if part]
        if not parts:
            continue
        argv0 = parts[0].decode("utf-8", "replace")
        base = argv0.rsplit("/", 1)[-1]
        if base != "ssh":
            continue
        args = [part.decode("utf-8", "replace") for part in parts]
        if target in args:
            found.append(int(name))
    return found

def field(line, key):
    match = re.search(r"(?:^|\s)" + re.escape(key) + r"=(-?\d+)", line or "")
    if not match:
        return None
    return int(match.group(1))

alias = "mf-local-stay.invalid"
nproc = online_cpus()
xdg = tempfile.mkdtemp(prefix="mainframe-local-")
log_path = ""
try:
    os.makedirs(os.path.join(xdg, "mainframe"))
    with open(os.path.join(xdg, "mainframe", "hosts.json"), "w", encoding="utf-8") as handle:
        handle.write('{"hosts":[{"name":"Away","ssh":"%s"}]}\n' % alias)
    env = dict(os.environ)
    env.pop("MAINFRAME_SMOKE_LIVE", None)
    env.pop("MAINFRAME_SMOKE_TAB", None)
    env.pop("MAINFRAME_SMOKE_TAB_NAME", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MAINFRAME_SMOKE"] = "1"
    env["MAINFRAME_SMOKE_START_LOCAL"] = "1"
    env["MAINFRAME_SMOKE_MS"] = "10000"
    env["MAINFRAME_SMOKE_W"] = "1800"
    env["MAINFRAME_SMOKE_H"] = "1125"
    env["XDG_CONFIG_HOME"] = xdg
    log_fd, log_path = tempfile.mkstemp(prefix="mainframe-local-")
    os.close(log_fd)
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [qs, "-p", os.path.join(root, "mainframe")],
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    deadline = time.monotonic() + 30.0
    code = None
    while time.monotonic() < deadline:
        got = proc.poll()
        if got is not None:
            code = got
            break
        time.sleep(0.2)
    if code is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            code = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            code = proc.wait(timeout=2)
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        log = handle.read()
    log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
    fail_re = re.compile(r"Error|Warning|Binding loop|Cannot assign|Unable to|failed|TypeError|ReferenceError")
    bad = [line for line in log.splitlines() if fail_re.search(line)]
    sample_re = re.compile(r"(?:^|\s)SAMPLE(?:\s|$)")
    samples = 0
    layout_line = None
    gauge_line = None
    tab_re = re.compile(r'TAB index=(\d+) status=(\S+) wsl=\d+ local=(\d+) name=(".*")')
    tab_rows = []
    for line in log.splitlines():
        if sample_re.search(line):
            samples += 1
        if re.search(r"(?:^|\s)LAYOUT(?:\s|$)", line):
            layout_line = line
        if re.search(r"(?:^|\s)GAUGE(?:\s|$)", line):
            gauge_line = line
        match = tab_re.search(line)
        if match:
            tab_rows.append((int(match.group(1)), match.group(2), match.group(3) == '1', json.loads(match.group(4))))
    local_names = {name for _, _, local, name in tab_rows if local}
    local_tab = any(local and name in local_names and status == 'connected' for _, status, local, name in tab_rows)
    remote_rows = [(index, status) for index, status, _, name in tab_rows if name == 'Away']
    remote_idle = any(status == 'none' for _, status in remote_rows)
    remote_moved = any(status != 'none' for _, status in remote_rows)
    cards = field(layout_line, "cards")
    overflow = field(layout_line, "overflow")
    laid_samples = field(layout_line, "samples")
    meters = field(gauge_line, "meters")
    want_meters = 0 if nproc > 32 else nproc
    leftover = ssh_leftovers(alias)
    for pid in leftover:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    problems = []
    if bad:
        problems.append("log")
    if samples < 1:
        problems.append("samples")
    if layout_line is None or cards is None or cards < 1 or overflow != 0 or laid_samples is None or laid_samples < 1:
        problems.append("layout")
    if gauge_line is None or meters != want_meters:
        problems.append("meters")
    if not local_tab or not remote_idle or remote_moved:
        problems.append("tabs")
    if leftover:
        problems.append("ssh")
    if code != 0:
        problems.append("exit")
    if problems:
        print("local tab: FAIL %s exit=%s samples=%s cards=%s overflow=%s laid=%s meters=%s want_meters=%s leftover=%s" % (
            ",".join(problems), code, samples, cards, overflow, laid_samples, meters, want_meters, leftover,
        ))
        if bad:
            sys.stdout.write("\n".join(bad[:30]) + "\n")
        tail = [line for line in log.splitlines() if "TAB " in line or "LAYOUT" in line or "GAUGE" in line or "SAMPLE" in line or "SMOKE" in line]
        sys.stdout.write("\n".join(tail[-40:]) + "\n")
        sys.exit(1)
    print("local tab: cards=%s samples=%s meters=%s ssh gone" % (cards, laid_samples, meters))
finally:
    shutil.rmtree(xdg, ignore_errors=True)
    if log_path:
        try:
            os.remove(log_path)
        except OSError:
            pass
PY
then
  echo "local tab with hosts: pass"
else
  echo "local tab with hosts: FAIL"
  fail=1
fi

echo "== theme preview =="
if python3 "$ROOT/mainframe/tests/theme-preview-smoke.py"; then
  echo "theme preview: pass"
else
  echo "theme preview: FAIL"
  fail=1
fi

echo "== v1.5 fixture views =="
if python3 "$ROOT/mainframe/tests/v15-smoke.py"; then
  echo "v1.5 fixture views: pass"
else
  echo "v1.5 fixture views: FAIL"
  fail=1
fi
fi

if [[ "${MAINFRAME_SMOKE_LIVE:-}" == "1" && "${MAINFRAME_SMOKE_NO_GUI:-}" != "1" ]]; then
  echo "== live window =="
  if command -v qs >/dev/null 2>&1; then
    # 45 s hold covers the 5 s wait plus the 30 s sample, then the app quits itself.
    run_qml 1800 1125 45000 90 4 2 1 live
  else
    echo "live window: qs is not on PATH"
    fail=1
  fi
else
  echo "live window: skipped (set MAINFRAME_SMOKE_LIVE=1 on a Wayland session; gate is < 2% over 30s)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "smoke: FAIL"
  exit 1
fi
echo "smoke: pass"
exit 0
