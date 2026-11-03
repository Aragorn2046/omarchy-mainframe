import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, statSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {runInNewContext} from 'node:vm';
const require = createRequire(import.meta.url);
const N = require('../lib/navigation.js'), A = require('../lib/agents.js'), M = require('../lib/metrics.js'), H = require('../lib/hosts.js'), S = require('../lib/fleet_storage.js');
test('settings read errors appear as plain text', () => {
  const shell = readFileSync(resolve('mainframe/shell.qml'), 'utf8');
  const statement = shell.split('\n').find(line => line.includes('if (data.errors && Object.keys(data.errors).length)'));
  assert.ok(statement);
  const settingsOverlay = {message:''};
  runInNewContext(statement, {data:{errors:{hosts:'hosts.json: Invalid machine name'}}, settingsOverlay});
  assert.equal(settingsOverlay.message, 'hosts.json: Invalid machine name');
  assert.match(readFileSync(resolve('mainframe/SettingsOverlay.qml'), 'utf8'), /textFormat: Text\.PlainText; text: root\.message/);
});
test('overview navigation keys and cycling', () => {
  assert.equal(N.key('systems','d'), 'storage'); assert.equal(N.key('storage','a'), 'agents');
  assert.equal(N.key('agents','Tab'), 'systems'); assert.equal(N.key('systems','Tab',true), 'agents');
});
test('slow connection is visible without changing retry policy', () => {
  assert.equal(H.statusOf({phase:'connecting', since:100}, 5099), 'connecting');
  assert.equal(H.statusOf({phase:'connecting', since:100}, 5100), 'connecting (slow link)');
  assert.equal(H.RETRY_MS,30000);
});
test('WSL host memory merges or falls back', () => {
  const sample = {wsl:true, mem:{total:1000,used:400,available:600,cached:800,swapUsed:0,swapTotal:0}, windows:{total:2000,used:1000,cpu:32}, filesystems:[]};
  let view = M.step(M.emptyState(),sample,1000).view;
  assert.equal(view.mem.fraction,0.5); assert.equal(view.mem.wslFraction,0.2); assert.match(view.mem.wslText,/WSL/); assert.equal(view.cpu.windowsText,'Windows 32%');
  assert.equal(view.mem.cacheFraction,0); assert.equal(view.mem.headerText,'1000 B used · — cache / 1.95 KB');
  sample.windows = null; view = M.step(M.emptyState(),sample,1000).view;
  assert.equal(view.mem.fraction,0.4); assert.equal(view.mem.windowsUnavailable,true);
  assert.equal(view.mem.cacheFraction,0.6); assert.equal(view.mem.headerText,'400 B used · 800 B cache / 1000 B');
});
test('memory bar renders the WSL share and bounds all segments', () => {
  const sample = {wsl:true, mem:{total:1000,used:400,available:600,cached:800}, windows:{total:2000,used:1000}, filesystems:[]};
  const mem = M.step(M.emptyState(),sample,1000).view.mem;
  const source = readFileSync(resolve('mainframe/shell.qml'), 'utf8');
  const wsl = source.match(/Rectangle \{\s*id: wslSegment([\s\S]*?)\n              \}/)?.[1];
  assert.ok(wsl);
  assert.match(wsl, /anchors\.right: parent\.right/);
  assert.match(wsl, /anchors\.rightMargin: parent\.width \* \(1 - parent\.fraction\)/);
  assert.match(wsl, /color: shell\.themeCyan/);
  const binding = (block, name) => {
    const expression = block.match(new RegExp(`^\\s*${name}: (.+)$`, 'm'))?.[1];
    assert.ok(expression, `missing ${name} binding`);
    return expression;
  };
  const visible = binding(wsl, 'visible');
  const wslFraction = binding(wsl, 'property real segmentFraction');
  const wslWidth = binding(wsl, 'width');
  const cache = source.match(/Rectangle \{\s*x: parent\.width \* parent\.shown([\s\S]*?)\n              \}/)?.[1];
  assert.ok(cache);
  const cacheWidth = binding(cache, 'width');
  for (const view of [mem, {...mem, fraction:0.9, wslFraction:0.8, cacheFraction:0.5}, {...mem, fraction:0.4, wslFraction:0.3, cacheFraction:0.9}]) {
    const parent = {width:100, shown:view.fraction, fraction:view.fraction};
    const shell = {memView:view};
    const isVisible = runInNewContext(visible, {parent, shell});
    const segmentFraction = runInNewContext(wslFraction, {parent, shell, visible:isVisible});
    const renderedWslWidth = runInNewContext(wslWidth, {parent, segmentFraction});
    const width = runInNewContext(cacheWidth, {parent, shell, wslSegment:{segmentFraction}});
    assert.ok(isVisible && renderedWslWidth > 0);
    assert.ok(parent.shown + renderedWslWidth / parent.width + width / parent.width <= 1 + Number.EPSILON);
  }
});
test('memory cache segment is capped and missing cache is empty', () => {
  const sample = {mem:{total:1000,used:400,available:600,cached:900,swapUsed:0,swapTotal:0},filesystems:[]};
  let mem = M.step(M.emptyState(),sample,1000).view.mem;
  assert.equal(mem.fraction,0.4); assert.equal(mem.cacheFraction,0.6);
  assert.equal(mem.headerText,'400 B used · 900 B cache / 1000 B');
  sample.mem.cached = null;
  mem = M.step(M.emptyState(),sample,1000).view.mem;
  assert.equal(mem.cacheFraction,0); assert.equal(mem.headerText,'400 B used · — cache / 1000 B');
  sample.os = 'darwin'; sample.mem.cached = 100;
  mem = M.step(M.emptyState(),sample,1000).view.mem;
  assert.equal(mem.cacheFraction,0.1); assert.equal(mem.headerText,'400 B used · 100 B cache / 1000 B');
});
test('storage thresholds and precise agent percentages', () => {
  assert.equal(S.cue(84,100).label,''); assert.equal(S.cue(85,100).symbol,'!'); assert.equal(S.cue(95,100).symbol,'!!');
  assert.equal(A.percent(0.3),'0.3%'); assert.equal(A.percent(0.01),'0.1%'); assert.equal(A.percent(0),'0%');
  const records=[A.parse('{"ready":false,"usageStatusText":"unavailable"}','x',Date.now()), A.parse('{"updatedAt":"2026-11-01T00:00:00Z","limits":[{"percent":0}]}','y',Date.now())];
  assert.equal(A.visible(records,false).length,1); assert.equal(A.visible(records,true).length,2);
});
test('validated atomic settings and account configuration', async () => {
  const dir=mkdtempSync(join(tmpdir(),'mf16-node-'));
  try {
    const env={...process.env, XDG_CONFIG_HOME:dir, XDG_CACHE_HOME:join(dir,'cache')};
    const run=(obj)=>new Promise((resolveResult,reject)=>{ const p=spawn('python3',[resolve('mainframe/config_manager.py'),'write'],{env,stdio:['pipe','ignore','ignore']}); p.on('error',reject); p.on('exit',status=>resolveResult({status})); p.stdin.end(JSON.stringify(obj)); });
    const accounts={accounts:[{id:'claude-bob', provider:'claude', name:'bob@', dir:'~/.claude-accounts/bob'},{id:'api',provider:'command',name:'API',command:['/bin/true']}]};
    assert.equal((await run({kind:'accounts',data:accounts})).status,0);
    const file=join(dir,'mainframe/accounts.json'); assert.deepEqual(JSON.parse(readFileSync(file,'utf8')),accounts); assert.equal(statSync(file).mode & 0o777,0o600);
    assert.equal((await run({kind:'accounts',data:{accounts:[{id:'../bad',provider:'command',name:'x',command:['x']}]}})).status,1);
    assert.deepEqual(JSON.parse(readFileSync(file,'utf8')),accounts);
    assert.equal((await run({kind:'hosts',data:{hosts:[{name:'bad',ssh:'-oProxyCommand'}]}})).status,1);
    assert.equal((await run({kind:'settings',data:{overviewView:'storage',showUnavailable:true}})).status,0);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
