import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {summarize, remember, relativeDir, normalizeAccounts, buildEntries} = createRequire(import.meta.url)('../lib/live_agents.js');
const now = 1000000;
const session = (provider, dir, billing=null, interactive=true) => ({provider, dir, billing, interactive});
const entry = (host, sessions, extra={}) => ({host, receivedMs:now, live:{at:now/1000, supported:true, sessions}, ...extra});
test('local receipt time controls freshness', () => {
  const result = summarize([entry('past', [], {live:{at:1,supported:true,sessions:[]}}), entry('future', [], {live:{at:1e15,supported:true,sessions:[]}}), entry('stale',[],{receivedMs:now-61000}), entry('offline',[],{status:'unreachable'})], [], now);
  assert.equal(result.reporting, 2); assert.equal(result.hosts[2].status, 'not reporting');
});
test('account attribution is local unless a remote override is set', () => {
  const accounts = [{id:'work',name:'Work',provider:'claude',dir:'~/.claude'}];
  const result = summarize([entry('local',[session('claude','~/.claude')],{local:true}), entry('remote',[session('claude','~/.claude')]), entry('mapped',[session('claude','~/.claude')],{accountMap:{'~/.claude':'work'}}), entry('unknown',[session('claude',null),session('codex',null)])],accounts,now);
  assert.equal(result.hosts[0].sessions[0].account,'Work');
  assert.equal(result.hosts[1].sessions[0].account,'~/.claude · remote');
  assert.equal(result.hosts[2].sessions[0].account,'Work');
  assert.deepEqual(result.hosts[3].sessions.map(x=>x.account),['unknown claude · unknown','unknown codex · unknown']);
  assert.equal(result.accounts.find(x=>x.label === 'Work').count, 2);
});
test('account IDs and billing types stay distinct when names match', () => {
  const accounts = [{id:'one',name:'Shared',provider:'claude',dir:'~/.claude'},
    {id:'two',name:'Shared',provider:'claude',dir:'~/.other'},
    {id:'wrong',name:'Wrong',provider:'codex',dir:'~/.codex'}];
  const result = summarize([
    entry('local',[session('claude','~/.claude','api'), session('claude','~/.other')],{local:true}),
    entry('override',[session('claude','~/.claude','api')],{local:true,accountMap:{'~/.claude':'two'}}),
    entry('mismatch',[session('claude','~/.claude','api')],{accountMap:{'~/.claude':'wrong'}}),
    entry('fallback',[session('claude','~/.claude')],{local:true,accountMap:{'~/.claude':'wrong'}})
  ], accounts, now);
  assert.deepEqual(result.hosts.map(x=>x.sessions.map(s=>s.account)), [['Shared (API key)','Shared'],['Shared (API key)'],['claude API key'],['Shared']]);
  assert.deepEqual(result.accounts.filter(x=>x.label === 'Shared').map(x=>x.count).sort(), [1,1]);
  assert.deepEqual(result.accounts.filter(x=>x.label === 'Shared (API key)').map(x=>x.count).sort(), [1,1]);
  assert.equal(result.accounts.find(x=>x.label === 'claude API key').count, 1);
});
test('mapped account groups separate API billing from unknown across hosts', () => {
  const accounts = [{id:'work',name:'Work',provider:'claude',dir:'~/.claude'}];
  const result = summarize([
    entry('local',[session('claude','~/.claude'),session('claude','~/.claude','api')],{local:true}),
    entry('remote',[session('claude','~/.claude','api'),session('claude','~/.claude','subscription')],{accountMap:{'~/.claude':'work'}})
  ],accounts,now);
  assert.deepEqual(result.accounts, [
    {label:'Work',provider:'claude',count:2,billing:null},
    {label:'Work (API key)',provider:'claude',count:2,billing:'api'}
  ]);
});
test('account directories and mapping keys normalize dot segments and trailing slashes', () => {
  const accounts = [{id:'work',name:'Work',provider:'claude',dir:'~/.claude/./'}];
  const result = summarize([
    entry('local',[session('claude','~/.claude/')],{local:true}),
    entry('remote',[session('claude','~/./.claude/./')],{accountMap:{'~/.claude/':'work'}}),
    entry('other',[session('claude','~/.claude')],{accountMap:{'~/./.claude/./':'work'}})
  ],accounts,now);
  assert.equal(result.accounts.length,1);
  assert.equal(result.accounts[0].count,3);
  assert.deepEqual(result.hosts.map(x=>x.sessions[0].account),['Work','Work','Work']);
});
test('failed probes do not report zero and unmapped directories stay per host', () => {
  const result = summarize([entry('one',[session('claude','~/.claude')]), entry('two',[session('claude','~/.claude')]), entry('failed',[],{live:{supported:false,sessions:[]}})], [], now);
  assert.equal(result.reporting,2); assert.equal(result.total,2);
  assert.equal(result.hosts[2].status,'not reporting');
  assert.deepEqual(result.accounts.map(x=>x.label),['~/.claude · one','~/.claude · two']);
  const sameName = summarize([entry('Laptop',[session('claude','~/.claude')],{alias:'one'}), entry('Laptop',[session('claude','~/.claude')],{alias:'two'})], [], now);
  assert.equal(sameName.accounts.length,2);
});
test('wiring uses current generation, configured hosts, local status and actual home', () => {
  assert.equal(relativeDir('/srv/person/.claude','/srv/person'), '~/.claude');
  assert.equal(relativeDir('/home/other/.claude','/srv/person'), '/home/other/.claude');
  assert.equal(relativeDir('/srv/person2/.claude','/srv/person'), '/srv/person2/.claude');
  const accounts = normalizeAccounts([{dir:'/srv/person/.claude'}], '/srv/person');
  assert.equal(accounts[0].dir, '~/.claude');
  const hosts = [{name:'Laptop',ssh:'a'}, {name:'Offline',ssh:'b'}];
  const report = {generation:2, receivedMs:now, live:{supported:true,sessions:[]}};
  let entries = buildEntries(hosts, {a:{generation:3,phase:'ready'}}, [{ssh:'a',agentCap:4,agentAccounts:{'~/.claude':'work'}}], null, report, {a:report}, true);
  assert.equal(entries[0].status,'unreachable'); assert.equal(entries[0].cap,undefined);
  assert.equal(entries[1].live,null); assert.equal(entries[1].cap,4); assert.equal(entries[1].accountMap['~/.claude'],'work');
  assert.equal(entries[2].status,'unreachable');
  entries = buildEntries(hosts, {a:{generation:2,phase:'ready'}}, [], {localAgentCap:2}, report, {a:report}, false);
  assert.equal(entries[1].live,report.live); assert.equal(entries[0].status,''); assert.equal(entries[0].cap,2);
});
test('untrusted sessions cannot corrupt aggregation', () => {
  const rows = [session('__proto__',{},123,{}), session('constructor',42,{},2), {provider:'claude',project:{},rss:-1,age_s:Infinity,pid:'2'}];
  const result = summarize([entry('host',rows), entry('bad',[],{live:'bad'}), entry('malformed',[null, session('claude',null), []])],[],now);
  assert.equal(result.reporting,2); assert.equal(result.total,4); assert.equal(result.hosts[1].status,'not reporting');
  assert.equal(result.hosts[2].status,'reporting'); assert.equal(result.hosts[2].invalid,2); assert.equal(result.hosts[2].count,1);
  assert.equal(result.hosts[0].sessions[0].provider,'unknown');
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
