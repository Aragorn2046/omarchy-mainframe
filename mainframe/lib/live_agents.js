// Pure fleet aggregation for the live process snapshots.
function relativeDir(path, homeDir) {
  if (typeof path !== 'string') return null;
  var home = typeof homeDir === 'string' ? homeDir.replace(/\/+$/, '') : '';
  return (home && (path === home || path.indexOf(home + '/') === 0) ? '~' + path.slice(home.length) : path).replace(/\/$/, '');
}
function normalizeDir(path) {
  if (typeof path !== 'string') return null;
  var normalized = path.replace(/\/\.(?=\/|$)/g, '').replace(/\/+$/, '');
  return normalized || (path.charAt(0) === '/' ? '/' : '');
}
function buildEntries(hosts, sessions, config, settings, local, remote, localSilent) {
  hosts = Array.isArray(hosts) ? hosts : [];
  sessions = sessions || {}; config = Array.isArray(config) ? config : []; settings = settings || {}; remote = remote || {};
  var entries = [{host:'this machine', local:true, live:local && local.live, receivedMs:local && local.receivedMs, cap:settings.localAgentCap, status:localSilent ? 'unreachable' : ''}];
  hosts.forEach(function(host) {
    var session = sessions[host.ssh], report = remote[host.ssh];
    var configured = config.find(function(item) { return item && item.ssh === host.ssh; }) || {};
    var current = report && session && report.generation === session.generation;
    entries.push({host:host.name, alias:host.ssh, live:current ? report.live : null, receivedMs:current ? report.receivedMs : null,
      cap:configured.agentCap, accountMap:configured.agentAccounts, status:session ? session.phase : 'unreachable'});
  });
  return entries;
}
function normalizeAccounts(accounts, homeDir) {
  return (Array.isArray(accounts) ? accounts : []).map(function(account) {
    var copy = Object.assign({}, account);
    if (typeof copy.dir === 'string') copy.dir = relativeDir(copy.dir, homeDir);
    return copy;
  });
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
  var known = ['claude', 'codex', 'gemini', 'qwen', 'grok', 'cursor-agent', 'opencode', 'aider', 'crush'];
  function increment(map, key, make) { if (!map[key]) map[key] = make(); map[key].count++; }
  function stringField(value, limit) { return typeof value === 'string' && value.length <= limit ? value : null; }
  function numberField(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null; }
  function accountFor(session, entry, hostName) {
    var map = entry.accountMap, dir = normalizeDir(session.dir);
    var mapKey = dir && map ? Object.keys(map).find(function(key) { return normalizeDir(key) === dir; }) : null;
    var id = mapKey != null ? map[mapKey] : null;
    var account = id == null ? null : accounts.find(function(a) { return a && a.id === id && a.provider === session.provider; });
    if (!account && entry.local === true && dir) account = accounts.find(function(a) { return a && a.provider === session.provider && normalizeDir(a.dir) === dir; });
    if (account && typeof account.name === 'string' && account.name) return {label:account.name + (session.billing === 'api' ? ' (API key)' : ''), id:account.id, scope:null};
    if (session.billing === 'api') return {label:session.provider + ' API key', scope:null};
    return {label:(session.dir || 'unknown ' + session.provider) + ' · ' + hostName, scope:entry.alias || hostName};
  }
  function sortProviders(a, b) { return b.count - a.count || String(a.provider).localeCompare(String(b.provider)); }
  entries.forEach(function(entry) {
    var host = {host:'unknown', count:0, invalid:0, cap:null, over:false, headless:0, providers:[], sessions:[], truncated:false, status:'not reporting'};
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
        if (!original || typeof original !== 'object' || Array.isArray(original)) { host.invalid++; return; }
        var provider = typeof original.provider === 'string' && known.indexOf(original.provider) >= 0 ? original.provider : 'unknown';
        var session = {provider:provider, dir:stringField(original.dir, 200), project:stringField(original.project, 120),
          billing:original.billing === 'api' ? 'api' : null,
          interactive:typeof original.interactive === 'boolean' ? original.interactive : null,
          pid:numberField(original.pid), parent_pid:numberField(original.parent_pid), age_s:numberField(original.age_s), rss:numberField(original.rss)};
        var account = accountFor(session, entry, host.host);
        session.account = account.label;
        host.sessions.push(session);
        if (session.interactive === false) host.headless++;
        increment(hostProviders, provider, function() { return {provider:provider, count:0}; });
        var key = account.id != null ? JSON.stringify(['account', account.id, session.billing]) : JSON.stringify([provider, session.account, session.billing, account.scope]);
        increment(hostGroups, key, function() { return {label:session.account, provider:provider, count:0, billing:session.billing}; });
        if (hostGroups[key].billing !== session.billing) hostGroups[key].billing = null;
      });
      host.truncated = live.truncated === true || live.sessions.length > 256;
      host.count = host.sessions.length;
      host.providers = Object.keys(hostProviders).map(function(k) { return hostProviders[k]; }).sort(sortProviders);
      host.over = host.cap !== null && (host.truncated ? host.count >= host.cap : host.count > host.cap);
      host.status = 'reporting';
      result.reporting++; result.total += host.count; result.truncated = result.truncated || host.truncated;
      Object.keys(hostProviders).forEach(function(k) { if (!providers[k]) providers[k] = {provider:k, count:0}; providers[k].count += hostProviders[k].count; });
      Object.keys(hostGroups).forEach(function(k) { if (!groups[k]) groups[k] = hostGroups[k]; else { groups[k].count += hostGroups[k].count; if (groups[k].billing !== hostGroups[k].billing) groups[k].billing = null; } });
    } catch (err) {
      host.count = 0; host.over = false; host.headless = 0; host.providers = []; host.sessions = []; host.truncated = false; host.status = 'not reporting';
    }
    result.hosts.push(host);
  });
  result.providers = Object.keys(providers).map(function(k) { return providers[k]; }).sort(sortProviders);
  result.accounts = Object.keys(groups).map(function(k) { return groups[k]; }).sort(function(a, b) { return b.count - a.count || String(a.label).localeCompare(String(b.label)) || String(a.provider).localeCompare(String(b.provider)); });
  return result;
}
if (typeof module !== 'undefined') module.exports = {summarize:summarize, remember:remember, relativeDir:relativeDir, normalizeAccounts:normalizeAccounts, buildEntries:buildEntries};
