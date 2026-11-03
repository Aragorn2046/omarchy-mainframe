#!/usr/bin/env python3
"""Offscreen storage view smoke test, using a fixture cache."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[2]
tmp = os.environ.get('TMPDIR') or str(root)
with tempfile.TemporaryDirectory(prefix='.r', dir=root) as runtime, tempfile.TemporaryDirectory(prefix='storage-smoke-', dir=tmp) as temp:
    base = Path(temp)
    for name in ('config', 'cache/mainframe'):
        (base / name).mkdir(parents=True)
    Path(runtime).chmod(0o700)
    fixture = {'timestamp': time.time(), 'total': 1000000000, 'used': 700000000, 'free': 300000000,
               'categories': {'Apps': 100000000, 'Games': 50000000, 'Documents': 25000000,
                              'Images': 35000000, 'Videos': 45000000, 'Music': 15000000,
                              'Downloads & archives': 55000000, 'Caches & trash': 25000000, 'Other': 15000000}}
    (base / 'cache/mainframe/storage.json').write_text(json.dumps(fixture))
    for width in (1800, 900):
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_CONFIG_HOME=str(base / 'config'),
                   XDG_CACHE_HOME=str(base / 'cache'), XDG_RUNTIME_DIR=runtime,
                   MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_STORAGE='1', MAINFRAME_SMOKE_STORAGE_MONO='1', MAINFRAME_SMOKE_W=str(width),
                   MAINFRAME_SMOKE_H='1125', MAINFRAME_SMOKE_MS='1500')
        env.pop('WAYLAND_DISPLAY', None)
        proc = subprocess.run(['qs', '-p', str(root / 'mainframe')], env=env, capture_output=True, text=True, timeout=15)
        log = proc.stdout + proc.stderr
        line = next((line for line in log.splitlines() if 'STORAGE w=' in line), '')
        errors = [line for line in log.splitlines() if re.search(r'TypeError|ReferenceError|Binding loop|Cannot assign|Error:', line)]
        if proc.returncode or not line or 'visible=1' not in line or 'data=1' not in line or 'rows=11' not in line or not re.search(r'patterns=[1-9]', line) or 'overflow=0' not in line or errors:
            print('FAIL', width, line, '\n'.join(errors), log[-3000:])
            sys.exit(1)
        print('PASS', width, line.split('STORAGE ', 1)[1])

    # A stale cache starts a real child scan; closing the view must stop its group.
    (base / 'cache/mainframe/storage.json').unlink()
    home = base / 'home'
    home.mkdir()
    for i in range(1000):
        (home / ('item-%d.txt' % i)).write_text('fixture')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_CONFIG_HOME=str(base / 'config'),
               XDG_CACHE_HOME=str(base / 'cache'), XDG_RUNTIME_DIR=runtime, HOME=str(home),
               MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_STORAGE='1', MAINFRAME_SMOKE_STORAGE_CANCEL='1',
               MAINFRAME_SMOKE_W='900', MAINFRAME_SMOKE_H='1125', MAINFRAME_SMOKE_MS='2000')
    env.pop('WAYLAND_DISPLAY', None)
    proc = subprocess.run(['qs', '-p', str(root / 'mainframe')], env=env, capture_output=True, text=True, timeout=15)
    log = proc.stdout + proc.stderr
    match = re.search(r'STORAGE_SCAN pid=(\d+)', log)
    if proc.returncode or not match or 'STORAGE_CANCEL closed=1' not in log:
        print('FAIL cancellation', log[-3000:])
        sys.exit(1)
    try:
        os.killpg(int(match.group(1)), 0)
    except ProcessLookupError:
        print('PASS closing Storage stops scanner process group')
    else:
        print('FAIL scanner process group survived closing Storage')
        sys.exit(1)
