import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';

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
  assert.equal(scrollTarget(100, 1000, 40, 'page-down'), 120);
  assert.equal(scrollTarget(100, 1000, 40, 'line-down'), 120);
  assert.equal(scrollTarget(100, 1000, 40, 'line-up'), 80);
  assert.equal(scrollTarget(100, 1000, 60, 'page-down'), 130);
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

// Count nested braces while ignoring strings and comments in QML/JavaScript.
function shortcutBlocks(source) {
  const blocks = [];
  const startPattern = /\bShortcut\s*\{/g;
  let match;
  while ((match = startPattern.exec(source))) {
    const start = startPattern.lastIndex;
    let depth = 1, quote = '', lineComment = false, blockComment = false;
    let i = start;
    for (; i < source.length && depth; i++) {
      const c = source[i], next = source[i + 1];
      if (lineComment) { if (c === '\n') lineComment = false; continue; }
      if (blockComment) { if (c === '*' && next === '/') { blockComment = false; i++; } continue; }
      if (quote) { if (c === '\\') i++; else if (c === quote) quote = ''; continue; }
      if (c === '"' || c === "'" || c === '`') quote = c;
      else if (c === '/' && next === '/') { lineComment = true; i++; }
      else if (c === '/' && next === '*') { blockComment = true; i++; }
      else if (c === '{') depth++;
      else if (c === '}') depth--;
    }
    assert.equal(depth, 0, 'unclosed Shortcut');
    blocks.push(source.slice(start, i - 1));
    startPattern.lastIndex = i;
  }
  return blocks;
}

function sequences(block) {
  const list = block.match(/sequences:\s*\[([^\]]*)\]/);
  assert.ok(list, 'Shortcut must declare sequences');
  return [...list[1].matchAll(/"([^"]+)"/g)].map(match => match[1]);
}

test('help keys are bound once and shortcuts respect repeat and focus guards', () => {
  const shortcuts = shortcutBlocks(read('../shell.qml'));
  const scrollKeys = new Set(['Down', 'j', 'Up', 'k', 'PgDown', 'Space', 'PgUp', 'Shift+Space', 'Home', 'g', 'End', 'Shift+G']);
  const closeSettings = new Set(['Escape', 'Ctrl+,']);
  const helpKeys = new Set(['?', 'F1', 'Escape']);
  for (const {keys} of keyHelp) {
    for (const helpKey of keys) {
      const key = helpKey === 'G' ? 'Shift+G' : helpKey;
      const matches = shortcuts.filter(block => sequences(block).includes(key));
      assert.equal(matches.length, 1, key);
    }
  }
  for (const block of shortcuts) {
    const keys = sequences(block);
    const enabled = block.match(/enabled:\s*([^;\n]+)/)?.[1] || '';
    assert.match(enabled, /!shell\.textFieldFocused\(\)/, keys.join(', '));
    if (!keys.some(key => closeSettings.has(key))) assert.match(enabled, /!shell\.settingsOpen/, keys.join(', '));
    if (!keys.some(key => scrollKeys.has(key) || helpKeys.has(key))) assert.match(enabled, /!shell\.helpOpen/, keys.join(', '));
    if (!keys.some(key => scrollKeys.has(key))) assert.match(block, /autoRepeat:\s*false/, keys.join(', '));
    else assert.doesNotMatch(block, /autoRepeat:\s*false/, keys.join(', '));
  }
});

function qmlFunction(source, name) {
  const match = new RegExp('function\\s+' + name + '\\s*\\([^)]*\\)\\s*\\{').exec(source);
  assert.ok(match, name);
  let depth = 1, end = match.index + match[0].length;
  while (depth && end < source.length) {
    if (source[end] === '{') depth++;
    if (source[end] === '}') depth--;
    end++;
  }
  assert.equal(depth, 0, name);
  return source.slice(match.index, end);
}

test('storage selection tracks the first fully visible row and content coordinates', () => {
  const source = read('../StorageView.qml');
  const list = { visible: true, contentY: 0, contentHeight: 250, height: 80, contentItem: {} };
  const rows = [0, 1, 2, 3].map(i => ({
    height: 36,
    mapToItem(item) { assert.equal(item, list.contentItem); return {y: 50 + i * 37}; }
  }));
  const rowRepeater = {itemAt(index) { return rows[index]; }};
  const state = {currentRow: 0, keyboardSelection: false};
  const run = new Function('list', 'rows', 'rowRepeater', 'state', `
    with (state) { ${qmlFunction(source, 'moveRow')}\n${qmlFunction(source, 'selectAfterScroll')}
      return {moveRow, selectAfterScroll}; }
  `)(list, rows, rowRepeater, state);
  run.moveRow(1);
  assert.equal(state.currentRow, 1);
  assert.equal(list.contentY, 43);
  assert.equal(state.keyboardSelection, true);
  list.contentY = 70;
  run.selectAfterScroll('page-down');
  assert.equal(state.currentRow, 1);
  run.selectAfterScroll('bottom');
  assert.equal(state.currentRow, 3);
  run.selectAfterScroll('top');
  assert.equal(state.currentRow, 0);
});

test('storage navigation selects rows and help takes scroll priority', () => {
  const source = read('../shell.qml');
  const list = {visible: true, contentY: 100, contentHeight: 1000, height: 200};
  const help = {visible: true, contentY: 0, contentHeight: 1000, height: 200};
  const systems = {visible: true, flick: {visible: true, contentY: 0, contentHeight: 1000, height: 200}};
  const moved = [], selected = [];
  const storageView = {visible: true, flick: list,
    moveRow(step) { moved.push(step); }, selectAfterScroll(kind) { selected.push(kind); }};
  const state = {helpOpen: false, storageOpen: true};
  const scrollActive = new Function('state', 'storageView', 'helpFlick', 'Navigation', 'systemsView', `
    with (state) { const agentsView = {visible: false};
      ${qmlFunction(source, 'scrollActive')} return scrollActive; }
  `)(state, storageView, help, {scrollTarget}, systems);
  const moveVertical = new Function('state', 'storageView', 'scrollActive', `
    with (state) { ${qmlFunction(source, 'moveVertical')} return moveVertical; }
  `)(state, storageView, scrollActive);
  moveVertical(1);
  moveVertical(-1);
  assert.deepEqual(moved, [1, -1]);
  assert.equal(list.contentY, 100);
  for (const kind of ['page-down', 'page-up', 'top', 'bottom']) scrollActive(kind);
  assert.deepEqual(selected, ['page-down', 'page-up', 'top', 'bottom']);
  assert.equal(list.contentY, 800);
  state.helpOpen = true;
  moveVertical(1);
  assert.equal(help.contentY, 48);
  assert.equal(list.contentY, 800);
  assert.deepEqual(moved, [1, -1]);
  assert.equal(selected.length, 4);
  state.helpOpen = false;
  state.storageOpen = false;
  moveVertical(1);
  assert.equal(systems.flick.contentY, 48);
  assert.deepEqual(moved, [1, -1]);
  assert.equal(selected.length, 4);
});

test('Enter opens the current row only while Storage is open', () => {
  const shortcut = shortcutBlocks(read('../shell.qml')).find(block => sequences(block).includes('Enter'));
  assert.ok(shortcut);
  assert.ok(sequences(shortcut).includes('Return'));
  const handler = shortcut.match(/onActivated:\s*([^\n]+)/)?.[1];
  assert.ok(handler);
  let opened = 0;
  const run = new Function('shell', 'storageView', handler);
  const storageView = {openCurrentRow() { opened++; }};
  run({storageOpen: false}, storageView);
  assert.equal(opened, 0);
  run({storageOpen: true}, storageView);
  assert.equal(opened, 1);
});

test('QML files contain no obsolete detail flick alias', () => {
  function checkDirectory(directory) {
    for (const entry of readdirSync(directory, {withFileTypes: true})) {
      const path = new URL(encodeURIComponent(entry.name) + (entry.isDirectory() ? '/' : ''), directory);
      if (entry.isDirectory()) checkDirectory(path);
      else if (entry.isFile() && entry.name.endsWith('.qml')) assert.doesNotMatch(readFileSync(path, 'utf8'), /detailFlick/, path.pathname);
    }
  }
  checkDirectory(new URL('../../', import.meta.url));
});

test('storage refresh preserves the selected category or clamps the row', () => {
  const source = read('../StorageView.qml');
  const start = source.indexOf('  onRowsChanged: {');
  assert.notEqual(start, -1);
  const bodyStart = source.indexOf('{', start);
  let depth = 1, end = bodyStart + 1;
  while (depth && end < source.length) {
    if (source[end] === '{') depth++;
    if (source[end] === '}') depth--;
    end++;
  }
  assert.equal(depth, 0);
  const update = new Function('state', `with (state) { ${source.slice(bodyStart + 1, end - 1)} }`);
  const state = {rows: [{name: 'B'}, {name: 'A'}, {name: 'C'}], currentRow: 1, selectedCategory: 'B'};
  update(state);
  assert.equal(state.currentRow, 0);
  assert.equal(state.selectedCategory, 'B');
  state.rows = [{name: 'A'}, {name: 'C'}];
  state.currentRow = 2;
  update(state);
  assert.equal(state.currentRow, 1);
  assert.equal(state.selectedCategory, 'C');
  state.rows = [];
  update(state);
  assert.equal(state.currentRow, 0);
  assert.equal(state.selectedCategory, '');
});
