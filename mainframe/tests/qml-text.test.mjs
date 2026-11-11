import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

// Requiring plain text on every Text also covers future changes to literals.
// Ignore quoted strings and comments, then track braces so a nested object's
// textFormat cannot accidentally satisfy its parent.
function missingPlainText(source) {
  const masked = source.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\/[^\n]*|\/\*[\s\S]*?\*\//g,
    match => match.replace(/[^\n]/g, " "));
  const tokens = /\bText\s*\{|\btextFormat\s*:\s*Text\.PlainText\b|[{}]/g;
  const stack = [], missing = [];
  for (const match of masked.matchAll(tokens)) {
    const token = match[0];
    if (/^Text\s*\{/.test(token)) stack.push({ text: true, plain: false, at: match.index });
    else if (token === "{") stack.push({ text: false });
    else if (token === "}") {
      const object = stack.pop();
      if (object?.text && !object.plain) missing.push(source.slice(0, object.at).split("\n").length);
    } else if (stack.at(-1)?.text) stack.at(-1).plain = true;
  }
  return missing;
}

function qmlFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? qmlFiles(path) : entry.name.endsWith(".qml") ? [path] : [];
  });
}

test("QML Text lint catches missing and nested text formats", () => {
  assert.deepEqual(missingPlainText('Text { text: host.name }'), [1]);
  assert.deepEqual(missingPlainText('Text { Text { textFormat: Text.PlainText } }'), [1]);
  assert.deepEqual(missingPlainText('Text { text: "}"; textFormat: Text.PlainText }'), []);
});

test("all QML Text objects render as plain text", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const problems = qmlFiles(root).flatMap(path =>
    missingPlainText(readFileSync(path, "utf8")).map(line => `${path}:${line}`));
  assert.deepEqual(problems, []);
});

test("CPU card binds the temperature chart, colours and optional peak without changing card dimensions", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const source = readFileSync(join(root, "shell.qml"), "utf8");
  const cpu = source.slice(source.indexOf('objectName: "card-cpu"'), source.indexOf('id: coreArea'));
  assert.match(cpu, /Layout\.preferredHeight:\s*180/);
  assert.match(cpu, /Layout\.minimumHeight:\s*48/);
  assert.match(cpu, /samplesB:\s*shell\.cpuView\s*\?\s*shell\.cpuView\.tempHistory/);
  assert.match(cpu, /labelA:\s*"CPU"/);
  assert.match(cpu, /labelB:\s*"temp"/);
  assert.match(cpu, /unitB:\s*"°C"/);
  assert.match(cpu, /strokeColorB:\s*shell\.themeCyan/);
  assert.match(cpu, /yMin:\s*0[\s\S]*yMax:\s*100/);
  assert.match(cpu, /tempLevel === "hot"\s*\?\s*shell\.sensorColor/);
  assert.match(cpu, /tempLevel === "warm"\s*\?\s*Metrics\.qtColor\(shell\.themeColors\.yellow/);
  assert.match(cpu, /objectName: "cpu-temperature-peak"[\s\S]*?visible: text !== ""[\s\S]*?Layout\.fillWidth: true[\s\S]*?Layout\.minimumWidth: 0[\s\S]*?elide: Text\.ElideRight/);
  assert.equal((source.match(/unitB:\s*"°C"/g) || []).length, 1);
});

test("agent rows retain their alphabetical order", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const source = readFileSync(join(root, "shell.qml"), "utf8");
  const assignment = source.split('\n').find(line => line.includes('shell.agentRows = Agents.'));
  const shell = {settingsData:{settings:{showUnavailable:false}}};
  const Agents = {visible:(rows, show) => rows.filter(row => show || !row.unavailable), sorted:rows => rows.slice().sort((a, b) => a.name.localeCompare(b.name))};
  runInNewContext(assignment, {shell, Agents, rows:[{name:'Z'}, {name:'Hidden', unavailable:true}, {name:'A'}]});
  assert.deepEqual(shell.agentRows.map(row => row.name), ['A', 'Z']);
});

test("overview changes wait for settings and validate the first loaded view", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const source = readFileSync(join(root, "shell.qml"), "utf8");
  const setter = source.match(/function setOverviewView\(value\) \{[\s\S]*?\n  \}/)[0];
  const writes = [];
  const state = {overviewView:"systems", settingsLoaded:false, settingsData:{settings:{showUnavailable:false}},
    agentsVisible:false, saveConfig:(...args) => writes.push(args)};
  runInNewContext(`${setter}; setOverviewView("storage")`, state);
  assert.equal(state.overviewView, "storage");
  assert.deepEqual(writes, []);
  state.settingsLoaded = true;
  state.settingsData.settings.showUnavailable = true;
  runInNewContext(`${setter}; setOverviewView("storage")`, state);
  assert.equal(JSON.stringify(writes), '[["settings",{"overviewView":"storage","showUnavailable":true}]]');
  const firstLoad = source.split('\n').find(line => line.includes('if (!shell.settingsLoaded) { shell.settingsLoaded = true;'));
  for (const [saved, expected] of [["systems", "systems"], ["storage", "storage"], ["agents", "agents"], ["invalid", "systems"]]) {
    const shell = {settingsLoaded:false, smokeMode:false, overviewView:"agents", agentsVisible:false};
    runInNewContext(firstLoad, {shell, data:{settings:{overviewView:saved}}});
    assert.equal(shell.overviewView, expected);
    assert.equal(shell.settingsLoaded, true);
  }
});


test("slow connection refresh reaches five seconds without fleet updates", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const source = readFileSync(join(root, "shell.qml"), "utf8");
  const fn = source.match(/function refreshConnectingSlow\(\) \{[\s\S]*?\n  \}/)[0];
  const timer = source.match(/Timer \{\s*interval: 1000\s*repeat: true\s*running: !!shell.connectingTo\s*onTriggered: shell.refreshConnectingSlow\(\)/);
  assert.ok(timer);
  let now = 4999;
  const state = {fleet:{sessions:{remote:{since:0}}}, connectingTo:'remote', connectingSlow:false,
    Hosts:{selectedHost:() => ({ssh:'remote'})}, Date:{now:() => now}};
  runInNewContext(fn + '; refreshConnectingSlow()', state);
  assert.equal(state.connectingSlow, false);
  now = 5000;
  runInNewContext(fn + '; refreshConnectingSlow()', state);
  assert.equal(state.connectingSlow, true);
  state.connectingTo = '';
  runInNewContext(fn + '; refreshConnectingSlow()', state);
  assert.equal(state.connectingSlow, false);
});
