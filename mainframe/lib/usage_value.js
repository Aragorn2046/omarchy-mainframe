// Pure fleet value calculation. Dates use the viewer's local calendar.
function localDay(date) {
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}
function priceFor(table, provider, model) {
  var models = table && table[provider] && table[provider].models || {};
  if (Object.prototype.hasOwnProperty.call(models, model)) return models[model];
  var normalized = model.replace(/\[[^\]]+\]$/, '').replace(/-\d{8}$/, '');
  return Object.prototype.hasOwnProperty.call(models, normalized) ? models[normalized] : null;
}
function zero() { return {today: 0, seven: 0, thirty: 0}; }
function money(value) {
  var digits = value < 10 ? 2 : value < 100 ? 1 : 0;
  var parts = Number(value || 0).toFixed(digits).split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return '$' + parts.join('.');
}
function calculate(hosts, prices, now) {
  var date = now === undefined ? new Date() : new Date(now);
  var today = localDay(date), sevenDate = new Date(date), thirtyDate = new Date(date);
  sevenDate.setDate(sevenDate.getDate() - 6); thirtyDate.setDate(thirtyDate.getDate() - 29);
  var seven = localDay(sevenDate), thirty = localDay(thirtyDate);
  var result = {totals:zero(), providers:{claude:zero(), codex:zero()}, hosts:[], partial:false, stale:false, unpriced:[], unpricedTokens:{}, excluded:0};
  var unknown = {};
  (hosts || []).forEach(function(entry) {
    var row = {host: entry.host || 'this machine', status: entry.status || '', totals:zero()};
    result.hosts.push(row);
    if (!entry.usage || !entry.usage.days) {
      row.status = row.status === 'offline' ? 'offline' : 'waiting'; result.excluded++; result.partial = true; return;
    }
    var offline = row.status === 'offline';
    row.status = 'ready';
    var scanned = Date.parse(entry.usage.scanned_at);
    if (offline || entry.usage.stale === true || !isFinite(scanned) || date.getTime() - scanned > 45 * 60000) result.stale = true;
    if (entry.usage.partial) result.partial = true;
    Object.keys(entry.usage.days).forEach(function(hour) {
      var bucket = /^\d{4}-\d{2}-\d{2}T\d{2}$/.test(hour) ? new Date(hour + ':00:00Z') : null;
      var day = bucket && isFinite(bucket.getTime()) ? localDay(bucket) : hour;
      if (day < thirty || day > today) return;
      var models = entry.usage.days[hour] || {};
      Object.keys(models).forEach(function(key) {
        var slash = key.indexOf('/'), provider = key.slice(0, slash), model = key.slice(slash + 1);
        var rate = priceFor(prices, provider, model), tokens = models[key] || {};
        var fields = provider === 'claude' ? ['input','output','cache_read','cache_write_5m','cache_write_1h'] : ['input','cached_input','output'];
        function n(k) { return Math.max(0, Number(tokens[k]) || 0); }
        if (!fields.some(function(k) { return n(k) > 0; })) return;
        if (!rate || fields.some(function(k) { return typeof rate[k] !== 'number' || !isFinite(rate[k]) || rate[k] < 0; })) {
          unknown[key] = true;
          var count = Math.max(0, Number(tokens.input) || 0) + Math.max(0, Number(tokens.output) || 0);
          if (provider === 'claude') count += Math.max(0, Number(tokens.cache_read) || 0) + Math.max(0, Number(tokens.cache_write_5m) || 0) + Math.max(0, Number(tokens.cache_write_1h) || 0);
          result.unpricedTokens[key] = (result.unpricedTokens[key] || 0) + count;
          result.partial = true; return;
        }
        var cost = provider === 'claude' ? n('input')*rate.input + n('output')*rate.output + n('cache_read')*rate.cache_read + n('cache_write_5m')*rate.cache_write_5m + n('cache_write_1h')*rate.cache_write_1h : Math.max(0,n('input')-n('cached_input'))*rate.input + n('cached_input')*rate.cached_input + n('output')*rate.output;
        cost /= 1000000;
        [result.totals, result.providers[provider], row.totals].forEach(function(total) {
          if (!total) return;
          total.thirty += cost; if (day >= seven) total.seven += cost; if (day === today) total.today += cost;
        });
      });
    });
  });
  result.unpriced = Object.keys(unknown).sort();
  return result;
}
if (typeof module !== 'undefined') module.exports = {calculate:calculate, priceFor:priceFor, money:money, localDay:localDay};
