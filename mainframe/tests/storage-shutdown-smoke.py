#!/usr/bin/env python3
"""Quit an offscreen Mainframe while its real storage scanner is active."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def scanners(home):
    found = []
    marker = ('HOME=' + str(home)).encode()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            environ = (entry / 'environ').read_bytes().split(b'\0')
            stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if marker in environ and b'--storage' in args and any(arg.endswith(b'/collect.py') for arg in args) and stat[0] != 'Z':
                found.append(int(entry.name))
        except (OSError, IndexError):
            continue
    return found


def main():
    faults = '--faults' in sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='.storage-shutdown-', dir=ROOT) as tmp:
        base = Path(tmp)
        app = ROOT / 'mainframe'
        if faults:
            app = base / 'mainframe'
            shutil.copytree(ROOT / 'mainframe', app, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shell = app / 'shell.qml'
            text = shell.read_text()
            injections = {
                'try { closeStorage() }': 'try { closeStorage(); throw new Error("injected storage failure") }',
                'try { stopRemotes() }': 'try { stopRemotes(); throw new Error("injected remote failure") }',
                'try { collector.write("quit\\n") }': 'try { collector.write("quit\\n"); throw new Error("injected collector failure") }',
                '&& storageCleaners === 0) Qt.quit()': '&& storageCleaners === 0 && false) Qt.quit()',
            }
            for old, new in injections.items():
                if text.count(old) != 1:
                    raise RuntimeError('cannot inject shutdown failure: ' + old)
                text = text.replace(old, new)
            shell.write_text(text)
        home = base / 'home'
        home.mkdir()
        (home / 'Documents').mkdir()
        (home / 'Documents' / 'fixture.txt').write_text('storage fixture')
        runtime = Path(tempfile.mkdtemp(prefix='mf-rt-'))
        try:
            # Reserve 32 bytes for Quickshell's generated instance ID.
            socket_path = runtime / 'quickshell' / 'by-id' / ('x' * 32) / 'ipc.sock'
            if len(os.fsencode(socket_path)) > 100:
                raise RuntimeError('Quickshell IPC socket path may exceed 100 bytes: %s' % socket_path)
            for name in ('config', 'cache', 'data', 'state'):
                (base / name).mkdir()
            env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM='offscreen',
                       XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(base / 'config'),
                       XDG_CACHE_HOME=str(base / 'cache'), XDG_DATA_HOME=str(base / 'data'),
                       XDG_STATE_HOME=str(base / 'state'), MAINFRAME_SMOKE='1',
                       MAINFRAME_SMOKE_STORAGE='1', MAINFRAME_SMOKE_STORAGE_QUIT='1',
                       MAINFRAME_SMOKE_MS='10000')
            env.pop('WAYLAND_DISPLAY', None)
            env.pop('MAINFRAME_SMOKE_STORAGE_CANCEL', None)
            log_path = base / 'qs.log'
            pid = None
            with log_path.open('w') as log_file:
                proc = subprocess.Popen(['qs', '-p', str(app)], env=env,
                                        stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 8
                    match = None
                    while time.monotonic() < deadline and proc.poll() is None:
                        match = re.search(r'STORAGE_QUIT pid=(\d+) running=1', log_path.read_text(errors='replace'))
                        if match:
                            break
                        time.sleep(.01)
                    if not match:
                        match = re.search(r'STORAGE_QUIT pid=(\d+) running=1', log_path.read_text(errors='replace'))
                    if not match:
                        raise AssertionError('no quit request while scanner was running')
                    pid = int(match.group(1))
                    started = time.monotonic()
                    try:
                        code = proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        raise AssertionError('qs did not exit within 3 seconds of the quit request')
                    elapsed = time.monotonic() - started
                    log = log_path.read_text(errors='replace')
                    if code != 0:
                        raise AssertionError('qs exited with %s' % code)
                    if re.search(r'ReferenceError|TypeError', log):
                        raise AssertionError('JavaScript error in log')
                    if faults:
                        for label in ('storage', 'remote', 'collector'):
                            if 'injected ' + label + ' failure' not in log:
                                raise AssertionError('missing injected ' + label + ' failure')
                        if elapsed < 1.6:
                            raise AssertionError('fallback timer did not control exit')
                    remaining = scanners(home)
                    if remaining:
                        raise AssertionError('storage scanners remain: %s' % remaining)
                    try:
                        os.killpg(pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise AssertionError('storage process group %s remains' % pid)
                    print('storage quit%s: scan pid=%s running=1; exit=0 in %.3fs; no scanner or group remains; no ReferenceError/TypeError' %
                          (' with injected failures and fallback' if faults else '', pid, elapsed))
                except (AssertionError, OSError) as err:
                    print('storage quit: FAIL:', err)
                    print(log_path.read_text(errors='replace')[-4000:])
                    return 1
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    if pid and scanners(home):
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        finally:
            shutil.rmtree(runtime)
    return 0


if __name__ == '__main__':
    sys.exit(main())
