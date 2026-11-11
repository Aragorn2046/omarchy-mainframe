import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const M = require("../lib/metrics.js");

test("filesystem rows retain literal markup and enforce the fixed schema and limit", () => {
  const attack = "<img src=http://x/y>";
  const entry = { mount: "\u0000" + attack + "\n", device: "d\u007fisk", label: "x".repeat(121), total: 10, used: 20, extra: "discard" };
  const rows = [entry, { mount: 7, device: null, label: {}, total: Infinity, used: -1 }, ...Array(40).fill(entry)];
  const sample = { filesystems: rows, windows: { total: 10, used: 5, cpu: 1, disks: rows } };
  const view = M.step(M.emptyState(), sample, 1000).view;
  for (const list of [view.filesystems, view.windows.disks]) {
    assert.equal(list.length, 32);
    assert.deepEqual(list[0], { mount: attack, device: "disk", label: "x".repeat(120), total: 10, used: 10 });
    assert.deepEqual(list[1], { mount: "", device: "", label: "", total: 0, used: 0 });
  }
  assert.equal(entry.mount, "\u0000" + attack + "\n");
});

const PROC = [
  "cpu  1531630 70981 475295 19469478 19825 79001 33376 0 0 0",
  "cpu0 102910 5811 19580 1203174 1572 4214 5624 0 0 0",
  "cpu1 107421 6252 20483 1210621 1307 4453 2107 0 0 0",
  "intr 1 2 3",
  "ctxt 9",
  "",
].join("\n");

const MEM = [
  "MemTotal:       64950096 kB",
  "MemFree:         9903808 kB",
  "MemAvailable:   29070968 kB",
  "Buffers:            4388 kB",
  "Cached:         22228336 kB",
  "SwapTotal:      129904172 kB",
  "SwapFree:       129900000 kB",
  "Dirty:             11192 kB",
].join("\n");

const NET = [
  "Inter-|   Receive                                                |  Transmit",
  " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed",
  "    lo: 78663047  106055    0    0    0     0          0         0 78663047  106055    0    0    0     0       0          0",
  "  wlo1: 1000 10 0 0 0 0 0 0 400 8 0 0 0 0 0 0",
  "tailscale0: 50 1 0 0 0 0 0 0 25 1 0 0 0 0 0 0",
  "docker0: 10 1 0 0 0 0 0 0 10 1 0 0 0 0 0 0",
].join("\n");

const DISK = [
  " 259       0 nvme0n1 146914 45073 14933049 43715 1492883 2476243 48320141 2007271 0 196041 2071923 0 0 0 0 31089 20936",
  " 259       1 nvme0n1p1 40 0 3056 2 0 0 0 0 0 1 2 0 0 0 0 0 0",
  " 253       0 dm-0 10 0 100 1 20 0 200 1 0 2 2 0 0 0 0",
].join("\n");

const DARK_THEME = [
  'mode = "dark"',
  'accent = "#82FB9C"',
  'background = "#0B0C16"',
  'lighter_background = "#151828"',
  'foreground = "#ddf7ff"',
  'dark_foreground = "#6a6e95"',
  'muted = "#2d3450"',
  'yellow = "#50f7d4"',
  'red = "#50f872"',
  'cyan = "#7cf8f7"',
  'hyprland_active_border = "rgba(26a269ee) rgba(2ec27eee) 45deg"',
].join("\n");

const LIGHT_THEME = [
  'mode = "light"',
  'accent = "#205EA6"',
  'selection = "#CECDC3"',
  'muted = "#B7B5AC"',
  'background = "#FFFCF0"',
  'lighter_background = "#E6E4D9"',
  'foreground = "#100F0F"',
  'dark_foreground = "#878580"',
  'red = "#D14D41"',
  'yellow = "#D0A215"',
  'cyan = "#3AA99F"',
].join("\n");

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

test("every export is covered by name", () => {
  const covered = new Set([
    "HISTORY_LIMIT",
    "LABEL_MIX",
    "MIN_ELAPSED_MS",
    "MAX_ELAPSED_MS",
    "parseProcStat",
    "cpuDeltas",
    "parseMeminfo",
    "parseNetDev",
    "isVirtualIface",
    "netRates",
    "defaultRouteIface",
    "ifaceLabel",
    "parseDiskstats",
    "diskRates",
    "gpuBusy",
    "gpuStallIdle",
    "genericThreadName",
    "collectorLineAlive",
    "collectorKillDue",
    "collectorExitIgnored",
    "parseColorsToml",
    "oklabDistance",
    "warningColor",
    "seriesFlat",
    "meterColor",
    "batteryMeterColor",
    "mixHex",
    "qtColor",
    "resolveTheme",
    "pushHistory",
    "batteryPowerW",
    "batteryStatus",
    "parsePs",
    "topProcesses",
    "procDisplayName",
    "procCpuPercent",
    "procMemPercent",
    "groupProcesses",
    "formatBytes",
    "formatRate",
    "formatPercent",
    "formatPercentPrecise",
    "formatMhz",
    "formatMhzShort",
    "formatGpuFreq",
    "formatTemp",
    "formatPower",
    "formatUsage",
    "gridShape",
    "coreLayout",
    "netDetailLines",
    "buildSparkline",
    "seriesSame",
    "emptyState",
    "emptyView",
    "step",
  ]);
  for (const key of Object.keys(M)) {
    assert.ok(covered.has(key), "untested export " + key);
  }
  assert.equal(M.HISTORY_LIMIT, 60);
  assert.ok(M.LABEL_MIX >= 0.45 && M.LABEL_MIX <= 0.55);
  assert.equal(M.MIN_ELAPSED_MS, 200);
  assert.equal(M.MAX_ELAPSED_MS, 10000);
});

test("parseProcStat reads the aggregate line and per-core lines", () => {
  const parsed = M.parseProcStat(PROC);
  assert.equal(parsed.coreCount, 2);
  assert.equal(parsed.total.user, 1531630);
  assert.equal(parsed.total.idle, 19469478);
  assert.equal(parsed.total.iowait, 19825);
  assert.equal(parsed.cores[0].user, 102910);
  assert.equal(parsed.cores[1].nice, 6252);
  assert.equal(parsed.total.guest, 0);
});

test("parseProcStat places cores by index and leaves a missing id empty", () => {
  const parsed = M.parseProcStat("cpu  1 0 0 1 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0\ncpu2 1 0 0 1 0 0 0 0\n");
  assert.equal(parsed.coreCount, 3);
  assert.equal(parsed.cores[1], null);
  assert.equal(parsed.cores[2].user, 1);
});

test("cpuDeltas reports busy percent and ignores idle plus iowait", () => {
  const prev = M.parseProcStat("cpu  0 0 0 100 0 0 0 0\ncpu0 0 0 0 100 0 0 0 0\n");
  const half = M.parseProcStat("cpu  50 0 0 150 0 0 0 0\ncpu0 50 0 0 150 0 0 0 0\n");
  const io = M.parseProcStat("cpu  0 0 0 100 50 0 0 0\ncpu0 0 0 0 100 50 0 0 0\n");
  assert.equal(M.cpuDeltas(prev, half).total, 50);
  assert.equal(M.cpuDeltas(prev, half).cores[0], 50);
  assert.equal(M.cpuDeltas(prev, io).total, 0);
});

test("cpuDeltas treats a counter reset as zero", () => {
  const prev = M.parseProcStat("cpu  10 0 10 1000 0 0 0 0\ncpu0 10 0 10 1000 0 0 0 0\n");
  const next = M.parseProcStat("cpu  1 0 1 1 0 0 0 0\ncpu0 1 0 1 1 0 0 0 0\n");
  const delta = M.cpuDeltas(prev, next);
  assert.equal(delta.total, 0);
  assert.equal(delta.cores[0], 0);
});

test("cpuDeltas of an unchanged sample is zero", () => {
  const parsed = M.parseProcStat(PROC);
  const delta = M.cpuDeltas(parsed, parsed);
  assert.equal(delta.total, 0);
  assert.equal(delta.cores[0], 0);
});

test("parseMeminfo used is total minus available, cache matches free", () => {
  const mem = M.parseMeminfo(MEM);
  assert.equal(mem.total, 64950096 * 1024);
  assert.equal(mem.available, 29070968 * 1024);
  assert.equal(mem.cached, (22228336 + 4388) * 1024);
  assert.equal(mem.used, (64950096 - 29070968) * 1024);
  assert.equal(mem.swapUsed, (129904172 - 129900000) * 1024);
  assert.notEqual(mem.used, (64950096 - 9903808 - 4388 - 22228336) * 1024);
});

test("parseMeminfo tolerates missing keys and ignores the MemFree branch", () => {
  const onlyTotal = M.parseMeminfo("MemTotal: 1024 kB\n");
  assert.equal(onlyTotal.total, 1024 * 1024);
  assert.equal(onlyTotal.available, null);
  assert.equal(onlyTotal.cached, null);
  assert.equal(onlyTotal.used, null);
  assert.equal(onlyTotal.swapUsed, null);

  const availOnly = M.parseMeminfo("MemTotal: 1000 kB\nMemAvailable: 250 kB\n");
  assert.equal(availOnly.used, 750 * 1024);
  assert.equal(availOnly.free, null);

  const freeOnly = M.parseMeminfo("MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 10 kB\nCached: 10 kB\n");
  assert.equal(freeOnly.used, null);
  assert.equal(freeOnly.cached, 20 * 1024);

  const reclaim = M.parseMeminfo(
    "MemTotal: 1000 kB\nMemAvailable: 400 kB\nBuffers: 10 kB\nCached: 50 kB\nSReclaimable: 25 kB\n",
  );
  assert.equal(reclaim.used, 600 * 1024);
  assert.equal(reclaim.cached, 85 * 1024);
});

test("parseNetDev and netRates sum physical interfaces only", () => {
  const prev = M.parseNetDev(NET);
  const nextText = NET
    .replace("wlo1: 1000 ", "wlo1: 3000 ")
    .replace(" 400 ", " 900 ")
    .replace("tailscale0: 50 ", "tailscale0: 5000 ")
    .replace("docker0: 10 ", "docker0: 8000 ");
  const next = M.parseNetDev(nextText);
  assert.equal(prev.length, 4);
  const rates = M.netRates(prev, next, 1000, ["tailscale0", "docker0"]);
  assert.equal(rates.rxBps, 2000);
  assert.equal(rates.txBps, 500);
  assert.deepEqual(rates.interfaces.map((row) => row.name), ["wlo1"]);
  const bare = M.netRates(prev, next, 1000, []);
  assert.equal(bare.rxBps, 2000);
  assert.deepEqual(bare.interfaces.map((row) => row.name), ["wlo1"]);
});

test("netRates zeroes a wrapped counter and a zero elapsed time", () => {
  const prev = [{ name: "wlo1", rxBytes: 5000, txBytes: 100 }, { name: "eth0", rxBytes: 10, txBytes: 10 }];
  const next = [{ name: "wlo1", rxBytes: 1000, txBytes: 100 }, { name: "eth0", rxBytes: 110, txBytes: 10 }];
  const wrapped = M.netRates(prev, next, 1000, []);
  assert.equal(wrapped.rxBps, 100);
  assert.equal(wrapped.txBps, 0);
  const frozen = M.netRates(prev, next, 0, []);
  assert.equal(frozen.rxBps, 0);
  assert.equal(frozen.txBps, 0);
});

test("isVirtualIface always drops virtual name patterns, plus the sysfs list", () => {
  assert.equal(M.isVirtualIface("lo", []), true);
  assert.equal(M.isVirtualIface("wlo1", []), false);
  assert.equal(M.isVirtualIface("enp3s0", []), false);
  assert.equal(M.isVirtualIface("weird0", ["weird0"]), true);
  assert.equal(M.isVirtualIface("weird0", []), false);
  assert.equal(M.isVirtualIface("docker0", []), true);
  assert.equal(M.isVirtualIface("docker0", null), true);
  assert.equal(M.isVirtualIface("docker_gwbridge", []), true);
  assert.equal(M.isVirtualIface("br-lan", []), true);
  assert.equal(M.isVirtualIface("veth123", undefined), true);
  assert.equal(M.isVirtualIface("virbr0", []), true);
  assert.equal(M.isVirtualIface("podman0", []), true);
  assert.equal(M.isVirtualIface("tailscale0", []), true);
  assert.equal(M.isVirtualIface("wg0", []), true);
  assert.equal(M.isVirtualIface("tun0", []), true);
  assert.equal(M.isVirtualIface("zt0", []), true);
  assert.equal(M.isVirtualIface("enp0s3", undefined), false);
  assert.equal(M.isVirtualIface("wlo1", []), false);
});

test("parseDiskstats and diskRates use 512-byte sectors", () => {
  const parsed = M.parseDiskstats(DISK);
  const nvme = parsed.find((row) => row.name === "nvme0n1");
  assert.equal(nvme.sectorsRead, 14933049);
  assert.equal(nvme.sectorsWritten, 48320141);
  const prev = [{ name: "nvme0n1", sectorsRead: 1000, sectorsWritten: 50 }, { name: "dm-0", sectorsRead: 9, sectorsWritten: 9 }];
  const next = [{ name: "nvme0n1", sectorsRead: 1100, sectorsWritten: 50 }, { name: "dm-0", sectorsRead: 100000, sectorsWritten: 9 }];
  const rates = M.diskRates(prev, next, 1000, "nvme0n1");
  assert.equal(rates.found, true);
  assert.equal(rates.readBps, 100 * 512);
  assert.equal(rates.writeBps, 0);
});

test("diskRates treats reset and zero elapsed time as zero", () => {
  const prev = [{ name: "nvme0n1", sectorsRead: 5000, sectorsWritten: 80 }];
  const next = [{ name: "nvme0n1", sectorsRead: 10, sectorsWritten: 180 }];
  const reset = M.diskRates(prev, next, 1000, "nvme0n1");
  assert.equal(reset.readBps, 0);
  assert.equal(reset.writeBps, 100 * 512);
  const frozen = M.diskRates(prev, next, 0, "nvme0n1");
  assert.equal(frozen.readBps, 0);
  assert.equal(frozen.writeBps, 0);
  const missing = M.diskRates(prev, next, 1000, "sda");
  assert.equal(missing.found, false);
  assert.equal(missing.readBps, 0);
});

test("darwin combined iostat rate is I/O with write n/a", () => {
  const disk = (io) => ({
    device: "disk0",
    io_bytes_per_s: io,
    sectors_read: null,
    sectors_written: null,
    root_used: 10,
    root_total: 100,
  });
  const first = M.step(M.emptyState(), {
    t_ms: 1000,
    mono_ms: 1000,
    os: "darwin",
    disk: disk(null),
  }, 1000);
  assert.equal(first.view.disk.device, "disk0");
  assert.equal(first.view.disk.readLabel, "I/O");
  assert.equal(first.view.disk.readText, "unavailable");
  assert.equal(first.view.disk.writeText, "n/a");
  assert.equal(first.view.disk.usageText, M.formatUsage(10, 100));
  assert.deepEqual(first.view.disk.writeHistory, []);

  const second = M.step(first.state, {
    t_ms: 2000,
    mono_ms: 2000,
    os: "darwin",
    disk: disk(1048576),
  }, 2000);
  assert.equal(second.view.disk.readText, "1.00 MB/s");
  assert.equal(second.view.disk.writeText, "n/a");
  assert.equal(second.view.disk.readLabel, "I/O");
  assert.equal(second.view.disk.readHistory.length, 1);
  assert.deepEqual(second.view.disk.writeHistory, []);

  const third = M.step(second.state, {
    t_ms: 3000,
    mono_ms: 3000,
    os: "darwin",
    disk: disk(262144),
  }, 3000);
  assert.equal(third.view.disk.readText, "256 KB/s");
  assert.equal(third.view.disk.readHistory.length, 2);
  assert.equal(third.view.disk.readHistory[0], 1048576);

  const held = M.step(third.state, {
    t_ms: 4000,
    mono_ms: 4000,
    os: "darwin",
    disk: disk(null),
  }, 4000);
  assert.equal(held.view.disk.readText, "256 KB/s");
  assert.equal(held.view.disk.writeText, "n/a");
  assert.equal(held.view.disk.readLabel, "I/O");
  assert.equal(held.view.disk.readHistory.length, 2);

  const opened = M.step(M.emptyState(), {
    t_ms: 1000,
    mono_ms: 1000,
    os: "darwin",
    disk: disk(1048576),
  }, 1000);
  assert.equal(opened.view.disk.readLabel, "I/O");
  assert.equal(opened.view.disk.readText, "1.00 MB/s");
  assert.equal(opened.view.disk.readHistory.length, 0);
  const lived = M.step(opened.state, {
    t_ms: 2000,
    mono_ms: 2000,
    os: "darwin",
    disk: disk(2048),
  }, 2000);
  assert.equal(lived.view.disk.readHistory.length, 1);
  const jumped = M.step(lived.state, {
    t_ms: 2000 + 11000,
    mono_ms: 2000 + 11000,
    os: "darwin",
    disk: disk(8192),
  }, 13000);
  assert.equal(jumped.view.disk.readHistory.length, 1);
  assert.equal(jumped.view.disk.readLabel, "I/O");
  assert.equal(jumped.view.disk.readText, M.formatRate(8192));
});

test("a held sector read is not relabelled as combined I/O", () => {
  const first = M.step(M.emptyState(), {
    t_ms: 1000,
    mono_ms: 1000,
    disk: { device: "nvme0n1", sectors_read: 1000, sectors_written: 1000, root_used: 1, root_total: 10 },
  }, 1000);
  const second = M.step(first.state, {
    t_ms: 2000,
    mono_ms: 2000,
    disk: { device: "nvme0n1", sectors_read: 1000 + 2048, sectors_written: 1000, root_used: 1, root_total: 10 },
  }, 2000);
  assert.equal(second.view.disk.readLabel, "read");
  assert.equal(second.view.disk.readText, "1.00 MB/s");
  const heldRead = second.view.disk.readHistory.length;
  const next = M.step(second.state, {
    t_ms: 3000,
    mono_ms: 3000,
    os: "darwin",
    disk: {
      device: "nvme0n1",
      io_bytes_per_s: null,
      sectors_read: null,
      sectors_written: null,
      root_used: 1,
      root_total: 10,
    },
  }, 3000);
  assert.equal(next.view.disk.readLabel, "read");
  assert.equal(next.view.disk.readText, second.view.disk.readText);
  assert.equal(next.view.disk.writeText, second.view.disk.writeText);
  assert.equal(next.view.disk.readHistory.length, heldRead);
});

test("gpuBusy follows idle residency over wall time", () => {
  assert.equal(M.gpuBusy(1000, 2000, 1000), 0);
  assert.equal(M.gpuBusy(1000, 1000, 1000), 100);
  assert.equal(M.gpuBusy(1000, 1500, 1000), 50);
  assert.equal(M.gpuBusy(5000, 1000, 1000), 0);
  assert.equal(M.gpuBusy(1000, 5000, 1000), 0);
  assert.equal(M.gpuBusy(1000, 1100, 0), 0);
  assert.equal(M.gpuBusy(null, null, 1000), null);
  assert.equal(M.gpuBusy(undefined, 10, 1000), null);
});

test("parseColorsToml reads flat quoted keys and ignores other tables", () => {
  const text = [
    "# a comment",
    "",
    'mode = "dark"',
    'accent = "#82FB9C" # trailing',
    "muted = '#2d3450'",
    'hyprland_active_border = "rgba(26a269ee) rgba(2ec27eee) 45deg"',
    "[ignored]",
    'mode = "light"',
    'background = "#000000"',
    "extra = '#abcdef'",
    "[[also]]",
    'name = "nope"',
  ].join("\n");
  const colors = M.parseColorsToml(text);
  assert.equal(colors.mode, "dark");
  assert.equal(colors.accent, "#82FB9C");
  assert.equal(colors.muted, "#2d3450");
  assert.equal(colors.hyprland_active_border, "rgba(26a269ee) rgba(2ec27eee) 45deg");
  assert.equal(colors.ignored, undefined);
  assert.equal(colors.background, undefined);
  assert.equal(colors.extra, undefined);
  assert.equal(colors.name, undefined);
});

test("meterColor ramps accent, yellow, red and falls back when keys are missing", () => {
  const colors = M.parseColorsToml(DARK_THEME);
  assert.equal(M.meterColor(0.69, colors), "#82fb9c");
  assert.equal(M.meterColor(0.7, colors), "#50f7d4");
  assert.equal(M.meterColor(0.89, colors), "#50f7d4");
  assert.equal(M.meterColor(0.9, colors), "#50f872");
  assert.equal(M.meterColor(0.5, {}), "#7aa2f7");
  assert.equal(M.meterColor(0.75, { accent: "#112233" }), "#e0c36a");
  assert.equal(M.meterColor(0.95, { accent: "#112233" }), "#e06c75");
  assert.equal(M.meterColor(Number.NaN, colors), "#82fb9c");
});

test("mixHex blends 6 percent toward the foreground", () => {
  assert.equal(M.mixHex("#000000", "#ffffff", 0.06), "#0f0f0f");
  assert.equal(M.mixHex("#ffffff", "#000000", 0.06), "#f0f0f0");
});

test("resolveTheme mixes labels toward the card and keeps 8-digit alpha", () => {
  const dark = M.resolveTheme(M.parseColorsToml(DARK_THEME));
  assert.equal(dark.mode, "dark");
  assert.equal(dark.card, "#151828");
  assert.equal(dark.label, M.mixHex(dark.foreground, dark.card, M.LABEL_MIX));
  assert.notEqual(dark.label, "#6a6e95");
  assert.equal(dark.border, "#ddf7ff14");
  assert.equal(M.qtColor(dark.border), "#14ddf7ff");
  assert.ok(luminance(dark.foreground) > luminance(dark.background));
  assert.ok(luminance(dark.label) > luminance(dark.card));

  const mixed = M.resolveTheme({ background: "#000000", foreground: "#ffffff", mode: "dark" });
  assert.equal(mixed.card, "#0f0f0f");
  assert.equal(mixed.label, M.mixHex("#ffffff", "#0f0f0f", 0.5));
  assert.equal(mixed.accent, "#7aa2f7");

  const alpha = M.resolveTheme({
    accent: "#82FB9C80",
    background: "#000000",
    foreground: "#ffffff",
    mode: "dark",
  });
  assert.equal(alpha.accent, "#82fb9c80");
  assert.equal(M.qtColor(alpha.accent), "#8082fb9c");
});

test("accent #ff000080 stays red at 50% alpha through resolveTheme and meterColor", () => {
  const theme = M.resolveTheme({
    accent: "#ff000080",
    background: "#000000",
    foreground: "#ffffff",
    mode: "dark",
  });
  assert.equal(theme.accent, "#ff000080");
  assert.equal(theme.colors.accent, "#ff000080");
  const meter = M.meterColor(0.5, theme.colors);
  assert.equal(meter, "#ff000080");
  assert.equal(M.qtColor(meter), "#80ff0000");
  assert.equal(M.qtColor("#82fb9c"), "#82fb9c");
  assert.equal(M.mixHex("#ff000080", "#000000ff", 0), "#ff000080");
});

test("light-mode theme stays readable", () => {
  const light = M.resolveTheme(M.parseColorsToml(LIGHT_THEME));
  assert.equal(light.mode, "light");
  assert.equal(light.background, "#fffcf0");
  assert.equal(light.card, "#e6e4d9");
  assert.equal(light.foreground, "#100f0f");
  assert.equal(light.label, M.mixHex(light.foreground, light.card, M.LABEL_MIX));
  assert.notEqual(light.label, "#878580");
  assert.equal(M.meterColor(0.95, light.colors), "#d14d41");
  assert.ok(luminance(light.foreground) < luminance(light.background));
  assert.ok(luminance(light.label) < luminance(light.card));
  assert.notEqual(light.card, light.background);
});

test("mode is respected, and a missing mode follows background luminance", () => {
  const forced = M.resolveTheme({ background: "#ffffff", foreground: "#000000", mode: "dark" });
  assert.equal(forced.mode, "dark");
  const inferredLight = M.resolveTheme({ background: "#FFFCF0", foreground: "#100F0F" });
  assert.equal(inferredLight.mode, "light");
  const inferredDark = M.resolveTheme({ background: "#0B0C16", foreground: "#ddf7ff" });
  assert.equal(inferredDark.mode, "dark");
});

test("pushHistory caps the series at 60 samples and does not mutate", () => {
  let hist = [];
  for (let i = 0; i < 75; i++) hist = M.pushHistory(hist, i);
  assert.equal(hist.length, 60);
  assert.equal(hist[0], 15);
  assert.equal(hist[59], 74);
  const original = [1];
  const replaced = M.pushHistory(original, -5);
  assert.deepEqual(replaced, [1, 0]);
  assert.deepEqual(original, [1]);
  assert.notEqual(replaced, original);
});

test("batteryPowerW prefers power_now and hides a missing battery", () => {
  assert.equal(M.batteryPowerW(null), null);
  assert.equal(M.batteryPowerW({}), null);
  assert.ok(Math.abs(M.batteryPowerW({ power_now_uw: 16393000 }) - 16.393) < 1e-9);
  assert.equal(M.batteryPowerW({ power_now_uw: 0, current_now_ua: 1000000, voltage_now_uv: 12000000 }), 0);
  assert.equal(M.batteryPowerW({ current_now_ua: 1000000, voltage_now_uv: 12000000 }), 12);
  assert.equal(M.batteryStatus("Discharging"), "discharging");
  assert.equal(M.batteryStatus("Full"), "full");
  assert.equal(M.batteryStatus("Charging"), "charging");
  assert.equal(M.batteryStatus(""), null);
  assert.equal(M.batteryStatus(null), null);
});

test("parsePs and topProcesses keep the top 8 by cpu and by memory", () => {
  const lines = ["COMMAND         %CPU %MEM"];
  for (let i = 0; i < 10; i++) {
    lines.push("proc" + i + "  " + (10 - i) + ".0  " + i + ".5");
  }
  lines.push("Web Content  1.0  20.0");
  const rows = M.parsePs(lines.join("\n"));
  assert.equal(rows.length, 11);
  assert.equal(rows[10].name, "Web Content");
  assert.equal(rows[10].cpu, 1);
  assert.equal(rows[10].mem, 20);
  const byCpu = M.topProcesses(rows, "cpu", 8);
  const byMem = M.topProcesses(rows, "mem", 8);
  assert.equal(byCpu.length, 8);
  assert.equal(byCpu[0].name, "proc0");
  assert.equal(byMem[0].name, "Web Content");
  assert.equal(byMem[1].name, "proc9");
});

test("formatters", () => {
  assert.equal(M.formatBytes(1536), "1.50 KB");
  assert.equal(M.formatBytes(1024 * 1024 * 1024), "1.00 GB");
  assert.equal(M.formatBytes(null), "—");
  assert.equal(M.formatRate(2048), "2.00 KB/s");
  assert.equal(M.formatPercent(12.4), "12%");
  assert.equal(M.formatPercent(null), "—");
  assert.equal(M.formatPercentPrecise(1.26), "1.3%");
  assert.equal(M.formatMhz(2988), "2.99 GHz");
  assert.equal(M.formatMhz(450), "450 MHz");
  assert.equal(M.formatMhz(null), "—");
  assert.equal(M.formatTemp(36.8), "37°C");
  assert.equal(M.formatTemp(null), "—");
  assert.equal(M.formatPower(16.393), "16.4 W");
  assert.equal(M.formatPower(1.2), "1.20 W");
  assert.equal(M.formatUsage(1024, 2048), "1.00 KB / 2.00 KB");
  assert.equal(M.formatUsage(null, 10), "—");
});

test("emptyState and emptyView are safe blanks", () => {
  const state = M.emptyState();
  const view = M.emptyView();
  assert.equal(state.t, null);
  assert.equal(view.gpu, null);
  assert.equal(view.battery, null);
  assert.deepEqual(view.cpu.cores, []);
  assert.equal(view.cpu.percentText, "—");
});

test("CPU temperature history accepts live valid samples and keeps the recent peak", () => {
  const sample = (i, temp) => ({ proc_stat: `cpu  ${i} 0 0 ${i} 0 0 0 0\n`, package_temp_c: temp, cpu_mhz: 3100 });
  let result = M.step(M.emptyState(), sample(1, 77), 1000);
  assert.deepEqual(result.state.cpuTempHist, []);
  assert.equal(result.view.cpu.tempPeakText, "");
  for (let i = 2; i <= M.HISTORY_LIMIT + 5; i++) result = M.step(result.state, sample(i, i), i * 1000);
  assert.equal(result.state.cpuTempHist.length, M.HISTORY_LIMIT);
  assert.deepEqual(result.view.cpu.tempHistory, Array.from({length: M.HISTORY_LIMIT}, (_, i) => i + 6));
  assert.equal(result.view.cpu.tempPeakText, "peak 65°C");
  assert.equal(result.view.cpu.percentText, "50%");
  assert.equal(result.view.cpu.tempText, "65°C");
  assert.equal(result.view.cpu.freqText, "3.10 GHz");
  assert.equal(result.view.cpu.history.length, M.HISTORY_LIMIT);
  for (const [index, value] of [NaN, Infinity, -Infinity, -20.01, 150.01, null, undefined, "", "50"].entries()) {
    const previous = result.state.cpuTempHist;
    result = M.step(result.state, sample(70 + index, value), (70 + index) * 1000);
    assert.equal(result.state.cpuTempHist, previous);
  }
  result = M.step(result.state, sample(80, -20), 80000);
  result = M.step(result.state, sample(81, 150), 81000);
  assert.deepEqual(result.view.cpu.tempHistory.slice(-2), [-20, 150]);
  assert.equal(result.view.cpu.tempPeakText, "peak 150°C");
});

test("CPU temperature thresholds use unrounded values and both sample formats", () => {
  let result = M.step(M.emptyState(), {package_temp_c: 40}, 1000);
  for (const [i, temp, level] of [[2,84.9,"normal"], [3,85,"warm"], [4,94.9,"warm"], [5,95,"hot"]]) {
    result = M.step(result.state, {temps: {package_c: temp}}, i * 1000);
    assert.equal(result.view.cpu.tempLevel, level);
    assert.equal(result.view.cpu.tempText, M.formatTemp(temp));
  }
  result = M.step(result.state, {}, 6000);
  assert.equal(result.view.cpu.tempLevel, "normal");
});

test("CPU temperature plot clips above the shared 100 maximum", () => {
  const points = M.buildSparkline([20, 120], 300, 100, 0, 100, M.HISTORY_LIMIT).points;
  assert.equal(points[points.length - 1].y, 1.5);
});

test("CPU and temperature history carry on failures and rebaseline, and clear on n/a", () => {
  const sample = (i, temp) => ({proc_stat: `cpu  ${i} 0 0 ${i} 0 0 0 0\n`, temps:{package_c:temp}});
  let result = M.step(M.emptyState(), sample(1, 40), 1000);
  result = M.step(result.state, sample(2, 96), 2000);
  const previous = result;
  result = M.step(result.state, {cpu:null, temps:{package_c:100}, errors:{cpu:"failed"}}, 3000);
  assert.equal(result.state.cpuHist, previous.state.cpuHist);
  assert.equal(result.state.cpuTempHist, previous.state.cpuTempHist);
  assert.equal(result.view.cpu.tempLevel, "hot");
  result = M.step(result.state, {proc_stat:sample(3, 0).proc_stat, temps:null, errors:{temps:"failed"}}, 4000);
  assert.equal(result.state.cpuTempHist, previous.state.cpuTempHist);
  assert.equal(result.view.cpu.tempLevel, "hot");
  const beforeGap = result;
  result = M.step(result.state, sample(4, 120), 100000);
  assert.equal(result.state.cpuHist, beforeGap.state.cpuHist);
  assert.equal(result.state.cpuTempHist, beforeGap.state.cpuTempHist);
  result = M.step(result.state, {cpu:null, temps:{na:true}, errors:{cpu:"failed"}}, 101000);
  assert.deepEqual(result.state.cpuTempHist, []);
  assert.equal(result.view.cpu.tempPeakText, "");
  assert.equal(result.view.cpu.tempText, "n/a");
  result = M.step(result.state, sample(5, 60), 102000);
  assert.deepEqual(result.state.cpuTempHist, [60]);
  result = M.step(result.state, {cpu:{na:true}, temps:{package_c:70}}, 103000);
  assert.deepEqual(result.state.cpuHist, []);
  assert.deepEqual(result.state.cpuTempHist, []);
  assert.equal(result.view.cpu.tempLevel, "normal");
});

test("step keeps 60 samples, zeroes a reset, and hides gpu and battery", () => {
  let state = M.emptyState();
  let view = null;
  for (let i = 0; i < 65; i++) {
    const user = 100 * i;
    const idle = 100 * i;
    const raw = {
      proc_stat: "cpu  " + user + " 0 0 " + idle + " 0 0 0 0\ncpu0  " + user + " 0 0 " + idle + " 0 0 0 0\n",
      meminfo: "MemTotal: 1000 kB\nMemFree: 400 kB\nBuffers: 0 kB\nCached: 100 kB\nMemAvailable: 500 kB\nSwapTotal: 100 kB\nSwapFree: 100 kB\n",
      net_dev: "  wlo1: " + (1000 * i) + " 0 0 0 0 0 0 0 " + (100 * i) + " 0 0 0 0 0 0 0\n  lo: 9 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0\n",
      diskstats: " 259 0 nvme0n1 0 0 " + (10 * i) + " 0 0 0 " + (4 * i) + " 0 0 0 0 0 0 0 0 0 0\n",
      virtual_ifaces: [],
      default_iface: "wlo1",
      disk_device: "nvme0n1",
      cpu_mhz: 3100,
      package_temp_c: 47,
      nvme_temp_c: 36.2,
      root_used: 25,
      root_total: 100,
      gpu: { present: false },
      battery: null,
      procs: null,
    };
    const result = M.step(state, raw, i * 1000);
    state = result.state;
    view = result.view;
  }
  assert.equal(state.cpuHist.length, 60);
  assert.equal(state.memHist.length, 60);
  assert.equal(state.rxHist.length, 60);
  assert.equal(view.gpu, null);
  assert.equal(view.battery, null);
  assert.equal(view.cpu.cores.length, 1);
  assert.equal(view.cpu.cores[0].percent, 50);
  assert.equal(view.cpu.tempText, "47°C");
  assert.equal(view.cpu.freqText, "3.10 GHz");
  assert.equal(view.net.iface, "wlo1");
  assert.equal(view.disk.device, "nvme0n1");
  assert.equal(view.disk.tempText, "36°C");
  assert.equal(view.cpu.history.length, 60);
  assert.notEqual(view.cpu.history[0], undefined);

  const reset = M.step(state, {
    proc_stat: "cpu  1 0 0 1 0 0 0 0\ncpu0  1 0 0 1 0 0 0 0\n",
    meminfo: "",
    net_dev: "  wlo1: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\n",
    diskstats: " 259 0 nvme0n1 0 0 1 0 0 0 1 0 0 0 0 0 0 0 0 0 0\n",
    virtual_ifaces: [],
    disk_device: "nvme0n1",
    gpu: { present: true, idle_ms: 5, mhz: 0 },
    battery: null,
  }, state.t + 1000);
  assert.equal(reset.view.cpu.percent, 0);
  assert.equal(reset.view.disk.readText, "0 B/s");
  assert.equal(reset.view.net.downText, "0 B/s");
  assert.equal(reset.view.gpu.percentText, "—");
  assert.equal(reset.view.gpu.freqText, "idle");
  assert.notEqual(reset.state.cpuHist, state.cpuHist);
  assert.equal(state.cpuHist.length, 60);
});

test("step gpu busy, battery, and zero elapsed time", () => {
  const base = {
    proc_stat: "cpu  10 0 0 10 0 0 0 0\ncpu0  5 0 0 5 0 0 0 0\ncpu1  5 0 0 5 0 0 0 0\n",
    meminfo: "MemTotal: 2000 kB\nMemAvailable: 1000 kB\n",
    net_dev: "  wlo1: 100 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n",
    diskstats: " 259 0 nvme0n1 0 0 100 0 0 0 40 0 0 0 0 0 0 0 0 0 0\n",
    virtual_ifaces: [],
    default_iface: "wlo1",
    disk_device: "nvme0n1",
    gpu: { present: true, idle_ms: 1000, mhz: 450 },
    battery: { capacity: 64, status: "Discharging", power_now_uw: 16393000 },
  };
  const first = M.step(M.emptyState(), base, 5000);
  assert.equal(first.view.cpu.percentText, "—");
  assert.equal(first.view.cpu.history.length, 0);
  assert.equal(first.view.net.downText, "—");
  assert.equal(first.view.net.rxHistory.length, 0);
  assert.equal(first.view.disk.readText, "unavailable");
  assert.equal(first.view.disk.readHistory.length, 0);
  assert.equal(first.view.gpu.percentText, "—");
  assert.equal(first.view.gpu.freqText, "450 MHz");
  assert.equal(first.view.gpu.history.length, 0);
  assert.equal(first.view.battery.percentText, "64%");
  assert.equal(first.view.battery.statusText, "discharging");
  assert.equal(first.view.battery.powerText, "16.4 W");
  assert.equal(first.view.battery.history.length, 1);
  assert.equal(first.view.cpu.cores.length, 2);
  assert.equal(first.view.cpu.cores[0].percentText, "—");
  assert.equal(first.view.mem.fraction, 0.5);
  assert.equal(first.view.mem.history.length, 1);
  assert.equal(first.view.mem.history[0], 50);

  const busy = M.step(first.state, Object.assign({}, base, {
    proc_stat: "cpu  60 0 0 60 0 0 0 0\ncpu0  40 0 0 20 0 0 0 0\ncpu1  20 0 0 40 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1000, mhz: 900 },
    battery: { capacity: 80, status: "Charging", current_now_ua: 2000000, voltage_now_uv: 8000000 },
  }), 5000);
  assert.equal(busy.skip, true);
  assert.equal(busy.state, first.state);
  assert.equal(busy.view.cpu.percentText, "—");
  assert.equal(busy.view.gpu.percentText, "—");
  assert.equal(busy.view.net.downText, "—");
  assert.equal(busy.view.disk.readText, "unavailable");
  assert.equal(busy.state.cpuHist.length, first.state.cpuHist.length);

  const moved = M.step(first.state, Object.assign({}, base, {
    proc_stat: "cpu  110 0 0 110 0 0 0 0\ncpu0  80 0 0 30 0 0 0 0\ncpu1  30 0 0 80 0 0 0 0\n",
    net_dev: "  wlo1: 1100 0 0 0 0 0 0 0 250 0 0 0 0 0 0 0\n",
    diskstats: " 259 0 nvme0n1 0 0 200 0 0 0 40 0 0 0 0 0 0 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1500, mhz: 900 },
  }), 6000);
  assert.equal(moved.view.cpu.percent, 50);
  assert.equal(moved.view.cpu.cores[0].percent, 75);
  assert.equal(moved.view.cpu.cores[1].percent, 25);
  assert.equal(moved.view.gpu.percent, 50);
  assert.equal(moved.view.gpu.freqText, "900 MHz");
  assert.equal(moved.view.net.downText, "1000 B/s");
  assert.equal(moved.view.net.upText, "200 B/s");
  assert.equal(moved.view.net.iface, "wlo1");
  assert.equal(moved.view.disk.readText, "50.0 KB/s");
  assert.equal(moved.view.disk.readHistory.length, 1);
  assert.equal(moved.view.mem.usedText, M.formatUsage(1000 * 1024, 2000 * 1024));
  assert.notEqual(moved.state.cpuHist, first.state.cpuHist);
  assert.deepEqual(first.state.cpuHist, []);
});

test("step falls back to current times voltage when power_now is absent", () => {
  const raw = {
    proc_stat: "",
    meminfo: "",
    net_dev: "",
    diskstats: "",
    gpu: { present: false },
    battery: { capacity: 10, status: "Full", current_now_ua: 500000, voltage_now_uv: 10000000 },
  };
  const result = M.step(M.emptyState(), raw, 1);
  assert.equal(result.view.battery.statusText, "full");
  assert.equal(result.view.battery.powerText, "5.00 W");
  assert.equal(result.view.gpu, null);
});

test("iface label lists summed physical interfaces, not the default route", () => {
  assert.equal(M.ifaceLabel(["wlo1"], "tailscale0"), "wlo1");
  assert.equal(M.ifaceLabel(["enp3s0", "wlo1"], "enp3s0"), "enp3s0 + wlo1");
  assert.equal(M.ifaceLabel(["enp3s0", "wlo1"], "wlo1"), "wlo1 + enp3s0");
  assert.equal(M.ifaceLabel(["wlo1", "docker0"], null), "docker0 + wlo1");
  assert.equal(M.ifaceLabel([], "wlo1"), "—");
});

test("default route prefers ipv4 and falls back to ipv6, skipping lo", () => {
  const v4 = "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\nwlo1 00000000 FE02A8C0 0003 0 0 600 00000000 0 0 0\n";
  const v6 = [
    "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200 lo",
    "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000008ec5b4fffe3b44a0 00000258 00000011 00000000 08000003 wlo1",
    "fd7a115ca1e000000000000000000000 30 00000000000000000000000000000000 00 00000000000000000000000000000000 00000400 00000001 00000000 00000001 tailscale0",
  ].join("\n");
  assert.equal(M.defaultRouteIface(v4, v6), "wlo1");
  assert.equal(M.defaultRouteIface("", v6), "wlo1");
  assert.equal(M.defaultRouteIface("", ""), null);
  assert.equal(M.defaultRouteIface("wlo1 00000000 0 0001 0 0 10 00000000 0 0 0\n", ""), "wlo1");
  assert.equal(M.defaultRouteIface("ppp0 00000000 00000000 0005 0 0 0 00000000 0 0 0\n", ""), "ppp0");
  assert.equal(M.defaultRouteIface("wlo1 00000000 0 0000 0 0 10 00000000 0 0 0\n", ""), null);
  assert.equal(M.defaultRouteIface("wlo1 00000000 0 0002 0 0 10 00000000 0 0 0\n", ""), null);
  assert.equal(M.defaultRouteIface("wlo1 00000000 0 0003 0 0 10 FFFFFFFF 0 0 0\n", ""), null);
  assert.equal(M.defaultRouteIface("wlo1 00000000 0 0003 0 0 10 00000000 0 0 0\n", ""), "wlo1");
  const prefix = "00000000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000001 00000000 00000000 00000003 wlo1\n";
  const upOnly = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00000001 eth0\n";
  const down = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00000000 eth0\n";
  assert.equal(M.defaultRouteIface("", prefix), null);
  assert.equal(M.defaultRouteIface("", upOnly), "eth0");
  assert.equal(M.defaultRouteIface("", down), null);
});

test("network headline ignores virtual patterns and names the summed interfaces", () => {
  const prev = M.step(M.emptyState(), {
    proc_stat: "cpu  1 0 0 1 0 0 0 0\n",
    net_dev: "  wlo1: 1000 0 0 0 0 0 0 0 400 0 0 0 0 0 0 0\n  enp3s0: 50 0 0 0 0 0 0 0 10 0 0 0 0 0 0 0\n  docker0: 10 0 0 0 0 0 0 0 10 0 0 0 0 0 0 0\n  tailscale0: 5 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n  lo: 9 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0\n",
    route_v4: "",
    route_v6: "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000008ec5b4fffe3b44a0 00000010 00000001 00000000 00000003 enp3s0\n",
    virtual_ifaces: ["docker0"],
    disk_device: null,
  }, 1000);
  assert.equal(prev.view.net.downText, "—");
  assert.equal(prev.view.net.iface, "enp3s0 + wlo1");
  const next = M.step(prev.state, {
    proc_stat: "cpu  2 0 0 2 0 0 0 0\n",
    net_dev: "  wlo1: 3000 0 0 0 0 0 0 0 900 0 0 0 0 0 0 0\n  enp3s0: 1050 0 0 0 0 0 0 0 10 0 0 0 0 0 0 0\n  docker0: 9000 0 0 0 0 0 0 0 10 0 0 0 0 0 0 0\n  tailscale0: 8000 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n  lo: 99 0 0 0 0 0 0 0 99 0 0 0 0 0 0 0\n",
    route_v4: "wlo1 00000000 0101A8C0 0003 0 0 100 00000000 0 0 0\n",
    route_v6: "",
    virtual_ifaces: [],
    disk_device: null,
  }, 2000);
  assert.equal(next.view.net.downText, "2.93 KB/s");
  assert.equal(next.view.net.upText, "500 B/s");
  assert.equal(next.view.net.iface, "wlo1 + enp3s0");
  assert.equal(next.view.net.perIface.length, 2);
  assert.equal(next.view.net.perIface[0].name, "wlo1");
  assert.equal(next.view.disk.readText, "unavailable");
});

test("clock jump rebaselines without a gpu or cpu spike", () => {
  const base = {
    proc_stat: "cpu  10 0 0 90 0 0 0 0\ncpu0  10 0 0 90 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    net_dev: "  wlo1: 100 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n",
    diskstats: " 259 0 nvme0n1 0 0 100 0 0 0 40 0 0 0 0 0 0 0 0 0 0\n",
    virtual_ifaces: [],
    default_iface: "wlo1",
    disk_device: "nvme0n1",
    gpu: { present: true, idle_ms: 1000, mhz: 800 },
    battery: null,
  };
  const first = M.step(M.emptyState(), base, 0);
  const second = M.step(first.state, Object.assign({}, base, {
    proc_stat: "cpu  60 0 0 140 0 0 0 0\ncpu0  60 0 0 140 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1500, mhz: 800 },
    net_dev: "  wlo1: 1100 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n",
  }), 1000);
  assert.equal(second.view.cpu.percent, 50);
  assert.equal(second.view.gpu.percent, 50);
  const hist = second.state.gpuHist.slice();
  const jumped = M.step(second.state, Object.assign({}, base, {
    proc_stat: "cpu  50000 0 0 50000 0 0 0 0\ncpu0  50000 0 0 50000 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1500, mhz: 0 },
    net_dev: "  wlo1: 900000 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n",
  }), 31000);
  assert.equal(jumped.view.gpu.percent, 50);
  assert.notEqual(jumped.view.gpu.percentText, "100%");
  assert.equal(jumped.view.gpu.freqText, "idle");
  assert.deepEqual(jumped.state.gpuHist, hist);
  assert.equal(jumped.view.cpu.percent, 50);
  assert.equal(jumped.state.gpuIdle, 1500);
  const after = M.step(jumped.state, Object.assign({}, base, {
    proc_stat: "cpu  50050 0 0 50050 0 0 0 0\ncpu0  50050 0 0 50050 0 0 0 0\n",
    gpu: { present: true, idle_ms: 2500, mhz: 400 },
  }), 32000);
  assert.equal(after.view.gpu.percent, 0);
  assert.equal(after.view.cpu.percent, 50);
  assert.equal(after.view.gpu.freqText, "400 MHz");
});

test("gpu frequency distinguishes idle from unavailable", () => {
  assert.equal(M.formatGpuFreq(0), "idle");
  assert.equal(M.formatGpuFreq(null), "unavailable");
  assert.equal(M.formatGpuFreq(undefined), "unavailable");
  assert.equal(M.formatGpuFreq(450), "450 MHz");
  assert.equal(M.formatMhzShort(2500), "2.5G");
  assert.equal(M.formatMhzShort(800), "800M");
  assert.equal(M.formatMhzShort(null), "");
});

test("battery meter uses its own low-charge ramp", () => {
  const colors = M.parseColorsToml(DARK_THEME);
  assert.equal(M.batteryMeterColor(0.14, colors), "#50f872");
  assert.equal(M.batteryMeterColor(0.15, colors), "#50f7d4");
  assert.equal(M.batteryMeterColor(0.29, colors), "#50f7d4");
  assert.equal(M.batteryMeterColor(0.3, colors), "#82fb9c");
  assert.equal(M.batteryMeterColor(0.9, colors), "#82fb9c");
  assert.notEqual(M.batteryMeterColor(0.9, colors), M.meterColor(0.9, colors));
});

test("process names, live cpu percent, and grouped rows", () => {
  assert.equal(M.procDisplayName("missioncenter-m", "/usr/bin/missioncenter"), "missioncenter");
  assert.equal(M.procDisplayName("missioncenter-m", ""), "missioncenter-m");
  assert.equal(M.procDisplayName("systemd", "/usr/lib/systemd/systemd"), "systemd");
  assert.equal(M.procDisplayName("Web Content", ""), "Web Content");
  assert.equal(M.procCpuPercent(100, 2000, 100), 50);
  assert.equal(M.procCpuPercent(400, 2000, 100), 200);
  assert.equal(M.procCpuPercent(-5, 1000, 100), 0);
  assert.equal(M.procMemPercent(250, 4096, 1000 * 4096), 25);

  const grouped = M.groupProcesses([
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "worker.bin", cpu: 10, mem: 1 },
    { name: "Web Content", cpu: 4, mem: 3 },
    { name: "Web Content", cpu: 6, mem: 4 },
    { name: "firefox", cpu: 80, mem: 20 },
  ]);
  const byCpu = M.topProcesses(grouped, "cpu", 8);
  assert.equal(byCpu[0].name, "firefox");
  assert.equal(byCpu[1].name, "worker.bin ×6");
  assert.equal(byCpu[1].cpu, 60);
  assert.equal(byCpu[2].name, "Web Content ×2");
  assert.equal(byCpu[2].cpu, 10);
  assert.equal(byCpu[2].mem, 7);
});

test("step ranks processes from tick deltas and keeps a suspend from spiking", () => {
  const procs = (ticks, rss) => ({
    clk_tck: 100,
    page_size: 4096,
    rows: [
      { pid: 10, comm: "missioncenter-m", argv0: "/usr/bin/missioncenter", ticks: ticks[0], rss: rss[0] },
      { pid: 11, comm: "worker.bin", ticks: ticks[1], rss: rss[1] },
      { pid: 12, comm: "worker.bin", ticks: ticks[2], rss: rss[2] },
      { pid: 13, comm: "Web Content", ticks: ticks[3], rss: rss[3] },
    ],
  });
  const raw = (ticks) => ({
    proc_stat: "cpu  1 0 0 1 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    procs: procs(ticks, [250, 40, 40, 10]),
  });
  const first = M.step(M.emptyState(), raw([1000, 0, 0, 0]), 0);
  assert.equal(first.view.processes.byCpu.length, 0);
  assert.equal(first.view.processes.byMem[0].name, "missioncenter");
  const second = M.step(first.state, raw([1000, 100, 100, 10]), 2000);
  assert.equal(second.view.processes.byCpu[0].name, "worker.bin ×2");
  assert.equal(second.view.processes.byCpu[0].text, "100%");
  assert.equal(second.view.processes.byCpu[1].name, "Web Content");
  assert.equal(second.view.processes.byMem[0].name, "missioncenter");
  const jumped = M.step(second.state, raw([50000, 50000, 50000, 50000]), 40000);
  assert.equal(jumped.view.processes.byCpu[0].name, "worker.bin ×2");
  assert.equal(jumped.view.processes.byCpu[0].text, "100%");
  const after = M.step(jumped.state, raw([50000, 50100, 50100, 50010]), 42000);
  assert.equal(after.view.processes.byCpu[0].name, "worker.bin ×2");
  assert.equal(after.view.processes.byCpu[0].text, "100%");
});

test("grid is hole-free: cpu spans 2, every other card spans 1", () => {
  for (const width of [886, 900, 1079, 1080, 1280, 1499, 1500, 1800]) {
    const shape = M.gridShape(width);
    assert.equal(shape.cpuSpan, 2);
    assert.equal(shape.cpuSpan + 6, shape.columns * shape.rows);
    assert.ok(shape.cpuSpan <= 2);
  }
  assert.deepEqual(M.gridShape(1800), { columns: 4, rows: 2, cpuSpan: 2 });
  assert.deepEqual(M.gridShape(1500), { columns: 4, rows: 2, cpuSpan: 2 });
  assert.deepEqual(M.gridShape(1080), { columns: 4, rows: 2, cpuSpan: 2 });
  assert.deepEqual(M.gridShape(1079), { columns: 2, rows: 4, cpuSpan: 2 });
  assert.deepEqual(M.gridShape(900), { columns: 2, rows: 4, cpuSpan: 2 });
});

test("sparkline fill is the area under the stroke, right-aligned", () => {
  const flat = M.buildSparkline([40, 40, 40, 40], 590, 80, 0, 100, 60);
  assert.equal(flat.points.length, 4);
  assert.equal(flat.points[0].x, 560);
  assert.equal(flat.points[3].x, 590);
  assert.ok(Math.abs(flat.points[0].y - flat.points[3].y) < 1e-9);
  const moves = flat.fill.filter((cmd) => cmd.t === "M");
  assert.equal(moves.length, 1);
  assert.equal(flat.fill[0].t, "M");
  assert.equal(flat.fill[0].x, flat.points[0].x);
  assert.equal(flat.fill[0].y, 80);
  assert.equal(flat.fill[flat.fill.length - 1].t, "Z");
  const down = flat.fill[flat.fill.length - 2];
  assert.equal(down.t, "L");
  assert.equal(down.x, flat.points[3].x);
  assert.equal(down.y, 80);
  assert.equal(flat.fill.filter((cmd) => cmd.t === "M").length, 1);

  const short = M.buildSparkline([10, 90], 590, 50, 0, 100, 60);
  assert.equal(short.points.length, 2);
  assert.ok(short.points[0].x > 500);
  assert.equal(short.points[1].x, 590);
  assert.ok(short.points[0].y > short.points[1].y);

  const one = M.buildSparkline([40], 590, 80, 0, 100, 60);
  assert.equal(one.points.length, 2);
  assert.equal(one.points[0].y, one.points[1].y);
  assert.equal(one.points[1].x, 590);
  assert.ok(one.points[0].x < one.points[1].x);
  assert.equal(one.fill.filter((cmd) => cmd.t === "M").length, 1);

  const empty = M.buildSparkline([], 100, 40, 0, 100, 60);
  assert.equal(empty.fill.length, 0);
  assert.equal(empty.points.length, 0);

  const low = M.buildSparkline([50], 100, 40, 0, 100, 60);
  const raised = M.buildSparkline([50], 100, 40, 40, 100, 60);
  assert.ok(low.points[0].y < raised.points[0].y);
});

test("seriesSame ignores a new array with the same numbers", () => {
  assert.equal(M.seriesSame([1, 2, 3], [1, 2, 3]), true);
  assert.equal(M.seriesSame([1, 2], [1, 2, 3]), false);
  assert.equal(M.seriesSame([], []), true);
  assert.equal(M.seriesSame(null, []), true);
  assert.equal(M.seriesSame(null, null), true);
  assert.equal(M.seriesSame([1], [2]), false);
});

test("battery_skip keeps the previous charge instead of clearing the card", () => {
  const first = M.step(M.emptyState(), {
    proc_stat: "cpu  1 0 0 1 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    battery: { capacity: 40, status: "Discharging", power_now_uw: 5000000 },
  }, 1000);
  assert.equal(first.view.battery.percentText, "40%");
  assert.equal(first.view.battery.powerText, "5.00 W");
  assert.equal(first.view.battery.history.length, 1);
  const skipped = M.step(first.state, {
    proc_stat: "cpu  2 0 0 2 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    battery_skip: true,
  }, 2000);
  assert.equal(skipped.view.battery.percentText, "40%");
  assert.equal(skipped.view.battery.powerText, "5.00 W");
  assert.equal(skipped.view.battery.history.length, 1);
  assert.equal(skipped.view.battery.history, first.view.battery.history);
  const gone = M.step(skipped.state, {
    proc_stat: "cpu  3 0 0 3 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    battery: null,
  }, 3000);
  assert.equal(gone.view.battery, null);
});

test("too-short tick keeps every card and does not move baselines", () => {
  const raw = (user, idleMs) => ({
    proc_stat: "cpu  " + user + " 0 0 10 0 0 0 0\ncpu0  " + user + " 0 0 10 0 0 0 0\n",
    meminfo: "MemTotal: 2000 kB\nMemAvailable: 1000 kB\n",
    net_dev: "  wlo1: " + (1000 + user) + " 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n",
    diskstats: " 259 0 nvme0n1 0 0 " + (100 + user) + " 0 0 0 40 0 0 0 0 0 0 0 0 0 0\n",
    virtual_ifaces: [],
    default_iface: "wlo1",
    disk_device: "nvme0n1",
    cpu_mhz: 3100,
    package_temp_c: 40,
    gpu: { present: true, idle_ms: idleMs, mhz: 400 },
    battery: { capacity: 50, status: "Discharging", power_now_uw: 5000000 },
    procs: { presented: { byCpu: [{ name: "firefox", text: "10.0%" }], byMem: [{ name: "firefox", text: "5.0%" }] } },
  });
  const first = M.step(M.emptyState(), raw(10, 1000), 1000);
  const second = M.step(first.state, raw(80, 1500), 2000);
  assert.notEqual(second.view.cpu.percentText, "—");
  assert.notEqual(second.view.disk.readText, "unavailable");
  assert.equal(second.view.gpu.percent, 50);
  assert.equal(second.view.battery.percentText, "50%");
  assert.equal(second.view.processes.byCpu[0].name, "firefox");
  const skipped = M.step(second.state, raw(500, 9000), 2050);
  assert.equal(skipped.skip, true);
  assert.equal(skipped.state, second.state);
  assert.equal(skipped.view, second.view);
  assert.equal(skipped.state.t, 2000);
  assert.equal(skipped.state.gpuIdle, second.state.gpuIdle);
  assert.equal(skipped.state.gpuAt, second.state.gpuAt);
  assert.equal(skipped.state.diskDevice, "nvme0n1");
  assert.equal(skipped.view.cpu.percentText, second.view.cpu.percentText);
  assert.equal(skipped.view.mem.usedText, second.view.mem.usedText);
  assert.equal(skipped.view.disk.readText, second.view.disk.readText);
  assert.equal(skipped.view.disk.readHistory, second.view.disk.readHistory);
  assert.equal(skipped.view.net.downText, second.view.net.downText);
  assert.equal(skipped.view.gpu.percentText, second.view.gpu.percentText);
  assert.equal(skipped.view.gpu.history, second.view.gpu.history);
  assert.equal(skipped.view.battery.percentText, second.view.battery.percentText);
  assert.equal(skipped.view.processes.byCpu, second.view.processes.byCpu);
});

test("step never throws on empty, error-only, missing, or partial views", () => {
  const partial = M.emptyState();
  partial.t = 0;
  partial.view = {};
  const missingCards = M.emptyState();
  missingCards.t = 0;
  missingCards.view = { cpu: null, mem: null, disk: null, net: null, gpu: null, processes: null, battery: null };
  const samples = [
    [M.emptyState(), {}, 1000],
    [M.emptyState(), { error: "disk read failed" }, 1000],
    [M.emptyState(), { gpu: {}, procs: {}, battery: {}, net_dev: null, diskstats: null }, 1000],
    [partial, { proc_stat: "cpu  5 0 0 5 0 0 0 0\n", gpu: { present: true, idle_ms: 10, mhz: 1 } }, 20000],
    [missingCards, { error: "x" }, 40000],
    [partial, { procs: { presented: { byCpu: "nope", byMem: [] } }, disk_device: "sda" }, 30000],
  ];
  for (const [state, raw, t] of samples) {
    assert.doesNotThrow(() => M.step(state, raw, t));
  }
});

test("gpu bad idle stays visible and does not distort the next delta", () => {
  const base = {
    proc_stat: "cpu  10 0 0 10 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    disk_device: "nvme0n1",
    gpu: { present: true, idle_ms: 1000, mhz: 400 },
  };
  const first = M.step(M.emptyState(), base, 1000);
  assert.equal(first.view.gpu.percentText, "—");
  assert.equal(first.view.gpu.history.length, 0);
  const bad = M.step(first.state, Object.assign({}, base, {
    gpu: { present: true, idle_ms: null, mhz: 900 },
  }), 2000);
  assert.notEqual(bad.view.gpu, null);
  assert.equal(bad.view.gpu.percent, null);
  assert.equal(bad.view.gpu.percentText, "—");
  assert.equal(bad.view.gpu.fraction, 0);
  assert.equal(bad.view.gpu.history.length, 0);
  assert.equal(bad.state.gpuIdle, 1000);
  assert.equal(bad.state.gpuAt, 1000);
  const next = M.step(bad.state, Object.assign({}, base, {
    gpu: { present: true, idle_ms: 2500, mhz: 900 },
  }), 3000);
  assert.equal(next.view.gpu.percent, 25);
  assert.equal(next.view.gpu.history.length, 1);
  assert.equal(next.view.gpu.history[0], 25);
  const wild = M.step(next.state, Object.assign({}, base, {
    gpu: { present: true, idle_ms: Number.NaN, mhz: 1 },
  }), 4000);
  assert.notEqual(wild.view.gpu, null);
  assert.equal(wild.view.gpu.percentText, "—");
  assert.equal(wild.view.gpu.history.length, 1);
});

test("disk histories are keyed by device and clear when the device is gone", () => {
  let state = M.emptyState();
  let at = 1000;
  let view = null;
  state = M.step(state, { diskstats: " 259 0 nvme0n1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n", disk_device: "nvme0n1" }, at).state;
  for (let i = 1; i <= 4; i++) {
    at += 1000;
    const stepped = M.step(state, {
      diskstats: " 259 0 nvme0n1 0 0 " + (100 * i) + " 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n  8 0 sda 0 0 " + (50 * i) + " 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n",
      disk_device: "nvme0n1",
    }, at);
    state = stepped.state;
    view = stepped.view;
  }
  assert.ok(view.disk.readHistory.length >= 3);
  const nvmeHist = view.disk.readHistory.slice();
  at += 1000;
  const switched = M.step(state, {
    diskstats: " 259 0 nvme0n1 0 0 900 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n  8 0 sda 0 0 900 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
  }, at);
  assert.notDeepEqual(switched.view.disk.readHistory, nvmeHist);
  assert.ok(switched.view.disk.readHistory.length < nvmeHist.length);
  assert.equal(switched.view.disk.device, "sda");
  at += 1000;
  const back = M.step(switched.state, {
    diskstats: " 259 0 nvme0n1 0 0 1000 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n  8 0 sda 0 0 1000 0 0 0 10 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "nvme0n1",
  }, at);
  assert.equal(back.view.disk.readHistory[0], nvmeHist[0]);
  assert.ok(back.view.disk.readHistory.length >= nvmeHist.length);
  at += 1000;
  const gone = M.step(back.state, { diskstats: "", disk_device: null }, at);
  assert.equal(gone.view.disk.readText, "unavailable");
  assert.deepEqual(gone.view.disk.readHistory, []);
  assert.deepEqual(gone.view.disk.writeHistory, []);
});

test("processes go stale after 10s, cap at 8, and reject a bad table", () => {
  const rows = [];
  for (let i = 0; i < 10; i++) rows.push({ name: "p" + i, text: i + "%" });
  const first = M.step(M.emptyState(), {
    procs: { presented: { byCpu: rows, byMem: rows } },
  }, 1000);
  assert.equal(first.view.processes.byCpu.length, 8);
  assert.equal(first.view.processes.byCpu[0].name, "p0");
  assert.equal(first.view.processes.byMem.length, 8);
  assert.equal(first.view.processes.stale, false);
  const kept = M.step(first.state, { proc_stat: "cpu  1 0 0 1 0 0 0 0\n" }, 5000);
  assert.equal(kept.view.processes.byCpu.length, 8);
  assert.equal(kept.view.processes.stale, false);
  const fast = M.step(first.state, {
    procs: { presented: { byCpu: [{ name: "other", text: "1%" }], byMem: [{ name: "other", text: "1%" }] } },
  }, 1100);
  assert.equal(fast.view.processes.byCpu[0].name, "p0");
  const stale = M.step(first.state, { proc_stat: "cpu  2 0 0 2 0 0 0 0\n" }, 12001);
  assert.equal(stale.view.processes.stale, true);
  assert.equal(stale.view.processes.byCpu.length, 8);
  assert.equal(stale.view.processes.byCpu[0].name, "p0");
  assert.equal(stale.view.processes.byMem[0].name, "p0");
  assert.equal(stale.view.processes.freshAt, first.view.processes.freshAt);
  const bad = M.step(first.state, {
    procs: { presented: { byCpu: "nope", byMem: rows } },
  }, 2000);
  assert.equal(bad.view.processes.byCpu[0].name, "p0");
});

test("pid plus start time misses a reused pid", () => {
  const procs = (start, ticks) => ({
    clk_tck: 100,
    page_size: 4096,
    rows: [{ pid: 10, comm: "worker", ticks: ticks, rss: 10, start: start }],
  });
  const raw = (start, ticks) => ({
    proc_stat: "cpu  1 0 0 1 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    procs: procs(start, ticks),
  });
  const first = M.step(M.emptyState(), raw(100, 0), 0);
  const second = M.step(first.state, raw(100, 50), 1000);
  assert.equal(second.view.processes.byCpu[0].text, "50.0%");
  const reused = M.step(second.state, raw(999, 500), 2000);
  assert.equal(reused.view.processes.byCpu.length, 0);
  const after = M.step(reused.state, raw(999, 600), 3000);
  assert.equal(after.view.processes.byCpu[0].text, "100%");
});

test("step shows a presented process table and keeps it across ticks", () => {
  const presented = {
    byCpu: [{ name: "worker.bin ×6", text: "60.0%" }],
    byMem: [{ name: "firefox", text: "20.0%" }],
  };
  const first = M.step(M.emptyState(), {
    proc_stat: "cpu  1 0 0 1 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 400 kB\n",
    procs: {
      presented: presented,
      rows: [{ pid: 1, comm: "should-not-win", ticks: 0, rss: 1 }],
      clk_tck: 100,
      page_size: 4096,
    },
  }, 1000);
  assert.equal(first.view.processes.byCpu.length, 1);
  assert.equal(first.view.processes.byCpu[0].name, "worker.bin ×6");
  assert.equal(first.view.processes.byMem[0].name, "firefox");
  const next = M.step(first.state, {
    proc_stat: "cpu  2 0 0 2 0 0 0 0\n",
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 400 kB\n",
  }, 2000);
  assert.equal(next.view.processes.byCpu[0].name, "worker.bin ×6");
  assert.equal(next.view.processes.byMem[0].text, "20.0%");
});

test("a core that disappears and comes back is not zero-baselined", () => {
  const withBoth = "cpu  10 0 0 10 0 0 0 0\ncpu0 10 0 0 10 0 0 0 0\ncpu1 5 0 0 5 0 0 0 0\n";
  const only0 = "cpu  20 0 0 20 0 0 0 0\ncpu0 20 0 0 20 0 0 0 0\n";
  const back = "cpu  30 0 0 30 0 0 0 0\ncpu0 30 0 0 30 0 0 0 0\ncpu1 100 0 0 0 0 0 0 0\n";
  const first = M.parseProcStat(withBoth);
  const gone = M.parseProcStat(only0);
  const returned = M.parseProcStat(back);
  assert.equal(gone.cores.length, 1);
  assert.equal(M.cpuDeltas(gone, returned).cores[1], null);
  assert.equal(M.cpuDeltas(first, gone).cores[0], 50);
  const hole = M.parseProcStat("cpu  10 0 0 10 0 0 0 0\ncpu0 10 0 0 10 0 0 0 0\ncpu2 4 0 0 4 0 0 0 0\n");
  const holeNext = M.parseProcStat("cpu  20 0 0 20 0 0 0 0\ncpu0 20 0 0 20 0 0 0 0\ncpu1 80 0 0 0 0 0 0 0\ncpu2 8 0 0 8 0 0 0 0\n");
  assert.equal(hole.cores[1], null);
  assert.equal(M.cpuDeltas(hole, holeNext).cores[1], null);
  assert.equal(M.cpuDeltas(hole, holeNext).cores[2], 50);

  const a = M.step(M.emptyState(), { proc_stat: withBoth }, 1000);
  const b = M.step(a.state, { proc_stat: only0 }, 2000);
  assert.equal(b.view.cpu.cores.length, 1);
  const c = M.step(b.state, { proc_stat: back }, 3000);
  assert.equal(c.view.cpu.cores[0].percentText, "50%");
  assert.equal(c.view.cpu.cores[1].percent, null);
  assert.equal(c.view.cpu.cores[1].percentText, "—");
  const d = M.step(c.state, {
    proc_stat: "cpu  40 0 0 40 0 0 0 0\ncpu0 40 0 0 40 0 0 0 0\ncpu1 150 0 0 50 0 0 0 0\n",
  }, 4000);
  assert.equal(d.view.cpu.cores[1].percentText, "50%");
});

test("a process table refreshes freshness and a slow gap does not spike cpu", () => {
  const presented = {
    byCpu: [{ name: "firefox", text: "10.0%" }],
    byMem: [{ name: "firefox", text: "5.0%" }],
  };
  const rows = [{ pid: 10, comm: "firefox", ticks: 100, rss: 10, start: 5 }];
  const first = M.step(M.emptyState(), {
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    procs: { rows: rows, clk_tck: 100, page_size: 4096 },
  }, 1000);
  const snapT = first.state.procSnap.t;
  const snapTicks = Object.assign({}, first.state.procSnap.ticks);
  const shown = M.step(first.state, {
    procs: { presented: presented },
  }, 3000);
  assert.equal(shown.view.processes.byCpu[0].name, "firefox");
  assert.equal(shown.state.procSnap.t, snapT);
  assert.deepEqual(shown.state.procSnap.ticks, snapTicks);
  assert.equal(shown.view.processes.freshAt, 3000);

  // Presented-only after a long gap still refreshes freshness and does not move ticks.
  const slow = M.step(shown.state, {
    procs: { presented: { byCpu: [{ name: "other", text: "99%" }], byMem: [{ name: "other", text: "99%" }] } },
  }, 20000);
  assert.equal(slow.view.processes.byCpu[0].name, "other");
  assert.equal(slow.view.processes.freshAt, 20000);
  assert.equal(slow.view.processes.stale, false);
  assert.equal(slow.state.procSnap.t, snapT);
  assert.deepEqual(slow.state.procSnap.ticks, snapTicks);

  // Rows with no per-row read time: keep the rows on screen, move the snapshot, refresh freshness.
  const recovered = M.step(slow.state, {
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    procs: { rows: [{ pid: 10, comm: "firefox", ticks: 900, rss: 10, start: 5 }], clk_tck: 100, page_size: 4096 },
  }, 21000);
  assert.equal(recovered.state.procSnap.t, 21000);
  assert.notDeepEqual(recovered.state.procSnap.ticks, snapTicks);
  assert.equal(recovered.state.procSnap.ticks["10:5"], 900);
  assert.equal(recovered.view.processes.freshAt, 21000);
  assert.equal(recovered.view.processes.byCpu[0].name, "other");
  assert.equal(recovered.view.processes.stale, false);
});

test("per-row read times rank cpu across a long wall gap", () => {
  const raw = (ticks, readMs) => ({
    meminfo: "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
    procs: {
      clk_tck: 100,
      page_size: 4096,
      rows: [{ pid: 7, comm: "worker", ticks: ticks, rss: 10, start: 3, read_ms: readMs }],
    },
  });
  const first = M.step(M.emptyState(), raw(0, 1000), 1000);
  const second = M.step(first.state, raw(100, 2000), 9000);
  assert.equal(second.view.processes.byCpu[0].text, "100%");
  assert.equal(second.view.processes.freshAt, 9000);
  assert.equal(second.view.processes.stale, false);
});

test("a partial presented table is shown and does not move the tick snapshot", () => {
  const baseRows = [{ pid: 4, comm: "init", ticks: 10, rss: 2, start: 1 }];
  const first = M.step(M.emptyState(), {
    meminfo: "MemTotal: 1000 kB\n",
    procs: { rows: baseRows, clk_tck: 100, page_size: 4096 },
  }, 1000);
  const partial = M.step(first.state, {
    procs: {
      presented: { byCpu: [{ name: "partial", text: "1.0%" }], byMem: [{ name: "partial", text: "2.0%" }] },
      complete: false,
    },
  }, 4000);
  assert.equal(partial.view.processes.byCpu[0].name, "partial");
  assert.equal(partial.view.processes.freshAt, 4000);
  assert.equal(partial.state.procSnap.t, first.state.procSnap.t);
  assert.deepEqual(partial.state.procSnap.ticks, first.state.procSnap.ticks);
});

test("rate_mono_ms is the window for net and disk rates", () => {
  const first = M.step(M.emptyState(), {
    net_dev: "  wlo1: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    diskstats: " 8 0 sda 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
    virtual_ifaces: [],
    rate_mono_ms: 1000,
  }, 5000);
  const second = M.step(first.state, {
    net_dev: "  wlo1: 2000 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    diskstats: " 8 0 sda 0 0 100 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
    virtual_ifaces: [],
    rate_mono_ms: 3000,
  }, 6000);
  assert.equal(second.view.net.downText, "1000 B/s");
  assert.equal(second.view.disk.readText, "25.0 KB/s");
  assert.equal(second.state.rateMono, 3000);
});

test("gpu busy_pct is a direct percent and a failed read does not replay it", () => {
  const first = M.step(M.emptyState(), {
    gpu: { present: true, driver: "amdgpu", busy_pct: 40, mhz: 800 },
  }, 1000);
  assert.equal(first.view.gpu.percent, 40);
  assert.equal(first.view.gpu.percentText, "40%");
  assert.equal(first.view.gpu.driver, "amdgpu");
  assert.equal(first.view.gpu.history.length, 1);
  const missed = M.step(first.state, {
    gpu: { present: true, driver: "amdgpu", busy_pct: null, mhz: 800 },
  }, 2000);
  assert.equal(missed.view.gpu.percent, null);
  assert.equal(missed.view.gpu.percentText, "—");
  assert.equal(missed.view.gpu.history.length, 1);
  const nvidia = M.step(M.emptyState(), {
    gpu: { present: true, driver: "nvidia", unsupported: true },
  }, 1000);
  assert.equal(nvidia.view.gpu.unsupported, true);
  assert.equal(nvidia.view.gpu.percentText, "not supported");
  assert.equal(nvidia.view.gpu.driver, "nvidia");
});

test("network detail lines list each interface once", () => {
  const row = (name) => ({ name: name, downText: "1 B/s", upText: "2 B/s" });
  assert.deepEqual(M.netDetailLines([row("wlo1")], "wlo1"), []);
  assert.deepEqual(M.netDetailLines([], "—"), []);
  const headlinePlusOne = M.netDetailLines([row("wlan0"), row("enp1s0")], "wlan0");
  assert.equal(headlinePlusOne.length, 1);
  assert.equal(headlinePlusOne[0].name, "enp1s0");
  const two = M.netDetailLines([row("wlo1"), row("enp3s0"), row("wlo1")], "wlo1 + enp3s0");
  assert.equal(two.length, 2);
  assert.deepEqual(two.map((item) => item.name), ["wlo1", "enp3s0"]);
  const many = [row("a"), row("b"), row("c"), row("d"), row("e"), row("e"), row("a + b")];
  const lines = M.netDetailLines(many, "a + b");
  assert.equal(lines.length, 5);
  assert.deepEqual(lines.slice(0, 4).map((item) => item.name), ["a", "b", "c", "d"]);
  assert.equal(lines[4].more, true);
  assert.equal(lines[4].text, "+1 more");
  const six = M.netDetailLines([row("a"), row("b"), row("c"), row("d"), row("e"), row("f")], "headline");
  assert.equal(six[4].text, "+2 more");
});

test("core layout stays at least one column and compacts dense cpus", () => {
  const narrow = M.coreLayout(8, 0, 0);
  assert.equal(narrow.columns >= 1, true);
  assert.equal(narrow.compact, false);
  assert.equal(M.coreLayout(8, 700, 200).columns, 8);
  assert.equal(M.coreLayout(4, 400, 100).columns, 4);
  assert.equal(M.coreLayout(2, 200, 80).columns, 2);
  const dense = M.coreLayout(64, 860, 360);
  assert.equal(dense.compact, true);
  assert.equal(dense.columns >= 1, true);
  assert.equal(dense.cellH > 0, true);
  assert.equal(dense.cellW > 0, true);
  const packed = M.coreLayout(128, 900, 200);
  assert.equal(packed.columns >= 1, true);
  assert.equal(packed.cellH > 0, true);
  const cold = M.coreLayout(128, 0, 0);
  assert.equal(cold.columns >= 1, true);
  assert.equal(cold.cellH, 0);
});

test("a 64-core sample stays compact through step", () => {
  const line = (label, busy, idle) => label + " " + busy + " 0 0 " + idle + " 0 0 0 0 0 0";
  const text = (busy, idle) => {
    const lines = [line("cpu", busy, idle)];
    for (let i = 0; i < 64; i++) lines.push(line("cpu" + i, busy, idle));
    return lines.join("\n") + "\n";
  };
  const first = M.step(M.emptyState(), { proc_stat: text(10, 10) }, 1000);
  const second = M.step(first.state, { proc_stat: text(20, 20) }, 2000);
  assert.equal(second.view.cpu.cores.length, 64);
  assert.equal(second.view.cpu.cores[63].percentText, "50%");
  assert.equal(M.coreLayout(second.view.cpu.cores.length, 860, 360).compact, true);
});

test("unchanged core cells keep the same cores array", () => {
  const stat = (n) => "cpu  " + n + " 0 0 " + n + " 0 0 0 0\ncpu0 " + n + " 0 0 " + n + " 0 0 0 0\n";
  const sample = (n) => ({ proc_stat: stat(n), cpu_mhz_cores: [2400] });
  const first = M.step(M.emptyState(), sample(10), 1000);
  const second = M.step(first.state, sample(20), 2000);
  const third = M.step(second.state, sample(30), 3000);
  assert.equal(second.view.cpu.cores[0].percentText, "50%");
  assert.equal(third.view.cpu.cores, second.view.cpu.cores);
});

test("parsed collector numbers drive cpu, disk, net, and temps", () => {
  const cpu = (user, idle) => ({
    total: { user: user, nice: 0, system: 0, idle: idle, iowait: 0, irq: 0, softirq: 0, steal: 0, guest: 0, guestNice: 0 },
    cores: [{ user: user, nice: 0, system: 0, idle: idle, iowait: 0, irq: 0, softirq: 0, steal: 0, guest: 0, guestNice: 0 }],
    mhz: 3200,
    core_mhz: [3200],
  });
  const mem = { total: 2000 * 1024, used: 1000 * 1024, available: 1000 * 1024, cached: 10, swapUsed: 0, swapTotal: 0 };
  const first = M.step(M.emptyState(), {
    mono_ms: 1000,
    cpu: cpu(10, 10),
    mem: mem,
    disk: { device: "nvme0n1", sectors_read: 0, sectors_written: 0, root_used: 50, root_total: 100 },
    net: { ifaces: [{ name: "wlan0", rx: 0, tx: 0 }, { name: "enp1s0", rx: 0, tx: 0 }], virtual: [], default_iface: "wlan0" },
    temps: { package_c: 47, disk_c: 31 },
  }, 1000);
  const second = M.step(first.state, {
    mono_ms: 3000,
    cpu: cpu(20, 20),
    mem: mem,
    disk: { device: "nvme0n1", sectors_read: 100, sectors_written: 0, root_used: 50, root_total: 100 },
    net: { ifaces: [{ name: "wlan0", rx: 2000, tx: 0 }, { name: "enp1s0", rx: 500, tx: 0 }], virtual: [], default_iface: "wlan0" },
    temps: { package_c: 48, disk_c: 32 },
  }, 3000);
  assert.equal(second.view.cpu.percentText, "50%");
  assert.equal(second.view.cpu.freqText, "3.20 GHz");
  assert.equal(second.view.cpu.cores[0].freqText, "3.2G");
  assert.equal(second.view.cpu.tempText, "48°C");
  assert.equal(second.view.disk.tempText, "32°C");
  assert.equal(second.view.disk.device, "nvme0n1");
  assert.equal(second.view.disk.readText, "25.0 KB/s");
  assert.equal(second.view.net.iface, "wlan0 + enp1s0");
  assert.equal(second.view.net.downText, "1.22 KB/s");
});

test("a failed sensor keeps its card and the rest of the sample still applies", () => {
  const first = M.step(M.emptyState(), {
    proc_stat: "cpu  10 0 0 10 0 0 0 0\n",
    diskstats: " 8 0 sda 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
    root_used: 10,
    root_total: 100,
    battery: { capacity: 40, status: "Discharging", power_now_uw: 5000000 },
  }, 1000);
  const second = M.step(first.state, {
    proc_stat: "cpu  20 0 0 20 0 0 0 0\n",
    diskstats: " 8 0 sda 0 0 100 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
    root_used: 10,
    root_total: 100,
    battery: { capacity: 40, status: "Discharging", power_now_uw: 5000000 },
  }, 2000);
  assert.notEqual(second.view.disk.readText, "unavailable");
  const broken = M.step(second.state, {
    proc_stat: "cpu  30 0 0 30 0 0 0 0\n",
    disk: null,
    battery: null,
    errors: { disk: "disk read problem", battery: "battery read problem" },
  }, 3000);
  assert.equal(broken.view.disk.readText, second.view.disk.readText);
  assert.equal(broken.view.disk.device, "sda");
  assert.equal(broken.view.battery.percentText, "40%");
  assert.equal(broken.view.cpu.percentText, "50%");
  assert.equal(broken.state.diskDevice, "sda");
});

test("process display prefers argv for generic comms and drops cmdline arguments", () => {
  assert.equal(M.procDisplayName("MainThread", "/opt/foo/bar"), "bar");
  assert.equal(M.procDisplayName("MainThread", "mcp 6276 --auth-timeout 60"), "mcp");
  assert.equal(M.procDisplayName("mcp 6276 --auth-timeout 60", ""), "mcp");
  assert.equal(M.procDisplayName("Thread", "/opt/foo/bar"), "bar");
  assert.equal(M.procDisplayName("Main", "/opt/foo/bar"), "bar");
  assert.equal(M.procDisplayName("GeckoMain", "/usr/lib/firefox/firefox"), "firefox");
  assert.equal(M.procDisplayName("ThreadPool#3", "/usr/bin/app"), "app");
  assert.equal(M.procDisplayName("kworker/0:1", ""), "kworker/0:1");
  assert.equal(M.procDisplayName("kworker/u16:2", "/usr/lib/systemd/systemd"), "systemd");
  assert.equal(M.procDisplayName("Web Content", "/usr/lib/firefox/firefox"), "Web Content");
  assert.equal(M.procDisplayName("a".repeat(15), "mcp 6276 --auth-timeout 60"), "mcp");
  assert.equal(M.genericThreadName("ThreadPoolWorker"), true);
  assert.equal(M.genericThreadName("firefox"), false);
});

test("a stalled gpu residency counter is idle, not 100% busy", () => {
  const base = {
    proc_stat: "cpu  10 0 0 10 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1000, mhz: 0, runtime_status: "active" },
  };
  const first = M.step(M.emptyState(), base, 1000);
  assert.equal(first.view.gpu.percentText, "—");
  const stalled = M.step(first.state, base, 2000);
  assert.equal(stalled.view.gpu.percent, 0);
  assert.equal(stalled.view.gpu.percentText, "0%");
  assert.equal(stalled.view.gpu.freqText, "idle");
  assert.notEqual(stalled.view.gpu.percentText, "100%");
  const suspended = M.step(stalled.state, {
    proc_stat: "cpu  20 0 0 20 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1000, mhz: 400, runtime_status: "suspended" },
  }, 3000);
  assert.equal(suspended.view.gpu.percent, 0);
  assert.equal(suspended.view.gpu.freqText, "idle");
  assert.notEqual(suspended.view.gpu.percentText, "100%");
  const busy = M.step(suspended.state, {
    proc_stat: "cpu  30 0 0 30 0 0 0 0\n",
    gpu: { present: true, idle_ms: 1000, mhz: 900, runtime_status: "active" },
  }, 4000);
  assert.equal(busy.view.gpu.percent, 100);
  assert.equal(busy.view.gpu.percentText, "100%");
  assert.equal(busy.view.gpu.freqText, "900 MHz");
  assert.equal(M.gpuStallIdle(1000, 1000, 0, "active"), true);
  assert.equal(M.gpuStallIdle(1000, 1000, 900, "suspended"), true);
  assert.equal(M.gpuStallIdle(1000, 1000, 900, "active"), false);
  assert.equal(M.gpuStallIdle(1000, 1500, 0, "suspended"), false);
});

test("monotonic rate window skips a short delta and rebaselines a gap", () => {
  const raw = (user, rx, mono) => ({
    proc_stat: "cpu  " + user + " 0 0 " + user + " 0 0 0 0\ncpu0 " + user + " 0 0 " + user + " 0 0 0 0\n",
    net_dev: "  wlo1: " + rx + " 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    diskstats: " 8 0 sda 0 0 " + rx + " 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
    disk_device: "sda",
    virtual_ifaces: [],
    default_iface: "wlo1",
    mono_ms: mono,
  });
  const first = M.step(M.emptyState(), raw(10, 0, 0), 0);
  const second = M.step(first.state, raw(20, 1000, 1000), 1000);
  assert.equal(second.view.cpu.percent, 50);
  assert.equal(second.view.net.downText, "1000 B/s");
  assert.equal(second.view.disk.readText, "500 KB/s");
  const tiny = M.step(second.state, raw(90, 9000, 1100), 2000);
  assert.equal(tiny.skip, true);
  assert.equal(tiny.state, second.state);
  assert.equal(tiny.view.net.downText, "1000 B/s");
  const edge = M.step(second.state, raw(30, 2000, 1200), 2000);
  assert.notEqual(edge.skip, true);
  assert.equal(edge.state.rateMono, 1200);
  const gap = M.step(second.state, raw(30, 50000, 16000), 2000);
  assert.notEqual(gap.skip, true);
  assert.equal(gap.view.net.downText, "1000 B/s");
  assert.equal(gap.view.disk.readText, second.view.disk.readText);
  assert.equal(gap.view.net.rxHistory.length, second.view.net.rxHistory.length);
  assert.equal(gap.view.disk.readHistory.length, second.view.disk.readHistory.length);
  assert.equal(gap.state.rateMono, 16000);
  assert.equal(gap.view.cpu.percent, 50);
  const after = M.step(gap.state, raw(40, 52000, 17000), 3000);
  assert.equal(after.view.net.downText, "1.95 KB/s");
  assert.equal(after.view.disk.readText, "1000 KB/s");
  assert.equal(after.view.cpu.percent, 50);
});

test("collector liveness does not spend a restart, and a late exit is ignored", () => {
  const alive = M.collectorLineAlive(5000);
  assert.equal(alive.lastLineMs, 5000);
  assert.equal(alive.stale, false);
  assert.equal(alive.stopRestartTimer, true);
  assert.equal(alive.armRestart, false);
  assert.equal(alive.spendMark, false);
  assert.equal(M.collectorKillDue(1000, 0, true), false);
  assert.equal(M.collectorKillDue(2999, 1000, true), false);
  assert.equal(M.collectorKillDue(3000, 1000, true), true);
  assert.equal(M.collectorKillDue(5000, 1000, false), false);
  assert.equal(M.collectorExitIgnored(1, 1), false);
  assert.equal(M.collectorExitIgnored(2, 1), true);
  assert.equal(M.collectorExitIgnored(1, 2), true);
});

test("network detail lines cap the view at 4 plus the rest", () => {
  const names = ["wlo1", "enp1s0", "enp2s0", "enp3s0", "enp4s0", "enp5s0"];
  const perIface = names.map((name) => ({ name: name, downText: "1 B/s", upText: "2 B/s" }));
  const lines = M.netDetailLines(perIface, "wlo1");
  assert.equal(lines.length, 5);
  assert.deepEqual(lines.slice(0, 4).map((item) => item.name), ["enp1s0", "enp2s0", "enp3s0", "enp4s0"]);
  assert.equal(lines[4].more, true);
  assert.equal(lines[4].text, "+1 more");
});


test("OKLab and theme warning colors distinguish close colors", () => {
  assert.equal(M.oklabDistance("#ffffff", "#ffffff"), 0);
  assert.ok(Math.abs(M.oklabDistance("#ffffff", "#000000") - 100) < 0.001);
  const theme = M.resolveTheme(M.parseColorsToml(DARK_THEME));
  assert.ok(M.oklabDistance(theme.accent, theme.colors.yellow) >= 15);
  assert.ok(M.oklabDistance(theme.accent, theme.colors.red) >= 15);
  assert.equal(M.warningColor("#000000", "#ffffff", [], "#101010"), "#ffffff");
});

test("flat histories require two equal finite samples", () => {
  assert.equal(M.seriesFlat([]), false);
  assert.equal(M.seriesFlat([1]), false);
  assert.equal(M.seriesFlat([100, 100, 100]), true);
  assert.equal(M.seriesFlat([100, 99.9]), false);
  assert.equal(M.seriesFlat([1, NaN]), false);
});
