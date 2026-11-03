// Pure metric parsing and delta math for Mainframe.
// Top-level functions are imported by QML. Node tests read module.exports.
// Counters that move backwards (wrap or reset) contribute 0, never a negative rate.
// QML's JS engine is ES5: no let/const/arrows in this file.

var HISTORY_LIMIT = 60;
var LABEL_MIX = 0.5;
var MIN_ELAPSED_MS = 200;
var MAX_ELAPSED_MS = 10000;

function isFiniteNumber(value) {
  return typeof value === "number" && isFinite(value);
}

function toNumber(value) {
  var n = Number(value);
  return isFinite(n) ? n : 0;
}

function clamp01(value) {
  if (!isFiniteNumber(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function zeroCpu() {
  return {
    user: 0, nice: 0, system: 0, idle: 0, iowait: 0,
    irq: 0, softirq: 0, steal: 0, guest: 0, guestNice: 0
  };
}

function parseCpuFields(parts) {
  var nums = [];
  var i;
  for (i = 1; i < parts.length; i++) nums.push(toNumber(parts[i]));
  while (nums.length < 10) nums.push(0);
  return {
    user: nums[0],
    nice: nums[1],
    system: nums[2],
    idle: nums[3],
    iowait: nums[4],
    irq: nums[5],
    softirq: nums[6],
    steal: nums[7],
    guest: nums[8],
    guestNice: nums[9]
  };
}

// /proc/stat. Guest jiffies are already inside user/nice, so they are kept
// for completeness and not added again when summing.
function parseProcStat(text) {
  var lines = String(text || "").split("\n");
  var total = null;
  var cores = [];
  var i;
  for (i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (!line || line.indexOf("cpu") !== 0) continue;
    var parts = line.trim().split(/\s+/);
    var label = parts[0];
    if (label === "cpu") {
      total = parseCpuFields(parts);
      continue;
    }
    var match = /^cpu(\d+)$/.exec(label);
    if (!match) continue;
    cores[Number(match[1])] = parseCpuFields(parts);
  }
  // A missing id stays null. A zero-filled hole would be stored as the
  // previous sample and the next time that core appears it would look busy.
  for (i = 0; i < cores.length; i++) {
    if (!cores[i]) cores[i] = null;
  }
  if (!total) total = zeroCpu();
  return { total: total, cores: cores, coreCount: cores.length };
}

function sumTicks(sample) {
  if (!sample) return 0;
  return sample.user + sample.nice + sample.system + sample.idle +
    sample.iowait + sample.irq + sample.softirq + sample.steal;
}

// Idle includes iowait, matching the usual "CPU busy" reading.
function cpuPercent(prev, next) {
  if (!prev || !next) return 0;
  var dt = sumTicks(next) - sumTicks(prev);
  if (dt <= 0) return 0;
  var di = (next.idle + next.iowait) - (prev.idle + prev.iowait);
  if (di < 0) return 0;
  var busy = dt - di;
  if (busy < 0) return 0;
  return 100 * busy / dt;
}

function cpuDeltas(prev, next) {
  var cores = [];
  var nextCores = (next && next.cores) || [];
  var prevCores = (prev && prev.cores) || [];
  var i;
  for (i = 0; i < nextCores.length; i++) {
    // No fabricated baseline: a core with no real previous sample is null,
    // and the view shows an em dash for that tick instead of 0%.
    if (!nextCores[i] || !prevCores[i]) cores.push(null);
    else cores.push(cpuPercent(prevCores[i], nextCores[i]));
  }
  return {
    total: cpuPercent(prev && prev.total, next && next.total),
    cores: cores
  };
}

function parseMeminfo(text) {
  var raw = {};
  var lines = String(text || "").split("\n");
  var i;
  for (i = 0; i < lines.length; i++) {
    var match = /^([A-Za-z0-9_()]+):\s+(\d+)/.exec(lines[i]);
    if (match) raw[match[1]] = Number(match[2]);
  }
  function bytes(key) {
    if (!Object.prototype.hasOwnProperty.call(raw, key)) return null;
    return raw[key] * 1024;
  }
  var total = bytes("MemTotal");
  var free = bytes("MemFree");
  var available = bytes("MemAvailable");
  var cached = bytes("Cached");
  var reclaimable = bytes("SReclaimable");
  var buffers = bytes("Buffers");
  var swapTotal = bytes("SwapTotal");
  var swapFree = bytes("SwapFree");
  // used matches MemAvailable, not the older MemFree − buffers − cache branch.
  var used = null;
  if (total != null && available != null) {
    used = total - available;
    if (used < 0) used = 0;
  }
  // free(1) buff/cache is Cached + SReclaimable + Buffers.
  var cachedDisplay = null;
  if (cached != null || reclaimable != null || buffers != null) {
    cachedDisplay = (cached || 0) + (reclaimable || 0) + (buffers || 0);
  }
  var swapUsed = null;
  if (swapTotal != null && swapFree != null) {
    swapUsed = swapTotal - swapFree;
    if (swapUsed < 0) swapUsed = 0;
  }
  return {
    total: total,
    free: free,
    available: available,
    cached: cachedDisplay,
    buffers: buffers,
    swapTotal: swapTotal,
    swapFree: swapFree,
    used: used,
    swapUsed: swapUsed
  };
}

function parseNetDev(text) {
  var lines = String(text || "").split("\n");
  var ifaces = [];
  var i;
  for (i = 0; i < lines.length; i++) {
    var match = /^\s*([^:]+):\s*(.*)$/.exec(lines[i]);
    if (!match) continue;
    var name = match[1].trim();
    if (!name || name === "Inter-" || name === "face") continue;
    var nums = match[2].trim().split(/\s+/);
    if (nums.length < 9) continue;
    ifaces.push({
      name: name,
      rxBytes: toNumber(nums[0]),
      txBytes: toNumber(nums[8])
    });
  }
  return ifaces;
}

// Name patterns that are never physical, even when sysfs has a device link.
function matchesVirtualPattern(name) {
  if (!name) return true;
  if (name === "lo" || name === "docker_gwbridge") return true;
  if (name.indexOf("docker") === 0) return true;
  if (name.indexOf("br-") === 0) return true;
  if (name.indexOf("veth") === 0) return true;
  if (name.indexOf("virbr") === 0) return true;
  if (name.indexOf("podman") === 0) return true;
  if (name.indexOf("tailscale") === 0) return true;
  if (name.indexOf("wg") === 0) return true;
  if (name.indexOf("tun") === 0) return true;
  if (name.indexOf("zt") === 0) return true;
  return false;
}

function isVirtualIface(name, virtualNames) {
  if (!name || name === "lo") return true;
  if (matchesVirtualPattern(name)) return true;
  if (virtualNames && typeof virtualNames.length === "number") {
    var i;
    for (i = 0; i < virtualNames.length; i++) {
      if (virtualNames[i] === name) return true;
    }
  }
  return false;
}

function indexByName(list) {
  var map = {};
  var i;
  var items = list || [];
  for (i = 0; i < items.length; i++) map[items[i].name] = items[i];
  return map;
}

function bytesPerSecond(bytes, elapsedMs) {
  if (!(elapsedMs > 0) || !(bytes > 0)) return 0;
  return bytes * 1000 / elapsedMs;
}

function physicalNames(list, virtualNames) {
  var names = [];
  var items = list || [];
  var i;
  for (i = 0; i < items.length; i++) {
    if (!isVirtualIface(items[i].name, virtualNames)) names.push(items[i].name);
  }
  return names;
}

function netRates(prev, next, elapsedMs, virtualNames) {
  var prevMap = indexByName(prev);
  var rx = 0;
  var tx = 0;
  var per = [];
  var items = next || [];
  var i;
  for (i = 0; i < items.length; i++) {
    var iface = items[i];
    if (isVirtualIface(iface.name, virtualNames)) continue;
    var before = prevMap[iface.name];
    if (!before) continue;
    var dr = iface.rxBytes - before.rxBytes;
    var dw = iface.txBytes - before.txBytes;
    if (dr < 0) dr = 0;
    if (dw < 0) dw = 0;
    per.push({
      name: iface.name,
      rxBps: bytesPerSecond(dr, elapsedMs),
      txBps: bytesPerSecond(dw, elapsedMs)
    });
    rx += dr;
    tx += dw;
  }
  return {
    rxBps: bytesPerSecond(rx, elapsedMs),
    txBps: bytesPerSecond(tx, elapsedMs),
    interfaces: per
  };
}

// RTF_UP. Point-to-point links publish a default route without RTF_GATEWAY.
var RTF_UP = 0x1;

function routeFlagsOk(text) {
  var flags = parseInt(text, 16);
  if (!isFinite(flags)) return false;
  return (flags & RTF_UP) === RTF_UP;
}

// IPv4 /proc/net/route: destination and mask 00000000, flags include
// RTF_UP (with or without RTF_GATEWAY), lowest metric wins.
function parseIpv4Default(text) {
  var lines = String(text || "").split("\n");
  var best = null;
  var bestMetric = null;
  var i;
  for (i = 0; i < lines.length; i++) {
    var parts = lines[i].trim().split(/\s+/);
    if (parts.length < 8 || parts[1] !== "00000000" || parts[7] !== "00000000") continue;
    if (!parts[0] || parts[0] === "Iface") continue;
    if (!routeFlagsOk(parts[3])) continue;
    var metric = Number(parts[6]);
    if (!isFinite(metric)) metric = 0;
    if (bestMetric === null || metric < bestMetric) {
      bestMetric = metric;
      best = parts[0];
    }
  }
  return best;
}

// IPv6 /proc/net/ipv6_route: prefix length 0 and RTF_UP (gateway optional).
// Metric is the hex field after the gateway (index 5). Skip lo.
function parseIpv6Default(text) {
  var lines = String(text || "").split("\n");
  var best = null;
  var bestMetric = null;
  var i;
  for (i = 0; i < lines.length; i++) {
    var parts = lines[i].trim().split(/\s+/);
    if (parts.length < 10) continue;
    if (parts[0] !== "00000000000000000000000000000000") continue;
    var prefix = parseInt(parts[1], 16);
    if (!isFinite(prefix) || prefix !== 0) continue;
    if (!routeFlagsOk(parts[8])) continue;
    var iface = parts[parts.length - 1];
    if (!iface || iface === "lo") continue;
    var metric = parseInt(parts[5], 16);
    if (!isFinite(metric)) metric = 0;
    if (bestMetric === null || metric < bestMetric) {
      bestMetric = metric;
      best = iface;
    }
  }
  return best;
}

function defaultRouteIface(routeV4, routeV6) {
  return parseIpv4Default(routeV4) || parseIpv6Default(routeV6) || null;
}

function orderIfaces(names, preferred) {
  var unique = [];
  var seen = {};
  var i;
  var list = names || [];
  for (i = 0; i < list.length; i++) {
    var name = list[i];
    if (!name || seen[name]) continue;
    seen[name] = true;
    unique.push(name);
  }
  unique.sort();
  if (preferred && seen[preferred]) {
    var rest = [];
    for (i = 0; i < unique.length; i++) {
      if (unique[i] !== preferred) rest.push(unique[i]);
    }
    unique = [preferred].concat(rest);
  }
  return unique;
}

function ifaceLabel(names, preferred) {
  var ordered = orderIfaces(names, preferred);
  if (ordered.length === 0) return "—";
  return ordered.join(" + ");
}

function parseDiskstats(text) {
  var lines = String(text || "").split("\n");
  var devs = [];
  var i;
  for (i = 0; i < lines.length; i++) {
    var parts = lines[i].trim().split(/\s+/);
    // major minor name reads merged sectorsRead ms writes merged sectorsWritten ...
    if (parts.length < 14 || !parts[2]) continue;
    var sectorsRead = Number(parts[5]);
    var sectorsWritten = Number(parts[9]);
    if (!isFinite(sectorsRead) || !isFinite(sectorsWritten)) continue;
    devs.push({
      name: parts[2],
      sectorsRead: sectorsRead,
      sectorsWritten: sectorsWritten
    });
  }
  return devs;
}

function findDev(list, name) {
  if (!name) return null;
  var items = list || [];
  var i;
  for (i = 0; i < items.length; i++) {
    if (items[i].name === name) return items[i];
  }
  return null;
}

function diskRates(prev, next, elapsedMs, deviceName) {
  var before = findDev(prev, deviceName);
  var after = findDev(next, deviceName);
  if (!before || !after) return { readBps: 0, writeBps: 0, found: false };
  var dr = after.sectorsRead - before.sectorsRead;
  var dw = after.sectorsWritten - before.sectorsWritten;
  if (dr < 0) dr = 0;
  if (dw < 0) dw = 0;
  if (!(elapsedMs > 0)) return { readBps: 0, writeBps: 0, found: true };
  var scale = 512 * 1000 / elapsedMs;
  return { readBps: dr * scale, writeBps: dw * scale, found: true };
}

// busy% = 100 * (1 - Δidle_residency_ms / Δwall_ms). Null inputs mean "no GT".
function gpuBusy(prevIdleMs, nextIdleMs, elapsedMs) {
  if (prevIdleMs == null || nextIdleMs == null) return null;
  var prev = Number(prevIdleMs);
  var next = Number(nextIdleMs);
  if (!isFinite(prev) || !isFinite(next)) return null;
  var dt = Number(elapsedMs);
  if (!(dt > 0)) return 0;
  var di = next - prev;
  if (di < 0) return 0;
  var idleFrac = di / dt;
  if (idleFrac < 0) idleFrac = 0;
  if (idleFrac > 1) idleFrac = 1;
  return 100 * (1 - idleFrac);
}

// A residency counter that does not move while the GPU is powered down is
// stalled, not 100% busy. act_freq 0 or runtime_status "suspended" says so.
function gpuStallIdle(prevIdleMs, nextIdleMs, mhz, runtimeStatus) {
  if (prevIdleMs == null || nextIdleMs == null) return false;
  var prev = Number(prevIdleMs);
  var next = Number(nextIdleMs);
  if (!isFinite(prev) || !isFinite(next) || next !== prev) return false;
  var status = runtimeStatus == null ? "" : String(runtimeStatus).toLowerCase();
  if (status === "suspended") return true;
  if (mhz == null || mhz === "") return false;
  var freq = Number(mhz);
  return isFinite(freq) && freq === 0;
}

// A parsed line is liveness even when step throws. It must not arm a restart.
function collectorLineAlive(now) {
  return {
    lastLineMs: Number(now) || 0,
    stale: false,
    stopRestartTimer: true,
    armRestart: false,
    spendMark: false
  };
}

// SIGKILL once a stop request is still unanswered after 2 s.
function collectorKillDue(now, requestedAt, stillUp) {
  if (!stillUp) return false;
  var at = Number(requestedAt);
  var t = Number(now);
  if (!(at > 0) || !isFinite(t)) return false;
  return (t - at) >= 2000;
}

// starts is how many children have reached onStarted. exits is how many
// onExited handlers have run. A late exit from an older child does not match.
function collectorExitIgnored(starts, exits) {
  return Number(exits) !== Number(starts);
}

function stripComment(line) {
  var inSingle = false;
  var inDouble = false;
  var i;
  for (i = 0; i < line.length; i++) {
    var ch = line.charAt(i);
    if (ch === '"' && !inSingle) inDouble = !inDouble;
    else if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === "#" && !inSingle && !inDouble) return line.slice(0, i);
  }
  return line;
}

function isTableHeader(line) {
  return /^\[[\s\S]*\]$/.test(line);
}

// Top-level keys only. Keys under [table] / [[table]] belong to that table.
function parseColorsToml(text) {
  var colors = {};
  var lines = String(text || "").split("\n");
  var inTable = false;
  var i;
  for (i = 0; i < lines.length; i++) {
    var line = stripComment(lines[i]).trim();
    if (!line) continue;
    if (isTableHeader(line)) {
      inTable = true;
      continue;
    }
    if (inTable) continue;
    var match = /^([A-Za-z0-9_]+)\s*=\s*(.*)$/.exec(line);
    if (!match) continue;
    var value = match[2].trim();
    var quoted = (value.charAt(0) === '"' && value.charAt(value.length - 1) === '"') ||
      (value.charAt(0) === "'" && value.charAt(value.length - 1) === "'");
    if (quoted && value.length >= 2) value = value.slice(1, -1);
    colors[match[1]] = value;
  }
  return colors;
}

// Internal form is #RRGGBB or #RRGGBBAA (Omarchy). Qt's #AARRGGBB is
// produced only by qtColor(), at the QML boundary.
function parseHex(input) {
  if (typeof input !== "string") return null;
  var s = input.trim();
  if (s.charAt(0) !== "#") return null;
  s = s.slice(1);
  var hasAlpha = false;
  var alpha = 255;
  if (s.length === 3) {
    s = s.charAt(0) + s.charAt(0) + s.charAt(1) + s.charAt(1) + s.charAt(2) + s.charAt(2);
  } else if (s.length === 8) {
    hasAlpha = true;
    alpha = parseInt(s.slice(6, 8), 16);
    s = s.slice(0, 6);
    if (!isFinite(alpha)) return null;
  } else if (s.length !== 6) {
    return null;
  }
  var n = parseInt(s, 16);
  if (!isFinite(n)) return null;
  return {
    r: (n >> 16) & 255,
    g: (n >> 8) & 255,
    b: n & 255,
    a: alpha,
    hasAlpha: hasAlpha
  };
}

function byteHex(value) {
  var v = Math.max(0, Math.min(255, value | 0));
  var s = v.toString(16);
  return s.length === 1 ? "0" + s : s;
}

function formatColor(color) {
  if (!color) return null;
  var rgb = "#" + byteHex(color.r) + byteHex(color.g) + byteHex(color.b);
  if (color.a < 255) return rgb + byteHex(color.a);
  return rgb;
}

// Qt named colors are #AARRGGBB. Call this only when assigning a QML color.
function qtColor(hex) {
  var color = parseHex(hex);
  if (!color) return "#000000";
  var rgb = "#" + byteHex(color.r) + byteHex(color.g) + byteHex(color.b);
  if (color.a >= 255) return rgb;
  return "#" + byteHex(color.a) + rgb.slice(1);
}

function validColor(value) {
  return formatColor(parseHex(value));
}

function mixHex(a, b, t) {
  var pa = parseHex(a);
  var pb = parseHex(b);
  if (!pa || !pb) return validColor(a) || validColor(b) || "#000000";
  var amount = Number(t);
  if (!isFinite(amount)) amount = 0;
  function channel(from, to) {
    return Math.round(from + (to - from) * amount);
  }
  return formatColor({
    r: channel(pa.r, pb.r),
    g: channel(pa.g, pb.g),
    b: channel(pa.b, pb.b),
    a: channel(pa.a, pb.a),
    hasAlpha: pa.hasAlpha || pb.hasAlpha || pa.a < 255 || pb.a < 255
  });
}

function hexWithAlpha(hex, alpha) {
  var rgb = parseHex(hex);
  if (!rgb) return "#00000000";
  var a = Math.round(Math.max(0, Math.min(1, Number(alpha))) * 255);
  if (!isFinite(a)) a = 0;
  var body = "#" + byteHex(rgb.r) + byteHex(rgb.g) + byteHex(rgb.b);
  if (a >= 255) return body;
  return body + byteHex(a);
}

function srgbChannel(c) {
  var s = c / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex) {
  var rgb = parseHex(hex);
  if (!rgb) return 0;
  return 0.2126 * srgbChannel(rgb.r) + 0.7152 * srgbChannel(rgb.g) + 0.0722 * srgbChannel(rgb.b);
}

// OKLab distance on a 0–100 scale (the conventional ΔE_OK scale).
function oklabDistance(a, b) {
  function lab(hex) {
    var p = parseHex(hex);
    if (!p) return null;
    var r = srgbChannel(p.r), g = srgbChannel(p.g), b = srgbChannel(p.b);
    var l = Math.pow(0.4122214708*r + 0.5363325363*g + 0.0514459929*b, 1/3);
    var m = Math.pow(0.2119034982*r + 0.6806995451*g + 0.1073969566*b, 1/3);
    var s = Math.pow(0.0883024619*r + 0.2817188376*g + 0.6299787005*b, 1/3);
    return [0.2104542553*l + 0.793617785*m - 0.0040720468*s,
      1.9779984951*l - 2.428592205*m + 0.4505937099*s,
      0.0259040371*l + 0.7827717662*m - 0.808675766*s];
  }
  var x = lab(a), y = lab(b);
  if (!x || !y) return 0;
  return 100 * Math.sqrt(Math.pow(x[0]-y[0], 2) + Math.pow(x[1]-y[1], 2) + Math.pow(x[2]-y[2], 2));
}

function warningColor(accent, desired, palette, background) {
  if (oklabDistance(accent, desired) >= 15) return desired;
  var candidates = (palette || []).concat(["#f2b84b", "#f05a67", "#ffffff", "#000000"]);
  var best = desired, score = -1;
  for (var i = 0; i < candidates.length; i++) {
    var c = validColor(candidates[i]);
    if (!c) continue;
    var distance = oklabDistance(accent, c);
    var backgroundDistance = oklabDistance(background, c);
    var value = Math.min(distance, backgroundDistance);
    if (value > score) { best = c; score = value; }
  }
  return best;
}

function seriesFlat(samples) {
  if (!samples || samples.length < 2) return false;
  var first = Number(samples[0]);
  if (!isFinite(first)) return false;
  for (var i = 1; i < samples.length; i++) {
    var value = Number(samples[i]);
    if (!isFinite(value) || Math.abs(value - first) > 0.000001) return false;
  }
  return true;
}

function meterColor(fraction, colors) {
  var c = colors || {};
  var accent = validColor(c.accent) || "#7aa2f7";
  var yellow = validColor(c.yellow) || "#e0c36a";
  var red = validColor(c.red) || "#e06c75";
  var f = Number(fraction);
  if (!isFinite(f) || f < 0.7) return accent;
  if (f >= 0.9) return red;
  return yellow;
}

// Charge left, not utilisation: low is the warning.
function batteryMeterColor(fraction, colors) {
  var c = colors || {};
  var accent = validColor(c.accent) || "#7aa2f7";
  var yellow = validColor(c.yellow) || "#e0c36a";
  var red = validColor(c.red) || "#e06c75";
  var f = Number(fraction);
  if (!isFinite(f)) return accent;
  if (f < 0.15) return red;
  if (f < 0.30) return yellow;
  return accent;
}

function resolveTheme(parsed) {
  var c = parsed || {};
  var background = validColor(c.background) || "#101315";
  var foreground = validColor(c.foreground) || "#cacccc";
  var muted = validColor(c.muted) || "#707880";
  var accent = validColor(c.accent) || "#7aa2f7";
  var yellow = validColor(c.yellow) || "#e0c36a";
  var red = validColor(c.red) || "#e06c75";
  var palette = [foreground, c.blue, c.cyan, c.magenta, c.green, c.yellow, c.red];
  yellow = warningColor(accent, yellow, palette, background);
  red = warningColor(accent, red, palette, background);
  var card = validColor(c.lighter_background) || mixHex(background, foreground, 0.06);
  // Labels sit between the text colour and the card, about halfway, so they
  // stay readable without using dark_foreground (that one is too close to the card).
  var label = mixHex(foreground, card, LABEL_MIX);
  var cyan = validColor(c.cyan) || validColor(c.blue) || accent;
  var modeRaw = String(c.mode || "").trim().toLowerCase();
  var mode = (modeRaw === "light" || modeRaw === "dark")
    ? modeRaw
    : (relativeLuminance(background) >= 0.5 ? "light" : "dark");
  return {
    background: background,
    foreground: foreground,
    card: card,
    label: label,
    accent: accent,
    yellow: yellow,
    red: red,
    cyan: cyan,
    muted: muted,
    mode: mode,
    border: hexWithAlpha(foreground, 0.08),
    track: hexWithAlpha(foreground, 0.10),
    colors: { accent: accent, yellow: yellow, red: red }
  };
}

function pushHistory(history, value, limit) {
  var cap = limit || HISTORY_LIMIT;
  var next = (history || []).slice();
  var sample = Number(value);
  if (!isFinite(sample) || sample < 0) sample = 0;
  next.push(sample);
  if (next.length > cap) next = next.slice(next.length - cap);
  return next;
}

function batteryPowerW(sample) {
  if (!sample) return null;
  if (sample.power_now_uw != null && sample.power_now_uw !== "") {
    var fromPower = Number(sample.power_now_uw) / 1e6;
    return isFinite(fromPower) ? fromPower : null;
  }
  if (sample.current_now_ua != null && sample.voltage_now_uv != null) {
    var watts = (Number(sample.current_now_ua) / 1e6) * (Number(sample.voltage_now_uv) / 1e6);
    return isFinite(watts) ? watts : null;
  }
  return null;
}

function batteryStatus(raw) {
  var s = String(raw || "").trim().toLowerCase();
  if (!s) return null;
  return s;
}

function formatPercent(value) {
  if (value == null || !isFinite(Number(value))) return "—";
  return Math.round(Number(value)) + "%";
}

function formatPercentPrecise(value) {
  if (value == null || !isFinite(Number(value))) return "—";
  var v = Number(value);
  if (Math.abs(v) >= 100) return Math.round(v) + "%";
  return v.toFixed(1) + "%";
}

function formatMhz(mhz) {
  if (mhz == null || mhz === "") return "—";
  var n = Number(mhz);
  if (!isFinite(n)) return "—";
  if (n >= 1000) {
    var g = n / 1000;
    return g.toFixed(g >= 10 ? 1 : 2) + " GHz";
  }
  return Math.round(n) + " MHz";
}

function formatMhzShort(mhz) {
  if (mhz == null || mhz === "") return "";
  var n = Number(mhz);
  if (!isFinite(n)) return "";
  if (n >= 1000) return (n / 1000).toFixed(1) + "G";
  return Math.round(n) + "M";
}

function formatGpuFreq(mhz) {
  if (mhz == null || mhz === "") return "unavailable";
  var n = Number(mhz);
  if (!isFinite(n)) return "unavailable";
  if (n === 0) return "idle";
  return formatMhz(n);
}

function formatTemp(celsius) {
  if (celsius == null || !isFinite(Number(celsius))) return "—";
  return Math.round(Number(celsius)) + "°C";
}

function formatBytes(value) {
  if (value == null || !isFinite(Number(value))) return "—";
  var units = ["B", "KB", "MB", "GB", "TB"];
  var v = Number(value);
  var sign = v < 0 ? "-" : "";
  v = Math.abs(v);
  var i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  var s;
  if (i === 0) s = String(Math.round(v));
  else if (v >= 100) s = v.toFixed(0);
  else if (v >= 10) s = v.toFixed(1);
  else s = v.toFixed(2);
  return sign + s + " " + units[i];
}

function formatRate(bps) {
  if (bps == null || !isFinite(Number(bps))) return "—";
  return formatBytes(bps) + "/s";
}

function formatPower(watts) {
  if (watts == null || !isFinite(Number(watts))) return "—";
  var n = Number(watts);
  return (Math.abs(n) >= 10 ? n.toFixed(1) : n.toFixed(2)) + " W";
}

function formatUsage(used, total) {
  if (used == null || total == null || !isFinite(Number(used)) || !isFinite(Number(total))) return "—";
  return formatBytes(used) + " / " + formatBytes(total);
}

function memorySegments(used, cached, total) {
  if (total == null || !isFinite(Number(total)) || Number(total) <= 0 ||
      used == null || !isFinite(Number(used))) return { cache: 0, fraction: 0 };
  var size = Number(total);
  var usedSize = Math.max(0, Math.min(Number(used), size));
  var cache = cached == null || !isFinite(Number(cached)) ? 0 : Math.max(0, Number(cached));
  cache = Math.min(cache, size - usedSize);
  return { cache: cache, fraction: cache / size };
}

function memoryHeader(used, cached, total) {
  if (used == null || total == null || !isFinite(Number(used)) || !isFinite(Number(total))) return "—";
  var segments = memorySegments(used, cached, total);
  return formatBytes(used) + " used · " + (cached == null || !isFinite(Number(cached)) ? "—" : formatBytes(segments.cache)) + " cache / " + formatBytes(total);
}

function parsePs(text) {
  var lines = String(text || "").split("\n");
  var rows = [];
  var i;
  for (i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;
    if (/^COMMAND\b/i.test(line) || line.indexOf("%CPU") !== -1) continue;
    var match = /^(.*)\s+([0-9.]+)\s+([0-9.]+)$/.exec(line);
    if (!match) continue;
    rows.push({
      name: match[1].trim(),
      cpu: Number(match[2]),
      mem: Number(match[3])
    });
  }
  return rows;
}

function topProcesses(rows, key, limit) {
  var n = limit || 8;
  var copy = (rows || []).slice();
  copy.sort(function(a, b) {
    var d = (b[key] || 0) - (a[key] || 0);
    if (d !== 0) return d;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });
  if (copy.length > n) copy = copy.slice(0, n);
  return copy;
}

function decorateProcesses(rows, key) {
  var out = [];
  var i;
  for (i = 0; i < rows.length; i++) {
    out.push({ name: rows[i].name, text: formatPercentPrecise(rows[i][key]) });
  }
  return out;
}

function basenamePath(path) {
  var s = String(path || "");
  if (!s) return "";
  var cut = s.length - 1;
  var i;
  for (i = s.length - 1; i >= 0; i--) {
    if (s.charAt(i) === "/" || s.charAt(i) === "\\") {
      cut = i;
      break;
    }
    cut = -1;
  }
  if (cut >= 0) s = s.slice(cut + 1);
  return s;
}

// comm is truncated at 15 bytes. A full 15 means the name was cut; argv0's
// basename is the uncut program name (fixes "missioncenter-m").
// Generic thread comms (MainThread, kworker/…) also hide the program.
var GENERIC_THREAD_EXACT = { mainthread: 1, thread: 1, main: 1, geckomain: 1 };
var GENERIC_THREAD_PREFIXES = ["threadpool", "kworker", "ksoftirqd", "migration", "kswapd", "rcu_"];

function genericThreadName(comm) {
  var name = comm == null ? "" : String(comm);
  if (!name) return false;
  var low = name.toLowerCase();
  if (GENERIC_THREAD_EXACT[low]) return true;
  var i;
  for (i = 0; i < GENERIC_THREAD_PREFIXES.length; i++) {
    if (low.indexOf(GENERIC_THREAD_PREFIXES[i]) === 0) return true;
  }
  return false;
}

// First token, then its basename. A rewritten cmdline is one string that
// contains the program and its arguments: "mcp 6276 --auth-timeout 60".
function programFromCmdline(text) {
  var s = text == null ? "" : String(text);
  if (!s) return "";
  var token = s;
  var space = s.indexOf(" ");
  if (space >= 0) token = s.slice(0, space);
  return basenamePath(token);
}

// "Web Content" is a real comm. A title that includes an argument
// (a number, or a token that starts with "-") is a rewritten cmdline.
function cmdlineHasArgs(text) {
  var s = text == null ? "" : String(text);
  var parts = s.split(" ");
  if (parts.length < 2) return false;
  var i;
  for (i = 1; i < parts.length; i++) {
    var token = parts[i];
    if (!token) continue;
    if (token.charAt(0) === "-") return true;
    var digits = true;
    var n;
    for (n = 0; n < token.length; n++) {
      var c = token.charAt(n);
      if (c < "0" || c > "9") { digits = false; break; }
    }
    if (digits) return true;
  }
  return false;
}

function procDisplayName(comm, argv0) {
  var name = comm == null ? "" : String(comm);
  if (name.length === 15 || genericThreadName(name)) {
    var base = programFromCmdline(argv0);
    if (base) return base;
  }
  if (cmdlineHasArgs(name)) {
    var titled = programFromCmdline(name);
    if (titled) return titled;
  }
  return name;
}

// IRIX mode, same as top's default: 100% per core, so a multi-thread process
// may exceed 100. deltaTicks is utime+stime over elapsedMs at clkTck Hz.
function procCpuPercent(deltaTicks, elapsedMs, clkTck) {
  if (!(elapsedMs > 0) || !(clkTck > 0)) return null;
  var delta = Number(deltaTicks);
  if (!isFinite(delta)) return null;
  if (delta < 0) return 0;
  var elapsedTicks = (elapsedMs / 1000) * Number(clkTck);
  if (!(elapsedTicks > 0)) return null;
  return 100 * delta / elapsedTicks;
}

function procMemPercent(rssPages, pageSize, memTotalBytes) {
  if (rssPages == null || !(pageSize > 0) || !(memTotalBytes > 0)) return null;
  var rss = Number(rssPages);
  if (!isFinite(rss) || rss < 0) return null;
  return 100 * (rss * Number(pageSize)) / Number(memTotalBytes);
}

function groupProcesses(rows) {
  var order = [];
  var map = {};
  var i;
  var list = rows || [];
  for (i = 0; i < list.length; i++) {
    var row = list[i];
    var key = row && row.name != null ? String(row.name) : "";
    if (!Object.prototype.hasOwnProperty.call(map, key)) {
      map[key] = { name: key, cpu: 0, mem: 0, count: 0, cpuKnown: false };
      order.push(key);
    }
    var g = map[key];
    var cpu = Number(row.cpu);
    var mem = Number(row.mem);
    // null cpu means this pid has not been seen twice yet. Do not treat it as 0%.
    if (row.cpu != null && isFinite(cpu)) {
      g.cpu += cpu;
      g.cpuKnown = true;
    }
    if (isFinite(mem)) g.mem += mem;
    var count = Number(row.count);
    g.count += (isFinite(count) && count > 0) ? count : 1;
  }
  var out = [];
  for (i = 0; i < order.length; i++) {
    var item = map[order[i]];
    out.push({
      name: item.count > 1 ? item.name + " ×" + item.count : item.name,
      cpu: item.cpu,
      mem: item.mem,
      count: item.count,
      cpuKnown: item.cpuKnown
    });
  }
  return out;
}

function emptyProcesses() {
  return { byCpu: [], byMem: [], freshAt: null, stale: false };
}

// PID reuse: /proc/<pid>/stat field 22 (starttime) distinguishes a recycled pid.
// Rows without a start time keep the legacy pid-only key.
function procBaseKey(row) {
  if (!row || row.pid == null) return null;
  if (row.start == null || row.start === "") return String(row.pid);
  return String(row.pid) + ":" + String(row.start);
}

function procSnapFrom(spec, now) {
  var ticks = {};
  var reads = {};
  var rows = (spec && spec.rows) || [];
  var i;
  for (i = 0; i < rows.length; i++) {
    var row = rows[i];
    var key = procBaseKey(row);
    if (key == null) continue;
    ticks[key] = Number(row.ticks) || 0;
    if (row.read_ms != null && isFinite(Number(row.read_ms))) reads[key] = Number(row.read_ms);
    else reads[key] = now;
  }
  return { t: now, ticks: ticks, reads: reads };
}

function procRows(spec, prevSnap, elapsedMs, memTotal, withCpu) {
  var list = (spec && spec.rows) || [];
  var clk = spec && spec.clk_tck ? Number(spec.clk_tck) : 100;
  var page = spec && spec.page_size ? Number(spec.page_size) : 4096;
  var prevTicks = (prevSnap && prevSnap.ticks) || {};
  var out = [];
  var i;
  for (i = 0; i < list.length; i++) {
    var row = list[i];
    if (!row) continue;
    var name = procDisplayName(row.comm, row.argv0);
    var mem = procMemPercent(row.rss, page, memTotal);
    var cpu = withCpu ? null : 0;
    if (withCpu) {
      var key = procBaseKey(row);
      var before = key != null ? prevTicks[key] : null;
      // No previous (pid, starttime): no CPU% until the next sighting.
      if (before != null) {
        var dt = elapsedMs;
        if (row.read_ms != null && prevSnap && prevSnap.reads && prevSnap.reads[key] != null) {
          dt = Number(row.read_ms) - Number(prevSnap.reads[key]);
        }
        var pct = procCpuPercent(Number(row.ticks) - Number(before), dt, clk);
        cpu = pct == null ? null : pct;
      }
    }
    out.push({
      name: name,
      cpu: cpu,
      mem: mem == null ? 0 : mem,
      count: 1
    });
  }
  return out;
}

function presentProcesses(rows, withCpu) {
  var grouped = groupProcesses(rows);
  var cpuGroups = [];
  var i;
  for (i = 0; i < grouped.length; i++) {
    if (grouped[i].cpuKnown) cpuGroups.push(grouped[i]);
  }
  return {
    byCpu: withCpu ? decorateProcesses(topProcesses(cpuGroups, "cpu", 8), "cpu") : [],
    byMem: decorateProcesses(topProcesses(grouped, "mem", 8), "mem")
  };
}

// Per-interface lines under the network headline. One interface is already
// named by the headline, so it adds no rows. Several interfaces are listed
// once each, never repeating the headline text, at most 4, then "+N more".
function netDetailLines(perIface, headline) {
  var unique = [];
  var seen = {};
  var items = perIface || [];
  var head = headline == null ? "" : String(headline);
  var i;
  for (i = 0; i < items.length; i++) {
    var item = items[i];
    if (!item || item.more) continue;
    var name = item.name == null ? "" : String(item.name);
    if (!name || seen[name]) continue;
    if (head && name === head) continue;
    seen[name] = true;
    unique.push({
      name: name,
      downText: item.downText == null ? "—" : String(item.downText),
      upText: item.upText == null ? "—" : String(item.upText),
      more: false,
      text: ""
    });
  }
  // The headline was already removed. One remaining NIC is the other interface
  // and must be listed; an empty list means the headline was the only NIC.
  if (unique.length === 0) return [];
  var shown = unique.length > 4 ? 4 : unique.length;
  var rows = [];
  for (i = 0; i < shown; i++) rows.push(unique[i]);
  if (unique.length > 4) {
    rows.push({
      name: "",
      downText: "",
      upText: "",
      more: true,
      text: "+" + (unique.length - 4) + " more"
    });
  }
  return rows;
}

// Column count for the per-core grid. cols is always >= 1 so the first
// layout pass (width 0) never divides or mods by zero. More than 32 logical
// cores switch to a compact heat map so a 64-128 core machine still fits.
function coreLayout(count, width, height) {
  var n = Number(count);
  if (!isFinite(n) || n < 0) n = 0;
  n = Math.floor(n);
  var w = Number(width);
  if (!isFinite(w) || w < 0) w = 0;
  var h = Number(height);
  if (!isFinite(h) || h < 0) h = 0;
  var compact = n > 32;
  var colGap = compact ? 2 : 6;
  var rowGap = compact ? 2 : 4;
  var cols = 1;
  if (n > 1 && !compact) {
    if (n >= 8 && w >= 700) cols = 8;
    else if (n >= 4 && w >= 320) cols = 4;
    else if (w >= 180) cols = 2;
    else cols = 1;
    if (cols > n) cols = n;
  } else if (n > 1 && compact) {
    var minCell = 8;
    var inner = w > 0 ? w : minCell;
    var maxCols = Math.floor((inner + colGap) / (minCell + colGap));
    if (!(maxCols >= 1)) maxCols = 1;
    if (maxCols > n) maxCols = n;
    var best = 1;
    var bestScore = null;
    var c;
    for (c = 1; c <= maxCols; c++) {
      var rowsTry = Math.ceil(n / c);
      var tryW = (inner - (c - 1) * colGap) / c;
      var tryH = h > 0 ? (h - (rowsTry - 1) * rowGap) / rowsTry : tryW;
      if (!(tryW > 0)) continue;
      var score = 0;
      if (tryW >= minCell && tryH >= minCell) score += 1000000;
      if (tryH < 0) score -= 1000000;
      score -= Math.abs(tryW - (tryH > 0 ? tryH : 0));
      if (bestScore == null || score > bestScore) {
        bestScore = score;
        best = c;
      }
    }
    cols = best;
  }
  if (!(cols >= 1)) cols = 1;
  var rows = n > 0 ? Math.ceil(n / cols) : 1;
  if (!(rows >= 1)) rows = 1;
  var cellW = 0;
  var cellH = 0;
  if (cols >= 1 && w > 0) cellW = (w - (cols - 1) * colGap) / cols;
  if (rows >= 1 && h > 0) cellH = (h - (rows - 1) * rowGap) / rows;
  if (!(cellW > 0)) cellW = 0;
  if (!(cellH > 0)) cellH = 0;
  return {
    columns: cols,
    rows: rows,
    compact: compact,
    colGap: colGap,
    rowGap: rowGap,
    cellW: cellW,
    cellH: cellH
  };
}

// Hole-free 8-cell grid. CPU takes 2 cells, each other card takes 1.
// Wide and medium share 4×2; narrow is 2×4 so the CPU row is full width.
function gridShape(width) {
  var w = Number(width);
  if (isFinite(w) && w >= 1080) return { columns: 4, rows: 2, cpuSpan: 2 };
  return { columns: 2, rows: 4, cpuSpan: 2 };
}

function appendCurves(cmds, pts) {
  var i;
  for (i = 1; i < pts.length - 1; i++) {
    var xc = (pts[i].x + pts[i + 1].x) / 2;
    var yc = (pts[i].y + pts[i + 1].y) / 2;
    cmds.push({ t: "Q", cx: pts[i].x, cy: pts[i].y, x: xc, y: yc });
  }
  var last = pts[pts.length - 1];
  cmds.push({ t: "L", x: last.x, y: last.y });
}

// Points are right-aligned in a `limit`-slot window. The fill is one subpath:
// baseline → up the first sample → along the stroke → down to the baseline.
// No second moveTo, so closePath cannot draw a diagonal wedge.
function buildSparkline(samples, width, height, yMin, yMax, limit) {
  var cap = limit || HISTORY_LIMIT;
  if (!(cap > 1)) cap = HISTORY_LIMIT;
  var w = Number(width) || 0;
  var h = Number(height) || 0;
  var list = samples || [];
  var n = list.length;
  var minv = Number(yMin);
  if (!isFinite(minv)) minv = 0;
  var maxv = Number(yMax);
  if (!(maxv > minv)) {
    maxv = minv;
    var s;
    for (s = 0; s < n; s++) {
      var sample = Number(list[s]);
      if (isFinite(sample) && sample > maxv) maxv = sample;
    }
    if (!(maxv > minv)) maxv = minv + 1;
  }
  var pts = [];
  if (n > 0 && w >= 2 && h >= 2 && maxv > minv) {
    var slot = w / (cap - 1);
    var use = n > cap ? cap : n;
    var offset = n - use;
    var start = cap - use;
    var i;
    for (i = 0; i < use; i++) {
      var v = Number(list[offset + i]);
      if (!isFinite(v)) v = minv;
      if (v < minv) v = minv;
      if (v > maxv) v = maxv;
      var x = (start + i) * slot;
      var y = h - ((v - minv) / (maxv - minv)) * (h - 3) - 1.5;
      pts.push({ x: x, y: y });
    }
    if (pts.length > 0) pts[pts.length - 1].x = w;
    if (use === 1) {
      var onlyY = pts[0].y;
      pts = [{ x: Math.max(0, w - slot), y: onlyY }, { x: w, y: onlyY }];
    }
  }
  var fill = [];
  var stroke = [];
  if (pts.length >= 2) {
    var last = pts[pts.length - 1];
    stroke.push({ t: "M", x: pts[0].x, y: pts[0].y });
    appendCurves(stroke, pts);
    fill.push({ t: "M", x: pts[0].x, y: h });
    fill.push({ t: "L", x: pts[0].x, y: pts[0].y });
    appendCurves(fill, pts);
    fill.push({ t: "L", x: last.x, y: h });
    fill.push({ t: "Z" });
  }
  return { points: pts, fill: fill, stroke: stroke, yMin: minv, yMax: maxv };
}

function emptyState() {
  var state = {
    t: null,
    proc: null,
    net: null,
    disk: null,
    diskDevice: null,
    diskHistMap: {},
    gpuIdle: null,
    gpuAt: null,
    cpuHist: [],
    memHist: [],
    gpuHist: [],
    rxHist: [],
    txHist: [],
    diskReadHist: [],
    diskWriteHist: [],
    batHist: [],
    processes: emptyProcesses(),
    procSnap: null,
    memInfo: null,
    rateMono: null,
    view: null
  };
  state.view = emptyView();
  return state;
}

function emptyView() {
  return {
    cpu: {
      percent: 0,
      percentText: "—",
      tempText: "—",
      freqText: "—",
      cores: [],
      history: []
    },
    mem: {
      usedText: "—",
      availableText: "—",
      cachedText: "—",
      swapText: "—",
      fraction: 0,
      history: []
    },
    gpu: null,
    disk: {
      device: "—",
      readLabel: "read",
      readText: "unavailable",
      writeText: "unavailable",
      usageText: "—",
      tempText: "—",
      fraction: 0,
      readHistory: [],
      writeHistory: []
    },
    net: {
      iface: "—",
      downText: "—",
      upText: "—",
      rxHistory: [],
      txHistory: [],
      perIface: []
    },
    battery: null,
    processes: emptyProcesses()
  };
}

function finiteOrNull(value) {
  if (value == null || value === "") return null;
  var n = Number(value);
  return isFinite(n) ? n : null;
}

function coreViews(percents, freqs, live, prevCores) {
  var cores = [];
  var i;
  var n = percents ? percents.length : 0;
  // Reuse the previous array when every cell is unchanged so QML does not
  // re-evaluate per-core bindings on a sample that did not move those values.
  var allSame = !!(prevCores && prevCores.length === n);
  for (i = 0; i < n; i++) {
    var prev = prevCores && prevCores[i] ? prevCores[i] : null;
    var value = null;
    var text = "—";
    if (live) {
      // null means this core had no previous sample. 0 is a real idle reading.
      if (percents[i] == null || !isFiniteNumber(Number(percents[i]))) {
        value = null;
        text = "—";
      } else {
        value = Number(percents[i]);
        text = formatPercent(value);
      }
    } else if (prev && prev.percent != null && isFiniteNumber(Number(prev.percent))) {
      value = prev.percent;
      text = prev.percentText || formatPercent(value);
    }
    var freqText = "";
    if (freqs && i < freqs.length && freqs[i] != null && freqs[i] !== "") {
      freqText = formatMhzShort(freqs[i]);
    } else if (!live && prev && prev.freqText) {
      freqText = prev.freqText;
    }
    if (allSame && prev && prev.percent === value && prev.percentText === text && prev.freqText === freqText) {
      cores.push(prev);
    } else {
      allSame = false;
      cores.push({ percent: value, percentText: text, freqText: freqText });
    }
  }
  if (allSame && prevCores) return prevCores;
  return cores;
}

function blankPerIface(names) {
  var rows = [];
  var i;
  for (i = 0; i < names.length; i++) {
    rows.push({ name: names[i], downText: "—", upText: "—" });
  }
  return rows;
}

function ratePerIface(interfaces, names) {
  var map = {};
  var i;
  var items = interfaces || [];
  for (i = 0; i < items.length; i++) map[items[i].name] = items[i];
  var rows = [];
  for (i = 0; i < names.length; i++) {
    var row = map[names[i]];
    rows.push({
      name: names[i],
      downText: row ? formatRate(row.rxBps) : "—",
      upText: row ? formatRate(row.txBps) : "—"
    });
  }
  return rows;
}

// True when two history arrays would draw the same sparkline. A fresh array
// with the same numbers must not force a Canvas repaint.
function seriesSame(a, b) {
  if (a === b) return true;
  var an = (a && typeof a.length === "number") ? a.length : 0;
  var bn = (b && typeof b.length === "number") ? b.length : 0;
  if (an !== bn) return false;
  var i;
  for (i = 0; i < an; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function cardOf(view, key) {
  if (!view || view[key] == null) return null;
  return view[key];
}

function isArray(value) {
  return Object.prototype.toString.call(value) === "[object Array]";
}

// Presented rows are untrusted. A non-array, or a list containing a non-row,
// is rejected whole. Each list is capped at 8.
function clipProcList(list) {
  if (!isArray(list)) return null;
  var out = [];
  var n = list.length > 8 ? 8 : list.length;
  var i;
  for (i = 0; i < n; i++) {
    var row = list[i];
    if (!row || typeof row !== "object") return null;
    out.push({
      name: row.name == null ? "" : String(row.name),
      text: row.text == null ? "" : String(row.text)
    });
  }
  return out;
}

function takePresented(presented) {
  if (!presented || typeof presented !== "object") return null;
  var byCpu = clipProcList(presented.byCpu);
  var byMem = clipProcList(presented.byMem);
  if (!byCpu || !byMem) return null;
  return { byCpu: byCpu, byMem: byMem };
}

function procGate(procSnap, now) {
  if (!procSnap || procSnap.t == null) return "baseline";
  var pelapsed = now - procSnap.t;
  if (pelapsed >= 0 && pelapsed < MIN_ELAPSED_MS) return "fast";
  if (pelapsed > MAX_ELAPSED_MS || pelapsed < 0) return "slow";
  return "live";
}

function procsHaveRows(spec) {
  return !!(spec && isArray(spec.rows));
}

// Ticks and the timestamp are one sample. A presented-only payload has no
// tick table, so it must not stamp a new time onto the previous ticks.
function snapFromRows(spec, now) {
  if (!procsHaveRows(spec)) return null;
  return procSnapFrom(spec, now);
}

function stampProcesses(processes, now) {
  var current = processes || emptyProcesses();
  return {
    byCpu: isArray(current.byCpu) ? current.byCpu : [],
    byMem: isArray(current.byMem) ? current.byMem : [],
    freshAt: now,
    stale: false
  };
}

function ageProcesses(processes, now) {
  var current = processes || emptyProcesses();
  var freshAt = current.freshAt;
  if (freshAt == null || !(now - freshAt > MAX_ELAPSED_MS)) return current;
  if (current.stale) return current;
  // Keep the last rows. The card dims them and draws a stale badge.
  return {
    byCpu: isArray(current.byCpu) ? current.byCpu : [],
    byMem: isArray(current.byMem) ? current.byMem : [],
    freshAt: freshAt,
    stale: true
  };
}

function sensorDown(sample, name) {
  // A missing key is not a failure: legacy samples omit the parsed objects.
  // null plus errors[name], or a collector-wide failure, keeps the last card.
  if (!sample || sample[name] != null) return false;
  if (!sample.errors) return false;
  if (sample.errors[name] != null && sample.errors[name] !== "") return true;
  if (sample.errors.collector != null && sample.errors.collector !== "") return true;
  return false;
}

function cpuBlock(sample) {
  if (sample && sample.cpu && typeof sample.cpu === "object" && sample.cpu.total) {
    var cores = [];
    var rawCores = sample.cpu.cores || [];
    var i;
    for (i = 0; i < rawCores.length; i++) {
      cores.push(rawCores[i] && typeof rawCores[i] === "object" ? rawCores[i] : null);
    }
    return { total: sample.cpu.total, cores: cores, coreCount: cores.length };
  }
  return parseProcStat(sample && sample.proc_stat);
}

function memBlock(sample) {
  if (sample && sample.mem && typeof sample.mem === "object") return sample.mem;
  return parseMeminfo(sample && sample.meminfo);
}

function netBlock(sample) {
  if (sample && sample.net && typeof sample.net === "object" && isArray(sample.net.ifaces)) {
    var out = [];
    var items = sample.net.ifaces;
    var i;
    for (i = 0; i < items.length; i++) {
      var row = items[i];
      if (!row) continue;
      out.push({
        name: row.name == null ? "" : String(row.name),
        rxBytes: toNumber(row.rx != null ? row.rx : row.rxBytes),
        txBytes: toNumber(row.tx != null ? row.tx : row.txBytes)
      });
    }
    return out;
  }
  return parseNetDev(sample && sample.net_dev);
}

function diskBlock(sample) {
  if (sample && sample.disk && typeof sample.disk === "object" && !isArray(sample.disk)) {
    if (sample.disk.device && sample.disk.sectors_read != null && sample.disk.sectors_written != null) {
      return [{
        name: String(sample.disk.device),
        sectorsRead: toNumber(sample.disk.sectors_read),
        sectorsWritten: toNumber(sample.disk.sectors_written)
      }];
    }
    return [];
  }
  return parseDiskstats(sample && sample.diskstats);
}

// Darwin iostat publishes one combined rate. Null means the key is absent
// (Linux counters). An object with bps null means no interval has arrived.
function diskIoBytes(sample) {
  var disk = sample && sample.disk;
  if (!disk || typeof disk !== "object" || isArray(disk)) return null;
  if (!Object.prototype.hasOwnProperty.call(disk, "io_bytes_per_s")) return null;
  return { bps: finiteOrNull(disk.io_bytes_per_s) };
}

function rowsHaveReadTimes(spec, prevSnap) {
  var list = (spec && spec.rows) || [];
  if (!list.length || !prevSnap || !prevSnap.reads) return false;
  var i;
  for (i = 0; i < list.length; i++) {
    if (list[i] && list[i].read_ms != null) return true;
  }
  return false;
}

function copyDiskMap(prevMap) {
  var next = {};
  var map = prevMap || {};
  var key;
  for (key in map) {
    if (Object.prototype.hasOwnProperty.call(map, key) && map[key]) next[key] = map[key];
  }
  return next;
}

// Keep only the fields the storage view understands. Collector data is untrusted.
function filesystemRows(value) {
  if (!isArray(value)) return [];
  var rows = [];
  for (var i = 0; i < value.length && rows.length < 32; i++) {
    var row = value[i];
    if (!row || typeof row !== "object" || isArray(row)) continue;
    function cleanText(text) {
      return (typeof text === "string" ? text : "").replace(/[\x00-\x1f\x7f-\x9f]/g, "").slice(0, 120);
    }
    var total = isFiniteNumber(row.total) && row.total >= 0 ? row.total : 0;
    var used = isFiniteNumber(row.used) && row.used >= 0 ? Math.min(row.used, total) : 0;
    var cleaned = { mount: cleanText(row.mount), device: cleanText(row.device),
      label: cleanText(row.label), total: total, used: used };
    if (typeof row.bus === "string") cleaned.bus = cleanText(row.bus);
    rows.push(cleaned);
  }
  return rows;
}

function step(state, raw, nowMs) {
  var prev = state || emptyState();
  var sample = raw || {};
  var now = Number(nowMs);
  if (!isFinite(now)) now = 0;
  var first = prev.t == null;
  var elapsed = first ? 0 : (now - prev.t);
  // The monotonic stamp is the rate window. It uses the same bounds as wall
  // time: a short delta skips the tick, a gap rebaselines instead of rating.
  var rateMonoEarly = finiteOrNull(sample.mono_ms != null ? sample.mono_ms : sample.rate_mono_ms);
  var monoEarly = null;
  if (!first && rateMonoEarly != null && prev.rateMono != null && isFiniteNumber(Number(prev.rateMono))) {
    monoEarly = rateMonoEarly - Number(prev.rateMono);
  }
  var wallGap = !first && (elapsed > MAX_ELAPSED_MS || elapsed < 0);
  var wallShort = !first && elapsed >= 0 && elapsed < MIN_ELAPSED_MS;
  var monoShort = !wallGap && monoEarly != null && monoEarly > 0 && monoEarly < MIN_ELAPSED_MS;
  if (wallShort || monoShort) {
    return { state: prev, view: prev.view || emptyView(), skip: true };
  }
  var rateGap = monoEarly != null && (monoEarly > MAX_ELAPSED_MS || monoEarly < 0);
  if (!prev.view) prev.view = emptyView();

  var rebaseline = !first && (elapsed > MAX_ELAPSED_MS || elapsed < 0);
  var live = !first && !rebaseline;
  var prevView = prev.view;

  var cpuFailed = sensorDown(sample, "cpu");
  var memFailed = sensorDown(sample, "mem");
  var diskFailed = sensorDown(sample, "disk");
  var netFailed = sensorDown(sample, "net");
  var gpuFailed = sensorDown(sample, "gpu");
  var tempsFailed = sensorDown(sample, "temps");
  var batFailed = sensorDown(sample, "battery");
  // na is a host that cannot provide the sensor. It is not a failure.
  var cpuNa = !!(sample.cpu && sample.cpu.na === true);
  var memNa = !!(sample.mem && sample.mem.na === true);
  var diskNa = !!(sample.disk && sample.disk.na === true);
  var netNa = !!(sample.net && sample.net.na === true);
  var gpuNa = !!(sample.gpu && sample.gpu.na === true);
  var tempsNa = !!(sample.temps && sample.temps.na === true);

  var proc = cpuFailed ? (prev.proc || parseProcStat("")) : cpuBlock(sample);
  var mem = memFailed
    ? (prev.memInfo || { total: null, used: null, available: null, cached: null, swapUsed: null, swapTotal: null })
    : memBlock(sample);
  var netList = netFailed ? (prev.net || []) : netBlock(sample);
  var diskList = diskFailed ? (prev.disk || []) : diskBlock(sample);

  var cpu = { total: 0, cores: [] };
  if (!cpuFailed && live && prev.proc) cpu = cpuDeltas(prev.proc, proc);
  var percents = [];
  var ci;
  for (ci = 0; ci < proc.coreCount; ci++) {
    if (!live || !proc.cores[ci]) percents.push(null);
    else if (cpu.cores[ci] == null || !isFiniteNumber(Number(cpu.cores[ci]))) percents.push(null);
    else percents.push(cpu.cores[ci]);
  }

  // Counter files are stamped when they are read. That delta is the rate
  // window; arrival time includes the slow sensors that follow the read.
  // A gap keeps the new stamp as the baseline and does not emit a rate.
  var rateMono = rateMonoEarly;
  var rateDt = elapsed;
  if (!rateGap && monoEarly != null && monoEarly > 0) rateDt = monoEarly;

  var cpuHist = prev.cpuHist || [];
  if (live && !cpuFailed && !cpuNa) cpuHist = pushHistory(cpuHist, cpu.total, HISTORY_LIMIT);

  var memHist = prev.memHist || [];
  var memFraction = (mem.total && mem.used != null) ? clamp01(mem.used / mem.total) : 0;
  var memPct = (mem.total && mem.used != null) ? (100 * mem.used / mem.total) : null;
  if (!memFailed && memPct != null && !rebaseline) memHist = pushHistory(memHist, memPct, HISTORY_LIMIT);
  else if (!memFailed && rebaseline && memPct != null) memHist = pushHistory(memHist, memPct, HISTORY_LIMIT);

  var virtualNames = null;
  if (sample.net && typeof sample.net === "object" && Object.prototype.hasOwnProperty.call(sample.net, "virtual")) {
    virtualNames = sample.net.virtual;
  } else if (Object.prototype.hasOwnProperty.call(sample, "virtual_ifaces")) {
    virtualNames = sample.virtual_ifaces;
  }
  var net = { rxBps: 0, txBps: 0, interfaces: [] };
  if (!netFailed && live && !rateGap && prev.net) net = netRates(prev.net, netList, rateDt, virtualNames);

  var hasParsedDefault = sample.net && typeof sample.net === "object" &&
    Object.prototype.hasOwnProperty.call(sample.net, "default_iface");
  var hasRoute = Object.prototype.hasOwnProperty.call(sample, "route_v4") ||
    Object.prototype.hasOwnProperty.call(sample, "route_v6");
  var preferred = hasParsedDefault
    ? (sample.net.default_iface || null)
    : (hasRoute ? defaultRouteIface(sample.route_v4, sample.route_v6) : (sample.default_iface || null));

  var rxHist = prev.rxHist || [];
  var txHist = prev.txHist || [];
  if (live && !netFailed && !rateGap && !netNa) {
    rxHist = pushHistory(rxHist, net.rxBps, HISTORY_LIMIT);
    txHist = pushHistory(txHist, net.txBps, HISTORY_LIMIT);
  }

  var summedNames = [];
  var ni;
  for (ni = 0; ni < net.interfaces.length; ni++) summedNames.push(net.interfaces[ni].name);
  var physical = physicalNames(netList, virtualNames);
  var labelNames = live ? summedNames : physical;
  var orderedNames = orderIfaces(labelNames, preferred);

  var device = sample.disk_device || null;
  if (!device && sample.disk && typeof sample.disk === "object") device = sample.disk.device || null;
  if (diskFailed) device = prev.diskDevice || null;
  var ioRate = diskFailed ? null : diskIoBytes(sample);
  var combined = ioRate != null;
  var diskRate = { readBps: 0, writeBps: 0, found: false };
  if (!combined && !diskFailed && live && !rateGap && prev.disk && device) diskRate = diskRates(prev.disk, diskList, rateDt, device);

  // Histories are keyed by device. A change, or no device, drops the other
  // device's series from the card instead of stitching the curves together.
  var diskHistMap = copyDiskMap(prev.diskHistMap);
  var prevDevice = prev.diskDevice || null;
  var diskReadHist = [];
  var diskWriteHist = [];
  var readText = "unavailable";
  var writeText = "unavailable";
  var readLabel = "read";
  var prevDisk = cardOf(prevView, "disk");
  if (diskFailed) {
    diskHistMap = prev.diskHistMap || {};
    if (prevDisk) {
      readText = prevDisk.readText;
      writeText = prevDisk.writeText;
      readLabel = prevDisk.readLabel || "read";
      diskReadHist = prevDisk.readHistory || [];
      diskWriteHist = prevDisk.writeHistory || [];
    }
  } else if (combined) {
    // Already a one-second rate. History moves only on a live sample that
    // brought a number. A held sector read is not total I/O.
    var haveIo = ioRate.bps != null;
    var prevIsIo = !!(device && prevDevice === device && prevDisk && prevDisk.readLabel === "I/O");
    var prevReadRate = !!(device && prevDevice === device && prevDisk && prevDisk.readLabel !== "I/O" &&
      prevDisk.readText && prevDisk.readText !== "unavailable" && prevDisk.readText !== "n/a");
    if (device) {
      var ioBucket = diskHistMap[device] || { read: [], write: [] };
      diskReadHist = ioBucket.read || [];
      diskWriteHist = ioBucket.write || [];
    }
    if (!haveIo && prevReadRate) {
      readLabel = prevDisk.readLabel || "read";
      readText = prevDisk.readText;
      writeText = prevDisk.writeText;
      diskReadHist = prevDisk.readHistory || diskReadHist;
      diskWriteHist = prevDisk.writeHistory || diskWriteHist;
    } else {
      readLabel = "I/O";
      writeText = "n/a";
      diskWriteHist = [];
      if (!haveIo) {
        if (prevIsIo && prevDisk.readText && prevDisk.readText !== "unavailable" && prevDisk.readText !== "n/a") {
          readText = prevDisk.readText;
          diskReadHist = prevDisk.readHistory || diskReadHist;
        } else {
          readText = "unavailable";
          if (!prevIsIo) diskReadHist = [];
        }
      } else if (live && !rateGap) {
        readText = formatRate(ioRate.bps);
        if (!prevIsIo) diskReadHist = [];
        diskReadHist = pushHistory(diskReadHist, ioRate.bps, HISTORY_LIMIT);
      } else {
        readText = formatRate(ioRate.bps);
        if (prevIsIo && prevDisk) diskReadHist = prevDisk.readHistory || diskReadHist;
        else diskReadHist = [];
      }
    }
    if (device) diskHistMap[device] = { read: diskReadHist, write: diskWriteHist };
  } else if (device) {
    var bucket = diskHistMap[device] || { read: [], write: [] };
    diskReadHist = bucket.read || [];
    diskWriteHist = bucket.write || [];
    var sameDevice = prevDevice === device;
    if (live && !rateGap && diskRate.found) {
      readText = formatRate(diskRate.readBps);
      writeText = formatRate(diskRate.writeBps);
      diskReadHist = pushHistory(diskReadHist, diskRate.readBps, HISTORY_LIMIT);
      diskWriteHist = pushHistory(diskWriteHist, diskRate.writeBps, HISTORY_LIMIT);
    } else if ((rebaseline || rateGap) && sameDevice && prevDisk) {
      readText = prevDisk.readText;
      writeText = prevDisk.writeText;
    }
    diskHistMap[device] = { read: diskReadHist, write: diskWriteHist };
  }

  var prevGpu = cardOf(prevView, "gpu");
  var gpuView = null;
  var gpuIdle = prev.gpuIdle;
  var gpuAt = prev.gpuAt == null ? null : prev.gpuAt;
  var gpuHist = prev.gpuHist || [];
  var gpu = sample.gpu;
  if (gpuFailed) {
    gpuView = prevGpu;
  } else if (gpuNa) {
    gpuIdle = null;
    gpuAt = null;
    gpuHist = [];
    gpuView = {
      percent: null,
      percentText: "n/a",
      freqText: "",
      fraction: 0,
      history: [],
      driver: "",
      unsupported: false,
      na: true
    };
  } else if (gpu && gpu.present) {
    var idleNum = finiteOrNull(gpu.idle_ms);
    var directBusy = finiteOrNull(gpu.busy_pct);
    var gpuDriver = gpu.driver ? String(gpu.driver) : "";
    var freqText = formatGpuFreq(gpu.mhz);
    if (gpu.mhz_skip && prevGpu && prevGpu.freqText) freqText = prevGpu.freqText;
    var gpuPct = null;
    var gpuText = "—";
    if (gpu.unsupported) {
      gpuText = "not supported";
      gpuIdle = null;
      gpuAt = null;
      gpuHist = [];
    } else if (directBusy != null) {
      // amdgpu publishes a percent, not a residency counter. A failed read
      // leaves busy_pct null and must not replay the previous percent.
      if (directBusy < 0) directBusy = 0;
      if (directBusy > 100) directBusy = 100;
      gpuPct = directBusy;
      gpuText = formatPercent(directBusy);
      gpuHist = pushHistory(gpuHist, gpuPct, HISTORY_LIMIT);
    } else if (idleNum != null) {
      var gpuElapsed = gpuAt != null ? (now - gpuAt) : null;
      var gpuLive = gpuElapsed != null && gpuElapsed >= MIN_ELAPSED_MS && gpuElapsed <= MAX_ELAPSED_MS;
      var gpuJump = gpuElapsed != null && (gpuElapsed > MAX_ELAPSED_MS || gpuElapsed < 0);
      if (gpuLive && gpuIdle != null) {
        // Frozen residency plus freq 0 or a suspended device is idle, not 100%.
        if (gpuStallIdle(gpuIdle, idleNum, gpu.mhz, gpu.runtime_status)) {
          gpuPct = 0;
          gpuText = formatPercent(0);
          freqText = "idle";
          gpuHist = pushHistory(gpuHist, gpuPct, HISTORY_LIMIT);
        } else {
          var busy = gpuBusy(gpuIdle, idleNum, gpuElapsed);
          // Unknown or outside 0..100: no history point. gpuBusy already clamps
          // residency jitter; anything still outside is rejected.
          if (busy == null || !isFiniteNumber(busy) || busy < 0 || busy > 100) {
            gpuPct = null;
            gpuText = "—";
          } else {
            gpuPct = busy;
            gpuText = formatPercent(busy);
            gpuHist = pushHistory(gpuHist, gpuPct, HISTORY_LIMIT);
          }
        }
      } else if (gpuJump && prevGpu && prevGpu.percent != null && isFiniteNumber(Number(prevGpu.percent))) {
        gpuPct = Number(prevGpu.percent);
        if (gpuPct < 0 || gpuPct > 100) {
          gpuPct = null;
          gpuText = "—";
        } else {
          gpuText = prevGpu.percentText || formatPercent(gpuPct);
        }
      }
      gpuIdle = idleNum;
      gpuAt = now;
    }
    gpuView = {
      percent: gpuPct,
      percentText: gpuText,
      freqText: gpu.unsupported ? "" : freqText,
      fraction: gpuPct == null ? 0 : clamp01(gpuPct / 100),
      history: gpuHist,
      driver: gpuDriver,
      unsupported: gpu.unsupported ? true : false
    };
  } else {
    gpuIdle = null;
    gpuAt = null;
    gpuHist = [];
  }

  var batHist = prev.batHist || [];
  var batteryView = null;
  // The collector re-reads the battery only every few seconds. Between reads
  // it asks us to keep the card, including its history, instead of clearing it.
  if (sample.battery_skip || batFailed) {
    batteryView = cardOf(prevView, "battery");
  } else if (sample.battery) {
    var watts = batteryPowerW(sample.battery);
    var cap = finiteOrNull(sample.battery.capacity);
    if (cap != null) batHist = pushHistory(batHist, cap, HISTORY_LIMIT);
    batteryView = {
      percentText: cap == null ? "—" : formatPercent(cap),
      statusText: batteryStatus(sample.battery.status) || "—",
      powerText: watts == null ? "—" : formatPower(watts),
      fraction: cap == null ? 0 : clamp01(cap / 100),
      history: batHist
    };
  }

  var processes = prev.processes || emptyProcesses();
  var procSnap = prev.procSnap || null;
  var procUpdated = false;
  // A process table (presented rows or a tick table) refreshes freshness.
  // The card goes stale only when no table arrives for more than 10 s.
  // Presented-only never invents a tick baseline. A wall gap with no per-row
  // read times moves the snapshot but does not apply that gap as CPU%.
  if (sample.procs && (sample.procs.presented || procsHaveRows(sample.procs))) {
    var gate = procGate(procSnap, now);
    var presentedOk = sample.procs.presented ? takePresented(sample.procs.presented) : null;
    var hasRows = procsHaveRows(sample.procs);
    var rowSnap = snapFromRows(sample.procs, now);
    var hasRead = rowsHaveReadTimes(sample.procs, procSnap);
    if (gate === "fast") {
      // Keep the rows already on screen. Ticks and their timestamp stay paired.
    } else if (presentedOk && !hasRows) {
      processes = {
        byCpu: presentedOk.byCpu,
        byMem: presentedOk.byMem,
        freshAt: now,
        stale: false
      };
      procUpdated = true;
    } else if (hasRows && gate === "slow" && !hasRead) {
      processes = {
        byCpu: isArray(processes.byCpu) ? processes.byCpu : [],
        byMem: isArray(processes.byMem) ? processes.byMem : [],
        freshAt: now,
        stale: false
      };
      if (rowSnap) procSnap = rowSnap;
      procUpdated = true;
    } else if (hasRows) {
      var withCpu = !!(procSnap && procSnap.t != null && gate !== "baseline");
      var pelapsed = withCpu ? (now - procSnap.t) : 0;
      var computed = presentProcesses(
        procRows(sample.procs, withCpu ? procSnap : null, pelapsed, mem.total, withCpu),
        withCpu
      );
      if (presentedOk) {
        processes = {
          byCpu: presentedOk.byCpu,
          byMem: presentedOk.byMem,
          freshAt: now,
          stale: false
        };
      } else {
        processes = stampProcesses(computed, now);
      }
      if (rowSnap) procSnap = rowSnap;
      procUpdated = true;
    }
  }
  if (!procUpdated) processes = ageProcesses(processes, now);

  var rootUsed = finiteOrNull(sample.root_used);
  var rootTotal = finiteOrNull(sample.root_total);
  if (!diskFailed && sample.disk && typeof sample.disk === "object" && !isArray(sample.disk)) {
    if (sample.disk.root_used != null) rootUsed = finiteOrNull(sample.disk.root_used);
    if (sample.disk.root_total != null) rootTotal = finiteOrNull(sample.disk.root_total);
  }
  var diskFraction = (rootTotal && rootUsed != null) ? clamp01(rootUsed / rootTotal) : 0;

  var packageTemp = sample.package_temp_c;
  var diskTemp = sample.nvme_temp_c;
  if (sample.temps && typeof sample.temps === "object" && !tempsNa) {
    packageTemp = sample.temps.package_c;
    diskTemp = sample.temps.disk_c;
  }
  var freqAvg = sample.cpu_mhz;
  var freqs = sample.cpu_mhz_cores || null;
  if (!cpuFailed && sample.cpu && typeof sample.cpu === "object") {
    if (Object.prototype.hasOwnProperty.call(sample.cpu, "mhz")) freqAvg = sample.cpu.mhz;
    if (Object.prototype.hasOwnProperty.call(sample.cpu, "core_mhz")) freqs = sample.cpu.core_mhz;
  }

  var prevCpu = cardOf(prevView, "cpu");
  var prevMem = cardOf(prevView, "mem");
  var prevNet = cardOf(prevView, "net");
  var cpuPercentText = "—";
  var cpuPercentValue = 0;
  if (live && !cpuFailed) {
    cpuPercentValue = cpu.total;
    cpuPercentText = formatPercent(cpu.total);
  } else if (rebaseline && prevCpu) {
    cpuPercentValue = prevCpu.percent || 0;
    cpuPercentText = prevCpu.percentText || "—";
  }

  var downText = "—";
  var upText = "—";
  var perIface = blankPerIface(orderedNames);
  var iface = ifaceLabel(orderedNames, preferred);
  if (netNa) {
    downText = "n/a";
    upText = "n/a";
    iface = "n/a";
    perIface = [];
    rxHist = [];
    txHist = [];
  } else if (live && !netFailed && !rateGap) {
    downText = formatRate(net.rxBps);
    upText = formatRate(net.txBps);
    perIface = ratePerIface(net.interfaces, orderedNames);
  } else if ((rebaseline || netFailed || rateGap) && prevNet) {
    downText = prevNet.downText;
    upText = prevNet.upText;
    iface = prevNet.iface;
    perIface = isArray(prevNet.perIface) ? prevNet.perIface : [];
  }

  var cpuCard;
  if (cpuNa) {
    cpuCard = {
      percent: null,
      percentText: "n/a",
      tempText: tempsNa ? "n/a" : "—",
      freqText: "n/a",
      cores: [],
      history: []
    };
    cpuHist = [];
  } else if (cpuFailed && prevCpu) {
    cpuCard = prevCpu;
    cpuHist = prev.cpuHist || [];
  } else {
    var cores = coreViews(percents, freqs, live, prevCpu ? prevCpu.cores : null);
    var cpuTempText = tempsNa ? "n/a" : formatTemp(packageTemp);
    if (!tempsNa && tempsFailed && prevCpu) cpuTempText = prevCpu.tempText || cpuTempText;
    var cpuFreqText = freqAvg == null || freqAvg === "" ? "—" : formatMhz(freqAvg);
    if (!live && prevCpu && (freqAvg == null || freqAvg === "")) cpuFreqText = prevCpu.freqText || cpuFreqText;
    cpuCard = {
      percent: cpuPercentValue,
      percentText: cpuPercentText,
      tempText: cpuTempText,
      freqText: cpuFreqText,
      cores: cores,
      history: cpuHist
    };
  }

  var memCard;
  if (memNa) {
    memCard = {
      usedText: "n/a",
      headerText: "n/a",
      availableText: "n/a",
      cachedText: "n/a",
      swapText: "n/a",
      fraction: 0,
      history: []
    };
    memHist = [];
  } else if (memFailed && prevMem) {
    memCard = prevMem;
    memHist = prev.memHist || [];
  } else {
    memCard = {
      usedText: formatUsage(mem.used, mem.total),
      headerText: memoryHeader(mem.used, mem.cached, mem.total),
      availableText: formatBytes(mem.available),
      cachedText: formatBytes(mem.cached),
      swapText: formatUsage(mem.swapUsed, mem.swapTotal),
      fraction: memFraction,
      cacheFraction: memorySegments(mem.used, mem.cached, mem.total).fraction,
      history: memHist
    };
  }

  if (sample.wsl === true) {
    var win = sample.windows;
    memCard.wslText = "WSL " + formatUsage(mem.used, mem.total);
    memCard.windowsUnavailable = !(win && Number(win.total) > 0 && Number(win.used) >= 0 && Number(win.used) <= Number(win.total));
    if (!memCard.windowsUnavailable) {
      memCard.usedText = formatUsage(win.used, win.total);
      memCard.headerText = memoryHeader(win.used, null, win.total);
      memCard.fraction = clamp01(win.used / win.total);
      memCard.cacheFraction = 0;
      memCard.wslFraction = clamp01(Math.min(Number(mem.used) || 0, win.used) / win.total);
      cpuCard.windowsText = win.cpu == null ? "" : "Windows " + formatPercent(win.cpu);
    }
  }

  var diskTempText = tempsNa ? "n/a" : formatTemp(diskTemp);
  if (!tempsNa && tempsFailed && prevDisk) diskTempText = prevDisk.tempText || diskTempText;
  var diskCard;
  if (diskNa) {
    diskCard = {
      device: "n/a",
      readLabel: "read",
      readText: "n/a",
      writeText: "n/a",
      usageText: "n/a",
      tempText: "n/a",
      fraction: 0,
      readHistory: [],
      writeHistory: []
    };
  } else if (diskFailed && prevDisk) {
    diskCard = prevDisk;
  } else {
    diskCard = {
      device: device || "—",
      readLabel: readLabel,
      readText: readText,
      writeText: writeText,
      usageText: formatUsage(rootUsed, rootTotal),
      tempText: diskTempText,
      fraction: diskFraction,
      readHistory: diskReadHist,
      writeHistory: diskWriteHist
    };
  }

  if (netFailed && prevNet) {
    rxHist = prev.rxHist || [];
    txHist = prev.txHist || [];
  }

  var view = {
    cpu: cpuCard,
    mem: memCard,
    filesystems: filesystemRows(sample.filesystems),
    windows: sample.windows && typeof sample.windows === "object" && !isArray(sample.windows) ? {
      total: sample.windows.total, used: sample.windows.used, cpu: sample.windows.cpu,
      disks: filesystemRows(sample.windows.disks)
    } : null,
    gpu: gpuView,
    disk: diskCard,
    net: {
      iface: iface,
      downText: downText,
      upText: upText,
      rxHistory: rxHist,
      txHistory: txHist,
      perIface: perIface
    },
    battery: batteryView,
    processes: processes
  };

  if (cpuFailed) proc = prev.proc || proc;
  if (netFailed) netList = prev.net || netList;
  if (diskFailed) {
    diskList = prev.disk || diskList;
    device = prev.diskDevice || null;
  }

  return {
    state: {
      t: now,
      proc: proc,
      net: netList,
      disk: diskList,
      diskDevice: device || null,
      diskHistMap: diskHistMap,
      gpuIdle: gpuIdle,
      gpuAt: gpuAt,
      cpuHist: cpuHist,
      memHist: memHist,
      gpuHist: gpuHist,
      rxHist: rxHist,
      txHist: txHist,
      diskReadHist: diskReadHist,
      diskWriteHist: diskWriteHist,
      batHist: batHist,
      processes: processes,
      procSnap: procSnap,
      memInfo: mem,
      rateMono: rateMono != null ? rateMono : null,
      view: view
    },
    view: view
  };
}

var api = {
  HISTORY_LIMIT: HISTORY_LIMIT,
  LABEL_MIX: LABEL_MIX,
  MIN_ELAPSED_MS: MIN_ELAPSED_MS,
  MAX_ELAPSED_MS: MAX_ELAPSED_MS,
  parseProcStat: parseProcStat,
  cpuDeltas: cpuDeltas,
  parseMeminfo: parseMeminfo,
  parseNetDev: parseNetDev,
  isVirtualIface: isVirtualIface,
  netRates: netRates,
  defaultRouteIface: defaultRouteIface,
  ifaceLabel: ifaceLabel,
  parseDiskstats: parseDiskstats,
  diskRates: diskRates,
  gpuBusy: gpuBusy,
  gpuStallIdle: gpuStallIdle,
  genericThreadName: genericThreadName,
  collectorLineAlive: collectorLineAlive,
  collectorKillDue: collectorKillDue,
  collectorExitIgnored: collectorExitIgnored,
  parseColorsToml: parseColorsToml,
  oklabDistance: oklabDistance,
  warningColor: warningColor,
  seriesFlat: seriesFlat,
  meterColor: meterColor,
  batteryMeterColor: batteryMeterColor,
  mixHex: mixHex,
  qtColor: qtColor,
  resolveTheme: resolveTheme,
  pushHistory: pushHistory,
  batteryPowerW: batteryPowerW,
  batteryStatus: batteryStatus,
  parsePs: parsePs,
  topProcesses: topProcesses,
  procDisplayName: procDisplayName,
  procCpuPercent: procCpuPercent,
  procMemPercent: procMemPercent,
  groupProcesses: groupProcesses,
  formatBytes: formatBytes,
  formatRate: formatRate,
  formatPercent: formatPercent,
  formatPercentPrecise: formatPercentPrecise,
  formatMhz: formatMhz,
  formatMhzShort: formatMhzShort,
  formatGpuFreq: formatGpuFreq,
  formatTemp: formatTemp,
  formatPower: formatPower,
  formatUsage: formatUsage,
  gridShape: gridShape,
  coreLayout: coreLayout,
  netDetailLines: netDetailLines,
  buildSparkline: buildSparkline,
  seriesSame: seriesSame,
  emptyState: emptyState,
  emptyView: emptyView,
  step: step
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
