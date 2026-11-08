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


def session_processes(session):
    """Return live process IDs and groups in the session started for qs."""
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] != 'Z' and int(stat[3]) == session:
                found.append((int(entry.name), int(stat[2])))
        except (OSError, IndexError, ValueError):
            continue
    return found


def main():
    faults = '--faults' in sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='.storage-shutdown-', dir=ROOT) as tmp:
        base = Path(tmp)
        log_path = base / 'qs.log'
        try:
            return run(base, log_path, faults)
        except Exception as err:
            print('storage quit: FAIL:', err)
            print('Last 60 lines of qs log:')
            try:
                print('\n'.join(log_path.read_text(errors='replace').splitlines()[-60:]))
            except OSError:
                print('(qs log unavailable)')
            return 1


def run(base, log_path, faults):
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
        pid = None
        with log_path.open('w') as log_file:
            proc = subprocess.Popen(['qs', '-p', str(app)], env=env,
                                    stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
            passed = False
            try:
                deadline = time.monotonic() + 8
                match = None
                while time.monotonic() < deadline:
                    match = re.search(r'STORAGE_QUIT pid=(\d+) running=1', log_path.read_text(errors='replace'))
                    if match:
                        break
                    if proc.poll() is not None and not session_processes(proc.pid):
                        break
                    time.sleep(.01)
                if not match:
                    match = re.search(r'STORAGE_QUIT pid=(\d+) running=1', log_path.read_text(errors='replace'))
                if not match:
                    raise AssertionError('no quit request while scanner was running')
                pid = int(match.group(1))
                started = time.monotonic()
                deadline = started + 3
                while time.monotonic() < deadline:
                    proc.poll()  # Reap the launcher when it is our child.
                    if not session_processes(proc.pid):
                        break
                    time.sleep(.01)
                else:
                    raise AssertionError('qs session did not exit within 3 seconds of the quit request')
                code = proc.wait(timeout=3)
                elapsed = time.monotonic() - started
                log = log_path.read_text(errors='replace')
                if code != 0:
                    raise AssertionError('qs launcher exited with %s' % code)
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
                print('storage quit%s: scan pid=%s running=1; session exited in %.3fs; launcher exit=0; no scanner or group remains; no ReferenceError/TypeError' %
                      (' with injected failures and fallback' if faults else '', pid, elapsed))
                passed = True
            finally:
                # The launcher may already have exited while its child is alive.
                if not passed:
                    groups = {group for _, group in session_processes(proc.pid)}
                    groups.update(scanners(home))
                    if pid:
                        groups.add(pid)
                    for group in groups:
                        try:
                            os.killpg(group, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                proc.wait()
    finally:
        shutil.rmtree(runtime)
    return 0


if __name__ == '__main__':
    sys.exit(main())
