import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const runFile = promisify(execFile);
const require = createRequire(import.meta.url);
const F = require('../lib/forecast.js');
const A = require('../lib/agents.js');
const now = Date.parse('2026-11-09T09:00:00Z'); // Monday, 10:00 local
const h = 3600000;
const history = (hours, rise) => [[now / 1000 - hours * 3600, 20], [now / 1000, 20 + rise]];
const limit = (overrides = {}) => ({label:'Weekly (7-day)', percent:40, resetsAt:new Date(now + 5 * 24 * h).toISOString(), history:history(3, 6), ...overrides});
test('window labels are parsed case insensitively', () => {
  for (const [label, hours] of [['5-hour',5],['5H',5],['session',5],['Week',168],['7-day',168],['7d',168],['Daily',24],['24-hour',24],['Month',720],['30-day',720],['15-hour',15],['25h',25],['7-day session',168],['1.5 days',36],['0.5h',0.5],['v2 weekly',168],['v2h',null],['1.2.5h',null],['unknown',null]]) assert.equal(F.windowHours(label), hours);
});
test('recent pace beats window average', () => {
  assert.equal(F.forecast(limit({history:history(3, 2.4)}), now).kind, 'full');
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
  assert.equal(F.forecast(limit({percent:41.1, resetsAt:new Date(now+h).toISOString(), history:history(3, 0)}),now).text, 'on pace for ~42%');
});
test('flat and falling history take precedence over the window average', () => {
  for (const rise of [0, -5]) {
    assert.deepEqual(F.forecast(limit({percent:40, history:history(3, rise)}), now), {kind:'ends',text:'on pace for ~40%',warn:false});
    assert.equal(F.forecast(limit({history:history(3, rise), resetsAt:null}), now), null);
  }
});
test('zero usage with zero pace has no forecast', () => {
  assert.equal(F.forecast(limit({percent:0, history:history(3, 0)}), now), null);
  assert.equal(F.forecast(limit({percent:0, history:history(3, -5)}), now), null);
  assert.equal(F.forecast(limit({percent:0, history:[]}), now), null);
  assert.deepEqual(F.forecast(limit({percent:0.01, history:history(3, 0)}), now), {kind:'ends',text:'on pace for ~1%',warn:false});
  assert.ok(F.forecast(limit({percent:0, history:history(3, 6)}), now));
});
test('unknown reset, full bar, past reset and zero pace', () => {
  assert.equal(F.forecast(limit({resetsAt:null}),now).kind, 'full');
  assert.equal(F.forecast(limit({resetsAt:null, history:history(3, 0.1)}),now),null);
  assert.equal(F.forecast(limit({percent:100}),now),null);
  assert.equal(F.forecast(limit({resetsAt:new Date(now-h).toISOString()}),now),null);
  assert.equal(F.forecast(limit({percent:0, history:[], resetsAt:null}),now),null);
});
test('time format uses local calendar days across midnight and daylight saving', async () => {
  const source = `const F = require(${JSON.stringify(require.resolve('../lib/forecast.js'))});
    const when = (a,b) => F.when(Date.parse(a),Date.parse(b));
    require('fs').writeSync(1, JSON.stringify([
      when('2026-11-10T00:30:00Z','2026-11-09T22:30:00Z'),
      when('2026-11-10T05:30:00Z','2026-11-10T04:30:00Z'),
      when('2026-03-30T12:00:00Z','2026-03-24T12:00:00Z'),
      when('2026-03-09T12:00:00Z','2026-03-05T12:00:00Z'),
      when('2026-11-12T12:00:00Z','2026-11-09T09:00:00Z'),
      F.forecast({label:'weekly', percent:40, resetsAt:'2026-11-14T09:00:00Z',
        history:[[Date.parse('2026-11-09T06:00:00Z')/1000,20],[Date.parse('2026-11-09T09:00:00Z')/1000,22.4]]}, Date.parse('2026-11-09T09:00:00Z')).text
    ]));`;
  for (const [zone, expected] of [
    ['Europe/Amsterdam',['tomorrow 01:30','today 06:30','Mon 14:00','Mon 13:00','Thu 13:00','at this pace full Thu 13:00']],
    ['America/New_York',['today 19:30','tomorrow 00:30','Mon 08:00','Mon 08:00','Thu 07:00','at this pace full Thu 07:00']]
  ]) assert.deepEqual(JSON.parse((await runFile(process.execPath, ['-e', source], {env:{...process.env, TZ:zone}, encoding:'utf8'})).stdout), expected);
});
test('parser filters malformed history and passes raw reset', () => {
  const raw = limit({label:'unknown', resetsAt:null, history:[null,[1],[1,'2'],[1,2,3],...history(3,6)]});
  const result = A.parse(JSON.stringify({updatedAt:new Date(now).toISOString(), limits:[raw]}),'record',now).limits[0];
  assert.deepEqual(result.history,history(3,6));
  assert.equal(result.resetsAt,null); assert.equal(result.forecast.kind,'full');
  const many = A.parse(JSON.stringify({limits:[{history:Array.from({length:210},(_, i)=>[i,i % 100]).reverse()}]}),'record',now).limits[0];
  assert.equal(many.history.length,200); assert.equal(many.history[0][0],10);
});
test('stale or unknown update times suppress forecasts', () => {
  const parse = updatedAt => A.parse(JSON.stringify({updatedAt, limits:[limit()]}), 'record', now);
  assert.ok(parse(new Date(now - 7200000).toISOString()).limits[0].forecast);
  assert.equal(parse(new Date(now - 7200001).toISOString()).limits[0].forecast, null);
  assert.equal(parse(undefined).limits[0].forecast, null);
});
test('forecast ignores invalid, future, and unsorted samples before applying the cap', () => {
  const samples = Array.from({length:205}, (_, i) => [now/1000 - (204-i)*60, 20 + i/100]);
  const unordered = samples.slice().reverse().concat([[now/1000+1,100],[NaN,1],[Infinity,2],[0,NaN],[0,Infinity],[0,'2'],[0,-1],[0,101]]);
  assert.deepEqual(F.forecast(limit({history:unordered}), now), F.forecast(limit({history:samples.slice(-200)}), now));
  for (const value of [NaN, Infinity, -Infinity, '40']) assert.equal(F.forecast(limit({percent:value}), now), null);
  assert.equal(F.forecast(limit(), Infinity), null);
});
