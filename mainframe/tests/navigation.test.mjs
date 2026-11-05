import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { scrollTarget, keyHelp } = require('../lib/navigation.js');
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');

test('scroll targets move by line, page or endpoint and clamp to content', () => {
  const targets = {'line-down': 248, 'line-up': 152, 'page-down': 352, 'page-up': 48, top: 0, bottom: 800};
  for (const [kind, expected] of Object.entries(targets)) {
    assert.equal(scrollTarget(200, 1000, 200, kind), expected, kind);
    assert.ok(scrollTarget(-1000, 1000, 200, kind) >= 0, kind);
    assert.ok(scrollTarget(2000, 1000, 200, kind) <= 800, kind);
    assert.equal(scrollTarget(100, 100, 200, kind), 0, kind);
  }
  assert.equal(scrollTarget(0, 1000, 200, 'line-up'), 0);
  assert.equal(scrollTarget(800, 1000, 200, 'line-down'), 800);
  assert.equal(scrollTarget(0, 1000, 200, 'page-up'), 0);
  assert.equal(scrollTarget(800, 1000, 200, 'page-down'), 800);
  assert.equal(scrollTarget(100, 1000, 40, 'page-down'), 100);
  assert.equal(scrollTarget(100, 1000, 60, 'page-down'), 112);
});

test('README Keys table matches the help data', () => {
  const table = read('../../README.md').split('## Keys\n')[1].split('\n## ')[0];
  for (const {keys, action} of keyHelp) {
    const row = table.split('\n').find(line => line.includes('`' + keys[0] + '`'));
    assert.ok(row, keys[0]);
    for (const key of keys) assert.ok(row.includes('`' + key + '`'), key);
    assert.ok(row.includes(action), action);
  }
});

test('new shortcuts are unique and disabled in settings and text fields', () => {
  const source = read('../shell.qml');
  const shortcuts = [...source.matchAll(/Shortcut\s*\{([\s\S]*?)\n?\s*\}/g)].map(m => m[1]);
  const keys = ['Left', 'h', 'Right', 'l', 'Ctrl+Shift+Tab', 'Ctrl+Backtab', 'Ctrl+PgDown', 'Ctrl+PgUp',
    'Down', 'j', 'Up', 'k', 'PgDown', 'Space', 'PgUp', 'Shift+Space', 'Home', 'g', 'End', 'Shift+G',
    'Backspace', 'Alt+Left', 'Enter', 'Return', '?', 'F1'];
  for (const key of keys) {
    const matches = shortcuts.filter(block => {
      const list = block.match(/sequences:\s*\[([^\]]*)\]/);
      return list && [...list[1].matchAll(/"([^"]+)"/g)].some(m => m[1] === key);
    });
    assert.equal(matches.length, 1, key);
    assert.match(matches[0], /enabled:\s*!shell\.settingsOpen/, key);
    assert.match(matches[0], /!shell\.textFieldFocused\(\)/, key);
    if (key !== '?' && key !== 'F1') assert.match(matches[0], /!shell\.helpOpen/, key);
  }
});
