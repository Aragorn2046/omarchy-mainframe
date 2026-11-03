function view(value) { return ['systems', 'storage', 'agents'].indexOf(value) >= 0 ? value : 'systems'; }
function cycle(value, step) { var all = ['systems', 'storage', 'agents']; return all[(all.indexOf(view(value)) + (step < 0 ? 2 : 1)) % 3]; }
function key(value, k, shift) {
  if (k === 's') return 'systems';
  if (k === 'd') return 'storage';
  if (k === 'a') return 'agents';
  if (k === 'Tab') return cycle(value, shift ? -1 : 1);
  return view(value);
}
var api = {view:view, cycle:cycle, key:key};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
