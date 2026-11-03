import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
import subprocess
import signal
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import theme_manager as manager


class ThemeManagerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = patch.object(manager, 'schedule_previews')
        self.scheduler.start()
        self.addCleanup(self.scheduler.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.config = self.base / 'config'
        self.cache = self.base / 'cache'
        self.stock = self.base / 'stock'
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config),
                                          'XDG_CACHE_HOME': str(self.cache), 'OMARCHY_PATH': str(self.stock)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.current = self.home / '.local/state/omarchy/current/theme'
        self.image(self.current / 'backgrounds/current.jpg')
        (self.current / 'colors.toml').write_text('current')
        (self.current.parent / 'theme.name').write_text('system\n')

    def image(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'image')
        return path

    def test_render_cache_and_signature_invalidation(self):
        first = self.stock / 'themes/ocean'
        second = self.stock / 'themes/forest'
        for folder, color in ((first, 'blue'), (second, 'green')):
            self.image(folder / 'preview.jpg')
            (folder / 'colors.toml').write_text(color)
        result = manager.resolve()
        directory = Path(result['previewDir'])
        available = manager.themes([self.stock / 'themes'])
        calls = []

        def fake_render(folder, output):
            calls.append(folder.name)
            output.write_bytes(b'fake image')

        with patch.object(manager, 'render_theme', side_effect=fake_render), patch.object(manager, 'version_signature', return_value='version-1'):
            manager.render_previews(directory, available, self.current)
            self.assertEqual(calls, ['forest', 'ocean', 'theme'])
            self.assertEqual((directory / 'forest.png').read_bytes(), b'fake image')
            self.assertEqual((directory / 'ocean.png').read_bytes(), b'fake image')
            manager.render_previews(directory, available, self.current)
            self.assertEqual(calls, ['forest', 'ocean', 'theme'])
            (first / 'colors.toml').write_text('red')
            manager.render_previews(directory, available, self.current)
            self.assertEqual(calls, ['forest', 'ocean', 'theme', 'ocean'])
        with patch.object(manager, 'render_theme', side_effect=fake_render), patch.object(manager, 'version_signature', return_value='version-2'):
            manager.render_previews(directory, available, self.current)
            self.assertEqual(calls, ['forest', 'ocean', 'theme', 'ocean', 'forest', 'ocean', 'theme'])

    def test_failed_render_keeps_fallback_and_logs(self):
        image = self.image(self.stock / 'themes/ocean/preview.jpg')
        (image.parent / 'colors.toml').write_text('blue')
        result = manager.resolve()
        directory = Path(result['previewDir'])
        with patch.object(manager, 'render_theme', side_effect=OSError('render failed')), patch.object(manager.syslog, 'syslog') as log:
            manager.render_previews(directory, manager.themes([self.stock / 'themes']), self.current)
        self.assertEqual((directory / 'ocean.jpg').resolve(), image)
        self.assertFalse((directory / 'ocean.png').exists())
        self.assertEqual([args.args[1] for args in log.call_args_list], [
            'mainframe preview ocean: render failed', 'mainframe preview follow-omarchy: render failed'])

    def test_removed_theme_deletes_only_tracked_owned_regular_preview(self):
        folder = self.stock / 'themes/ocean'
        self.image(folder / 'preview.jpg')
        (folder / 'colors.toml').write_text('blue')
        directory = Path(manager.resolve()['previewDir'])
        with patch.object(manager, 'render_theme', side_effect=lambda folder, output: output.write_bytes(b'render')), patch.object(manager, 'version_signature', return_value='v'):
            manager.render_previews(directory, manager.themes([self.stock / 'themes']), self.current)
        self.assertEqual((directory / 'ocean.png').read_bytes(), b'render')
        (directory / 'untouched.png').write_bytes(b'user')
        manager.build_previews(directory, {}, self.current)
        self.assertFalse((directory / 'ocean.png').exists())
        self.assertEqual((directory / 'untouched.png').read_bytes(), b'user')
        state = json.loads((directory.parent / manager.SIGNATURE_NAME).read_text())
        self.assertNotIn('ocean', state['$renders'])

    def test_missing_renderer_files_keep_fallback_and_log_once(self):
        image = self.image(self.stock / 'themes/ocean/preview.jpg')
        directory = Path(manager.resolve()['previewDir'])
        real_is_file = Path.is_file
        for missing in ('shell.qml', 'fake-local.py'):
            with self.subTest(missing=missing), patch.object(Path, 'is_file', lambda path: False if path.name == missing else real_is_file(path)), patch.object(manager.syslog, 'syslog') as log, patch.object(manager, 'render_theme') as render:
                manager.render_previews(directory, manager.themes([self.stock / 'themes']), self.current)
            self.assertEqual((directory / 'ocean.jpg').resolve(), image)
            self.assertEqual(log.call_count, 1)
            self.assertEqual(log.call_args.args[1], f'mainframe preview: missing renderer files: {Path(manager.__file__).resolve().parent / ("shell.qml" if missing == "shell.qml" else "tests/fake-local.py")}')
            render.assert_not_called()

    def test_busy_worker_requests_rerun_with_fresh_themes(self):
        first = self.stock / 'themes/ocean'
        self.image(first / 'preview.jpg')
        (first / 'colors.toml').write_text('blue')
        directory = Path(manager.resolve()['previewDir'])
        available = manager.themes([self.stock / 'themes'])
        entered = threading.Event(); resume = threading.Event(); calls = []
        def render(folder, output):
            calls.append(folder.name)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(resume.wait(5))
            output.write_bytes(b'render')
        with patch.object(manager, 'render_theme', side_effect=render), patch.object(manager, 'version_signature', return_value='v'):
            worker = threading.Thread(target=manager.render_previews, args=(directory, available, self.current))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.image(self.stock / 'themes/forest/preview.jpg')
                (self.stock / 'themes/forest/colors.toml').write_text('green')
                manager.render_previews(directory, manager.themes([self.stock / 'themes']), self.current)
                self.assertTrue((directory.parent / '.theme-preview-rerun').is_file())
            finally:
                resume.set(); worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(calls, ['ocean', 'theme', 'forest'])
        self.assertEqual((directory / 'forest.png').read_bytes(), b'render')
        self.assertFalse((directory.parent / '.theme-preview-rerun').exists())

    def test_special_and_oversized_theme_files_are_skipped(self):
        root = self.stock / 'themes'
        for name in ('zero', 'fifo', 'large', 'good'):
            self.image(root / name / 'preview.jpg')
        (root / 'zero/colors.toml').symlink_to('/dev/zero')
        os.mkfifo(root / 'fifo/colors.toml')
        (root / 'large/colors.toml').write_bytes(b'x' * (256 * 1024 + 1))
        (root / 'good/colors.toml').write_text('green')
        directory = Path(manager.resolve()['previewDir'])
        script = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import theme_manager as manager
root, destination, current = map(Path, sys.argv[2:])
calls = []
def render(folder, output):
    calls.append(folder.name)
    output.write_bytes(b'render')
with patch.object(manager, 'render_theme', side_effect=render), patch.object(manager, 'version_signature', return_value='v'):
    manager.render_previews(destination, manager.themes([root]), current)
print(json.dumps(calls))
'''
        start = time.monotonic()
        result = subprocess.run([sys.executable, '-c', script, str(Path(manager.__file__).parent),
                                 str(root), str(directory), str(self.current)],
                                capture_output=True, text=True, timeout=2, check=True)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(json.loads(result.stdout), ['good', 'theme'])
        self.assertEqual((directory / 'good.png').read_bytes(), b'render')

    def test_regular_symlink_and_size_limit_are_readable(self):
        target = self.base / 'colors.toml'
        target.write_bytes(b'x' * (256 * 1024))
        link = self.base / 'linked.toml'
        link.symlink_to(target)
        self.assertEqual(manager.read_theme_file(link), target.read_bytes())

    def test_renderer_timeout_kills_child_process_group(self):
        bindir = self.base / 'bin'; bindir.mkdir()
        pidfile = self.base / 'child.pid'
        renderer = bindir / 'qs'
        renderer.write_text('#!/usr/bin/python3\nimport os,signal,subprocess,time\nchild=subprocess.Popen(["/usr/bin/python3", "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])\nopen(os.environ["TEST_CHILD_PID"], "w").write(str(child.pid))\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n')
        renderer.chmod(0o755)
        actual = subprocess.Popen
        def start(*args, **kwargs):
            kwargs['env']['PATH'] = str(bindir) + os.pathsep + os.environ.get('PATH', '')
            kwargs['env']['TEST_CHILD_PID'] = str(pidfile)
            self.assertTrue(kwargs['start_new_session'])
            proc = actual(*args, **kwargs)
            original_wait = proc.wait
            def wait(timeout=None):
                return original_wait(timeout=2 if timeout == 20 else timeout)
            proc.wait = wait
            return proc
        with patch.object(manager.subprocess, 'Popen', side_effect=start):
            with self.assertRaises(subprocess.TimeoutExpired):
                manager.render_theme(self.current, self.base / 'out.png')
        pid = int(pidfile.read_text())
        try:
            status = Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0]
        except FileNotFoundError:
            status = 'gone'
        self.assertIn(status, ('gone', 'Z'))

    def test_renderer_exit_kills_child_process_group(self):
        bindir = self.base / 'bin'; bindir.mkdir()
        pidfile = self.base / 'child.pid'
        renderer = bindir / 'qs'
        renderer.write_text('''#!/usr/bin/python3
import os, subprocess, time
child = subprocess.Popen(['/usr/bin/python3', '-c', 'import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(os.environ["TEST_CHILD_PID"], "w").write(str(os.getpid())); time.sleep(60)'])
while not os.path.exists(os.environ['TEST_CHILD_PID']): time.sleep(.01)
open(os.environ['MAINFRAME_PREVIEW_OUTPUT'], 'wb').write(bytes.fromhex('89504e470d0a1a0a000000000000000000000640000003e8'))
''')
        renderer.chmod(0o755)
        actual = subprocess.Popen
        def start(*args, **kwargs):
            kwargs['env']['PATH'] = str(bindir) + os.pathsep + os.environ.get('PATH', '')
            kwargs['env']['TEST_CHILD_PID'] = str(pidfile)
            self.assertTrue(kwargs['start_new_session'])
            return actual(*args, **kwargs)
        try:
            with patch.object(manager.subprocess, 'Popen', side_effect=start):
                manager.render_theme(self.current, self.base / 'out.png')
            pid = int(pidfile.read_text())
            deadline = time.monotonic() + 2
            while True:
                try:
                    status = Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0]
                except FileNotFoundError:
                    status = 'gone'
                if status in ('gone', 'Z') or time.monotonic() >= deadline:
                    break
                time.sleep(.01)
            self.assertIn(status, ('gone', 'Z'))
        finally:
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_preview_lookup_and_override(self):
        user = self.image(self.home / '.config/omarchy/themes/ocean/preview.JPG')
        self.image(self.home / '.config/omarchy/themes/ocean/backgrounds/a.png')
        self.image(self.stock / 'themes/ocean/preview.png')
        fallback = self.image(self.stock / 'themes/forest/backgrounds/a.webp')
        result = manager.resolve()
        directory = Path(result['previewDir'])
        self.assertEqual((directory / 'ocean.jpg').resolve(), user)
        self.assertEqual((directory / 'forest.webp').resolve(), fallback)
        self.assertEqual((directory / 'follow-omarchy.jpg').resolve(), self.current / 'backgrounds/current.jpg')
        user.unlink()
        manager.resolve()
        self.assertFalse((directory / 'ocean.jpg').exists())
        self.assertEqual((directory / 'ocean.png').resolve(), self.home / '.config/omarchy/themes/ocean/backgrounds/a.png')

    def test_settings_persistence_fallback_and_cancel(self):
        theme = self.home / '.config/omarchy/themes/ocean'
        self.image(theme / 'preview.png')
        settings = self.config / 'mainframe/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('{"other": 4}')
        result = manager.resolve('ocean')
        self.assertEqual(result['colors'], str(theme / 'colors.toml'))
        self.assertEqual(json.loads(settings.read_text()), {'other': 4, 'theme': 'ocean'})
        self.assertEqual(manager.resolve()['theme'], 'ocean')
        self.assertIsNone(manager.resolve('unknown'))
        self.assertEqual(json.loads(settings.read_text())['theme'], 'ocean')
        (theme / 'preview.png').unlink()
        theme.rmdir()
        result = manager.resolve()
        self.assertTrue(result['missing'])
        self.assertEqual(result['theme'], manager.FOLLOW)
        self.assertEqual(result['active'], 'system')
        self.assertEqual(json.loads(settings.read_text()), {'other': 4, 'theme': manager.FOLLOW})

    def test_updated_image_invalidates_picker_directory_cache(self):
        image = self.image(self.stock / 'themes/ocean/preview.png')
        result = manager.resolve()
        directory = Path(result['previewDir'])
        old_time = 1_000_000_000
        os.utime(directory, ns=(old_time, old_time))
        image.write_bytes(b'changed image')
        manager.resolve()
        self.assertGreater(directory.stat().st_mtime_ns, old_time)
        self.assertEqual((directory / 'ocean.png').resolve(), image)

    def test_missing_picker_and_empty_selection(self):
        self.image(self.stock / 'themes/ocean/preview.png')
        manager.resolve('ocean')
        with patch.object(manager.shutil, 'which', return_value=None):
            result = manager.resolve('')
        self.assertFalse(result['picker'])
        self.assertEqual(result['theme'], 'ocean')

    def test_user_colors_and_stock_preview(self):
        user = self.home / '.config/omarchy/themes/ocean'
        user.mkdir(parents=True)
        stock = self.image(self.stock / 'themes/ocean/preview.webp')
        result = manager.resolve('ocean')
        self.assertEqual(result['colors'], str(user / 'colors.toml'))
        self.assertEqual(Path(result['selected']).resolve(), stock)

    def test_symlink_destination_is_moved_aside_without_touching_target(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'unrelated.png').symlink_to('somewhere')
        (outside / 'tool').symlink_to('elsewhere')
        destination = self.cache / 'mainframe/theme-previews'
        destination.parent.mkdir(parents=True)
        destination.symlink_to(outside, target_is_directory=True)
        manager.resolve()
        self.assertTrue(destination.is_dir())
        self.assertFalse(destination.is_symlink())
        backups = list(destination.parent.glob('theme-previews.bad-*'))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_symlink())
        self.assertEqual(os.readlink(backups[0]), str(outside))
        self.assertEqual(os.readlink(outside / 'unrelated.png'), 'somewhere')
        self.assertEqual(os.readlink(outside / 'tool'), 'elsewhere')

    def test_non_directory_destination_is_moved_aside(self):
        destination = self.cache / 'mainframe/theme-previews'
        destination.parent.mkdir(parents=True)
        destination.write_text('keep me')
        manager.resolve()
        self.assertTrue(destination.is_dir())
        backups = list(destination.parent.glob('theme-previews.bad-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'keep me')

    def test_symlink_parent_is_refused(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'untouched').symlink_to('target')
        self.cache.mkdir()
        (self.cache / 'mainframe').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            manager.resolve()
        self.assertEqual(os.readlink(outside / 'untouched'), 'target')
        self.assertEqual([p.name for p in outside.iterdir()], ['untouched'])

    def test_invalid_theme_names_and_unrelated_links_are_ignored(self):
        for name in ('good', '.hidden', '-bad', 'has space', 'x' * 65):
            self.image(self.stock / 'themes' / name / 'preview.png')
        destination = self.cache / 'mainframe/theme-previews'
        destination.mkdir(parents=True)
        for name in ('.hidden.png', '-bad.png', 'has space.png', 'tool', 'old.txt'):
            (destination / name).symlink_to('keep')
        (destination / 'stale.png').symlink_to('remove')
        (destination / 'regular.png').write_text('keep')
        result = manager.resolve()
        self.assertTrue((destination / 'good.png').is_symlink())
        self.assertNotIn('.hidden', manager.themes([self.stock / 'themes']))
        self.assertIsNone(manager.resolve('has space'))
        for name in ('.hidden.png', '-bad.png', 'has space.png', 'tool', 'old.txt'):
            self.assertEqual(os.readlink(destination / name), 'keep')
        self.assertFalse((destination / 'stale.png').is_symlink())
        self.assertEqual((destination / 'regular.png').read_text(), 'keep')
        self.assertEqual(result['theme'], manager.FOLLOW)

    def test_build_previews_rejects_invalid_names_from_caller(self):
        folder = self.stock / 'themes/good'
        self.image(folder / 'preview.png')
        destination = self.cache / 'mainframe/theme-previews'
        previews = manager.build_previews(destination, {
            '../escape': [folder], '.hidden': [folder], '-bad': [folder],
            'x' * 65: [folder], 'x' * 64: [folder],
        }, self.current)
        self.assertEqual(set(previews), {'x' * 64, manager.FOLLOW})
        self.assertFalse((destination.parent / 'escape.png').exists())

    def test_xdg_cache_home_can_be_a_symlink(self):
        actual_cache = self.base / 'actual-cache'
        actual_cache.mkdir()
        self.cache.symlink_to(actual_cache, target_is_directory=True)
        manager.resolve()
        self.assertTrue((actual_cache / 'mainframe/theme-previews').is_dir())

    def test_swapped_destination_cannot_redirect_cleanup(self):
        destination = self.cache / 'mainframe/theme-previews'
        destination.mkdir(parents=True)
        (destination / 'stale.png').symlink_to('old')
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'stale.png').symlink_to('keep')
        original_listdir = os.listdir

        def swap_before_listing(fd):
            destination.rename(destination.parent / 'original')
            destination.symlink_to(outside, target_is_directory=True)
            return original_listdir(fd)

        with patch.object(manager.os, 'listdir', side_effect=swap_before_listing):
            manager.resolve()
        self.assertEqual(os.readlink(outside / 'stale.png'), 'keep')
        self.assertFalse((destination.parent / 'original/stale.png').is_symlink())

    def test_unowned_preview_directory_is_refused(self):
        destination = self.cache / 'mainframe/theme-previews'
        destination.mkdir(parents=True)
        (destination / 'stale.png').symlink_to('keep')
        real_fstat = os.fstat

        def unowned(fd):
            info = real_fstat(fd)
            values = list(info)
            values[4] = os.getuid() + 1
            return os.stat_result(values)

        with patch.object(manager.os, 'fstat', side_effect=unowned):
            with self.assertRaises(PermissionError):
                manager.resolve()
        self.assertEqual(os.readlink(destination / 'stale.png'), 'keep')


if __name__ == '__main__':
    unittest.main()
