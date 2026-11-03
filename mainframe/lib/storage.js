// Pure view model; shared by QML and the Node tests.
var ORDER = ["System & other", "Apps", "Games", "Documents", "Images", "Videos", "Music", "Downloads & archives", "Caches & trash", "Other", "Free"];
function patternInk(hex) {
  var n = parseInt(String(hex || "#777777").slice(1), 16);
  var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return (r * 0.299 + g * 0.587 + b * 0.114) > 150 ? "rgba(0,0,0,0.4)" : "rgba(255,255,255,0.5)";
}
function ageText(timestamp, now) {
  if (!timestamp) return "Not scanned yet";
  var minutes = Math.max(0, Math.floor((now / 1000 - timestamp) / 60));
  return minutes < 1 ? "Scanned just now" : "Scanned " + minutes + " min ago";
}
function model(data, palette, distance) {
  data = data || {};
  var categories = data.categories || {}, total = isFinite(Number(data.total)) ? Math.max(0, Number(data.total) || 0) : 0;
  var free = Math.min(total, Math.max(0, Number(data.free) || 0));
  var suppliedUsed = data.used === null || data.used === undefined ? NaN : Number(data.used);
  var used = isFinite(suppliedUsed) && suppliedUsed >= 0 && suppliedUsed <= total ? suppliedUsed : total - free;
  var values = {}, known = 0, key, i;
  for (key in categories) if (Object.prototype.hasOwnProperty.call(categories, key)) {
    var target = ORDER.indexOf(key) >= 0 && key !== "System & other" && key !== "Free" ? key : "Other";
    values[target] = (values[target] || 0) + (isFinite(Number(categories[key])) ? Math.max(0, Number(categories[key])) : 0);
  }
  for (key in values) if (Object.prototype.hasOwnProperty.call(values, key)) known += values[key];
  // Filesystem snapshots and allocated blocks can diverge during a scan.
  var scale = known > used && known > 0 ? used / known : 1;
  for (key in values) if (Object.prototype.hasOwnProperty.call(values, key)) values[key] *= scale;
  // Reserved blocks are neither reported used nor available as free.
  values["System & other"] = Math.max(0, used - known * scale) + Math.max(0, total - used - free);
  values.Free = free;
  var candidates = [], names = ["accent", "cyan", "yellow", "red", "green", "blue", "magenta", "orange", "color1", "color2", "color3", "color4", "color5", "color6"];
  for (i = 0; i < names.length; i++) {
    var c = palette && palette[names[i]];
    if (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c) && candidates.indexOf(c) < 0) candidates.push(c);
  }
  if (!candidates.length) candidates.push("#7aa2f7");
  var neutral = palette && /^#[0-9a-f]{6}$/i.test(palette.muted || "") ? palette.muted : "#707880";
  // If snapshots overlap, preserve byte values while fitting the bar to its width.
  var displayTotal = Math.max(total, used + free);
  var rows = [], prev = null, fractions = [], sum = 0;
  for (i = 0; i < ORDER.length; i++) {
    var name = ORDER[i], value = values[name] || 0;
    if (name === "Other" && !value) continue;
    var color = neutral;
    if (name !== "Free") {
      color = candidates[i % candidates.length];
      if (prev && distance(prev, color) < 15) {
        var best = -1;
        for (var k = 0; k < candidates.length; k++) {
          var d = distance(prev, candidates[k]);
          if (d > best) { best = d; color = candidates[k]; }
        }
      }
    }
    var exact = displayTotal > 0 ? value * 100 / displayTotal : 0;
    var rounded = Math.floor(exact); sum += rounded;
    var row = { name: name, value: value, fraction: displayTotal ? value / displayTotal : 0, percent: rounded, color: color, pattern: false };
    rows.push(row); fractions.push({ index: rows.length - 1, remainder: exact - rounded });
    if (value > 0) prev = color;
  }
  fractions.sort(function(a,b) { return b.remainder - a.remainder || a.index - b.index; });
  if (total) for (i = 0; i < 100 - sum && i < fractions.length; i++) rows[fractions[i].index].percent++;
  var prior = null;
  for (i = 0; i < rows.length; i++) if (rows[i].value > 0) {
    if (prior && distance(prior.color, rows[i].color) < 15) rows[i].pattern = !prior.pattern;
    prior = rows[i];
  }
  return rows;
}
if (typeof module !== "undefined" && module.exports) module.exports = { ORDER: ORDER, model: model, ageText: ageText, patternInk: patternInk };
