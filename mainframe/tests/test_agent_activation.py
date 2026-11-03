"""Exercise agent collectors through the real offscreen shell and cache."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('qs'), 'qs is required')
class AgentActivationTests(unittest.TestCase):
    def run_case(self, default, selected, cached):
        with tempfile.TemporaryDirectory(prefix='.a', dir=ROOT) as tmp:
            base = Path(tmp)
            for path in ('r', 'home', 'config/mainframe', 'cache/mainframe/agents', 'state'):
                (base / path).mkdir(parents=True)
            (base / 'r').chmod(0o700)
            marker = base / 'called'
            command = [sys.executable, '-c',
                       'from pathlib import Path; import json,sys; Path(sys.argv[1]).write_text("called"); print(json.dumps({"limits": []}))', str(marker)]
            account = {'id': 'fake', 'name': 'Fake', 'provider': 'command', 'command': command}
            (base / 'config/mainframe/accounts.json').write_text(json.dumps({'accounts': [account]}))
            (base / 'config/mainframe/settings.json').write_text(json.dumps({'overviewView': default, 'showUnavailable': False}))
            if cached:
                cache = base / 'cache/mainframe/agents/fake.json'
                cache.write_text(json.dumps({'limits': []}))
                if cached == 'stale':
                    os.utime(cache, (time.time() - 601,) * 2)
            env = dict(os.environ, HOME=str(base/'home'), XDG_RUNTIME_DIR=str(base/'r'),
                       XDG_CONFIG_HOME=str(base/'config'), XDG_CACHE_HOME=str(base/'cache'),
                       XDG_STATE_HOME=str(base/'state'), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='', DBUS_SESSION_BUS_ADDRESS='unix:path='+str(base/'missing'),
                       MAINFRAME_SMOKE='1', MAINFRAME_SMOKE_NO_REMOTE='1', MAINFRAME_SMOKE_MS='2200')
            env.pop('DISPLAY', None)
            env.pop('WAYLAND_DISPLAY', None)
            env.pop('MAINFRAME_SMOKE_PAGE', None)
            if selected:
                env['MAINFRAME_SMOKE_PAGE'] = selected
            run = subprocess.run(['qs', '-p', str(ROOT/'mainframe')], env=env,
                                 capture_output=True, text=True, timeout=12)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn('ReferenceError', run.stdout + run.stderr)
            return marker.exists()

    def test_no_refresh_at_startup_even_with_agents_default(self):
        self.assertFalse(self.run_case('agents', None, 'stale'))
        self.assertFalse(self.run_case('systems', None, 'stale'))

    def test_selected_agents_refreshes_only_stale_data(self):
        self.assertTrue(self.run_case('systems', 'agents', 'stale'))
        self.assertFalse(self.run_case('systems', 'agents', 'fresh'))


    def test_cancelled_refresh_reaps_the_collector(self):
        with tempfile.TemporaryDirectory(prefix='.a', dir=ROOT) as tmp:
            base = Path(tmp)
            (base/'config/mainframe').mkdir(parents=True)
            marker = base/'pid'
            command = [sys.executable, '-c',
                       'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)', str(marker)]
            account = {'id': 'fake', 'name': 'Fake', 'provider': 'command', 'command': command}
            (base/'config/mainframe/accounts.json').write_text(json.dumps({'accounts': [account]}))
            env = dict(os.environ, XDG_CONFIG_HOME=str(base/'config'), XDG_CACHE_HOME=str(base/'cache'))
            proc = subprocess.Popen([sys.executable, str(ROOT/'mainframe/config_manager.py'), 'refresh'], env=env)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), 'collector did not start')
                pid = int(marker.read_text())
                proc.terminate()
                self.assertEqual(proc.wait(timeout=5), 143)
                self.assertFalse(Path('/proc', str(pid)).exists(), 'collector survived cancellation')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


if __name__ == '__main__':
    unittest.main()
