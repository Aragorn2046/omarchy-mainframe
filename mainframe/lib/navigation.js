function view(value) { return ['systems', 'storage', 'agents'].indexOf(value) >= 0 ? value : 'systems'; }
function cycle(value, step) { var all = ['systems', 'storage', 'agents']; return all[(all.indexOf(view(value)) + (step < 0 ? 2 : 1)) % 3]; }
function key(value, k, shift) {
  if (k === 's') return 'systems';
  if (k === 'd') return 'storage';
  if (k === 'a') return 'agents';
  if (k === 'Tab') return cycle(value, shift ? -1 : 1);
  return view(value);
}
function scrollTarget(contentY, contentHeight, viewHeight, kind) {
  var max = Math.max(0, contentHeight - viewHeight);
  var step = Math.max(0, viewHeight - 48);
  var target = contentY;
  if (kind === 'line-down') target += 48;
  else if (kind === 'line-up') target -= 48;
  else if (kind === 'page-down') target += step;
  else if (kind === 'page-up') target -= step;
  else if (kind === 'top') target = 0;
  else if (kind === 'bottom') target = max;
  return Math.max(0, Math.min(max, target));
}
var keyHelp = [
  {group:'Tabs', keys:['Left', 'h'], action:'Previous tab; Back in storage detail'},
  {group:'Tabs', keys:['Right', 'l', 'Ctrl+Tab', 'Ctrl+PgDown'], action:'Next tab'},
  {group:'Tabs', keys:['Ctrl+Shift+Tab', 'Ctrl+Backtab', 'Ctrl+PgUp'], action:'Previous tab'},
  {group:'Tabs', keys:['1–9'], action:'Select the corresponding tab'},
  {group:'Views', keys:['s', 'd', 'a'], action:'Select Systems, Storage, or Agents in Overview'},
  {group:'Views', keys:['Tab', 'Shift+Tab', 'Backtab'], action:'Cycle Overview views'},
  {group:'Views', keys:['Backspace', 'Alt+Left'], action:'Back from storage detail or a machine tab'},
  {group:'Scroll', keys:['Down', 'j', 'Up', 'k'], action:'Scroll one step or select a storage row'},
  {group:'Scroll', keys:['PgDown', 'Space', 'PgUp', 'Shift+Space'], action:'Scroll one page'},
  {group:'Scroll', keys:['Home', 'g', 'End', 'G'], action:'Jump to the top or bottom'},
  {group:'Actions', keys:['Enter', 'Return'], action:'Open the selected storage row'},
  {group:'Actions', keys:['?', 'F1'], action:'Toggle keyboard help'},
  {group:'Actions', keys:['Esc'], action:'Close help, settings, storage detail, or the window'},
  {group:'Actions', keys:['q', 'Q'], action:'Close storage detail or the window'},
  {group:'Actions', keys:['t', 'T'], action:'Open the theme picker'},
  {group:'Actions', keys:['r', 'R'], action:'Refresh Agents or restart the current machine collector'},
  {group:'Actions', keys:[',', 'Ctrl+,'], action:'Open settings; Ctrl+, also closes settings'}
];
var api = {view:view, cycle:cycle, key:key, scrollTarget:scrollTarget, keyHelp:keyHelp};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
