#!/usr/bin/env bash
# Headless checks for mainframe: node unit tests, live samples, and a QML load.
# Install checks use a temporary XDG_CONFIG_HOME. No visible window unless
# MAINFRAME_SMOKE_LIVE=1.
# Offscreen (software) regression gate: < 3.0% of one core at both sizes.
# Live Wayland gate: < 2% of one core over 30 s, after a 5 s wait.
set -u

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

echo "== collector selftest =="
if python3 "$ROOT/mainframe/collect.py" --selftest; then
  echo "collector selftest: pass"
else
  echo "collector selftest: FAIL"
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
import errno
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


def cpu_gate_verdict(pct, limit):
    if pct is None or pct < 0 or pct >= limit:
        return "FAIL"
    return "PASS"


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
live = len(sys.argv) > 9 and sys.argv[9] == "live"

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
        # Only the leader's cutime/cstime: those are children it has reaped.
        if pid == root_pid:
            total += st["cutime"] + st["cstime"]
    return total, alive

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
use_scope = shutil.which("systemd-run") is not None
qs_cmd = qs_command(qs, os.path.join(root, "mainframe"))
if use_scope:
    argv = [
        "systemd-run", "--user", "--scope", "--unit", unit, "--collect", "--quiet", "--",
    ] + qs_cmd
else:
    argv = list(qs_cmd)

env = launch_env(os.environ, live)
env["MAINFRAME_SMOKE"] = "1"
env["MAINFRAME_SMOKE_W"] = str(width)
env["MAINFRAME_SMOKE_H"] = str(height)
env["MAINFRAME_SMOKE_MS"] = str(hold)

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
            if cpu_mode == "cgroup":
                after = usage_usec(cg) if cg else None
            else:
                after, alive = tree_ticks(leader)
                if not alive:
                    print("cpu qs+collector: qs exited before the %.0fs sample ended" % window_s)
                    fail = True
            t1 = time.time() * 1000.0
        time.sleep(0.1)
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

layout_line = last_word(log, "LAYOUT")
gauge_line = last_word(log, "GAUGE")
for line in log.splitlines():
    if re.search(r"(?:^|\s)(LAYOUT|SMOKE|GAUGE)(?:\s|$)", line):
        print(line.strip())

if layout_line is None or gauge_line is None:
    print("qml %dx%d: FAIL (no layout, qs exit %s)" % (width, height, code))
    if layout_line is None:
        sys.stdout.write(log)
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
            verdict = cpu_gate_verdict(pct, limit)
            kind = "live" if live else "offscreen"
            if pct is None:
                print("cpu qs+collector: no reading (%s)" % kind)
            else:
                print("cpu qs+collector: %.2f%% of one core over %.1fs (%s)" % (pct, elapsed, cpu_mode))
            print("cpu gate: %s (< %.1f%% of one core, %s)" % (verdict, limit, kind))
            if verdict != "PASS":
                fail = True
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

echo "== qml load =="
if ! command -v qs >/dev/null 2>&1; then
  echo "qml load: qs is not on PATH; cannot verify"
  fail=1
elif ! command -v qmllint >/dev/null 2>&1; then
  echo "qmllint: not available, skipped"
else
  if qmllint "$ROOT/mainframe/shell.qml" "$ROOT/mainframe/Card.qml" "$ROOT/mainframe/Meter.qml" \
      "$ROOT/mainframe/Sparkline.qml" "$ROOT/mainframe/ProcList.qml"; then
    echo "qmllint: pass"
  else
    echo "qmllint: FAIL"
    fail=1
  fi
fi

if command -v qs >/dev/null 2>&1; then
  # timeout_s is 60. Core count is this machine's nproc, inside the checker.
  run_qml 1800 1125 26000 60 4 2 1
  run_qml 900 1125 26000 60 2 4 1
else
  :
fi

echo "== kill -9 parent =="
if python3 - "$ROOT" <<'PY'
import os
import shutil
import signal
import sys
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
        return {"ppid": int(rest[1]), "start": int(rest[19]), "pgrp": int(rest[2])}
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
                    collectors.append((pid, st["start"]))
        if collectors:
            break
        time.sleep(0.1)
    if not collectors:
        print("kill -9: collect.py did not start")
        sys.exit(1)
    # Only the qs pid. A group kill would hide a missing death signal.
    os.kill(leader, signal.SIGKILL)
    try:
        os.waitpid(leader, 0)
    except OSError:
        pass
    left = time.monotonic() + 2.0
    still = list(collectors)
    while time.monotonic() < left:
        still = []
        for pid, start in collectors:
            st = read_stat(pid)
            if st and st["start"] == start:
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

if [[ "${MAINFRAME_SMOKE_LIVE:-}" == "1" ]]; then
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
