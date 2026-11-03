function cue(used, total) {
  var fraction = Number(total) > 0 ? Math.max(0, Math.min(1, Number(used) / Number(total))) : 0;
  return {fraction:fraction, label:fraction >= 0.95 ? 'Critical' : fraction >= 0.85 ? 'Warning' : '', symbol:fraction >= 0.95 ? '!!' : fraction >= 0.85 ? '!' : ''};
}
function rowLabel(row) { return String(row.label || row.mount || row.device || ''); }
var api = {cue:cue, rowLabel:rowLabel};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
