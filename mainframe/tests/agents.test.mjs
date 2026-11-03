import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const A = require('../lib/agents.js');
const H = require('../lib/hosts.js');
const now = Date.parse('2026-11-01T12:00:00Z');
test('empty, malformed and unknown schema files are independent', () => {
  const empty = A.parse('{}', 'empty.json', now);
  assert.equal(empty.name, 'empty.json'); assert.equal(empty.tokens, 0); assert.equal(empty.activity.length, 14);
  assert.equal(A.parse('{', 'bad.json', now).broken, true);
  assert.equal(A.parse('[]', 'bad.json', now).broken, true);
  const next = A.parse(JSON.stringify({schemaVersion:999, name:'Future', extra:{a:1}, todayTotalTokens:19}), 'x', now);
  assert.equal(next.name, 'Future'); assert.equal(next.tokens, 19); assert.equal(next.broken, false);
});
test('limit thresholds, reset, units and staleness', () => {
  const card = A.parse(JSON.stringify({updatedAt:'2026-11-01T09:59:59Z', limits:[{percent:79},{percent:80},{percent:95},{label:'no percent'}]}), 'x', now);
  assert.deepEqual(card.limits.map(x=>x.level), ['', 'Warning', 'Critical', '']);
  assert.equal(card.stale, true); assert.equal(A.age('2026-11-01T10:00:00Z', now).stale, false);
  assert.equal(A.age('bad', now).stale, true);
  assert.equal(A.reset('2026-11-01T13:30:00Z', now), 'resets in 1 h 30 min');
  assert.equal(A.reset('bad', now), ''); assert.equal(A.reset('2026-10-01T00:00:00Z', now), 'resets now');
  assert.equal(A.units(1200000), '1.2M');
});
test('sort, models, activity and help are safe', () => {
  assert.deepEqual(A.sorted([{name:'Z'},{name:'a'}]).map(x=>x.name), ['a','Z']);
  const c = A.parse(JSON.stringify({name:'a', authHelpText:'Bearer: secret123', recentDays:[{date:'2026-11-01',messageCount:3}], modelUsage:{m:{inputTokens:100,outputTokens:20,cacheReadInputTokens:8,cacheCreationInputTokens:2}}}), 'x', now);
  assert.equal(c.help, '[redacted]'); assert.equal(c.activity[13].count, 3); assert.equal(c.models[0].cache, 10);
});
test('redacts credentials in every displayed agent-file string', () => {
  const secrets = [
    'Authorization: Basic dXNlcjpwYXNz', 'Authorization: Bearer abc',
    'Authorization: Token x', 'Authorization: Custom q',
    'Authorization: Digest username="alice", response="abc def"',
    'key=abc', 'token=abc', 'secret=abc', 'password=abc', 'auth=abc', 'api_key="abc def"',
    'https://user:pass@example.com/path', 'https://example.com/?access_token=abc&ok=yes',
    'https://user:pa"ss@example.com/path', "https://user:pa'ss@example.com/path",
    'https://example.com/?auth=abc',
    'ab12cd34ef56gh78ij90', 'YWJjZGVmZ2hpamtsbW5v',
    'eyJabc.def.ghi', 'hf_abc', 'pk_abc', 'sk-abc', 'xai-abc', 'ghp_abc', 'gho_abc', 'github_pat_abc', 'AIzaabc',
    'Bearer abc123'
  ];
  for (const secret of secrets) {
    assert.equal(A.safeHelp(secret), '[redacted]', secret);
    assert.equal(A.safeHelp('Before ' + secret + ' after'), 'Before [redacted] after', secret);
  }
  assert.equal(A.safeHelp('Sign in to continue. Token usage is available.'), 'Sign in to continue. Token usage is available.');
  assert.equal(A.safeHelp('Sign in with grok login'), 'Sign in with grok login');
  assert.equal(A.safeHelp('Run claude /login to refresh'), 'Run claude /login to refresh');
  assert.equal(A.safeHelp('https://example.com/help'), 'https://example.com/help');
  const secret = 'Authorization: Basic dXNlcjpwYXNz';
  const card = A.parse(JSON.stringify({name:secret, tierLabel:secret, usageStatusText:secret, authHelpText:secret,
    limits:[{title:secret}], modelUsage:{[secret]:{}}, todayTokensByModel:{'token=abc':5}}), 'x', now);
  assert.deepEqual([card.name, card.tier, card.status, card.help, card.limits[0].label, ...card.models.map(x => x.name)], Array(7).fill('[redacted]'));
  assert.equal(A.parse('{', 'password=abc', now).name, '[redacted]');
  assert.equal(A.safeHelp('x '.repeat(99) + 'token=abc'), ('x '.repeat(99) + '[redacted]').slice(0, 200));
});

test('fails closed when targeted redaction leaves a credential pattern', () => {
  for (const secret of [
    'key_abcdefgh', 'token-abcdefgh', 'sk_abcdefgh', 'pk-abcdefgh',
    'user:pass@example.com', 'user:pa"ss@example.com',
  ]) {
    assert.equal(A.safeHelp('Before token=abc and ' + secret + ' after'), '[redacted]', secret);
  }
  assert.equal(A.safeHelp('Before ?auth='), '[redacted]');
  assert.equal(A.safeHelp('Before &auth='), '[redacted]');
  assert.equal(A.safeHelp('x '.repeat(101) + 'key_abcdefgh'), '[redacted]');
});

test('handles long credential-like strings promptly', () => {
  for (const text of ['key-'.repeat(20000), 'key-'.repeat(1000)]) {
    const start = performance.now();
    assert.equal(A.safeHelp(text), '[redacted]');
    assert.ok(performance.now() - start < 200);
  }
});

test('overview sessions survive the full linger, are reused, and all stop on expiry', (t) => {
  t.mock.timers.enable({apis: ['Date'], now: 1000});
  const f = H.createFleet('local');
  const names = ['a', 'b', 'c', 'd'];
  H.applyConfig(f, H.parseHosts(JSON.stringify({hosts:names.map(x=>({name:x,ssh:x}))}), false), Date.now());
  H.setOverview(f, true, Date.now());
  for (const name of names) H.noteSample(f, name, f.sessions[name].generation, {}, Date.now());
  const original = H.desired(f).map(x => [x.ssh, x.generation]);
  f.activeSelected = false;
  H.setOverview(f, false, Date.now());
  t.mock.timers.tick(59999); H.tick(f, Date.now());
  assert.deepEqual(H.desired(f).map(x => [x.ssh, x.generation]), original);
  H.setOverview(f, true, Date.now());
  assert.deepEqual(H.desired(f).map(x => [x.ssh, x.generation]), original);
  assert.ok(names.every(name => f.sessions[name].phase === 'connected'));
  H.setOverview(f, false, Date.now());
  t.mock.timers.tick(59999); H.tick(f, Date.now());
  assert.deepEqual(H.desired(f).map(x => [x.ssh, x.generation]), original);
  t.mock.timers.tick(1); H.tick(f, Date.now());
  assert.deepEqual(H.desired(f), []);
  assert.ok(names.every(name => f.sessions[name].phase === 'idle'));
  assert.equal(f.overviewLinger, false);
});
test('overview starts all hosts, isolates failures and lingers all after exit', () => {
  const f = H.createFleet('local');
  H.applyConfig(f, H.parseHosts(JSON.stringify({hosts:['a','b','c'].map(x=>({name:x,ssh:x}))}),false), 1000);
  H.setOverview(f,true,1000); assert.equal(H.desired(f).length,3);
  H.noteExit(f,'b',f.sessions.b.generation,1,'unreachable',2000);
  assert.equal(f.sessions.b.phase,'unreachable'); assert.equal(H.desired(f).length,2);
  H.noteSample(f,'a',f.sessions.a.generation,{os:'darwin'},2000);
  const rows = H.overviewRows(f, {cpu:{percent:3}}, {a:{view:{cpu:{percent:8}}}});
  assert.equal(rows.length,4); assert.equal(rows[1].badge,'macOS'); assert.equal(rows[1].view.cpu.percent,8); assert.equal(rows[2].status,'unreachable');
  H.setOverview(f,false,3000); f.activeSelected = false;
  assert.equal(H.desired(f).length,2); H.tick(f,62999); assert.equal(H.desired(f).length,2);
  H.tick(f,63000); assert.equal(H.desired(f).length,0);
});

test('leaving overview for a host preserves every other collector until its deadline', () => {
  const f = H.createFleet('local');
  H.applyConfig(f, H.parseHosts(JSON.stringify({hosts:['a','b','c'].map(x=>({name:x,ssh:x}))}),false), 1000);
  H.setOverview(f,true,1000);
  for (const ssh of ['a','b','c']) H.noteSample(f,ssh,f.sessions[ssh].generation,{},2000);
  H.setOverview(f,false,3000); H.selectIndex(f,1,3000);
  assert.equal(H.desired(f).length,3);
  H.tick(f,63000); assert.deepEqual(H.desired(f).map(x=>x.ssh), ['a']);
  assert.equal(f.overviewLinger,false);
});

test('conditional login help follows status, availability, and limits', () => {
  const record = {name:'bob@', sharedStatsWith:'alice@', limits:[{percent:42}], authHelpText:'Run claude auth login'};
  let card = A.parse(JSON.stringify(record), 'account', now);
  assert.equal(card.help, '');
  card = A.parse(JSON.stringify({...record, usageStatusText:'Sign-in expired'}), 'account', now);
  assert.equal(card.help, 'Run claude auth login');
  assert.equal(A.parse(JSON.stringify({...record, ready:false}), 'account', now).help, 'Run claude auth login');
  assert.equal(A.parse(JSON.stringify({...record, limits:[], todayPrompts:1}), 'account', now).help, 'Run claude auth login');
});

test('shared projects folder name is exposed to the card', () => {
  const card = A.parse(JSON.stringify({sharedStatsWith:'alice@'}), 'account', now);
  assert.equal(card.sharedStatsWith, 'alice@');
});

test('sections group providers and sort the exact cards', () => {
  const records = [
    {name:'bob@', provider:'Claude'}, {name:'Grok', id:'bob-grok'},
    {name:'ElevenLabs', id:'bob-elevenlabs'}, {name:'Unknown', id:'mystery'},
    {name:'Codex', provider:'codex'}, {name:'Higgsfield', id:'bob-higgsfield'},
    {name:'Image custom', category:'ImAgE'}, {name:'alice@', provider:'claude'},
  ];
  const sections = A.sections(records.map(record => A.parse(JSON.stringify(record), 'fixture', now)));
  assert.deepEqual(sections.map(section => section.heading), ['Language models', 'Video', 'Image', 'Voice', 'Other']);
  assert.deepEqual(sections.map(section => section.cards.map(card => card.name)), [
    ['alice@', 'bob@', 'Codex', 'Grok'], ['Higgsfield'], ['Image custom'], ['ElevenLabs'], ['Unknown']
  ]);
  assert.equal(A.category({provider:'unknown', id:'user-higgsfield', name:'Claude'}), 'video');
  assert.equal(A.category({provider:'Claude', category:'VOICE'}), 'voice');
  assert.equal(A.category({name:'notclaude'}), 'other');
  assert.deepEqual(A.sections([]), []);
});

test('local statistics are hidden only when explicitly absent and empty', () => {
  const card = record => A.parse(JSON.stringify(record), 'fixture', now);
  assert.equal(card({hasLocalStats:false, limits:[{percent:3}], tierLabel:'Pro'}).showLocalStats, false);
  assert.equal(card({hasLocalStats:false, todayPrompts:1}).showLocalStats, true);
  assert.equal(card({hasLocalStats:false, todaySessions:1}).showLocalStats, true);
  assert.equal(card({hasLocalStats:false, todayTotalTokens:1}).showLocalStats, true);
  assert.equal(card({hasLocalStats:false, recentDays:[{messageCount:1}]}).showLocalStats, true);
  assert.equal(card({}).showLocalStats, true);
});


test('hidden shared stats owner leaves visible card stats intact', () => {
  const owner = {name:'owner', unavailable:true};
  const card = {name:'card', unavailable:false, sharedStatsWith:'owner', prompts:42, models:[{name:'model'}]};
  assert.deepEqual(A.visible([owner, card], false), [{...card, sharedStatsWith:''}]);
  assert.equal(A.visible([owner, card], true)[1].sharedStatsWith, 'owner');
  assert.equal(card.sharedStatsWith, 'owner');
});

test('category recognizes provider in full account id', () => {
  assert.equal(A.category({id:'claude-work'}), 'llm');
  assert.equal(A.category({id:'claude_work'}), 'llm');
  assert.equal(A.category({id:'notclaude_work'}), 'other');
});
