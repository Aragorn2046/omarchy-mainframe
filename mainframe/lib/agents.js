// Load the same pure forecast functions in Node and QML.
var forecastForLimit;
if (typeof module !== 'undefined' && module.exports) forecastForLimit = require('./forecast.js').forecast;
else { Qt.include('forecast.js'); forecastForLimit = forecast; }
// Normalize each untrusted usage record without depending on its schema version.
function number(value) { return typeof value === 'number' && isFinite(value) && value >= 0 ? value : 0; }
function units(n) {
  n = number(n); var suffix = ['', 'K', 'M', 'B', 'T']; var i = 0;
  while (n >= 1000 && i < suffix.length - 1) { n /= 1000; i++; }
  return (i ? (Math.round(n * 10) / 10) : Math.round(n)) + suffix[i];
}
function age(updated, now) {
  var t = Date.parse(updated); if (!isFinite(t)) return { text: 'Update time unknown', stale: true };
  var mins = Math.max(0, Math.floor((now - t) / 60000));
  return { text: mins < 1 ? 'Updated just now' : 'Updated ' + mins + ' min ago', stale: now - t > 7200000 };
}
function reset(value, now) {
  var t = Date.parse(value); if (!isFinite(t)) return '';
  var mins = Math.ceil((t - now) / 60000); if (mins <= 0) return 'resets now';
  if (mins < 60) return 'resets in ' + mins + ' min';
  var hours = Math.floor(mins / 60); if (hours < 48) return 'resets in ' + hours + ' h ' + (mins % 60) + ' min';
  return 'resets in ' + Math.floor(hours / 24) + ' d ' + (hours % 24) + ' h';
}
function safeHelp(text) {
  if (typeof text !== 'string') return '';
  if (text.length > 4096) return '[redacted]';
  // Redact before truncating, so a secret crossing the display limit stays hidden.
  text = text.replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s<>]+/gi, function(url) {
    return /^[a-z][a-z0-9+.-]*:\/\/[^\/?#\s]*@/i.test(url) || /[?&](?:[^=&\s]*(?:token|key|secret|password|credential|auth)[^=&\s]*)=/i.test(url) ? '[redacted]' : url;
  });
  text = text.replace(/\bauthorization\s*:\s*[^\s,:;]+\s+(?:"[^"]*"|'[^']*'|[^\s,;]+)(?:\s*,\s*[\w-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s,;]+))*/gi, '[redacted]');
  text = text.replace(/\b(?:bearer|basic)\s*[: ]\s*[^\s,;]+/gi, '[redacted]');
  var tokens = /\b[\w-]+/g, assignment = /["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;&]+)/y, keyword = /key|token|secret|password|credential|auth/i;
  var match, result = '', start = 0;
  while ((match = tokens.exec(text))) {
    if (!keyword.test(match[0])) continue;
    assignment.lastIndex = tokens.lastIndex;
    if (assignment.exec(text)) {
      result += text.slice(start, match.index) + '[redacted]';
      start = tokens.lastIndex = assignment.lastIndex;
    }
  }
  text = result + text.slice(start);
  text = text.replace(/\b(?:hf_|pk_|sk-|xai-|ghp_|gho_|github_pat_|AIza|eyJ)[A-Za-z0-9+\/_=.-]*/g, '[redacted]');
  text = text.replace(/[A-Za-z0-9+\/_=.-]{20,}/g, '[redacted]');
  // Fail closed if a targeted replacement missed any known credential form.
  tokens.lastIndex = 0;
  assignment = /["']?\s*[:=]\s*\S+/y;
  while ((match = tokens.exec(text))) {
    if (keyword.test(match[0])) {
      assignment.lastIndex = tokens.lastIndex;
      if (assignment.test(text)) return '[redacted]';
    }
  }
  if (/\bBearer\s+\S+|\b(?:ghp|github_pat|hf|sk|pk|key|token)[_-][A-Za-z0-9_-]{8,}|\b[A-Za-z0-9_-]{24,}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|[?&](?:token|key|password|secret|credential|auth)=|\b(?:bearer|token|api[_ -]?key|secret|password)\s*[:=]\s*\S+|\b(?:sk|pk|key|token)[_-][A-Za-z0-9_-]{8,}|\b[a-z][a-z0-9+.-]*:\/\/[^\s/@]+@|\b[^\s/:@]+:[^\s/@]+@|\b(?:hf_|pk_|sk-|xai-|ghp_|gho_|github_pat_|AIza|eyJ)[A-Za-z0-9+\/_=.-]*|[A-Za-z0-9+\/_=.-]{20,}/i.test(text)) return '[redacted]';
  return text.slice(0, 200);
}
function activity(days, now) {
  var map = {}, out = [], i; if (!Array.isArray(days)) days = [];
  for (i = 0; i < days.length; i++) if (days[i] && typeof days[i].date === 'string') map[days[i].date.slice(0,10)] = number(days[i].messageCount);
  var date = new Date(now); var start = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  for (i = 13; i >= 0; i--) { var key = new Date(start - i * 86400000).toISOString().slice(0,10); out.push({date:key, count:map[key] || 0}); }
  return out;
}
function parse(text, filename, now) {
  var d; try { d = JSON.parse(text); if (!d || typeof d !== 'object' || Array.isArray(d)) throw 0; }
  catch (e) { return { name: safeHelp(filename) || 'Agent', unavailable: true, broken: true, age: '', stale: false, limits: [], models: [], activity: [] }; }
  var updated = age(d.updatedAt, now), limits = [], models = [], seenModels = Object.create(null), k, v;
  if (Array.isArray(d.limits)) d.limits.forEach(function(l) {
    if (!l || typeof l !== 'object') return;
    var pct = typeof l.percent === 'number' && isFinite(l.percent) ? Math.max(0, Math.min(100, l.percent)) : null;
    var history = Array.isArray(l.history) ? l.history.filter(function(p) { return Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && isFinite(p[0]) && p[0] * 1000 <= now && typeof p[1] === 'number' && isFinite(p[1]) && p[1] >= 0 && p[1] <= 100; }).sort(function(a, b) { return a[0] - b[0]; }).slice(-200) : [];
    var limit = {label:safeHelp(l.title) || safeHelp(l.label) || 'Limit', percent:pct, reset:reset(l.resetsAt, now), resetsAt:l.resetsAt, history:history, level:pct >= 95 ? 'Critical' : pct >= 80 ? 'Warning' : ''};
    limit.forecast = updated.stale ? null : forecastForLimit(limit, now); limits.push(limit);
  });
  if (d.modelUsage && typeof d.modelUsage === 'object' && !Array.isArray(d.modelUsage)) for (k in d.modelUsage) if (Object.prototype.hasOwnProperty.call(d.modelUsage,k)) { v=d.modelUsage[k]; if (!v || typeof v !== 'object') continue; seenModels[k] = true; models.push({name:safeHelp(k), input:number(v.inputTokens), output:number(v.outputTokens), cache:number(v.cacheReadInputTokens)+number(v.cacheCreationInputTokens)}); }
  if (d.todayTokensByModel && typeof d.todayTokensByModel === 'object') for (k in d.todayTokensByModel) if (Object.prototype.hasOwnProperty.call(d.todayTokensByModel,k) && !seenModels[k]) models.push({name:safeHelp(k), total:number(d.todayTokensByModel[k]), input:0, output:0, cache:0});
  models.sort(function(a,b) { return a.name.localeCompare(b.name); });
  var unavailable = d.ready === false || /unavailable|sign[ -]?in|not configured/i.test(String(d.usageStatusText || '')) || (!(Array.isArray(d.limits) && d.limits.length) && !d.modelUsage && !d.todayTokensByModel && !d.todayTotalTokens && !d.todayPrompts && !d.todaySessions && !(Array.isArray(d.recentDays) && d.recentDays.length));
  var hasToday = number(d.todayPrompts) || number(d.todaySessions) || number(d.todayTotalTokens) || (Array.isArray(d.recentDays) && d.recentDays.some(function(day) { return day && number(day.messageCount); }));
  return {category:category(d), showLocalStats:d.hasLocalStats !== false || !!hasToday, id:safeHelp(d.id), provider:safeHelp(d.provider), dir:safeHelp(d.dir), updatedAt:d.updatedAt || '', unavailable:unavailable, name:safeHelp(d.name) || safeHelp(d.id) || safeHelp(filename) || 'Agent', tier:safeHelp(d.tierLabel), broken:false, age:updated.text, stale:updated.stale, limits:limits, models:models, activity:activity(d.recentDays, now), prompts:number(d.todayPrompts), sessions:number(d.todaySessions), tokens:number(d.todayTotalTokens), status:safeHelp(d.usageStatusText), help:(d.usageStatusText || unavailable || !limits.length) ? safeHelp(d.authHelpText) : '', sharedStatsWith:safeHelp(d.sharedStatsWith), sharedProjectsFolder:d.sharedProjectsFolder === true};
}
function percent(n) { if (n == null || !isFinite(n)) return '—'; return (n > 0 && n < 1 ? Math.max(0.1, Math.round(n * 10) / 10).toFixed(1) : Math.round(n)) + '%'; }
function visible(items, show) {
  var shown = items.filter(function(x) { return show || !x.unavailable; });
  return shown.map(function(x) {
    if (!x.sharedStatsWith || shown.some(function(y) { return y !== x && y.name === x.sharedStatsWith; })) return x;
    var copy = {}; for (var key in x) if (Object.prototype.hasOwnProperty.call(x, key)) copy[key] = x[key];
    copy.sharedStatsWith = ''; return copy;
  });
}
var categories = {llm:['claude','codex','openai','gpt','grok','gemini','fireworks','openrouter','mistral','deepseek','qwen','kimi'], video:['higgsfield','runway','kling','pika','luma','sora','veo','seedance'], image:['midjourney','ideogram','leonardo','flux','stability'], voice:['elevenlabs','cartesia','playht','suno']};
function category(d) {
  var explicit = typeof d.category === 'string' ? d.category.toLowerCase() : '';
  if (['llm','video','image','voice','other'].indexOf(explicit) >= 0) return explicit;
  var fields = [d.provider, d.id, String(d.id || '').replace(/^\w+-/, ''), d.name];
  for (var i = 0; i < fields.length; i++) for (var kind in categories) for (var j = 0; j < categories[kind].length; j++)
    if (new RegExp('\\b' + categories[kind][j] + '\\b', 'i').test(String(fields[i] || '').replace(/_/g, ' '))) return kind;
  return 'other';
}
function provider(item) {
  var value = String(item.provider || '').toLowerCase();
  if (!value) value = String(item.id || '').replace(/^\w+-/, '').toLowerCase();
  if (!value) value = String(item.name || '').toLowerCase();
  var known = categories.llm;
  for (var i = 0; i < known.length; i++) if (new RegExp('\\b' + known[i] + '\\b', 'i').test(value)) return known[i];
  return value;
}
function sections(items) {
  var labels = [['llm','Language models'],['video','Video'],['image','Image'],['voice','Voice'],['other','Other']];
  return labels.map(function(pair) {
    var cards = items.filter(function(item) { return (item.category || 'other') === pair[0]; });
    cards.sort(function(a,b) {
      if (pair[0] === 'llm') {
        var x = provider(a), y = provider(b), rank = function(p) { return p === 'claude' ? 0 : p === 'codex' ? 1 : 2; };
        var difference = rank(x) - rank(y) || x.localeCompare(y);
        if (difference) return difference;
      }
      return a.name.localeCompare(b.name, undefined, {sensitivity:'base'});
    });
    return {key:pair[0], heading:pair[1], cards:cards};
  }).filter(function(section) { return section.cards.length > 0; });
}
// Place sections in horizontal bands, then pack cards within their columns.
function pack(blocks, width, options) {
  options = options || {};
  var gap = options.gap === undefined ? 10 : options.gap;
  var pixelGap = Math.floor(gap);
  var minWidth = options.minCardWidth === undefined ? 340 : options.minCardWidth;
  var maxColumns = options.maxColumns === undefined ? 6 : options.maxColumns;
  width = isFinite(width) ? Math.max(0, Math.floor(width)) : 0;
  var columns = Math.max(1, Math.min(maxColumns, Math.floor((width + gap) / (minWidth + gap))));
  var available = width - (columns - 1) * pixelGap;
  var columnWidth = Math.floor(available / columns), extra = available - columnWidth * columns;
  var starts = [], widths = [], result = [], bands = [], band = null, i, nextX = 0;
  for (i = 0; i < columns; i++) {
    starts.push(nextX); widths.push(columnWidth + (i < extra ? 1 : 0));
    nextX += widths[i] + pixelGap;
  }
  blocks.forEach(function(block, index) {
    var desired = Math.min(block.cardHeights.length, columns);
    if (!desired) {
      result[index] = {key:block.key, x:0, y:0, width:0, heading:{x:0, y:0, width:0}, cards:[]};
      return;
    }
    if (!band || columns - band.used < Math.ceil(desired / 2)) {
      band = {used:0, headingHeight:0, hasHeading:false, sections:[]};
      bands.push(band);
    }
    var span = Math.min(desired, columns - band.used);
    band.sections.push({block:block, index:index, start:band.used, span:span});
    band.used += span;
    if (!block.noHeading) {
      band.hasHeading = true;
      band.headingHeight = Math.max(band.headingHeight, number(block.headingHeight));
    }
  });
  var top = 0, bottom = 0;
  bands.forEach(function(current) {
    var cardTop = top + (current.hasHeading ? current.headingHeight + gap : 0), skyline = [], liveColumn = -1;
    for (var c = 0; c < columns; c++) skyline.push(cardTop);
    current.sections.forEach(function(section) {
      var block = section.block, start = section.start, last = start + section.span - 1;
      var headingX = starts[start], headingWidth = starts[last] + widths[last] - headingX;
      var cards = [], minColumn = start, maxColumn = last;
      block.cardHeights.forEach(function(height) {
        height = number(height);
        var chosen = start;
        for (var k = start + 1; k <= last; k++) if (skyline[k] < skyline[chosen]) chosen = k;
        if (block.flowAround && liveColumn >= 0 && skyline[liveColumn] < skyline[chosen]) chosen = liveColumn;
        cards.push({x:starts[chosen], y:skyline[chosen], width:widths[chosen], height:height});
        minColumn = Math.min(minColumn, chosen); maxColumn = Math.max(maxColumn, chosen);
        bottom = Math.max(bottom, skyline[chosen] + height);
        skyline[chosen] += height + gap;
      });
      liveColumn = block.noHeading && section.span === 1 && block.cardHeights.length === 1 ? start : -1;
      result[section.index] = {key:block.key, x:starts[minColumn], y:top,
        width:starts[maxColumn] + widths[maxColumn] - starts[minColumn],
        heading:{x:headingX, y:top, width:headingWidth}, cards:cards};
    });
    top = bottom + gap;
  });
  return {columns:columns, columnWidth:columnWidth, height:bottom, blocks:result};
}
function sorted(items) { return items.slice().sort(function(a,b) { return a.name.localeCompare(b.name, undefined, {sensitivity:'base'}); }); }
var api = {percent:percent, visible:visible, parse:parse, sorted:sorted, age:age, reset:reset, units:units, activity:activity, safeHelp:safeHelp, category:category, sections:sections, pack:pack};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
