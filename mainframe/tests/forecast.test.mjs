import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const F = require('../lib/forecast.js');
const A = require('../lib/agents.js');
process.env.TZ = 'Europe/Amsterdam';
const now = Date.parse('2026-11-09T09:00:00Z'); // Monday, 10:00 local
const h = 3600000;
const history = (hours, rise) => [[now / 1000 - hours * 3600, 20], [now / 1000, 20 + rise]];
const limit = (overrides = {}) => ({label:'Weekly (7-day)', percent:40, resetsAt:new Date(now + 5 * 24 * h).toISOString(), history:history(3, 6), ...overrides});
test('window labels are parsed case insensitively', () => {
  for (const [label, hours] of [['5-hour',5],['5H',5],['session',5],['Week',168],['7-day',168],['7d',168],['Daily',24],['24-hour',24],['Month',720],['30-day',720],['unknown',null]]) assert.equal(F.windowHours(label), hours);
});
test('recent pace beats window average and gives weekday in local time', () => {
  assert.deepEqual(F.forecast(limit({history:history(3, 2.4)}), now), {kind:'full', text:'at this pace full Thu 13:00', warn:true});
  assert.equal(new Date('2026-11-12T12:00:00Z').getDay(), 4);
});
test('minimum recent span and window average thresholds', () => {
  assert.equal(F.forecast(limit({label:'unknown', resetsAt:null, history:history(2.99, 6)}), now), null);
  assert.ok(F.forecast(limit({label:'unknown', resetsAt:null, history:history(3, 6)}), now));
  assert.ok(F.forecast(limit({label:'session', resetsAt:null, history:history(0.5, 10)}), now));
  assert.equal(F.forecast(limit({label:'daily', resetsAt:new Date(now + 22*h).toISOString(), history:[]}), now), null);
  assert.ok(F.forecast(limit({label:'daily', resetsAt:new Date(now + 21*h).toISOString(), history:[]}), now));
});
test('end projection rounds to five and caps at 99', () => {
  assert.deepEqual(F.forecast(limit({percent:40, resetsAt:new Date(now+10*h).toISOString(), history:history(3, 6)}),now), {kind:'ends',text:'on pace for ~60%',warn:false});
  assert.equal(F.forecast(limit({percent:80, resetsAt:new Date(now+9.9*h).toISOString(), history:history(3, 6)}),now).text, 'on pace for ~99%');
});
test('unknown reset, full bar, past reset and zero pace', () => {
  assert.equal(F.forecast(limit({resetsAt:null}),now).kind, 'full');
  assert.equal(F.forecast(limit({resetsAt:null, history:history(3, 0.1)}),now),null);
  assert.equal(F.forecast(limit({percent:100}),now),null);
  assert.equal(F.forecast(limit({resetsAt:new Date(now-h).toISOString()}),now),null);
  assert.equal(F.forecast(limit({percent:0, history:[], resetsAt:null}),now),null);
});
test('time format uses calendar days and English names', () => {
  assert.equal(F.when(now+4*h,now),'today 14:00');
  assert.equal(F.when(now+23*h,now),'tomorrow 09:00');
  assert.equal(F.when(now+3*24*h+4*h,now),'Thu 14:00');
  assert.equal(F.when(now+8*24*h+4*h,now),'17 Nov 14:00');
});
test('parser filters malformed history and passes raw reset', () => {
  const raw = limit({label:'unknown', resetsAt:null, history:[null,[1],[1,'2'],[1,2,3],...history(3,6)]});
  const result = A.parse(JSON.stringify({limits:[raw]}),'record',now).limits[0];
  assert.deepEqual(result.history,history(3,6));
  assert.equal(result.resetsAt,null); assert.equal(result.forecast.kind,'full');
  const many = A.parse(JSON.stringify({limits:[{history:Array.from({length:210},(_, i)=>[i,i])}]}),'record',now).limits[0];
  assert.equal(many.history.length,200); assert.equal(many.history[0][0],10);
});
