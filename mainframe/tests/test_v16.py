import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'collect.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
spec = importlib.util.spec_from_file_location('config_manager', ROOT / 'config_manager.py')
config_manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_manager)


def wait_for_file(path, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(): return int(path.read_text())
        time.sleep(.01)
    raise AssertionError(f'PID file not written: {path}')


def process_running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
    except FileNotFoundError:
        return False


def wait_for_exit(pid, timeout=3):
    deadline = time.monotonic() + timeout
    while process_running(pid) and time.monotonic() < deadline:
        time.sleep(.01)
    return not process_running(pid)

class V16Tests(unittest.TestCase):
    def test_collector_bounds_endless_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'pid'
            script = 'import os,sys; open(sys.argv[1],"w").write(str(os.getpid())); chunk=b"x"*65536\nwhile True: os.write(1,chunk)'
            account = {'id':'endless', 'name':'Endless', 'provider':'command', 'command':[sys.executable, '-c', script, str(pidfile)]}
            count = 0
            max_chunk = 0
            buffers = []
            real_read = os.read
            def measured_read(fd, size):
                nonlocal count, max_chunk
                chunk = real_read(fd, size)
                count += len(chunk)
                max_chunk = max(max_chunk, len(chunk))
                return chunk
            def buffer(size):
                result = bytearray(size)
                buffers.append(result)
                return result
            with patch.object(config_manager, 'CACHE', Path(tmp) / 'cache'), patch.object(config_manager.os, 'read', side_effect=measured_read), patch.object(config_manager, 'bytearray', side_effect=buffer, create=True):
                started = time.monotonic()
                self.assertIs(config_manager.collect(account), False)
                self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(count, 2_000_001)
            self.assertLessEqual(sys.getsizeof(buffers[0]) + max_chunk, 2_100_000)
            self.assertTrue(wait_for_exit(wait_for_file(pidfile)))

    def test_collector_kills_group_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'pid'
            child = 'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)'
            script = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]])'
            account = {'id':'child', 'name':'Child', 'provider':'command', 'command':[sys.executable, '-c', script, child, str(pidfile)]}
            with patch.object(config_manager, 'CACHE', Path(tmp) / 'cache'), patch.object(config_manager, 'COLLECT_TIMEOUT', .5):
                started = time.monotonic()
                self.assertIs(config_manager.collect(account), False)
                self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(wait_for_exit(wait_for_file(pidfile)))

    def test_terminate_test_account_kills_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'pid'
            script = 'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)'
            account = {'id':'sleep', 'name':'Sleep', 'provider':'command', 'command':[sys.executable, '-c', script, str(pidfile)]}
            env = dict(os.environ, XDG_CACHE_HOME=tmp)
            proc = subprocess.Popen([sys.executable, str(ROOT / 'config_manager.py'), 'test-account'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                proc.stdin.write(json.dumps(account)); proc.stdin.close()
                pid = wait_for_file(pidfile)
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=3), 143)
                self.assertTrue(wait_for_exit(pid))
            finally:
                if proc.poll() is None: proc.kill(); proc.wait(timeout=3)
                proc.stdout.close(); proc.stderr.close()

    def test_invalid_config_read_refusal_and_explicit_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'mainframe'; directory.mkdir()
            path = directory / 'hosts.json'; path.write_text('{"hosts":[{}]}')
            env = dict(os.environ, XDG_CONFIG_HOME=tmp)
            def run(action, payload=None):
                return subprocess.run([sys.executable, str(ROOT / 'config_manager.py'), action], env=env, input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
            result = json.loads(run('read').stdout)
            self.assertEqual(result['hosts'], {'hosts': []})
            self.assertEqual(result['errors'], {'hosts': f'{path}: Invalid machine name'})
            payload = {'kind':'hosts', 'data':{'hosts':[]}}
            refused = run('write', payload)
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(json.loads(refused.stdout)['error'], f'{path}: Invalid machine name. Fix or move the file before saving, or explicitly replace it.')
            self.assertEqual(path.read_text(), '{"hosts":[{}]}')
            payload['replaceInvalid'] = True
            self.assertEqual(run('write', payload).returncode, 0)
            self.assertEqual(json.loads(path.read_text()), {'hosts':[]})

    def test_write_refuses_config_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); directory = base / 'mainframe'; directory.mkdir()
            target = base / 'target.json'; target.write_bytes(b'{"overviewView":"systems"}\n')
            original = target.read_bytes()
            link = directory / 'settings.json'; link.symlink_to(target)
            payload = {'kind':'settings', 'data':{'overviewView':'agents', 'showUnavailable':True}}
            result = subprocess.run([sys.executable, str(ROOT / 'config_manager.py'), 'write'], env=dict(os.environ, XDG_CONFIG_HOME=tmp), input=json.dumps(payload), capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['error'], 'settings.json is a symbolic link; not overwriting it')
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), original)
            payload['replaceInvalid'] = True
            target.unlink()
            result = subprocess.run([sys.executable, str(ROOT / 'config_manager.py'), 'write'], env=dict(os.environ, XDG_CONFIG_HOME=tmp), input=json.dumps(payload), capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['error'], 'settings.json is a symbolic link; not overwriting it')
            self.assertTrue(link.is_symlink())
            self.assertFalse(target.exists())

    def test_refresh_keeps_fresh_cache_without_config_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = root / 'config'; cache = root / 'cache'; config.mkdir(); cache.mkdir()
            account = {'id':'user', 'name':'User', 'provider':'command', 'command':['/bin/true']}
            (config / 'accounts.json').write_text(json.dumps({'accounts':[account]}))
            path = cache / 'user.json'; path.write_text('{}')
            os.utime(path, (time.time() - 60, time.time() - 60))
            with patch.object(config_manager, 'CONFIG', config), patch.object(config_manager, 'CACHE', cache), patch.object(config_manager.os, 'nice'), patch.object(config_manager, 'collect') as collect:
                self.assertIs(config_manager.refresh(), True)
                collect.assert_not_called()

    def test_refresh_invalidates_cache_when_directory_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = root / 'config'; cache = root / 'cache'; config.mkdir(); cache.mkdir()
            account = {'id':'user', 'name':'User', 'provider':'command', 'dir':'new', 'command':['/bin/sh', '-c', 'printf "{}"']}
            old = dict(account, dir='old')
            (config / 'accounts.json').write_text(json.dumps({'accounts':[account]}))
            path = cache / 'user.json'; path.write_text(json.dumps({'configHash':config_manager.config_hash(old)}))
            os.utime(path, (time.time() - 60, time.time() - 60))
            with patch.object(config_manager, 'CONFIG', config), patch.object(config_manager, 'CACHE', cache), patch.object(config_manager.os, 'nice'):
                self.assertIs(config_manager.refresh(), True)
                self.assertEqual(json.loads(path.read_text())['configHash'], 'b1d5917ae869b1415b7a79cedb5f2fad6ef84080bffcd8ac0103d2e6a5e88e24')
                with patch.object(config_manager, 'collect') as collect:
                    self.assertIs(config_manager.refresh(), True)
                    collect.assert_not_called()

    def test_deep_collector_json_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = {'id':'deep', 'name':'Deep', 'provider':'command', 'command':[sys.executable, '-c', 'print("["*2000+"0"+"]"*2000)']}
            with patch.object(config_manager, 'CACHE', Path(tmp)):
                self.assertIs(config_manager.collect(account), False)

    def test_non_object_write_payload_exits_two(self):
        result = subprocess.run([sys.executable, str(ROOT / 'config_manager.py'), 'write'], input='[]', capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'ok':False, 'error':'Expected an object with kind and data'})

    def test_network_mount_timeout_and_cooldown(self):
        class Stat: f_blocks=100; f_frsize=1024; f_bfree=20
        calls, release, finished = [], threading.Event(), threading.Event()
        def stat(mount):
            calls.append(mount)
            if mount == '/network-timeout-test':
                release.wait(5)
                finished.set()
            return Stat()
        mounts = 'server:/data /network-timeout-test nfs rw 0 0\n/dev/sda1 / ext4 rw 0 0\n'
        try:
            started = time.monotonic()
            rows = collector.parse_mounts(mounts, stat)
            self.assertLess(time.monotonic() - started, 2.5)
            self.assertEqual(rows, [{'device':'/dev/sda1', 'mount':'/', 'total':102400, 'used':81920}])
            self.assertEqual(collector.parse_mounts(mounts, stat), rows)
            release.set()
            self.assertTrue(finished.wait(1))
            self.assertEqual(collector.parse_mounts(mounts, stat), rows)
            self.assertEqual(calls, ['/network-timeout-test', '/', '/', '/'])
        finally:
            release.set()

    def test_mounts_filter_dedupe_and_escaped_names(self):
        class Stat: f_blocks=100; f_frsize=1024; f_bfree=20
        mounts = '/dev/sda1 / ext4 rw 0 0\n/dev/sda1 /duplicate ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/loop0 /snap/x squashfs ro 0 0\n/dev/sdb1 /media/my\\040disk ext4 rw 0 0\n'
        rows = collector.parse_mounts(mounts, lambda _: Stat())
        self.assertEqual([r['mount'] for r in rows], ['/', '/media/my disk'])
        self.assertEqual(rows[0]['used'], 81920)

    def test_df_apfs_container_dedupe(self):
        data = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk3s1 1000 800 200 80% /\n/dev/disk3s5 1000 100 900 10% /System/Volumes/Data\n/dev/disk4s1 500 100 400 20% /Volumes/X\n'
        self.assertEqual(len(collector.parse_df(data)), 2)

    def test_windows_fixture_and_timeout(self):
        record = {'total':1000,'free':250,'cpu':[20,40], 'disks':[{'name':'C:','size':10000,'free':4000}]}
        parsed = collector.parse_windows(json.dumps(record))
        self.assertEqual((parsed['total'], parsed['used'], parsed['cpu']), (1024000, 768000, 30))
        self.assertEqual(parsed['disks'][0]['used'],6000)
        self.assertIsNone(collector.parse_windows('{'))
        with patch.object(collector.shutil, 'which', return_value='/fake/powershell.exe'), patch.object(collector, '_run_tracked', side_effect=subprocess.TimeoutExpired('ps',10)) as run:
            self.assertIsNone(collector.windows_probe()); self.assertEqual(run.call_args.kwargs['timeout'], 10)

    def test_powershell_discovery_without_path(self):
        suffix = 'Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        d_drive = '/mnt/d/' + suffix
        with patch.object(collector.shutil, 'which', return_value=None), \
             patch.object(collector.glob, 'glob', return_value=[d_drive]), \
             patch.object(collector.os.path, 'isfile', side_effect=lambda path: path == d_drive), \
             patch.object(collector, '_run_tracked', side_effect=OSError) as run:
            self.assertIsNone(collector.windows_probe())
            self.assertEqual(run.call_args.args[0][0], d_drive)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
        c_drive = '/mnt/c/' + suffix
        with patch.object(collector.shutil, 'which', return_value=None), \
             patch.object(collector.glob, 'glob', return_value=[d_drive]), \
             patch.object(collector.os.path, 'isfile', return_value=True), \
             patch.object(collector, '_run_tracked', side_effect=OSError) as run:
            collector.windows_probe()
            self.assertEqual(run.call_args.args[0][0], c_drive)

    def test_wsl_mounts_and_fixed_drives(self):
        class Stat: f_blocks=100; f_frsize=1024; f_bfree=20
        mounts = ('/dev/sdb /usr/src/linux-headers-6.18.54.1-microsoft-standard-WSL2 ext4 ro 0 0\n'
                  'drivers /usr/lib/wsl/drivers 9p rw 0 0\n'
                  '/dev/sdc / ext4 rw 0 0\n'
                  '/dev/sdd /mnt/wsl/data ext4 rw 0 0\n'
                  '/dev/sde /init ext4 rw 0 0\n'
                  '/dev/sdf /snap/test ext4 rw 0 0\n'
                  '/dev/sdg /readonly ext4 ro 0 0\n'
                  'C: /mnt/c 9p rw 0 0\nD: /mnt/d drvfs rw 0 0\n'
                  'other /somewhere 9p rw 0 0\n')
        rows = collector.parse_mounts(mounts, lambda _: Stat(), wsl=True)
        self.assertEqual([r['mount'] for r in rows], ['/', '/mnt/c', '/mnt/d'])
        self.assertEqual([r['mount'] for r in collector.wsl_filesystems(rows, None)], ['WSL (/)', 'C:', 'D:'])
        windows = collector.parse_windows(json.dumps({'total':100, 'free':50, 'cpu':[],
                            'disks':[{'name':'E:', 'size':1000, 'free':400}]}))
        fixed = collector.wsl_filesystems(rows, windows)
        self.assertEqual([r['mount'] for r in fixed], ['WSL (/)', 'C:', 'D:', 'E:'])
        self.assertEqual(fixed[3], {'device':'E:', 'mount':'E:', 'total':1000, 'used':600})
        self.assertEqual([r['mount'] for r in collector.wsl_filesystems(rows, {'disks': []})], ['WSL (/)', 'C:', 'D:'])
        c_drive = {'device':'C:', 'mount':'C:', 'total':2000, 'used':1200}
        self.assertEqual(collector.wsl_filesystems(rows, {'disks':[c_drive]})[1], c_drive)
        self.assertEqual([r['mount'] for r in collector.parse_mounts(mounts, lambda _: Stat())], ['/'])

    def test_windows_probe_is_nonblocking_and_single_flight(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def slow_windows():
            calls.append(1)
            entered.set()
            release.wait(2)
            finished.set()
            return None
        state = {'windows': None, 'storage': [], 'windows_at': 0.0, 'storage_at': 100.0,
                 'windows_busy': False, 'storage_busy': False}
        try:
            with patch.object(collector, '_probe', state), patch.object(collector, 'windows_probe', slow_windows), \
                 patch.object(collector.time, 'monotonic', return_value=100.0) as clock:
                start = time.perf_counter()
                collector.slow_probes({'wsl': True})
                self.assertLess(time.perf_counter() - start, .5)
                self.assertTrue(entered.wait(1))
                for _ in range(5):
                    collector.slow_probes({'wsl': True})
                self.assertEqual(len(calls), 1)
                release.set()
                self.assertTrue(finished.wait(1))
                deadline = time.perf_counter() + 1
                while state['windows_busy'] and time.perf_counter() < deadline:
                    time.sleep(.001)
                clock.return_value = 114.9
                collector.slow_probes({'wsl': True})
                self.assertEqual(len(calls), 1)
                clock.return_value = 115.0
                collector.slow_probes({'wsl': True})
                deadline = time.perf_counter() + 1
                while len(calls) < 2 and time.perf_counter() < deadline:
                    time.sleep(.001)
                self.assertEqual(len(calls), 2)
        finally:
            release.set()

    def test_dedupe_and_isolated_command(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); config=base/'config/mainframe'; config.mkdir(parents=True)
            usage=base/'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            cache=base/'cache/mainframe/agents'; cache.mkdir(parents=True)
            (usage/'claude.json').write_text(json.dumps({'id':'claude','name':'Claude Code','updatedAt':'2026-01-01'}))
            (cache/'main.json').write_text(json.dumps({'id':'main','provider':'claude','dir':str(base/'home/.claude'),'name':'me','updatedAt':'2026-02-01'}))
            env=dict(os.environ, HOME=str(base/'home'), XDG_CONFIG_HOME=str(base/'config'), XDG_CACHE_HOME=str(base/'cache'), XDG_STATE_HOME=str(base/'state'))
            out=subprocess.check_output([sys.executable, str(ROOT/'agents_usage.py')],env=env,text=True)
            self.assertEqual(len(json.loads(out)), 1)
            cmd=[sys.executable, '-c', 'import json; print(json.dumps({"updatedAt":"2026-01-01", "limits":[]}))']
            account={'id':'fake','provider':'command','name':'Fake','command':cmd}
            result=subprocess.run([sys.executable,str(ROOT/'config_manager.py'),'test-account'],env=env,input=json.dumps(account),text=True,capture_output=True,check=True)
            self.assertTrue(json.loads(result.stdout)['ok'])
            self.assertEqual(json.loads((cache/'fake.json').read_text())['name'],'Fake')

if __name__ == '__main__': unittest.main()
