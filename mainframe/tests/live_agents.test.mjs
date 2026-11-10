import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {summarize, remember} = createRequire(import.meta.url)('../lib/live_agents.js');
const now = 1000000;
const session = (provider, dir, billing='subscription', interactive=true) => ({provider, dir, billing, interactive});
const entry = (host, sessions, extra={}) => ({host, receivedMs:now, live:{at:now/1000, supported:true, sessions}, ...extra});
test('local receipt time controls freshness', () => {
  const result = summarize([entry('past', [], {live:{at:1,supported:true,sessions:[]}}), entry('future', [], {live:{at:1e15,supported:true,sessions:[]}}), entry('stale',[],{receivedMs:now-61000}), entry('offline',[],{status:'unreachable'})], [], now);
  assert.equal(result.reporting, 2); assert.equal(result.hosts[2].status, 'not reporting');
});
test('account attribution is local unless a remote override is set', () => {
  const accounts = [{id:'work',name:'Work',provider:'claude',dir:'~/.claude'}];
  const result = summarize([entry('local',[session('claude','~/.claude')],{local:true}), entry('remote',[session('claude','~/.claude')]), entry('mapped',[session('claude','~/.claude')],{accountMap:{'~/.claude':'work'}}), entry('unknown',[session('claude',null),session('codex',null)])],accounts,now);
  assert.equal(result.hosts[0].sessions[0].account,'Work');
  assert.equal(result.hosts[1].sessions[0].account,'~/.claude');
  assert.equal(result.hosts[2].sessions[0].account,'Work');
  assert.deepEqual(result.hosts[3].sessions.map(x=>x.account),['unknown claude','unknown codex']);
});
test('untrusted sessions cannot corrupt aggregation', () => {
  const rows = [session('__proto__',{},123,{}), session('constructor',42,{},2), {provider:'claude',project:{},rss:-1,age_s:Infinity,pid:'2'}];
  const result = summarize([entry('host',rows), entry('bad',[],{live:'bad'}), entry('malformed',[null])],[],now);
  assert.equal(result.reporting,1); assert.equal(result.total,3); assert.equal(result.hosts[1].status,'not reporting');
  assert.equal(result.hosts[2].status,'not reporting'); assert.equal(result.hosts[0].sessions[0].provider,'unknown');
  assert.equal(result.hosts[0].sessions[0].dir,null); assert.equal(result.hosts[0].sessions[2].rss,null);
  assert.equal(Object.prototype.count,undefined);
});
test('truncated reports mark totals and capacity', () => {
  const result = summarize([entry('host',Array.from({length:300},()=>session('codex',null)),{cap:256,live:{supported:true,truncated:true,sessions:Array.from({length:300},()=>session('codex',null))}})],[],now);
  assert.equal(result.total,256); assert.equal(result.hosts[0].sessions.length,256); assert.equal(result.truncated,true); assert.equal(result.hosts[0].over,true);
});
test('remember retains earlier reports and records local arrival time', () => {
  let store = remember({}, 'host', {at:1}, now, 2);
  store = remember(store, 'other', {}, now+5, 3);
  assert.equal(store.host.receivedMs,now); assert.equal(store.host.generation,2); assert.equal(store.other.receivedMs,now+5);
});
