import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const U = require('../lib/usage_value.js');
const prices = {claude:{models:{'m':{input:1,output:2,cache_read:0.1,cache_write_5m:1,cache_write_1h:2}}},codex:{models:{'c':{input:2,cached_input:0.1,output:10}}}};
test('matching suffixes, windows, providers and offline hosts', () => {
  const now = new Date(2026, 10, 3, 0, 1);
  const hosts = [{host:'this machine',usage:{days:{'2026-11-03':{'claude/m-20261001[1m]':{input:1000000}},'2026-10-28':{'codex/c':{input:1000000,cached_input:500000}},'2026-10-05':{'claude/m':{input:1000000}},'2026-10-04':{'claude/m':{input:1000000}}}}}, {host:'remote',usage:{days:{'2026-11-03':{'codex/c':{output:1000000}}}}}, {host:'away',status:'offline',usage:{days:{'2026-11-03':{'claude/m':{input:100000000}}}}}, {host:'pending'}];
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
