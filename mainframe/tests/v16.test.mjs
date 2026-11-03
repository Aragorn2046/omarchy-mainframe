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
  const sample = {wsl:true, mem:{total:1000,used:400,available:600,cached:0,swapUsed:0,swapTotal:0}, windows:{total:2000,used:1000,cpu:32}, filesystems:[]};
  let view = M.step(M.emptyState(),sample,1000).view;
  assert.equal(view.mem.fraction,0.5); assert.equal(view.mem.wslFraction,0.2); assert.match(view.mem.wslText,/WSL/); assert.equal(view.cpu.windowsText,'Windows 32%');
  sample.windows = null; view = M.step(M.emptyState(),sample,1000).view;
  assert.equal(view.mem.fraction,0.4); assert.equal(view.mem.windowsUnavailable,true);
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
