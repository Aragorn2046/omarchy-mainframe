import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);
const H = require("../lib/hosts.js");
const M = require("../lib/metrics.js");
const Slots = require("../lib/slotbind.js");

test("an alias stays reserved until its leader exits and its group is gone", () => {
  assert.equal(Slots.reserve("test-alias", 11), true);
  Slots.stopping("test-alias", 11);
  assert.equal(Slots.reserve("test-alias", 12), false);
  assert.equal(Slots.release("test-alias", 11, true, false), false);
  assert.equal(Slots.release("test-alias", 11, false, true), false);
  assert.equal(Slots.release("test-alias", 12, true, true), false);
  assert.equal(Slots.release("test-alias", 11, true, true), true);
  assert.equal(Slots.reserve("test-alias", 12), true);
  assert.equal(Slots.release("test-alias", 12, true, true), true);
});

test("cleanup kills a TERM-resistant group member after its leader exits", { skip: process.platform !== "linux" }, () => {
  const helper = H.groupCleanupCommand(123, false);
  const script = `
import ctypes, os, signal, subprocess, sys, time
ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)
leader = subprocess.Popen([sys.executable, '-c', '''
import os, signal, time
os.setpgid(0, 0)
child = os.fork()
if child == 0:
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 print(os.getpid(), flush=True)
 while True: time.sleep(1)
while True: time.sleep(1)
'''], stdout=subprocess.PIPE, text=True)
child = int(leader.stdout.readline())
cleaner = subprocess.Popen([sys.executable, '-c', sys.argv[1], str(leader.pid), '0'])
leader.wait(timeout=2)
deadline = time.monotonic() + 4
while time.monotonic() < deadline:
 try:
  got, status = os.waitpid(child, os.WNOHANG)
 except ChildProcessError:
  got = 0
 if got:
  assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
  break
 time.sleep(.02)
else: raise AssertionError('group member survived')
assert cleaner.wait(timeout=2) == 0
`;
  const result = spawnSync("python3", ["-c", script, helper[2]], { encoding: "utf8", timeout: 8000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
});

function ticks(user, system, idle, nice) {
  return {
    user, nice: nice || 0, system: system || 0, idle,
    iowait: 0, irq: 0, softirq: 0, steal: 0, guest: 0, guestNice: 0,
  };
}

test("hosts.json drops bad aliases and keeps the rest", () => {
  assert.equal(H.hostsPath("/tmp/cfg", "/home/a"), "/tmp/cfg/mainframe/hosts.json");
  assert.equal(H.hostsPath("  ", "/home/a"), "/home/a/.config/mainframe/hosts.json");
  assert.equal(H.hostsPath("", "/home/a"), "/home/a/.config/mainframe/hosts.json");

  const missing = H.parseHosts("", true);
  assert.equal(missing.ok, false);
  assert.equal(missing.hint, true);
  assert.equal(missing.hosts.length, 0);

  const broken = H.parseHosts("{", false);
  assert.equal(broken.hint, true);
  assert.equal(broken.hosts.length, 0);

  const shape = H.parseHosts('{"machines":[]}', false);
  assert.equal(shape.hint, true);

  const empty = H.parseHosts('{"hosts":[]}', false);
  assert.equal(empty.ok, true);
  assert.equal(empty.hint, false);
  assert.equal(empty.hosts.length, 0);

  const raw = JSON.stringify({
    hosts: [
      { name: "Host A", ssh: "host-a" },
      { name: "Nope", ssh: "host-a;rm" },
      { name: "Inject", ssh: "$(id)" },
      { name: "Space", ssh: "a b" },
      { name: "Piped", ssh: "host-b|sh" },
      { name: "Newline", ssh: "host-c\nid" },
      { name: "Proxy", ssh: "-oProxyCommand=touch" },
      { name: "Long", ssh: "a".repeat(65) },
      { name: "Slash", ssh: "../x" },
      { name: "", ssh: "host-b" },
      { name: "x".repeat(25), ssh: "host-b" },
      { name: "Bad\nname", ssh: "host-b" },
      { name: "Host B", ssh: "host-b" },
      { name: "Host B again", ssh: "host-b" },
      { name: "user@host", ssh: "user@host" },
      { name: "Host C box", ssh: "host-c.local" },
    ],
  });
  const parsed = H.parseHosts(raw, false);
  assert.equal(parsed.hint, false);
  assert.deepEqual(parsed.hosts.map((host) => host.ssh), ["host-a", "host-b", "user@host", "host-c.local"]);
  assert.equal(parsed.hosts[1].name, "Host B");

  const onlyBad = H.parseHosts('{"hosts":[{"name":"X","ssh":"a;b"}]}', false);
  assert.equal(onlyBad.hosts.length, 0);
  assert.equal(onlyBad.hint, true);

  for (const alias of ["host-a", "host-b", "user@host", "host.example", "a_b-c.d"]) {
    const argv = H.sshArgv(alias);
    assert.ok(argv);
    assert.equal(argv[0], "ssh");
    assert.equal(argv[9], "--");
    assert.equal(argv[10], alias);
    assert.deepEqual(argv.slice(1, 9), [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=15",
      "-o", "ServerAliveInterval=5",
      "-o", "ServerAliveCountMax=2",
    ]);
    assert.deepEqual(argv.slice(11), ["exec", "python3", "-u", "-", "--remote"]);
    const cmd = H.sshCommand(alias);
    assert.equal(cmd[0], "python3");
    assert.equal(cmd.includes("sh"), false);
    assert.equal(cmd[cmd.length - 7], "--");
    assert.equal(cmd[cmd.length - 6], alias);
    assert.equal(cmd.filter((part) => part === alias).length, 1);
  }
  for (const alias of [
    "host-a;id", "a b", "host-a|sh", "host-a\n", "", "a".repeat(65), "../x",
    "-oProxyCommand=x", "-Fpayload", "-J...", "-Jhost",
    "-user@host", "user@-host", "-@", "@-host",
  ]) {
    assert.equal(H.validAlias(alias), false);
    assert.equal(H.sshArgv(alias), null);
    assert.equal(H.sshCommand(alias), null);
    const dropped = H.parseHosts(JSON.stringify({ hosts: [{ name: "X", ssh: alias }] }), false);
    assert.equal(dropped.hosts.length, 0);
  }
});

test("tab state machine connects, lingers one host, and retries", () => {
  const fleet = H.createFleet("here");
  const parsed = H.parseHosts(JSON.stringify({
    hosts: [
      { name: "Host A", ssh: "host-a" },
      { name: "Host B", ssh: "host-b" },
      { name: "Host C", ssh: "host-c" },
    ],
  }), false);
  H.applyConfig(fleet, parsed, 0);
  assert.equal(H.tabModel(fleet).length, 4);
  assert.equal(H.tabModel(fleet)[0].name, "here");
  assert.equal(H.desired(fleet).length, 0);

  H.selectIndex(fleet, 1, 1000);
  assert.equal(fleet.sessions["host-a"].phase, "connecting");
  assert.equal(H.desired(fleet).map((row) => row.ssh).join(","), "host-a");
  const generation = fleet.sessions["host-a"].generation;
  assert.equal(H.noteSample(fleet, "host-a", generation, { host: "host-a" }, 1500), true);
  assert.equal(fleet.sessions["host-a"].phase, "connected");
  assert.equal(H.statusOf(fleet.sessions["host-a"]), "connected");

  H.selectIndex(fleet, 0, 2000);
  assert.equal(fleet.sessions["host-a"].phase, "lingering");
  assert.equal(H.statusOf(fleet.sessions["host-a"]), "connected");
  assert.equal(H.desired(fleet).map((row) => row.ssh).join(","), "host-a");
  assert.equal(fleet.sessions["host-a"].generation, generation);

  H.selectIndex(fleet, 1, 3000);
  assert.equal(fleet.sessions["host-a"].phase, "connected");
  assert.equal(fleet.sessions["host-a"].generation, generation);
  assert.equal(H.desired(fleet).length, 1);

  H.selectIndex(fleet, 2, 4000);
  assert.equal(fleet.sessions["host-a"].phase, "lingering");
  assert.equal(fleet.sessions["host-b"].phase, "connecting");
  assert.deepEqual(H.desired(fleet).map((row) => row.ssh), ["host-a", "host-b"]);

  H.selectIndex(fleet, 3, 5000);
  assert.equal(fleet.sessions["host-a"].phase, "idle");
  assert.equal(fleet.sessions["host-b"].phase, "lingering");
  assert.equal(fleet.sessions["host-c"].phase, "connecting");
  assert.deepEqual(H.desired(fleet).map((row) => row.ssh), ["host-b", "host-c"]);

  H.tick(fleet, 5000 + H.LINGER_MS - 1);
  assert.equal(fleet.sessions["host-b"].phase, "lingering");
  H.tick(fleet, 5000 + H.LINGER_MS);
  assert.equal(fleet.sessions["host-b"].phase, "idle");
  assert.deepEqual(H.desired(fleet).map((row) => row.ssh), ["host-c"]);

  H.noteExit(fleet, "host-c", fleet.sessions["host-c"].generation, 255, "ssh: connect to host host-c port 22: Connection timed out", 6000);
  assert.equal(fleet.sessions["host-c"].phase, "unreachable");
  assert.equal(H.reachMessage(fleet).title, "Can't reach Host C");
  assert.match(H.reachMessage(fleet).detail, /Connection timed out/);
  assert.equal(H.desired(fleet).length, 0);
  H.tick(fleet, 6000 + H.RETRY_MS - 1);
  assert.equal(fleet.sessions["host-c"].phase, "unreachable");
  H.selectIndex(fleet, 0, 7000);
  H.tick(fleet, 6000 + H.RETRY_MS + 10);
  assert.equal(fleet.sessions["host-c"].phase, "unreachable");
  H.selectIndex(fleet, 3, 8000);
  assert.equal(fleet.sessions["host-c"].phase, "connecting");
  const again = fleet.sessions["host-c"].generation;
  H.noteExit(fleet, "host-c", again, 255, "Connection timed out", 8100);
  assert.equal(fleet.sessions["host-c"].phase, "unreachable");
  H.tick(fleet, 8100 + H.RETRY_MS);
  assert.equal(fleet.sessions["host-c"].phase, "connecting");
  assert.notEqual(fleet.sessions["host-c"].generation, again);

  H.noteExit(fleet, "host-c", fleet.sessions["host-c"].generation, 127, "bash: python3: command not found", 90000);
  assert.equal(fleet.sessions["host-c"].phase, "error");
  assert.equal(H.reachMessage(fleet).title, "Problem on Host C");

  const staleGen = fleet.sessions["host-a"].generation;
  fleet.sessions["host-a"].generation = 4;
  fleet.sessions["host-a"].phase = "connected";
  H.noteExit(fleet, "host-a", staleGen, 255, "late", 91000);
  assert.equal(fleet.sessions["host-a"].phase, "connected");

  H.cycle(fleet, 1, 92000);
  assert.equal(fleet.selected, 0);
  H.cycle(fleet, 1, 93000);
  assert.equal(fleet.selected, 1);

  const same = H.parseHosts(JSON.stringify({
    hosts: [
      { name: "Host A", ssh: "host-a" },
      { name: "Host B", ssh: "host-b" },
      { name: "Host C", ssh: "host-c" },
    ],
  }), false);
  const genBefore = fleet.sessions["host-a"].generation;
  H.applyConfig(fleet, same, 94000);
  assert.equal(fleet.sessions["host-a"].generation, genBefore);

  H.selectIndex(fleet, 1, 95000);
  const hostAGen = fleet.sessions["host-a"].generation;
  H.restartSelected(fleet, 95100);
  assert.equal(fleet.selected, 1);
  assert.equal(fleet.sessions["host-a"].phase, "connecting");
  assert.equal(fleet.sessions["host-a"].generation, hostAGen + 1);
});

test("reload keeps the selected ssh alias and stops removed hosts", () => {
  const fleet = H.createFleet("here");
  H.applyConfig(fleet, H.parseHosts(JSON.stringify({
    hosts: [
      { name: "Host A", ssh: "host-a" },
      { name: "Host B", ssh: "host-b" },
    ],
  }), false), 1000);
  H.selectIndex(fleet, 2, 2000);
  const gen = fleet.sessions["host-b"].generation;
  assert.equal(fleet.sessions["host-b"].phase, "connecting");

  H.applyConfig(fleet, H.parseHosts(JSON.stringify({
    hosts: [
      { name: "Host B", ssh: "host-b" },
      { name: "Host C", ssh: "host-c" },
    ],
  }), false), 3000);
  assert.equal(fleet.selected, 1);
  assert.equal(fleet.hosts[0].ssh, "host-b");
  assert.equal(fleet.sessions["host-b"].phase, "connecting");
  assert.equal(fleet.sessions["host-b"].generation, gen);
  assert.equal(fleet.sessions["host-a"].phase, "idle");
  assert.deepEqual(H.desired(fleet).map((row) => row.ssh), ["host-b"]);

  fleet.sessions["host-b"].phase = "idle";
  H.applyConfig(fleet, H.parseHosts(JSON.stringify({
    hosts: [{ name: "Host B box", ssh: "host-b" }],
  }), false), 4000);
  assert.equal(fleet.selected, 1);
  assert.equal(fleet.sessions["host-b"].phase, "connecting");
  assert.equal(fleet.sessions["host-b"].name, "Host B box");

  H.applyConfig(fleet, H.parseHosts(JSON.stringify({
    hosts: [{ name: "Host C", ssh: "host-c" }],
  }), false), 5000);
  assert.equal(fleet.selected, 0);
  assert.equal(fleet.sessions["host-b"].phase, "idle");
  assert.equal(H.desired(fleet).length, 0);
});

test("sanitize keeps the error line plain", () => {
  assert.equal(H.sanitizeError("ssh: timed out\r\nnext"), "ssh: timed out next");
  assert.equal(H.sanitizeError("a\u0000b").indexOf("\u0000"), -1);
  assert.ok(H.sanitizeError("x".repeat(500)).length <= 200);
});

test("remote samples show n/a for sensors the host cannot provide", () => {
  const base = {
    t_ms: 1000,
    mono_ms: 5000,
    host: "host-a",
    os: "darwin",
    kernel: "24.5.0",
    cpu: {
      total: ticks(100, 0, 900),
      cores: [ticks(50, 0, 450), ticks(50, 0, 450)],
      mhz: null,
      core_mhz: [null, null],
    },
    mem: { total: 8e9, used: 4e9, available: 4e9, cached: 1e9, swapUsed: 0, swapTotal: 2e9 },
    disk: { device: "disk0", sectors_read: 1000, sectors_written: 500, root_used: 100, root_total: 1000 },
    net: {
      ifaces: [{ name: "en0", rx: 10000, tx: 2000 }, { name: "lo0", rx: 9e9, tx: 9e9 }],
      virtual: ["lo0"],
      default_iface: "en0",
    },
    gpu: { present: false, na: true },
    temps: { na: true, package_c: null, disk_c: null },
    battery: { capacity: 80, status: "discharging", power_now_uw: null },
    procs: {
      presented: {
        byCpu: [{ name: "Safari ×2", text: "13.5%" }],
        byMem: [{ name: "Safari ×2", text: "4.0%" }],
      },
      sweep_ms: 2,
    },
  };
  const next = {
    ...base,
    t_ms: 2000,
    mono_ms: 6000,
    cpu: {
      total: ticks(200, 0, 1700),
      cores: [ticks(120, 0, 780), ticks(80, 0, 920)],
      mhz: null,
      core_mhz: [null, null],
    },
    disk: { device: "disk0", sectors_read: 3048, sectors_written: 500, root_used: 100, root_total: 1000 },
    net: {
      ifaces: [{ name: "en0", rx: 510000, tx: 2000 }, { name: "lo0", rx: 9e9, tx: 9e9 }],
      virtual: ["lo0"],
      default_iface: "en0",
    },
    procs: null,
  };

  const first = M.step(M.emptyState(), base, 5000);
  assert.equal(first.skip, undefined);
  assert.equal(first.view.gpu.percentText, "n/a");
  assert.equal(first.view.gpu.na, true);
  assert.equal(first.view.cpu.tempText, "n/a");
  assert.equal(first.view.disk.tempText, "n/a");
  assert.equal(first.view.processes.byCpu[0].name, "Safari ×2");
  assert.equal(first.view.battery.percentText, "80%");

  const second = M.step(first.state, next, 6000);
  assert.equal(second.view.cpu.percentText, "11%");
  assert.equal(second.view.cpu.tempText, "n/a");
  assert.equal(second.view.disk.tempText, "n/a");
  assert.equal(second.view.disk.readText, "1.00 MB/s");
  assert.equal(second.view.net.downText, "488 KB/s");
  assert.equal(second.view.net.iface, "en0");
  assert.equal(second.view.gpu.percentText, "n/a");
  assert.ok(second.view.mem.usedText.indexOf("GB") >= 0);

  const partial = M.step(M.emptyState(), {
    t_ms: 1,
    mono_ms: 1,
    cpu: { na: true },
    mem: { na: true },
    disk: { na: true },
    net: { na: true },
    gpu: { na: true, present: false },
    temps: { na: true },
  }, 1000);
  assert.equal(partial.view.cpu.percentText, "n/a");
  assert.equal(partial.view.mem.usedText, "n/a");
  assert.equal(partial.view.disk.readText, "n/a");
  assert.equal(partial.view.disk.writeText, "n/a");
  assert.equal(partial.view.net.downText, "n/a");
  assert.equal(partial.view.gpu.percentText, "n/a");
});

test("darwin-shaped fields and the WSL badge", () => {
  assert.equal(H.sampleWsl({ wsl: true, kernel: "6.6.0" }), true);
  assert.equal(H.sampleWsl({ kernel: "5.15.153.1-microsoft-standard-WSL2" }), true);
  assert.equal(H.sampleWsl({ kernel: "6.8.0-arch1-1" }), false);
  assert.equal(H.sampleWsl({ os: "darwin", kernel: "24.5.0" }), false);

  const fleet = H.createFleet("here");
  H.applyConfig(fleet, H.parseHosts(JSON.stringify({
    hosts: [{ name: "Host B", ssh: "host-b" }, { name: "Host A", ssh: "host-a" }],
  }), false), 0);
  H.selectIndex(fleet, 1, 10);
  const gen = fleet.sessions["host-b"].generation;
  H.noteSample(fleet, "host-b", gen, { wsl: true, kernel: "5.15.0-microsoft-standard-WSL2", os: "linux" }, 20);
  const tabs = H.tabModel(fleet);
  assert.equal(tabs[1].name, "Host B");
  assert.equal(tabs[1].wsl, true);
  assert.equal(tabs[1].status, "connected");
  assert.equal(tabs[2].wsl, false);
  assert.equal(tabs[0].wsl, false);

  H.setLocal(fleet, "box", true);
  assert.equal(H.tabModel(fleet)[0].wsl, true);
  assert.equal(H.tabModel(fleet)[0].name, "box");

  const wslSample = M.step(M.emptyState(), {
    t_ms: 1,
    mono_ms: 1,
    host: "host-b",
    os: "linux",
    kernel: "5.15.0-microsoft-standard-WSL2",
    wsl: true,
    cpu: { total: ticks(1, 0, 9), cores: [ticks(1, 0, 9)], mhz: 1000, core_mhz: [1000] },
    mem: { total: 1000, used: 100, available: 900, cached: 10, swapUsed: 0, swapTotal: 0 },
    disk: { device: "sda", sectors_read: 1, sectors_written: 1, root_used: 1, root_total: 2 },
    net: { ifaces: [], virtual: [], default_iface: null },
    gpu: { present: false, na: true },
    temps: { package_c: null, disk_c: null },
  }, 1000);
  assert.equal(wslSample.view.gpu.percentText, "n/a");
  assert.equal(wslSample.view.gpu.na, true);
});
