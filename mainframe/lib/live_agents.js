// Pure fleet aggregation for the live process snapshots.
function relativeDir(path) {
  if (typeof path !== 'string') return null;
  return path.replace(/^\/(?:home|Users)\/[^/]+(?=\/|$)/, '~').replace(/\/$/, '');
}
function remember(store, alias, live, nowMs, generation) {
  var next = Object.assign(Object.create(null), store || {});
  next[alias] = {live:live, receivedMs:nowMs, generation:generation};
  return next;
}
function summarize(entries, accounts, nowMs) {
  entries = Array.isArray(entries) ? entries : [];
  accounts = Array.isArray(accounts) ? accounts : (accounts && Array.isArray(accounts.accounts) ? accounts.accounts : []);
  var result = {total:0, truncated:false, reporting:0, hostsTotal:entries.length, hosts:[], providers:[], accounts:[]};
  var providers = Object.create(null), groups = Object.create(null);
  var known = ['claude', 'codex', 'gemini', 'qwen', 'grok', 'cursor-agent', 'opencode', 'aider', 'crush', 'amp'];
  function increment(map, key, make) { if (!map[key]) map[key] = make(); map[key].count++; }
  function stringField(value, limit) { return typeof value === 'string' && value.length <= limit ? value : null; }
  function numberField(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null; }
  function accountFor(session, entry) {
    if (session.billing === 'api') return session.provider + ' API key';
    var map = entry.accountMap, id = session.dir && map && Object.prototype.hasOwnProperty.call(map, session.dir) ? map[session.dir] : null;
    var account = id == null ? null : accounts.find(function(a) { return a && a.id === id; });
    if (!account && entry.local === true && session.dir) account = accounts.find(function(a) { return a && a.provider === session.provider && relativeDir(a.dir) === session.dir; });
    var label = account && typeof account.name === 'string' ? account.name : session.dir;
    return label || 'unknown ' + session.provider;
  }
  function sortProviders(a, b) { return b.count - a.count || String(a.provider).localeCompare(String(b.provider)); }
  entries.forEach(function(entry) {
    var host = {host:'unknown', count:0, cap:null, over:false, headless:0, providers:[], sessions:[], truncated:false, status:'not reporting'};
    try {
      if (!entry || typeof entry !== 'object') throw new Error('invalid host');
      host.host = typeof entry.host === 'string' ? entry.host : 'unknown';
      host.cap = numberField(entry.cap);
      var live = entry.live, status = entry.status || '';
      if (!live || typeof live !== 'object' || live.supported !== true || !Array.isArray(live.sessions) ||
          typeof entry.receivedMs !== 'number' || !Number.isFinite(entry.receivedMs) || nowMs - entry.receivedMs > 60000 ||
          ['unreachable', 'error', 'offline'].indexOf(status) >= 0) throw new Error('not reporting');
      var hostProviders = Object.create(null), hostGroups = Object.create(null);
      live.sessions.slice(0, 256).forEach(function(original) {
        if (!original || typeof original !== 'object' || Array.isArray(original)) throw new Error('invalid session');
        var provider = typeof original.provider === 'string' && known.indexOf(original.provider) >= 0 ? original.provider : 'unknown';
        var session = {provider:provider, dir:stringField(original.dir, 200), project:stringField(original.project, 120),
          billing:original.billing === 'api' || original.billing === 'subscription' ? original.billing : null,
          interactive:typeof original.interactive === 'boolean' ? original.interactive : null,
          pid:numberField(original.pid), parent_pid:numberField(original.parent_pid), age_s:numberField(original.age_s), rss:numberField(original.rss)};
        session.account = accountFor(session, entry);
        host.sessions.push(session);
        if (session.interactive === false) host.headless++;
        increment(hostProviders, provider, function() { return {provider:provider, count:0}; });
        var key = JSON.stringify([provider, session.account, session.billing]);
        increment(hostGroups, key, function() { return {label:session.account, provider:provider, count:0, billing:session.billing}; });
      });
      host.truncated = live.truncated === true || live.sessions.length > 256;
      host.count = host.truncated ? 256 : host.sessions.length;
      host.providers = Object.keys(hostProviders).map(function(k) { return hostProviders[k]; }).sort(sortProviders);
      host.over = host.cap !== null && (host.truncated ? host.count >= host.cap : host.count > host.cap);
      host.status = 'reporting';
      result.reporting++; result.total += host.count; result.truncated = result.truncated || host.truncated;
      Object.keys(hostProviders).forEach(function(k) { if (!providers[k]) providers[k] = {provider:k, count:0}; providers[k].count += hostProviders[k].count; });
      Object.keys(hostGroups).forEach(function(k) { if (!groups[k]) groups[k] = hostGroups[k]; else groups[k].count += hostGroups[k].count; });
    } catch (err) {
      host.count = 0; host.over = false; host.headless = 0; host.providers = []; host.sessions = []; host.truncated = false; host.status = 'not reporting';
    }
    result.hosts.push(host);
  });
  result.providers = Object.keys(providers).map(function(k) { return providers[k]; }).sort(sortProviders);
  result.accounts = Object.keys(groups).map(function(k) { return groups[k]; }).sort(function(a, b) { return b.count - a.count || String(a.label).localeCompare(String(b.label)) || String(a.provider).localeCompare(String(b.provider)); });
  return result;
}
if (typeof module !== 'undefined') module.exports = {summarize:summarize, remember:remember};
