import importlib.util
import io
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
sys.path.insert(0, str(ROOT))
import storage_scan as storage

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-', dir=os.environ.get('TMPDIR'))
        self.home = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def create(self, name):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 6000)
        return path
    def test_darwin_df_filters_labels_spaces_and_caches_diskutil(self):
        import plistlib
        import collect
        fixture = (ROOT / 'tests/host-a-df.txt').read_text()
        metadata = {
            '/dev/disk4s1s1': {'Internal': True},
            '/dev/disk5s1': {'Protocol': 'USB', 'Internal': False},
            '/dev/disk6s1': {'Protocol': 'Disk Image'},
            '/dev/disk7s1': {'BusProtocol': 'USB', 'VolumeName': 'Backup'},
            '/dev/disk8s1': {'Protocol': 'Thunderbolt'},
        }
        calls = []
        def run(args, **kwargs):
            if args[0] == 'df':
                self.assertEqual(args, ['df', '-k', '-P'])
                return fixture
            self.assertEqual(args[:3], ['diskutil', 'info', '-plist'])
            self.assertEqual(kwargs['timeout'], 3)
            calls.append(args[3])
            return plistlib.dumps(metadata[args[3]])
        with patch.object(collect, '_darwin_disk_info', {}), patch.object(collect.sys, 'platform', 'darwin'), patch.object(collect, '_run_tracked', side_effect=run):
            rows = collect.storage_probe()
            self.assertEqual([(r['mount'], r['label'], r['bus']) for r in rows], [
                ('/', 'Mac (internal)', 'Internal'),
                ('/Volumes/External', 'External', 'USB'),
                ('/Volumes/Backup', 'Backup', 'USB'),
            ])
            self.assertEqual([(r['used'], r['total']) for r in rows], [(600000 * 1024, 1000000 * 1024), (300000 * 1024, 500000 * 1024), (50000 * 1024, 200000 * 1024)])
            self.assertEqual(collect.storage_probe(), rows)
            self.assertEqual(calls, ['/dev/disk4s1s1', '/dev/disk5s1', '/dev/disk6s1', '/dev/disk7s1'])
            spaced = fixture + '/dev/disk8s1 100 10 90 10% /Volumes/My External Disk\n'
            self.assertEqual(collect.parse_df(spaced)[-1]['mount'], '/Volumes/My External Disk')
            self.assertEqual(calls[-1], '/dev/disk8s1')

    def test_darwin_container_partitions_and_cache_lifecycle(self):
        import collect
        import plistlib
        header = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
        def line(dev, total, mount):
            return f'/dev/{dev} {total} 1 20 1% {mount}\n'
        data = header + line('disk4s2', 100, '/Volumes/Data') + line('disk4s1', 100, '/') + line('disk5s1', 200, '/Volumes/One') + line('disk5s2', 300, '/Volumes/Two')
        calls = []
        fail = [True]
        def run(args, **kwargs):
            device = args[-1]; calls.append(device)
            if device == '/dev/disk5s1' and fail[0]:
                fail[0] = False
                raise subprocess.CalledProcessError(1, args)
            info = {'APFSContainerReference': 'disk4'} if device.startswith('/dev/disk4') else {'Protocol': 'USB'}
            return plistlib.dumps(info)
        clock = [100.0]
        with patch.object(collect, '_darwin_disk_info', {}), patch.object(collect, '_darwin_disk_failures', {}), patch.object(collect.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(collect, '_run_tracked', side_effect=run):
            first = collect.parse_df(data)
            self.assertEqual([r['mount'] for r in first], ['/', '/Volumes/One'])
            second = collect.parse_df(data)
            self.assertEqual([r['mount'] for r in second], ['/', '/Volumes/One'])
            self.assertEqual(calls.count('/dev/disk5s1'), 1)
            clock[0] = 160.0
            second = collect.parse_df(data)
            self.assertEqual([r['mount'] for r in second], ['/', '/Volumes/One', '/Volumes/Two'])
            self.assertEqual(calls.count('/dev/disk5s1'), 2)
            collect.parse_df(header + line('disk5s1', 400, '/Volumes/One'))
            self.assertEqual(calls.count('/dev/disk5s1'), 3)
            self.assertEqual(set(collect._darwin_disk_info), {('/dev/disk5s1', 400 * 1024)})
            collect.parse_df(header)
            self.assertEqual(collect._darwin_disk_info, {})

    def test_darwin_failed_metadata_falls_back_to_whole_disk(self):
        import collect
        data = 'Filesystem blocks Used Available Capacity Mounted on\n/dev/disk5s1 100 1 20 1% /Volumes/One\n/dev/disk5s2 100 1 20 1% /Volumes/Two\n'
        with patch.object(collect, '_darwin_disk_info', {}), patch.object(collect, '_darwin_disk_failures', {}), patch.object(collect, '_run_tracked', side_effect=OSError('unavailable')):
            self.assertEqual([r['device'] for r in collect.parse_df(data)], ['/dev/disk5s1'])

    def test_darwin_failed_lookup_expires_per_device(self):
        import collect
        import plistlib
        clock = [100.0]
        calls = []
        def run(args, **kwargs):
            calls.append(args[-1])
            if len(calls) <= 2:
                raise subprocess.TimeoutExpired(args, 3)
            return plistlib.dumps({'Internal': True})
        with patch.object(collect, '_darwin_disk_info', {}), patch.object(collect, '_darwin_disk_failures', {}), patch.object(collect.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(collect, '_run_tracked', side_effect=run):
            self.assertIsNone(collect.darwin_disk_info('/dev/disk1', 100))
            self.assertIsNone(collect.darwin_disk_info('/dev/disk1', 200))
            self.assertIsNone(collect.darwin_disk_info('/dev/disk2', 100))
            clock[0] = 159.999
            self.assertIsNone(collect.darwin_disk_info('/dev/disk1', 100))
            self.assertEqual(calls, ['/dev/disk1', '/dev/disk2'])
            clock[0] = 160.0
            self.assertEqual(collect.darwin_disk_info('/dev/disk1', 100), {'Internal': True})
            self.assertEqual(collect.darwin_disk_info('/dev/disk1', 100), {'Internal': True})
            self.assertEqual(calls, ['/dev/disk1', '/dev/disk2', '/dev/disk1'])

    def test_tracked_probe_stops_and_does_not_restart_after_shutdown(self):
        import collect
        started = threading.Event()
        outcome, children = [], []
        track = collect._track_child
        def record(proc):
            track(proc)
            children.append(proc)
            started.set()
        def probe():
            try:
                collect._run_tracked([sys.executable, '-c', 'import time; time.sleep(60)'],
                                     timeout=30, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                outcome.append('success')
            except subprocess.SubprocessError:
                outcome.append('failed')
        with patch.object(collect, '_children_stopped', False), patch.object(collect, '_track_child', side_effect=record):
            thread = threading.Thread(target=probe)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                collect.stop_children()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(outcome, ['failed'])
                self.assertIsNotNone(children[0].poll())
                self.assertNotIn(children[0], collect._child_procs)
                with patch.object(collect.subprocess, 'Popen') as popen:
                    with self.assertRaises(subprocess.SubprocessError):
                        collect._run_tracked(['unused'], timeout=1)
                    popen.assert_not_called()
            finally:
                collect.stop_children()
                thread.join(5)

    def test_tracked_probe_timeout_cleans_up(self):
        import collect
        with patch.object(collect, '_children_stopped', False):
            with self.assertRaises(subprocess.TimeoutExpired):
                collect._run_tracked([sys.executable, '-c', 'import time; time.sleep(60)'],
                                     timeout=0.1, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.assertEqual(collect._child_procs, [])

    def test_precedence_and_extensions(self):
        cases = {
            '.local/share/Steam/a.pdf': 'Games', '.steam/a': 'Games', 'Games/a': 'Games',
            '.var/app/com.valvesoftware.Steam/a': 'Games', '.local/share/lutris/a': 'Games',
            '.local/share/heroic/a': 'Games', '.cache/a.pdf': 'Caches & trash',
            '.local/share/Trash/a': 'Caches & trash', '.local/share/flatpak/a': 'Apps',
            '.var/app/org.example/a': 'Apps', '.local/share/mise/a': 'Apps', '.npm/a': 'Apps',
            '.cargo/a': 'Apps', '.rustup/a': 'Apps', '.local/lib/a': 'Apps',
            'project/node_modules/x.pdf': 'Apps', 'Downloads/a.pdf': 'Downloads & archives',
            'misc/a.AppImage': 'Downloads & archives', 'misc/a.iso': 'Downloads & archives',
            'misc/a.heic': 'Images', 'misc/a.webp': 'Images', 'misc/a.cr3': 'Images',
            'misc/a.mp4': 'Videos', 'misc/a.flac': 'Music', 'misc/a.pdf': 'Documents',
            'misc/a.docx': 'Documents', 'misc/a.xlsx': 'Documents', 'misc/a.pptx': 'Documents',
            'misc/a.odt': 'Documents', 'misc/a.md': 'Documents', 'misc/a.txt': 'Documents',
            'misc/a.epub': 'Documents', 'misc/a.unknown': 'Other',
        }
        for path, expected in cases.items():
            with self.subTest(path=path): self.assertEqual(storage.classify(path), expected)
    def test_walk_and_hard_links_symlinks_and_other_device(self):
        image = self.create('a.jpg')
        os.link(image, self.home / 'b.jpg')
        self.create('node_modules/a.pdf')
        self.create('Downloads/a.mp4')
        self.create('Games/a.txt')
        self.create('.cache/a.mp3')
        self.create('other/a.pdf')
        self.create('other/a.mp4')
        self.create('other/a.mp3')
        self.create('other/a.xyz')
        self.create('foreign/a.jpg')
        os.symlink(self.home / 'foreign', self.home / 'linked')
        real = lambda entry: entry.stat(follow_symlinks=False)
        def fake(entry):
            stat = real(entry)
            if entry.name == 'foreign':
                class Different:
                    st_dev = stat.st_dev + 1
                    st_ino = stat.st_ino
                    st_blocks = stat.st_blocks
                return Different()
            return stat
        result = storage.scan(str(self.home), stat_fn=fake)
        totals = result['categories']
        self.assertEqual(totals['Images'], image.stat().st_blocks * 512)
        for key in storage.CATEGORIES:
            with self.subTest(key=key): self.assertGreater(totals[key], 0)
        self.assertFalse(result['partial'])
        self.assertFalse(result['cancelled'])
    def test_directory_swapped_for_symlink_is_not_followed(self):
        root = self.home / 'root'
        root.mkdir()
        victim = root / 'victim'
        victim.mkdir()
        (victim / 'original.txt').write_bytes(b'a' * 6000)
        outside = self.home / 'outside'
        outside.mkdir()
        (outside / 'secret.jpg').write_bytes(b'b' * 6000)
        real_open = os.open
        swapped = []
        def swap_on_descent(path, flags, *args, **kwargs):
            if path == 'victim' and kwargs.get('dir_fd') is not None and not swapped:
                victim.rename(self.home / 'original')
                victim.symlink_to(outside, target_is_directory=True)
                swapped.append(True)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(storage.os, 'open', side_effect=swap_on_descent):
            result = storage.scan(str(root))
        self.assertEqual(swapped, [True])
        self.assertEqual(result['files'], 0)
        self.assertEqual(result['categories']['Images'], 0)
        self.assertFalse(result['partial'])

    def test_opened_directory_device_is_checked(self):
        folder = self.home / 'folder'
        folder.mkdir()
        (folder / 'inside.jpg').write_bytes(b'a' * 6000)
        real_fstat = os.fstat
        root_inode = self.home.stat().st_ino
        def foreign_child(fd):
            result = real_fstat(fd)
            if result.st_ino != root_inode:
                fields = list(result)
                fields[2] = result.st_dev + 1
                return os.stat_result(fields)
            return result
        with patch.object(storage.os, 'fstat', side_effect=foreign_child):
            result = storage.scan(str(self.home))
        self.assertEqual(result['files'], 0)
        self.assertEqual(result['categories']['Images'], 0)

    def test_directory_descent_has_bounded_descriptors(self):
        current = self.home
        for _ in range(30):
            current = current / 'd'
            current.mkdir()
        (current / 'found.txt').write_bytes(b'content')
        real_open = os.open
        counts = []
        def count_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            counts.append(len(os.listdir('/proc/self/fd')))
            return fd
        before = len(os.listdir('/proc/self/fd'))
        with patch.object(storage.os, 'open', side_effect=count_open):
            result = storage.scan(str(self.home))
        self.assertEqual(result['files'], 1)
        self.assertLessEqual(max(counts), before + 4)
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)

    def test_cancel_and_timeout_return_partial_work(self):
        for i in range(20): self.create('a%d.txt' % i)
        calls = iter([False] * 6 + [True] * 100)
        cancelled = storage.scan(str(self.home), should_cancel=lambda: next(calls))
        self.assertTrue(cancelled['cancelled'])
        self.assertGreater(cancelled['files'], 0)
        ticks = iter([0, 0, 0, 0.1, 0.2, 2, 2, 2])
        timed = storage.scan(str(self.home), timeout=1, clock=lambda: next(ticks, 2))
        self.assertTrue(timed['partial'])
        self.assertGreater(timed['files'], 0)
    def test_deadline_interrupts_slow_filesystem_work(self):
        self.create('a.txt')
        checks = [0]
        def slow():
            checks[0] += 1
            if checks[0] > 1:
                time.sleep(.5)
            return False
        start = time.monotonic()
        result = storage.scan(str(self.home), timeout=.05, should_cancel=slow)
        self.assertTrue(result['partial'])
        self.assertLess(time.monotonic() - start, .4)
    def test_process_cancellation(self):
        self.create('dir/a.txt')
        env = dict(os.environ, HOME=str(self.home))
        code = ("import os,time,storage_scan; os.setsid(); "
                "print('ready', flush=True); "
                "storage_scan.scan(os.environ['HOME'], should_cancel=lambda: (time.sleep(.5) or False))")
        proc = subprocess.Popen([sys.executable, '-u', '-c', code], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline().strip(), 'ready')
        os.killpg(proc.pid, signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=3), -signal.SIGTERM)
        proc.stdout.close()
    def test_cache_expiry_and_partial(self):
        self.assertTrue(storage.cache_fresh({'timestamp': 100}, 3699))
        self.assertFalse(storage.cache_fresh({'timestamp': 100}, 3700))
        self.assertFalse(storage.cache_fresh({'timestamp': 100, 'partial': True}, 101))
        self.assertFalse(storage.cache_fresh({'timestamp': 200}, 100))

    def test_cache_write_does_not_follow_old_predictable_temp_symlink(self):
        cache = self.home / 'cache' / 'storage.json'
        cache.parent.mkdir()
        victim = self.home / 'victim'
        victim.write_text('unchanged')
        Path(str(cache) + '.' + str(os.getpid()) + '.tmp').symlink_to(victim)
        with patch.dict(os.environ, {'HOME': '/'}), \
             patch.object(storage, 'cache_path', return_value=str(cache)), \
             patch.object(storage, 'scan', return_value={'cancelled': False}), \
             patch.object(storage, 'emit') as emit, patch.object(storage.os, 'setsid'), \
             patch.object(storage.os, 'nice'), patch.object(storage.shutil, 'which', return_value=None), \
             patch('sys.stderr', new_callable=io.StringIO) as stderr:
            result = storage.run(force=True)
            self.assertEqual(result, 0, f'emitted: {emit.call_args_list}; stderr: {stderr.getvalue()}')
        self.assertEqual(victim.read_text(), 'unchanged')
        self.assertEqual(json.loads(cache.read_text())['type'], 'result')
    def test_category_opener_uses_baobab_or_fallback(self):
        pictures = self.home / 'Pictures'
        pictures.mkdir()
        with patch.dict(os.environ, {'HOME': str(self.home)}), \
             patch.object(storage.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
             patch.object(storage.subprocess, 'Popen') as execute:
            storage.open_category('Images')
            self.assertEqual(execute.call_args.args[0], ['/bin/baobab', str(pictures)])
        with patch.dict(os.environ, {'HOME': str(self.home)}), \
             patch.object(storage.shutil, 'which', side_effect=lambda name: None if name == 'baobab' else '/bin/xdg-open'), \
             patch.object(storage.subprocess, 'Popen') as execute:
            storage.open_category('Games')
            self.assertEqual(execute.call_args.args[0], ['/bin/xdg-open', str(self.home)])
    def test_cache_freshness(self):
        cache = self.home / 'cache' / 'mainframe'
        cache.mkdir(parents=True)
        (cache / 'storage.json').write_text(json.dumps({'timestamp': time.time(), 'categories': {}, 'total': 100, 'free': 50}))
        env = {k: v for k, v in os.environ.items() if k != 'MAINFRAME_USAGE_SCAN' and not k.startswith('XDG_')}
        env['XDG_CACHE_HOME'] = str(self.home / 'cache')
        result = subprocess.run([sys.executable, str(ROOT / 'collect.py'), '--storage'], env=env, capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(result.stdout)['cached'])

if __name__ == '__main__': unittest.main()
