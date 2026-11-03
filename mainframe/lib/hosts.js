// Remote machine tabs. hosts.json is validated here so a bad alias never
// reaches ssh. The fleet tracks selected, overview, and lingering collectors.

var SSH_ALIAS = /^[A-Za-z0-9._@-]{1,64}$/;
var LINGER_MS = 60000;
var RETRY_MS = 30000;

function isArray(value) {
  return Object.prototype.toString.call(value) === "[object Array]";
}

function hostsPath(xdg, home) {
  var base = String(xdg || "").replace(/^\s+|\s+$/g, "");
  if (!base) base = String(home || "") + "/.config";
  if (base.charAt(base.length - 1) === "/") base = base.slice(0, -1);
  return base + "/mainframe/hosts.json";
}

function validName(name) {
  if (typeof name !== "string") return false;
  if (name.length < 1 || name.length > 24) return false;
  var i;
  for (i = 0; i < name.length; i++) {
    var code = name.charCodeAt(i);
    if (code < 32 || code === 127) return false;
  }
  return true;
}

function validAlias(alias) {
  if (typeof alias !== "string" || !SSH_ALIAS.test(alias)) return false;
  // ssh parses a leading "-" as an option ("-oProxyCommand", "-F", "-J").
  // The same applies to either side of user@host.
  var parts = alias.split("@");
  var i;
  for (i = 0; i < parts.length; i++) {
    if (parts[i].charAt(0) === "-") return false;
  }
  return true;
}

// Exact argv. The alias is one element after "--". null means "do not start".
function sshArgv(alias) {
  if (!validAlias(alias)) return null;
  return [
    "ssh",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2",
    "--",
    alias,
    "exec", "python3", "-u", "-", "--remote"
  ];
}

// Puts that ssh in its own process group, then execs it. No shell.
function sshCommand(alias) {
  var argv = sshArgv(alias);
  if (!argv) return null;
  var cmd = [
    "python3", "-c",
    "import os,sys; os.setpgid(0,0); os.execvp(sys.argv[1], sys.argv[1:])"
  ];
  var i;
  for (i = 0; i < argv.length; i++) cmd.push(argv[i]);
  return cmd;
}

// Keep checking the original process group after its leader has exited.
// A nonzero exit means cleanup was not confirmed and the slot stays reserved.
function groupCleanupCommand(pid, hard) {
  return ["python3", "-c", [
    "import errno,os,signal,sys,time",
    "pid=int(sys.argv[1]); hard=sys.argv[2]=='1'",
    "def send(sig):",
    " try: os.killpg(pid,sig); return True",
    " except ProcessLookupError: return False",
    "if hard: send(signal.SIGKILL)",
    "else: send(signal.SIGTERM)",
    "time.sleep(0.5)",
    "while send(signal.SIGKILL): time.sleep(0.1)"
  ].join("\n"), String(pid), hard ? "1" : "0"];
}

function parseHosts(text, missing) {
  if (missing || text == null || String(text).replace(/^\s+|\s+$/g, "") === "") {
    return { ok: false, hosts: [], hint: true };
  }
  var data = null;
  try {
    data = JSON.parse(String(text));
  } catch (err) {
    return { ok: false, hosts: [], hint: true };
  }
  if (!data || typeof data !== "object" || !isArray(data.hosts)) {
    return { ok: false, hosts: [], hint: true };
  }
  var hosts = [];
  var seen = {};
  var dropped = 0;
  var i;
  for (i = 0; i < data.hosts.length; i++) {
    var item = data.hosts[i];
    if (!item || typeof item !== "object") {
      dropped += 1;
      continue;
    }
    var name = typeof item.name === "string" ? item.name : "";
    var ssh = typeof item.ssh === "string" ? item.ssh : "";
    if (!validName(name) || !validAlias(ssh) || seen[ssh]) {
      dropped += 1;
      continue;
    }
    seen[ssh] = true;
    hosts.push({ name: name, ssh: ssh });
  }
  var hint = hosts.length === 0 && dropped > 0;
  return { ok: true, hosts: hosts, hint: hint };
}

function sanitizeError(line) {
  var text = String(line || "");
  var out = "";
  var i;
  for (i = 0; i < text.length; i++) {
    var code = text.charCodeAt(i);
    if (code < 32 || code === 127) out += " ";
    else out += text.charAt(i);
  }
  out = out.replace(/[ \t]+/g, " ").replace(/^\s+|\s+$/g, "");
  if (out.length > 200) out = out.slice(0, 200);
  return out;
}

function sampleWsl(sample) {
  if (!sample || typeof sample !== "object") return false;
  if (sample.wsl === true) return true;
  var kernel = String(sample.kernel || "").toLowerCase();
  return kernel.indexOf("microsoft") >= 0 || kernel.indexOf("wsl") >= 0;
}

function createFleet(localName) {
  return {
    localName: localName ? String(localName) : "",
    localWsl: false,
    hosts: [],
    selected: 0,
    overview: false,
    activeSelected: true,
    localOs: "",
    sessions: {},
    hint: true
  };
}

function setLocal(fleet, name, wsl) {
  if (!fleet) return;
  if (name) fleet.localName = String(name);
  fleet.localWsl = wsl === true;
}

function selectedHost(fleet) {
  if (!fleet || !(fleet.selected > 0)) return null;
  var host = fleet.hosts[fleet.selected - 1];
  return host || null;
}

function ensureSession(fleet, host) {
  var sessions = fleet.sessions || {};
  fleet.sessions = sessions;
  var found = sessions[host.ssh];
  if (!found) {
    found = {
      name: host.name,
      ssh: host.ssh,
      phase: "idle",
      error: "",
      since: 0,
      lingerUntil: 0,
      retryAt: 0,
      samples: 0,
      wsl: false,
      os: "",
      generation: 0
    };
    sessions[host.ssh] = found;
  }
  found.name = host.name;
  return found;
}

function hostsSame(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  var i;
  for (i = 0; i < a.length; i++) {
    if (a[i].name !== b[i].name || a[i].ssh !== b[i].ssh) return false;
  }
  return true;
}

function stopSession(session) {
  session.phase = "idle";
  session.lingerUntil = 0;
  session.retryAt = 0;
  session.since = 0;
}

function applyConfig(fleet, parsed, now) {
  var next = (parsed && parsed.hosts) ? parsed.hosts : [];
  fleet.hint = !!(parsed && parsed.hint);
  var selectedSsh = "";
  if (fleet.selected > 0 && fleet.hosts && fleet.hosts[fleet.selected - 1]) {
    selectedSsh = fleet.hosts[fleet.selected - 1].ssh;
  }
  if (hostsSame(fleet.hosts, next)) return fleet;
  var keep = {};
  var i;
  for (i = 0; i < next.length; i++) keep[next[i].ssh] = true;
  var ssh;
  var sessions = fleet.sessions || {};
  for (ssh in sessions) {
    if (!Object.prototype.hasOwnProperty.call(sessions, ssh)) continue;
    if (!keep[ssh]) stopSession(sessions[ssh]);
  }
  fleet.hosts = [];
  for (i = 0; i < next.length; i++) {
    fleet.hosts.push({ name: next[i].name, ssh: next[i].ssh });
    ensureSession(fleet, next[i]);
  }
  // Selection follows the ssh alias. An index would point at a different
  // machine after a reorder or a removal.
  var found = 0;
  if (selectedSsh) {
    for (i = 0; i < fleet.hosts.length; i++) {
      if (fleet.hosts[i].ssh === selectedSsh) found = i + 1;
    }
  }
  fleet.selected = found;
  if (fleet.overview) setOverview(fleet, true, now || 0);
  if (found > 0) {
    var session = fleet.sessions[selectedSsh];
    if (session && session.phase === "idle") beginConnect(session, now || 0);
  }
  return fleet;
}

function beginConnect(session, now) {
  session.generation += 1;
  session.phase = "connecting";
  session.since = now;
  session.lingerUntil = 0;
  session.retryAt = 0;
  session.error = "";
}

function selectIndex(fleet, index, now) {
  var count = fleet.hosts ? fleet.hosts.length : 0;
  var next = Number(index);
  if (!isFinite(next) || next < 0) next = 0;
  if (next > count) next = count;
  next = Math.floor(next);
  if (next === fleet.selected) return fleet;
  var prev = fleet.selected;
  var prevSsh = null;
  if (prev > 0 && fleet.hosts[prev - 1]) {
    prevSsh = fleet.hosts[prev - 1].ssh;
    var prevSession = fleet.sessions[prevSsh];
    if (prevSession && (prevSession.phase === "connecting" || prevSession.phase === "connected" || prevSession.phase === "lingering")) {
      prevSession.phase = "lingering";
      prevSession.lingerUntil = now + LINGER_MS;
    }
  }
  // The host we just left lingers. The one we are opening stays up.
  // Any older linger stops, so only two collectors run.
  var nextSsh = null;
  if (next > 0 && fleet.hosts[next - 1]) nextSsh = fleet.hosts[next - 1].ssh;
  var i;
  for (i = 0; i < count; i++) {
    var other = fleet.sessions[fleet.hosts[i].ssh];
    if (!other || other.phase !== "lingering" || fleet.overviewLinger) continue;
    if (fleet.hosts[i].ssh === prevSsh || fleet.hosts[i].ssh === nextSsh) continue;
    stopSession(other);
  }
  fleet.selected = next;
  if (next > 0) {
    var host = fleet.hosts[next - 1];
    var session = ensureSession(fleet, host);
    if (session.phase === "lingering" || session.phase === "connected") {
      session.phase = session.samples > 0 ? "connected" : "connecting";
      session.lingerUntil = 0;
      session.retryAt = 0;
    } else if (session.phase !== "connecting") {
      beginConnect(session, now);
    }
  }
  return fleet;
}

function cycle(fleet, direction, now) {
  var count = (fleet.hosts ? fleet.hosts.length : 0) + 1;
  if (count < 1) count = 1;
  var step = direction < 0 ? -1 : 1;
  var next = fleet.selected + step;
  if (next < 0) next = count - 1;
  if (next >= count) next = 0;
  return selectIndex(fleet, next, now);
}

function tick(fleet, now) {
  var hosts = fleet.hosts || [];
  var i;
  for (i = 0; i < hosts.length; i++) {
    var session = fleet.sessions[hosts[i].ssh];
    if (!session) continue;
    var selected = fleet.overview || (fleet.activeSelected !== false && fleet.selected === i + 1);
    if (session.phase === "lingering" && session.lingerUntil && now >= session.lingerUntil) {
      stopSession(session);
      continue;
    }
    if (selected && (session.phase === "unreachable" || session.phase === "error") && session.retryAt && now >= session.retryAt) {
      beginConnect(session, now);
    }
  }
  if (fleet.overviewLinger && !fleet.overview) {
    var lingering = false;
    for (i = 0; i < hosts.length; i++) if (fleet.sessions[hosts[i].ssh] && fleet.sessions[hosts[i].ssh].phase === "lingering") lingering = true;
    if (!lingering) fleet.overviewLinger = false;
  }
  return fleet;
}

function classifyFailure(samples, code, line) {
  var text = String(line || "").toLowerCase();
  if (text.indexOf("command not found") >= 0 || text.indexOf("no such file") >= 0) return "error";
  if (text.indexOf("host key verification") >= 0) return "error";
  if (text.indexOf("permission denied") >= 0) return "error";
  if (samples > 0 && Number(code) === 0) return "error";
  return "unreachable";
}

function noteStderr(fleet, ssh, line) {
  var session = fleet.sessions && fleet.sessions[ssh];
  if (!session) return fleet;
  var clean = sanitizeError(line);
  if (clean) session.error = clean;
  return fleet;
}

function noteSample(fleet, ssh, generation, sample, now) {
  var session = fleet.sessions && fleet.sessions[ssh];
  if (!session) return false;
  if (Number(generation) !== Number(session.generation)) return false;
  if (session.phase !== "connecting" && session.phase !== "connected" && session.phase !== "lingering") return false;
  session.samples += 1;
  session.wsl = sampleWsl(sample);
  session.os = sample.os === "darwin" ? "macOS" : "";
  session.error = "";
  if (session.phase === "lingering") {
    // Still the background collector. The dot stays "connected".
    return true;
  }
  session.phase = "connected";
  session.since = now;
  return true;
}

function noteExit(fleet, ssh, generation, code, line, now) {
  var session = fleet.sessions && fleet.sessions[ssh];
  if (!session) return fleet;
  if (Number(generation) !== Number(session.generation)) return fleet;
  var clean = sanitizeError(line);
  if (!clean) clean = session.error || "";
  var selected = false;
  var host = selectedHost(fleet);
  if (fleet.overview || (fleet.activeSelected !== false && host && host.ssh === ssh)) selected = true;
  if (!selected) {
    stopSession(session);
    session.error = clean;
    return fleet;
  }
  session.phase = classifyFailure(session.samples, code, clean);
  session.error = clean;
  session.lingerUntil = 0;
  session.retryAt = now + RETRY_MS;
  session.since = now;
  return fleet;
}

function statusOf(session, now) {
  if (!session) return "";
  if (session.phase === "lingering") {
    return session.samples > 0 ? "connected" : "connecting";
  }
  if (session.phase === "connecting" && now && now - session.since >= 5000) return "connecting (slow link)";
  if (session.phase === "idle") return "";
  return session.phase;
}

function tabModel(fleet) {
  var tabs = [{
    name: fleet.localName || "this machine",
    remote: false,
    status: "connected",
    wsl: fleet.localWsl === true,
    os: fleet.localOs || "",
    ssh: ""
  }];
  var hosts = fleet.hosts || [];
  var i;
  for (i = 0; i < hosts.length; i++) {
    var session = fleet.sessions[hosts[i].ssh];
    tabs.push({
      name: hosts[i].name,
      remote: true,
      status: statusOf(session, Date.now()),
      wsl: !!(session && session.wsl),
      os: session ? session.os : "",
      ssh: hosts[i].ssh
    });
  }
  return tabs;
}

function desired(fleet) {
  var out = [];
  var hosts = fleet.hosts || [];
  var i;
  for (i = 0; i < hosts.length; i++) {
    var session = fleet.sessions[hosts[i].ssh];
    if (!session) continue;
    if (session.phase === "connecting" || session.phase === "connected" || session.phase === "lingering") {
      out.push({
        ssh: hosts[i].ssh,
        name: hosts[i].name,
        generation: session.generation
      });
    }
  }
  if (fleet.overview || fleet.overviewLinger) return out;
  if (out.length <= 2) return out;
  // Active first, then the linger with the latest deadline. Never more than two.
  var active = null;
  var linger = null;
  var host = selectedHost(fleet);
  for (i = 0; i < out.length; i++) {
    var session = fleet.sessions[out[i].ssh];
    if (host && out[i].ssh === host.ssh) active = out[i];
    else if (!linger || session.lingerUntil > fleet.sessions[linger.ssh].lingerUntil) linger = out[i];
  }
  var kept = [];
  if (active) kept.push(active);
  if (linger) kept.push(linger);
  return kept;
}

function setOverview(fleet, active, now) {
  var was = fleet.overview;
  fleet.overview = active;
  var hosts = fleet.hosts || [];
  var i;
  if (active) {
    fleet.overviewLinger = false;
    for (i = 0; i < hosts.length; i++) {
      var session = ensureSession(fleet, hosts[i]);
      if (session.phase === "idle") beginConnect(session, now);
      else if (session.phase === "lingering") { session.phase = session.samples ? "connected" : "connecting"; session.lingerUntil = 0; }
    }
  } else if (was) {
    fleet.overviewLinger = true;
    for (i = 0; i < hosts.length; i++) {
      var s = fleet.sessions[hosts[i].ssh];
      if (s && (s.phase === "connecting" || s.phase === "connected")) { s.phase = "lingering"; s.lingerUntil = now + LINGER_MS; }
    }
  }
  return fleet;
}

function overviewRows(fleet, localView, buckets) {
  var tabs = tabModel(fleet);
  return tabs.map(function(tab, i) {
    var bucket = tab.ssh && buckets ? buckets[tab.ssh] : null;
    return { name: tab.name, status: tab.status, badge: tab.wsl ? "WSL" : (tab.os || ""),
      index: i, view: i === 0 ? localView : (bucket ? bucket.view : null) };
  });
}

function reachMessage(fleet) {
  var host = selectedHost(fleet);
  if (!host) return { title: "", detail: "" };
  var session = fleet.sessions[host.ssh];
  if (!session) return { title: "", detail: "" };
  if (session.phase === "unreachable") {
    return { title: "Can't reach " + session.name, detail: session.error || "" };
  }
  if (session.phase === "error") {
    return { title: "Problem on " + session.name, detail: session.error || "" };
  }
  return { title: "", detail: "" };
}

function connectingName(fleet) {
  var host = selectedHost(fleet);
  if (!host) return "";
  var session = fleet.sessions[host.ssh];
  if (!session || session.phase !== "connecting") return "";
  return session.name || "";
}

// r on a remote tab drops the current ssh and starts a new generation.
function restartSelected(fleet, now) {
  var host = selectedHost(fleet);
  if (!host) return fleet;
  var session = ensureSession(fleet, host);
  beginConnect(session, now);
  return fleet;
}

var api = {
  setOverview: setOverview,
  overviewRows: overviewRows,
  LINGER_MS: LINGER_MS,
  RETRY_MS: RETRY_MS,
  hostsPath: hostsPath,
  validName: validName,
  validAlias: validAlias,
  sshArgv: sshArgv,
  sshCommand: sshCommand,
  groupCleanupCommand: groupCleanupCommand,
  parseHosts: parseHosts,
  sanitizeError: sanitizeError,
  sampleWsl: sampleWsl,
  createFleet: createFleet,
  setLocal: setLocal,
  applyConfig: applyConfig,
  selectIndex: selectIndex,
  cycle: cycle,
  tick: tick,
  noteSample: noteSample,
  noteExit: noteExit,
  noteStderr: noteStderr,
  classifyFailure: classifyFailure,
  tabModel: tabModel,
  desired: desired,
  reachMessage: reachMessage,
  connectingName: connectingName,
  statusOf: statusOf,
  selectedHost: selectedHost,
  restartSelected: restartSelected
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
