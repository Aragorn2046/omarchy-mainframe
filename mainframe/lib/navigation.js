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
  var step = Math.max(viewHeight - 48, Math.round(viewHeight / 2));
  var line = Math.min(48, Math.max(1, Math.round(viewHeight / 2)));
  var target = contentY;
  if (kind === 'line-down') target += line;
  else if (kind === 'line-up') target -= line;
  else if (kind === 'page-down') target += step;
  else if (kind === 'page-up') target -= step;
  else if (kind === 'top') target = 0;
  else if (kind === 'bottom') target = max;
  return Math.max(0, Math.min(max, target));
}
var keyHelp = [
  {group:'Tabs', keys:['Left', 'h'], action:'Previous tab; close Storage while Storage is open'},
  {group:'Tabs', keys:['Right', 'l', 'Ctrl+Tab', 'Ctrl+PgDown'], action:'Next tab; inactive while Storage is open'},
  {group:'Tabs', keys:['Ctrl+Shift+Tab', 'Ctrl+Backtab', 'Ctrl+PgUp'], action:'Previous tab; inactive while Storage is open'},
  {group:'Tabs', keys:['1', '2', '3', '4', '5', '6', '7', '8', '9'], action:'Select the corresponding tab'},
  {group:'Views', keys:['s', 'd', 'a'], action:'Select Systems, Storage, or Agents in Overview'},
  {group:'Views', keys:['Tab', 'Shift+Tab', 'Backtab'], action:'Cycle Overview views'},
  {group:'Views', keys:['Backspace', 'Alt+Left'], action:'Close Storage while Storage is open, or go back from a machine tab'},
  {group:'Scroll', keys:['Down', 'j', 'Up', 'k'], action:'Scroll one step; pick a row while Storage is open'},
  {group:'Scroll', keys:['PgDown', 'Space', 'PgUp', 'Shift+Space'], action:'Scroll one page'},
  {group:'Scroll', keys:['Home', 'g', 'End', 'G'], action:'Jump to the top or bottom'},
  {group:'Actions', keys:['Enter', 'Return'], action:'Open the selected row in the folder viewer while Storage is open'},
  {group:'Actions', keys:['?', 'F1'], action:'Toggle keyboard help'},
  {group:'Actions', keys:['Escape'], action:'Close help, settings, Storage, or the window'},
  {group:'Actions', keys:['q', 'Q'], action:'Close Storage while Storage is open, or close the window'},
  {group:'Actions', keys:['t', 'T'], action:'Open the theme picker'},
  {group:'Actions', keys:['r', 'R'], action:'Refresh Agents or restart the current machine collector'},
  {group:'Actions', keys:[',', 'Ctrl+,'], action:'Open settings; Ctrl+, also closes settings'}
];
var api = {view:view, cycle:cycle, key:key, scrollTarget:scrollTarget, keyHelp:keyHelp};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
