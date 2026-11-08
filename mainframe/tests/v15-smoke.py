#!/usr/bin/env python3
"""Run the v1.5 views offscreen with isolated files and simulated unreachable hosts."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='mf15-') as tmp:
    base = Path(tmp)
    for name in ('runtime', 'home', 'config/mainframe', 'state/omarchy/agents/usage', 'cache'):
        (base / name).mkdir(parents=True)
    (base / 'runtime').chmod(0o700)
    (base / 'config/mainframe/hosts.json').write_text(json.dumps({'hosts': [{'name': n, 'ssh': n.lower().replace(' ', '-')} for n in ('Host A', 'Host B', 'Host C')]}))
    usage = base / 'state/omarchy/agents/usage'
    for i, name in enumerate(('Claude Alice', 'Claude Bob', 'Codex', 'Grok', 'Antigravity', 'ElevenLabs', 'Higgsfield')):
        record = {'name': name, 'tierLabel': 'Pro', 'updatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'todayPrompts': 15, 'todaySessions': 2, 'todayTotalTokens': 12000,
                  'limits': [{'label': 'Weekly', 'percent': 0.81, 'resetsAt': '2030-01-01T00:00:00Z'}],
                  'recentDays': [{'date': datetime.date.today().isoformat(), 'messageCount': 7}],
                  'modelUsage': {'model': {'inputTokens': 1000, 'outputTokens': 200, 'cacheReadInputTokens': 50}}}
        if i == 1:  # A short Claude card shares a row with a taller one.
            record.update(hasLocalStats=False, todayPrompts=0, todaySessions=0, todayTotalTokens=0,
                          recentDays=[], modelUsage={})
        (usage / f'{i}.json').write_text('{' if i == 6 else json.dumps(record))
    for width in (1800, 900):
        for page in ('overview', 'agents', 'sessions'):
            env = dict(os.environ, HOME=str(base/'home'), XDG_CONFIG_HOME=str(base/'config'),
                       XDG_STATE_HOME=str(base/'state'), XDG_CACHE_HOME=str(base/'cache'), XDG_RUNTIME_DIR=str(base/'runtime'),
                       DBUS_SESSION_BUS_ADDRESS='unix:path='+str(base/'missing-bus'), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='', QSG_RENDER_LOOP='basic', MAINFRAME_SMOKE='1',
                       MAINFRAME_SMOKE_NO_REMOTE='1', MAINFRAME_SMOKE_W=str(width), MAINFRAME_SMOKE_H='1125', MAINFRAME_SMOKE_MS='2200')
            env.pop('DISPLAY', None); env.pop('WAYLAND_DISPLAY', None)
            if page == 'sessions':
                env.pop('MAINFRAME_SMOKE_NO_REMOTE')
                env['MAINFRAME_SMOKE_FAKE_REMOTE'] = '1'
            if page == 'agents': env['MAINFRAME_SMOKE_PAGE'] = 'agents'
            else: env.pop('MAINFRAME_SMOKE_PAGE', None)
            proc = subprocess.run(['qs', '-p', str(root/'mainframe')], env=env, capture_output=True, text=True, timeout=15)
            log = proc.stdout + proc.stderr
            line = next((l for l in log.splitlines() if 'PAGE name=' in l), '')
            errors = [l for l in log.splitlines() if re.search(r'TypeError|ReferenceError|Binding loop|Cannot assign|Failed to load configuration|Error: file:', l)]
            view = 'systems' if page in ('sessions', 'overview') else page
            expected = f'PAGE name={view} rows={6 if page == "agents" else 4} overflow=0'
            extra = 'unreachable=3' if page == 'overview' else ('connected=4' if page == 'sessions' else 'broken=0')
            if proc.returncode or expected not in line or extra not in line or errors:
                raise SystemExit(f'FAIL {width} {page}: {line}\n' + '\n'.join(errors) + '\n' + log[-2500:])
            print(f'PASS {width} {page}: {line.split("PAGE ", 1)[1]}')
