import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const U = require('../lib/usage_value.js');
const prices = {claude:{models:{'m':{input:1,output:2,cache_read:0.1,cache_write_5m:1,cache_write_1h:2}}},codex:{models:{'c':{input:2,cached_input:0.1,output:10}}}};
test('matching suffixes, windows, providers and offline hosts', () => {
  const now = new Date(2026, 10, 3, 0, 1);
  const hosts = [{host:'this machine',usage:{days:{'2026-11-03':{'claude/m-20261001[1m]':{input:1000000}},'2026-10-28':{'codex/c':{input:1000000,cached_input:500000}},'2026-10-05':{'claude/m':{input:1000000}},'2026-10-04':{'claude/m':{input:1000000}}}}}, {host:'remote',usage:{days:{'2026-11-03':{'codex/c':{output:1000000}}}}}, {host:'away',status:'offline'}, {host:'pending'}];
  const v = U.calculate(hosts,prices,now);
  assert.equal(v.totals.today,11); assert.equal(v.totals.seven,12.05); assert.equal(v.totals.thirty,13.05);
  assert.equal(v.providers.codex.thirty,11.05); assert.equal(v.hosts[1].totals.today,10);
  assert.equal(v.excluded,2); assert.equal(v.hosts[2].status,'offline'); assert.equal(v.hosts[3].status,'waiting');
  assert.equal(U.priceFor(prices,'claude','m-20261001[1m]').input,1);
});
test('unknown model is partial and no price is listed', () => {
  const v = U.calculate([{host:'test',usage:{days:{'2026-11-03':{'claude/unknown':{input:1}}}}}],prices,new Date(2026,10,3));
  assert.equal(v.partial,true); assert.deepEqual(v.unpriced,['claude/unknown']); assert.equal(v.totals.today,0);
  assert.equal(U.money(1234.1),'$1,234'); assert.equal(U.money(2.1),'$2.10');
});
test('zero-token unknown models do not make usage partial', () => {
  const now = new Date(2026,10,3);
  const hosts = [{host:'test',usage:{days:{'2026-11-03':{'claude/<synthetic>':{input:0,output:0,cache_read:0,cache_write_5m:0,cache_write_1h:0},'codex/unknown':{}}}}}];
  const v = U.calculate(hosts,prices,now);
  assert.equal(v.partial,false); assert.deepEqual(v.unpriced,[]); assert.deepEqual(v.unpricedTokens,{});
  hosts[0].usage.days['2026-11-02'] = {'claude/<synthetic>':{cache_read:1}};
  const withUsage = U.calculate(hosts,prices,now);
  assert.equal(withUsage.partial,true); assert.deepEqual(withUsage.unpriced,['claude/<synthetic>']);
  assert.equal(withUsage.unpricedTokens['claude/<synthetic>'],1);
});
test('dated Haiku 4.5 resolves to the published rates', () => {
  const actualPrices = require('../prices.json');
  assert.deepEqual(U.priceFor(actualPrices,'claude','claude-haiku-4-5-20251001'),
    {input:1,output:5,cache_read:0.1,cache_write_5m:1.25,cache_write_1h:2});
});
test('stale hosts remain counted and are flagged', () => {
  const now = new Date('2026-11-03T12:00:00Z');
  const hour = '2026-11-03T11:00';
  for (const usage of [
    {scanned_at:'2026-11-03T11:14:00Z'},
    {scanned_at:'2026-11-03T11:59:00Z', stale:true}
  ]) {
    usage.days = {[hour]:{'claude/m':{input:1000000}}};
    const value = U.calculate([{host:'local',status:'offline',usage}], prices, now);
    assert.equal(value.stale, true);
    assert.equal(value.totals.today, 1);
  }
  const fresh = U.calculate([{usage:{scanned_at:now.toISOString(),days:{}}}],prices,now);
  assert.equal(fresh.stale,false);
});
test('UTC hours map to the viewer local day at midnight', () => {
  const previous = process.env.TZ;
  process.env.TZ = 'Europe/Amsterdam';
  try {
    const usage = {scanned_at:'2026-11-03T00:30:00Z',days:{'2026-11-03T00:00':{'claude/m':{input:1000000}},'2026-11-02T22:00':{'claude/m':{input:2000000}}}};
    const value = U.calculate([{usage}], prices, '2026-11-03T00:30:00Z');
    assert.deepEqual(value.totals,{today:1,seven:3,thirty:3});
  } finally {
    if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous;
  }
});

test('quarter-hour UTC buckets map correctly in Nepal', () => {
  const previous = process.env.TZ; process.env.TZ = 'Asia/Kathmandu';
  try {
    const usage = {scanned_at:'2026-11-03T18:30:00Z', days:{'2026-11-03T18:00':{'claude/m':{input:1000000}}, '2026-11-03T18:15':{'claude/m':{input:2000000}}}};
    const value = U.calculate([{usage}],prices,'2026-11-03T18:30:00Z');
    assert.equal(value.totals.today,2); assert.equal(value.totals.seven,3);
  } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; }
});
