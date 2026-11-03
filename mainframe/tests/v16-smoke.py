#!/usr/bin/env python3
"""Exercise all 1.6 views without network or real user data."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='mf16-') as tmp:
    base=Path(tmp)
    for name in ('runtime','home','config/mainframe','state/omarchy/agents/usage','cache'):
        (base/name).mkdir(parents=True)
    (base/'runtime').chmod(0o700)
    (base/'config/mainframe/hosts.json').write_text(json.dumps({'hosts':[{'name':n,'ssh':n.lower().replace(' ', '-')} for n in ('Host A','Host B','Host C')]}))
    record={'name':'Fixture','updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'limits':[{'label':'Weekly','percent':0.3}]}
    (base/'state/omarchy/agents/usage/a.json').write_text(json.dumps(record))
    for width in (1800,900):
        for page in ('systems','storage','agents','settings'):
            env=dict(os.environ, HOME=str(base/'home'), XDG_CONFIG_HOME=str(base/'config'), XDG_STATE_HOME=str(base/'state'), XDG_CACHE_HOME=str(base/'cache'), XDG_RUNTIME_DIR=str(base/'runtime'), DBUS_SESSION_BUS_ADDRESS='unix:path='+str(base/'missing'), QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='', QSG_RENDER_LOOP='basic', MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_FIXTURE_LOCAL='1', MAINFRAME_SMOKE_NO_REMOTE='1', MAINFRAME_SMOKE_PAGE=page, MAINFRAME_SMOKE_W=str(width), MAINFRAME_SMOKE_H='1125', MAINFRAME_SMOKE_MS='1800')
            if page == 'settings': env['MAINFRAME_SMOKE_CONFIG_WRITE'] = '1'
            if page == 'storage':
                (base/'config/mainframe/hosts.json').write_text(json.dumps({'hosts':[{'name':n,'ssh':n.lower().replace(' ', '-')} for n in ('Host A','Host B','Host C','Node4','Node5')]}))
                env.pop('MAINFRAME_SMOKE_NO_REMOTE'); env['MAINFRAME_SMOKE_FAKE_REMOTE'] = '1'
            else:
                (base/'config/mainframe/hosts.json').write_text(json.dumps({'hosts':[{'name':n,'ssh':n.lower().replace(' ', '-')} for n in ('Host A','Host B','Host C')]}))
            env.pop('DISPLAY',None); env.pop('WAYLAND_DISPLAY',None)
            proc=subprocess.run(['qs','-p',str(root/'mainframe')],env=env,capture_output=True,text=True,timeout=15)
            log=proc.stdout+proc.stderr
            errors=[l for l in log.splitlines() if re.search(r'TypeError|ReferenceError|Binding loop|Cannot assign|Unable to assign|Failed to load configuration|Error: file:',l)]
            line=next((l for l in log.splitlines() if 'PAGE name=' in l),'')
            expected='systems' if page=='settings' else page
            if proc.returncode or f'PAGE name={expected}' not in line or (('rows=1' not in line) if page == 'agents' else ('rows=6' not in line or not re.search(r'drives=(1[5-9]|[2-9][0-9])',line)) if page == 'storage' else ('rows=4' not in line)) or 'overflow=0' not in line or errors:
                raise SystemExit(f'FAIL {width} {page}: {line}\n'+ '\n'.join(errors)+'\n'+log[-2000:])
            if page == 'settings' and json.loads((base/'config/mainframe/settings.json').read_text()) != {'overviewView':'systems','showUnavailable':True}: raise SystemExit('Settings write failed')
            print(f'PASS {width} {page}: {line.split("PAGE ",1)[1]}')
