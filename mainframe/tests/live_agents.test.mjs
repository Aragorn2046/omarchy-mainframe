import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {summarize} = createRequire(import.meta.url)('../lib/live_agents.js');
const now = 1000000;
const session = (provider, dir, billing='subscription', interactive=true) => ({provider, dir, billing, interactive});
const entry = (host, sessions, extra={}) => ({host, live:{at:now/1000, supported:true, sessions}, ...extra});
test('fleet excludes stale and unreachable, counts capacity and headless', () => {
  const result = summarize([entry('laptop', [session('claude', null), session('codex', null, null, false)], {cap:1}), entry('stale', [], {live:{at:1,supported:true,sessions:[session('grok',null)]}}), entry('offline',[session('grok',null)], {status:'unreachable'})], [], now);
  assert.equal(result.total, 2); assert.equal(result.reporting, 1); assert.equal(result.hostsTotal, 3);
  assert.equal(result.hosts[0].headless, 1); assert.equal(result.hosts[0].over, true);
  assert.equal(result.hosts[1].status, 'not reporting'); assert.equal(result.hosts[2].count, 0);
});
test('account precedence, API separation and sorting', () => {
  const accounts = [{id:'override',name:'Work',provider:'claude',dir:'~/.other'}, {id:'match',name:'Matched',provider:'claude',dir:'/home/example/.claude'}];
  const rows = [session('claude','~/.claude'), session('claude','~/.claude'), session('claude','~/.missing'), session('claude',null), session('claude','~/.claude','api'), session('codex',null)];
  let result = summarize([entry('laptop',rows,{accountMap:{'~/.claude':'override'}})], accounts, now);
  assert.deepEqual(result.accounts.map(x=>[x.label,x.count]), [['Work',2],['claude API key',1],['unknown',1],['unknown',1],['~/.missing',1]].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])));
  assert.equal(result.providers[0].provider, 'claude'); assert.equal(result.accounts.find(x=>x.label==='claude API key').billing,'api');
  result = summarize([entry('laptop',[session('claude','~/.claude')])], accounts, now);
  assert.equal(result.accounts[0].label, 'Matched');
});
