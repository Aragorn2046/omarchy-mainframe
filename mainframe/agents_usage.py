#!/usr/bin/env python3
"""Read usage files only. Do not follow file symlinks outside the usage directory."""
import json
import math
import os
from pathlib import Path
import sys
import stat
import time
import datetime
import secrets

MAX_JSON_DEPTH = 128

def json_depth_ok(text):
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in '[{':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return False
        elif char in ']}':
            depth = max(0, depth - 1)
    return True

base = Path(os.environ.get('XDG_STATE_HOME') or (str(Path.home()) + '/.local/state')) / 'omarchy/agents/usage'
records = []
try:
    directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    with os.scandir(directory) as entries:
        for entry in sorted((entry for entry in entries if entry.name.endswith('.json')), key=lambda entry: entry.name)[:64]:
            try:
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    import stat
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError('not a regular file')
                    raw = stream.read(256 * 1024 + 1)
                    if len(raw) > 256 * 1024:
                        raise ValueError('file too large')
                    raw = raw.decode('utf-8')
                records.append({'file': entry.name, 'raw': raw})
            except (OSError, ValueError, UnicodeError):
                records.append({'file': entry.name, 'raw': ''})
except OSError:
    pass
finally:
    if 'directory' in locals():
        os.close(directory)
# Read Mainframe account records with the same no-symlink and size rules.
cache = Path(os.environ.get('XDG_CACHE_HOME') or (str(Path.home()) + '/.cache')) / 'mainframe/agents'
try:
    directory = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    with os.scandir(directory) as entries:
        for entry in sorted((entry for entry in entries if entry.name.endswith('.json')), key=lambda entry: entry.name)[:64]:
            try:
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    import stat
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): continue
                    raw = stream.read(256 * 1024 + 1)
                if len(raw) <= 256 * 1024: records.append({'file': entry.name, 'raw': raw.decode('utf-8'), 'mainframe': True})
            except (OSError, ValueError, UnicodeError): pass
except OSError: pass
finally:
    if 'directory' in locals():
        try: os.close(directory)
        except OSError: pass

def identity(d):
    try:
        if not isinstance(d, dict): return None
        d = d.copy()
        # Account-specific Omarchy ids identify a provider, but not its directory.
        account_id = str(d.get('id') or '').lower()
        provider = str(d.get('provider') or '').lower()
        if not provider:
            for candidate in ('claude', 'codex'):
                if account_id == candidate or account_id.startswith(candidate + '-'):
                    provider = candidate
                    break
        if not isinstance(d.get('dir'), str):
            d.pop('dir', None)
        if provider in ('claude', 'codex'):
            d['provider'] = provider
            if not d.get('dir') and account_id == provider:
                d['dir'] = str(Path.home() / ('.claude' if provider == 'claude' else '.codex'))
        return d
    except (ValueError, TypeError, RecursionError, MemoryError): return None

# If any valid percent exceeds 1, the record uses 0..100; otherwise it uses 0..1.
# A 0..100 record with all values <= 1 is ambiguous and read as fractions; Omarchy
# helpers and state files always write fractions, so this only affects non-Omarchy files.
# config_manager's data.update uses the account provider, so command caches remain
# provider 'command' even if command output claims 'claude'; never scale them.
def normalize_limits(record):
    limits = record.get('limits')
    if not isinstance(limits, list): return False
    changed = False
    valid = []
    for limit in limits:
        if not isinstance(limit, dict): continue
        if 'percent' not in limit: continue
        value = limit['percent']
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                (isinstance(value, float) and not math.isfinite(value)) or value < 0):
            del limit['percent']
            changed = True
            continue
        valid.append((limit, value))
    percentages = any(value > 1 for _, value in valid)
    for limit, value in valid:
        normalized = min(value, 100) if percentages else round(value * 100, 2)
        if normalized != value:
            limit['percent'] = normalized
            changed = True
    return changed

# Rewrite raw only on change; every read starts from disk, never normalized output.
# Configured records are anchors; choose the strongest direct match for each
# Omarchy record before merging any unanchored records.
parsed = []
for item in records:
    try:
        if not json_depth_ok(item['raw']):
            item['raw'] = ''
            parsed.append(None)
            continue
        record = json.loads(item['raw'])
        if (isinstance(record, dict) and
                (not item.get('mainframe') or record.get('provider') in ('claude', 'codex')) and
                normalize_limits(record)):
            item['raw'] = json.dumps(record, ensure_ascii=True)
        parsed.append(record)
    except ValueError:
        parsed.append(None)
    except (RecursionError, MemoryError):
        item['raw'] = ''
        parsed.append(None)
identities = [identity(item) for item in parsed]
groups = {i: [i] for i, item in enumerate(records) if item.get('mainframe')}

realpaths = {}
def realpath(path):
    if path not in realpaths:
        try:
            realpaths[path] = os.path.realpath(path)
        except (ValueError, OSError):
            realpaths[path] = None
    if realpaths[path] is None:
        raise ValueError('invalid path')
    return realpaths[path]

def match_strength(d, o):
    if not d or not o or str(d.get('provider') or '').casefold() != str(o.get('provider') or '').casefold():
        return 0
    if d.get('id') and d.get('id') == o.get('id'):
        return 3
    try:
        if d.get('provider') and d.get('dir') and o.get('dir') and realpath(os.path.expanduser(d['dir'])) == realpath(os.path.expanduser(o['dir'])):
            return 2
    except (ValueError, OSError):
        pass
    if d.get('name') and str(d['name']).casefold() == str(o.get('name', '')).casefold():
        return 1
    return 0

unmatched = []
for i, item in enumerate(records):
    if item.get('mainframe'):
        continue
    matches = [(match_strength(identities[i], identities[j]), j) for j in groups]
    strength, anchor = max(matches, default=(0, -1))
    if strength:
        groups[anchor].append(i)
    else:
        unmatched.append(i)
# Preserve transitive merging for records without a configured anchor, without
# letting an unconfigured record bridge two configured accounts.
parents = {i: i for i in unmatched}
def find(i):
    while parents[i] != i:
        parents[i] = parents[parents[i]]
        i = parents[i]
    return i

for pos, i in enumerate(unmatched):
    for j in unmatched[:pos]:
        if match_strength(identities[i], identities[j]):
            parents[find(i)] = find(j)
for i in unmatched:
    groups.setdefault(find(i), []).append(i)

def freshness(i):
    updated = (identities[i] or {}).get('updatedAt')
    return (isinstance(updated, str), updated if isinstance(updated, str) else '',
            bool(records[i].get('mainframe')))

merged = []
for group in groups.values():
    winner = max(group, key=freshness)
    item = records[winner].copy()
    raw = parsed[winner].copy() if isinstance(parsed[winner], dict) else None
    configured = [i for i in group if records[i].get('mainframe') and identities[i] is not None]
    if configured and not item.get('mainframe'):
        source = parsed[max(configured, key=freshness)]
        changed = False
        for key in ('id', 'name', 'provider', 'dir', 'configHash'):
            if key in source and (key not in raw or raw[key] != source[key]):
                raw[key] = source[key]
                changed = True
        if changed:
            try:
                item['raw'] = json.dumps(raw, ensure_ascii=True)
            except (ValueError, RecursionError, MemoryError):
                item['raw'] = ''
                raw = None
    merged.append((item, raw))
# The default Claude account owns shared projects when its record is present.
default_dir = realpath(str(Path.home() / '.claude'))
for i, (item, raw) in enumerate(merged):
    d = identity(raw)
    if not d or d.get('provider') != 'claude' or not d.get('dir'):
        continue
    try:
        directory = realpath(os.path.expanduser(d['dir']))
        if directory != default_dir:
            continue
        path = realpath(os.path.join(directory, 'projects'))
        for j, (_, earlier) in enumerate(merged[:i]):
            other = identity(earlier)
            if (other and other.get('provider') == 'claude' and other.get('dir') and
                    realpath(os.path.join(os.path.expanduser(other['dir']), 'projects')) == path):
                merged.insert(j, merged.pop(i))
                break
    except (ValueError, OSError):
        continue
    break
# Configured projects folders determine sharing; use history only without a directory.
histories, folders = {}, {}
for item, raw in merged:
    original_shared = {key: raw[key] for key in ('sharedStatsWith', 'sharedProjectsFolder') if key in raw} if isinstance(raw, dict) else {}
    if isinstance(raw, dict) and ('sharedStatsWith' in raw or 'sharedProjectsFolder' in raw):
        raw.pop('sharedStatsWith', None)
        raw.pop('sharedProjectsFolder', None)
    d = identity(raw)
    if d and d.get('provider') in ('claude', 'codex') and isinstance(d.get('name'), str) and d.get('dir'):
        try:
            key = (d['provider'], realpath(os.path.join(os.path.expanduser(d['dir']), 'projects')))
            if key in folders:
                raw['sharedStatsWith'] = folders[key]
                raw['sharedProjectsFolder'] = True
            elif d['name']:
                folders[key] = d['name']
        except (ValueError, OSError):
            pass
    elif d and d.get('provider') in ('claude', 'codex') and isinstance(d.get('name'), str):
        days = d.get('recentDays') if isinstance(d.get('recentDays'), list) else []
        models = d.get('modelUsage') if isinstance(d.get('modelUsage'), dict) else {}
        active_days = len({day['date'] for day in days if isinstance(day, dict) and isinstance(day.get('date'), str) and day['date'] and any(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in day.values())})
        tokens = sum(v for model in models.values() if isinstance(model, dict) for k, v in model.items() if k in ('inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens') and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0)
        if active_days >= 2 and tokens >= 1000000:
            key = (d['provider'], json.dumps(days, sort_keys=True), json.dumps(models, sort_keys=True))
            if key in histories:
                raw['sharedStatsWith'] = histories[key]
            elif d['name']:
                histories[key] = d['name']
    current_shared = {key: raw[key] for key in ('sharedStatsWith', 'sharedProjectsFolder') if key in raw} if isinstance(raw, dict) else {}
    if original_shared != current_shared:
        item['raw'] = json.dumps(raw, ensure_ascii=True)
def _history_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _history_reset(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        result = parsed.timestamp()
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError, OSError):
        return None


def _history_directory():
    # Open each component relative to a verified directory, without following links.
    state = os.path.abspath(os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local/state'))
    parts = Path(state).parts[1:] + ('mainframe',)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _update_usage_history(merged, now):
    directory = _history_directory()
    temp_name = None
    try:
        data = {}
        try:
            fd = os.open('usage-history.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('not a regular file')
                contents = stream.read(512 * 1024 + 1)
            if len(contents) > 512 * 1024:
                raise ValueError('history too large')
            decoded = contents.decode('utf-8')
            if not json_depth_ok(decoded):
                raise ValueError('history too deep')
            data = json.loads(decoded)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, UnicodeError, RecursionError):
            data = {}
        clean = {}
        for key, samples in data.items():
            if not isinstance(key, str) or not isinstance(samples, list):
                continue
            valid = []
            for sample in samples:
                if not isinstance(sample, dict):
                    continue
                t, percent, reset = sample.get('time'), sample.get('percent'), sample.get('resetsAt')
                if (_history_number(t) and now - 8 * 86400 <= t <= now and _history_number(percent)
                        and 0 <= percent <= 100 and (reset is None or _history_number(reset))):
                    valid.append({'time': t, 'percent': percent, 'resetsAt': reset})
            if valid:
                clean[key] = sorted(valid, key=lambda sample: sample['time'])[-500:]
        for item, record in merged:
            if not isinstance(record, dict) or not isinstance(record.get('limits'), list):
                continue
            labels_seen = {}
            for limit in record['limits']:
                if not isinstance(limit, dict):
                    continue
                label = limit.get('title')
                if not isinstance(label, str) or not label:
                    label = limit.get('label')
                if not isinstance(label, str) or not label:
                    label = 'Limit'
                ident = record.get('id')
                if not isinstance(ident, str) or not ident:
                    ident = item['file']
                occurrence = labels_seen.get(label, 0)
                labels_seen[label] = occurrence + 1
                key = json.dumps([ident, label] if occurrence == 0 else [ident, label, occurrence], ensure_ascii=True, separators=(',', ':'))
                samples = clean.get(key, [])
                percent = limit.get('percent')
                reset = _history_reset(limit.get('resetsAt'))
                if _history_number(percent) and 0 <= percent <= 100:
                    if samples:
                        previous = samples[-1]
                        old_reset = previous['resetsAt']
                        if ((old_reset is not None and reset is not None and abs(reset - old_reset) > 3600)
                                or percent < previous['percent'] - 5):
                            samples = []
                    if (not samples or percent != samples[-1]['percent'] or reset != samples[-1]['resetsAt']
                            or now - samples[-1]['time'] >= 600):
                        samples.append({'time': now, 'percent': percent, 'resetsAt': reset})
                    clean[key] = samples[-500:]
                limit['history'] = [[sample['time'], sample['percent']] for sample in samples
                                    if sample['time'] >= now - 86400][-200:]
            item['raw'] = json.dumps(record, ensure_ascii=True)
        while len(clean) > 128:
            del clean[min(clean, key=lambda key: clean[key][-1]['time'])]
        encoded = json.dumps(clean, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        while len(encoded) > 512 * 1024 and clean:
            oldest = min(clean, key=lambda key: clean[key][0]['time'])
            clean[oldest].pop(0)
            if not clean[oldest]:
                del clean[oldest]
            encoded = json.dumps(clean, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        temp_name = '.usage-history-' + secrets.token_hex(12)
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
        os.replace(temp_name, 'usage-history.json', src_dir_fd=directory, dst_dir_fd=directory)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=directory)
            except OSError:
                pass
        os.close(directory)


try:
    _update_usage_history(merged, time.time())
except (OSError, ValueError, TypeError, OverflowError, RecursionError, MemoryError):
    pass
json.dump([item for item, _ in merged], sys.stdout, ensure_ascii=True)
