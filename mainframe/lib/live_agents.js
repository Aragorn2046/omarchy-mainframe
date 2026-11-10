// Pure fleet aggregation for the live process snapshots.
function relativeDir(path) {
  if (typeof path !== 'string') return null;
  return path.replace(/^\/(?:home|Users)\/[^/]+(?=\/|$)/, '~').replace(/\/$/, '');
}
function summarize(entries, accounts, nowMs) {
  entries = Array.isArray(entries) ? entries : [];
  accounts = Array.isArray(accounts) ? accounts : (accounts && accounts.accounts) || [];
  var result = {total:0, reporting:0, hostsTotal:entries.length, hosts:[], providers:[], accounts:[]};
  var providers = {}, groups = {};
  function increment(map, key, make) { if (!map[key]) map[key] = make(); map[key].count++; }
  function accountFor(session, map) {
    if (session.billing === 'api') return session.provider + ' API key';
    var id = session.dir && map && Object.prototype.hasOwnProperty.call(map, session.dir) ? map[session.dir] : null;
    var account = accounts.find(function(a) { return a && a.id === id; });
    if (!account && session.dir) account = accounts.find(function(a) { return a && a.provider === session.provider && relativeDir(a.dir) === session.dir; });
    return account ? account.name : session.dir || 'unknown';
  }
  entries.forEach(function(entry) {
    var live = entry.live, status = entry.status || '';
    var reporting = !!(live && live.supported === true && Array.isArray(live.sessions) && typeof live.at === 'number' && Number.isFinite(live.at) && nowMs - live.at * 1000 <= 60000 && ['unreachable', 'error', 'offline'].indexOf(status) < 0);
    var host = {host:entry.host, count:0, cap:entry.cap == null ? null : entry.cap, over:false, headless:0, providers:[], sessions:[], status:reporting ? 'reporting' : 'not reporting'};
    if (reporting) {
      result.reporting++;
      var hostProviders = {};
      live.sessions.forEach(function(original) {
        var session = Object.assign({}, original), provider = session.provider || 'unknown';
        session.account = accountFor(session, entry.accountMap);
        host.sessions.push(session); host.count++; result.total++;
        if (session.interactive === false) host.headless++;
        increment(hostProviders, provider, function() { return {provider:provider, count:0}; });
        increment(providers, provider, function() { return {provider:provider, count:0}; });
        var key = JSON.stringify([provider, session.account, session.billing || null]);
        increment(groups, key, function() { return {label:session.account, provider:provider, count:0, billing:session.billing || null}; });
      });
      host.providers = Object.keys(hostProviders).map(function(k) { return hostProviders[k]; }).sort(sortProviders);
      host.over = host.cap !== null && host.count > host.cap;
    }
    result.hosts.push(host);
  });
  function sortProviders(a, b) { return b.count - a.count || a.provider.localeCompare(b.provider); }
  result.providers = Object.keys(providers).map(function(k) { return providers[k]; }).sort(sortProviders);
  result.accounts = Object.keys(groups).map(function(k) { return groups[k]; }).sort(function(a, b) { return b.count - a.count || a.label.localeCompare(b.label) || a.provider.localeCompare(b.provider); });
  return result;
}
if (typeof module !== 'undefined') module.exports = {summarize:summarize};
