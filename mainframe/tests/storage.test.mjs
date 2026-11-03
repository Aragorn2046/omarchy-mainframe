import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const S = require('../lib/storage.js');
const M = require('../lib/metrics.js');
const palette = { accent: '#ff6655', cyan: '#55ccdd', yellow: '#e8cc55', red: '#cc5577', green: '#55dd77' };
const rows = (d, p = palette) => S.model(d, p, M.oklabDistance);
test('segments add up to disk and fold unrecognised categories into Other', () => {
  const list = rows({ total: 1000, free: 400, categories: { Apps: 100, Documents: 30, unexpected: 20, Other: 10 } });
  assert.equal(list.find(r => r.name === 'Other').value, 30);
  assert.equal(list.find(r => r.name === 'System & other').value, 440);
  assert.equal(list.at(-1).name, 'Free');
  assert.equal(list.reduce((n, r) => n + r.value, 0), 1000);
  assert.equal(list.reduce((n, r) => n + r.percent, 0), 100);
});
test('snapshot mismatches never make system negative or overflow the bar', () => {
  const list = rows({ total: 100, free: 10, categories: { Apps: 90, Games: 90 } });
  assert.equal(list.reduce((n, r) => n + r.value, 0), 100);
  assert.equal(list.find(r => r.name === 'System & other').value, 0);
  assert.equal(list.reduce((n, r) => n + r.percent, 0), 100);
});
test('adjacent visible categories are distinguishable or patterned', () => {
  const d = { total: 100, free: 10, categories: { Apps: 10, Games: 10, Documents: 10, Images: 10, Videos: 10, Music: 10, Other: 10 } };
  for (const p of [palette, { accent: '#777777', muted: '#777777' }]) {
    const visible = rows(d, p).filter(r => r.value > 0);
    for (let i=1; i<visible.length; i++) assert.ok(M.oklabDistance(visible[i-1].color, visible[i].color) >= 15 || visible[i-1].pattern !== visible[i].pattern);
  }
});
test('scan age text uses cached timestamp', () => {
  assert.equal(S.ageText(0, 50000), 'Not scanned yet');
  assert.equal(S.ageText(100, 159000), 'Scanned just now');
  assert.equal(S.ageText(100, 280000), 'Scanned 3 min ago');
});

test('pattern ink contrasts with both bright and dark segments', () => {
  assert.match(S.patternInk('#ffffff'), /0,0,0/);
  assert.match(S.patternInk('#000000'), /255,255,255/);
});


test('uses reported used space and includes reserved blocks in system', () => {
  const list = rows({ total: 1000, used: 500, free: 400, categories: { Apps: 200, Games: 100 } });
  assert.equal(list.find(r => r.name === 'Apps').value, 200);
  assert.equal(list.find(r => r.name === 'Games').value, 100);
  assert.equal(list.find(r => r.name === 'System & other').value, 300);
  assert.equal(list.find(r => r.name === 'Free').value, 400);
  assert.equal(list.reduce((n, r) => n + r.value, 0), 1000);
  assert.equal(list.reduce((n, r) => n + r.percent, 0), 100);
  assert.equal(list.reduce((n, r) => n + r.fraction, 0), 1);
});

test('scales categories against used, preserving reserved blocks', () => {
  const list = rows({ total: 100, used: 40, free: 50, categories: { Apps: 60, Games: 20 } });
  assert.equal(list.find(r => r.name === 'Apps').value, 30);
  assert.equal(list.find(r => r.name === 'Games').value, 10);
  assert.equal(list.find(r => r.name === 'System & other').value, 10);
  assert.equal(list.reduce((n, r) => n + r.percent, 0), 100);
});

test('zero and invalid used figures and overlapping snapshots remain bounded', () => {
  const value = (list, name) => list.find(r => r.name === name).value;
  const empty = rows({ total: 100, used: 0, free: 80, categories: { Apps: 10 } });
  assert.equal(value(empty, 'Apps'), 0);
  assert.equal(value(empty, 'System & other'), 20);
  for (const used of [undefined, null, -1, Infinity, 101]) {
    const list = rows({ total: 100, used, free: 40, categories: { Apps: 20 } });
    assert.equal(value(list, 'System & other'), 40);
    assert.equal(list.reduce((n, r) => n + r.percent, 0), 100);
  }
  const overlap = rows({ total: 100, used: 70, free: 60, categories: { Apps: 20 } });
  assert.equal(value(overlap, 'Apps'), 20);
  assert.equal(value(overlap, 'System & other'), 50);
  assert.equal(value(overlap, 'Free'), 60);
  assert.equal(overlap.reduce((n, r) => n + r.percent, 0), 100);
  assert.ok(Math.abs(overlap.reduce((n, r) => n + r.fraction, 0) - 1) < 1e-12);
});

test('fleet storage rows prefer the label and preserve the bus through the metrics model', () => {
  const F = require('../lib/fleet_storage.js');
  assert.equal(F.rowLabel({label:'Backup240', mount:'/Volumes/Backup240', device:'/dev/disk7s1'}), 'Backup240');
  assert.equal(F.rowLabel({mount:'/mnt/c', device:'disk'}), '/mnt/c');
  assert.equal(F.rowLabel({device:'disk'}), 'disk');
  const view = M.step(M.emptyState(), {filesystems:[{label:'Backup240', mount:'/Volumes/Backup240', device:'/dev/disk7s1', bus:'USB', total:100, used:20}]}, 1).view;
  assert.equal(view.filesystems[0].label, 'Backup240');
  assert.equal(view.filesystems[0].bus, 'USB');
});
