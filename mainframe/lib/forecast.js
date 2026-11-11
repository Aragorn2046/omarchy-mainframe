// Forecasting uses the caller's current time and the runtime's local time zone.
function windowHours(label) {
  label = typeof label === 'string' ? label.toLowerCase() : '';
  var explicit = /\b(\d+)\s*-?\s*(hours|hour|hr|h|days|day|d)\b/.exec(label);
  if (explicit) return Number(explicit[1]) * (/^d/.test(explicit[2]) ? 24 : 1);
  if (/\b(week|weekly)\b/.test(label)) return 168;
  if (/\b(daily|day)\b/.test(label)) return 24;
  if (/\b(month|monthly)\b/.test(label)) return 720;
  if (/\bsession\b/.test(label)) return 5;
  return null;
}
function forecastWhen(t, nowMs) {
  var date = new Date(t), now = new Date(nowMs);
  var day = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
  var today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  var difference = Math.round((day - today) / 86400000);
  var weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function pad(n) { return n < 10 ? '0' + n : String(n); }
  var prefix = difference === 0 ? 'today' : difference === 1 ? 'tomorrow' :
    difference > 1 && difference <= 6 ? weekdays[date.getDay()] : date.getDate() + ' ' + months[date.getMonth()];
  return prefix + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
}
function forecast(limit, nowMs) {
  if (!limit || typeof nowMs !== 'number' || !isFinite(nowMs) || typeof limit.percent !== 'number' ||
      !isFinite(limit.percent) || limit.percent < 0 || limit.percent >= 100) return null;
  var reset = typeof limit.resetsAt === 'string' ? Date.parse(limit.resetsAt) : NaN;
  if (isFinite(reset) && reset <= nowMs) return null;
  var length = windowHours(limit.label), minimum = length === 5 ? 0.5 : 3;
  var points = Array.isArray(limit.history) ? limit.history.filter(function(p) {
    return Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && isFinite(p[0]) &&
      typeof p[1] === 'number' && isFinite(p[1]) && p[1] >= 0 && p[1] <= 100 && p[0] * 1000 <= nowMs;
  }).sort(function(a, b) { return a[0] - b[0]; }).slice(-200) : [];
  var rate = null;
  if (points.length > 1) {
    var first = points[0], last = points[points.length - 1];
    var span = (last[0] - first[0]) / 3600;
    if (span >= minimum) rate = Math.max(0, (last[1] - first[1]) / span);
  }
  if (rate === null && length && isFinite(reset)) {
    var elapsed = length - (reset - nowMs) / 3600000;
    if (elapsed >= minimum) rate = limit.percent / elapsed;
  }
  if (rate === null || !isFinite(rate) || (rate === 0 && !isFinite(reset))) return null;
  var hit = nowMs + (100 - limit.percent) / rate * 3600000;
  if (isFinite(reset)) {
    if (hit < reset) return {kind:'full', text:'at this pace full ' + forecastWhen(hit, nowMs), warn:true};
    var projected = Math.min(99, Math.max(Math.ceil(limit.percent), Math.round((limit.percent + rate * (reset - nowMs) / 3600000) / 5) * 5));
    return {kind:'ends', text:'on pace for ~' + projected + '%', warn:false};
  }
  return hit <= nowMs + 7 * 86400000 ? {kind:'full', text:'at this pace full ' + forecastWhen(hit, nowMs), warn:true} : null;
}
if (typeof module !== 'undefined' && module.exports) module.exports = {forecast:forecast, windowHours:windowHours, when:forecastWhen};
