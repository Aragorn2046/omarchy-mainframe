#!/usr/bin/env python3
"""Validated settings and sequential, isolated account collectors."""
import json
import fcntl
import datetime
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'mainframe'
CACHE = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'mainframe' / 'agents'
ALIAS = re.compile(r'^[A-Za-z0-9._@-]{1,64}$')
ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
COLLECT_TIMEOUT = 60
COLLECT_MAX_BYTES = 2_000_000


def name_ok(value):
    return isinstance(value, str) and 1 <= len(value) <= 24 and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def validate(kind, data):
    if not isinstance(data, dict):
        raise ValueError('Expected an object')
    if kind == 'hosts':
        values = data.get('hosts')
        if not isinstance(values, list): raise ValueError('Expected hosts')
        seen = set()
        for item in values:
            if not isinstance(item, dict) or not name_ok(item.get('name')): raise ValueError('Invalid machine name')
            alias = item.get('ssh')
            if not isinstance(alias, str) or not ALIAS.fullmatch(alias) or any(p.startswith('-') for p in alias.split('@')) or alias in seen: raise ValueError('Invalid or duplicate SSH alias')
            seen.add(alias)
    elif kind == 'accounts':
        values = data.get('accounts')
        if not isinstance(values, list): raise ValueError('Expected accounts')
        seen = set()
        for item in values:
            if not isinstance(item, dict) or not name_ok(item.get('name')): raise ValueError('Invalid account name')
            ident, provider = item.get('id'), item.get('provider')
            if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen: raise ValueError('Invalid or duplicate account ID')
            seen.add(ident)
            if provider in ('claude', 'codex'):
                if not isinstance(item.get('dir'), str) or not item['dir'].strip() or '\x00' in item['dir']: raise ValueError('Account directory required')
            elif provider == 'command':
                cmd = item.get('command')
                if not isinstance(cmd, list) or not cmd or any(not isinstance(x, str) or not x or '\x00' in x for x in cmd): raise ValueError('Command must be a JSON argument list')
            else: raise ValueError('Unknown provider')
    elif kind == 'settings':
        if data.get('overviewView', 'systems') not in ('systems', 'storage', 'agents') or not isinstance(data.get('showUnavailable', False), bool): raise ValueError('Invalid display settings')
    else: raise ValueError('Unknown configuration')
    return data


def read_config(kind):
    defaults = {'hosts': {'hosts': []}, 'accounts': {'accounts': []}, 'settings': {'overviewView': 'systems', 'showUnavailable': False}}
    path = CONFIG / (kind + '.json')
    try:
        return validate(kind, json.loads(path.read_text())), None
    except FileNotFoundError as exc:
        if not os.path.lexists(path): return defaults[kind], None
        return defaults[kind], f'{path}: {exc}'
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return defaults[kind], f'{path}: {exc}'


def read(kind):
    return read_config(kind)[0]


def write(kind, data, replace_invalid=False):
    validate(kind, data)
    target = CONFIG / (kind + '.json')
    if target.is_symlink():
        raise ValueError(f'{kind}.json is a symbolic link; not overwriting it')
    _, error = read_config(kind)
    if error and replace_invalid is not True:
        raise ValueError(f'{error}. Fix or move the file before saving, or explicitly replace it.')
    CONFIG.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + kind + '-', dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, ensure_ascii=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def collect(account):
    # Refresh and the settings test may be requested at the same time.
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / '.collector.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _collect(account)


def config_hash(account):
    config = {key: account.get(key) for key in ('provider', 'dir', 'command')}
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _collect(account):
    validate('accounts', {'accounts': [account]})
    env = os.environ.copy()
    provider = account['provider']
    if provider == 'command':
        argv = account['command']
    else:
        exe = 'omarchy-agent-usage-' + provider
        candidate = Path(env.get('OMARCHY_PATH', '')) / 'bin' / exe if env.get('OMARCHY_PATH') else None
        argv = [str(candidate) if candidate and candidate.is_file() else (shutil.which(exe) or exe)]
        env['CLAUDE_CONFIG_DIR' if provider == 'claude' else 'CODEX_HOME'] = os.path.abspath(os.path.expanduser(account['dir']))
        env['XDG_CACHE_HOME'] = str(CACHE / account['id'])
    try:
        proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + COLLECT_TIMEOUT
            output = bytearray(COLLECT_MAX_BYTES + 1)
            used = 0
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining): return False
                    chunk = os.read(proc.stdout.fileno(), min(65536, COLLECT_MAX_BYTES + 1 - used))
                    if not chunk: break
                    output[used:used + len(chunk)] = chunk
                    used += len(chunk)
                    if used > COLLECT_MAX_BYTES: return False
            del output[used:]
            remaining = deadline - time.monotonic()
            if remaining <= 0: return False
            proc.wait(timeout=remaining)
        finally:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError): pass
            proc.stdout.close()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
        if proc.returncode != 0: raise ValueError('Invalid collector output')
        data = json.loads(output)
        if not isinstance(data, dict): raise ValueError('Expected a JSON record')
        data.update({'name': account['name'], 'id': account['id'], 'provider': provider, 'configHash': config_hash(account)})
        if provider != 'command': data['dir'] = os.path.realpath(os.path.expanduser(account['dir']))
        CACHE.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.' + account['id'] + '-', dir=CACHE)
        try:
            with os.fdopen(fd, 'w') as f: json.dump(data, f)
            os.replace(tmp, CACHE / (account['id'] + '.json'))
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return True
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
        return False


def refresh(force=False):
    try: os.nice(15)
    except OSError: pass
    success = True
    for account in read('accounts')['accounts']:
        path = CACHE / (account['id'] + '.json')
        try:
            stamp = path.stat().st_mtime
            with path.open(encoding='utf-8') as source:
                cached = json.load(source)
                updated = cached.get('updatedAt')
            if updated:
                stamp = datetime.datetime.fromisoformat(updated.replace('Z', '+00:00')).timestamp()
            fresh = ('configHash' not in cached or cached['configHash'] == config_hash(account)) and 0 <= time.time() - stamp < 600
        except (OSError, ValueError, TypeError, AttributeError, RecursionError): fresh = False
        if (force or not fresh) and not collect(account): success = False
    return success


def main():
    action = sys.argv[1]
    if action in ('refresh', 'test-account'):
        def terminate(_signum, _frame):
            raise SystemExit(128 + _signum)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
    if action == 'read':
        result, errors = {}, {}
        for kind in ('hosts', 'accounts', 'settings'):
            result[kind], error = read_config(kind)
            if error: errors[kind] = error
        result['errors'] = errors
        print(json.dumps(result))
    elif action == 'write':
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or 'kind' not in data or 'data' not in data:
            print(json.dumps({'ok': False, 'error': 'Expected an object with kind and data'})); return 2
        write(data['kind'], data['data'], data.get('replaceInvalid', False)); print('{"ok":true}')
    elif action == 'refresh':
        if not refresh('--force' in sys.argv): return 1
    elif action == 'test-account': print(json.dumps({'ok': collect(json.load(sys.stdin))}))
    elif action == 'test-host':
        alias = sys.argv[2]; validate('hosts', {'hosts': [{'name': 'Test', 'ssh': alias}]})
        start = time.monotonic()
        try:
            p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '--', alias, 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=17)
            print(json.dumps({'status': ('slow' if time.monotonic() - start >= 5 else 'reachable') if p.returncode == 0 else 'unreachable'}))
        except (OSError, subprocess.TimeoutExpired): print('{"status":"unreachable"}')


if __name__ == '__main__':
    try: sys.exit(main() or 0)
    except (ValueError, KeyError, IndexError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)})); sys.exit(1)
