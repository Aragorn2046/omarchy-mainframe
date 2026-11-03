import datetime
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parents[1] / 'collect.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.cache = self.home / 'cache'
        self.now = datetime.datetime.now().astimezone()
        self.stamp = self.now.isoformat()
        self.day = c._usage_hour(self.stamp)
    def file(self, relative):
        p = self.home / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    def scan(self, **kwargs):
        return c.usage_scan(self.home, str(self.cache), now=self.now, **kwargs)
    def claude(self, ident, usage=None):
        return {'type':'assistant', 'timestamp':self.stamp, 'message':{'id':ident, 'model':'model-a', 'usage':usage or {'input_tokens':10}}}
    def lines(self, path, records, mode='w'):
        with path.open(mode) as out:
            for record in records: out.write(json.dumps(record) + '\n')
    def test_claude_dedupe_cache_and_directory_links(self):
        p = self.file('.claude/projects/a/x.jsonl')
        usage = {'input_tokens':10, 'cache_creation_input_tokens':80, 'cache_creation':{'ephemeral_5m_input_tokens':20,'ephemeral_1h_input_tokens':60}}
        self.lines(p, [self.claude('one', usage), self.claude('one', usage), self.claude('two', {'cache_creation_input_tokens':7})])
        link = self.file('.claude-accounts/example/projects'); link.symlink_to(self.home / '.claude/projects', target_is_directory=True)
        result = self.scan()['days'][self.day]['claude/model-a']
        self.assertEqual((result['input'], result['cache_write_5m'], result['cache_write_1h']), (10,27,60))
    def test_codex_cumulative_and_model_switch(self):
        p = self.file('.codex/sessions/a.jsonl')
        def context(model): return {'type':'turn_context', 'payload':{'model':model}}
        def count(i,o,cached): return {'type':'event_msg','timestamp':self.stamp,'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':i,'output_tokens':o,'cached_input_tokens':cached}}}}
        self.lines(p, [context('a'), count(100,20,40), count(90,10,30), context('b'), count(150,30,60)])
        days = self.scan()['days'][self.day]
        self.assertEqual((days['codex/a']['input'],days['codex/b']['input'],days['codex/b']['cached_input'],days['codex/b']['output']), (100,50,20,10))
    def test_append_and_shrink(self):
        p = self.file('.claude/projects/a.jsonl'); self.lines(p,[self.claude('one')])
        self.scan(); self.lines(p,[self.claude('two')],'a')
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'],20)
        self.lines(p,[self.claude('three')])
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'],30)
    def test_old_file_and_partial_resume(self):
        old = self.file('.claude/projects/old.jsonl'); self.lines(old,[self.claude('old')]); os.utime(old,(self.now.timestamp()-32*86400,)*2)
        p = self.file('.claude/projects/new.jsonl'); self.lines(p,[self.claude('new')])
        result = self.scan(limit=25); self.assertTrue(result['partial'])
        for _ in range(30):
            result = self.scan(limit=25)
            if not result['partial']: break
        self.assertFalse(result['partial']); self.assertEqual(result['days'][self.day]['claude/model-a']['input'],10)
    def test_corrupt_and_symlink_index(self):
        p = self.file('.claude/projects/a.jsonl'); self.lines(p,[self.claude('one')]); self.cache.mkdir()
        index = self.cache / 'usage-index.json'; index.write_text('{bad')
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'],10)
        index.unlink(); target = self.home / 'target'; target.write_text('keep'); index.symlink_to(target)
        with self.assertRaises(ValueError): self.scan()
        self.assertEqual(target.read_text(),'keep')

    def test_child_scan_uses_script_from_stdin(self):
        from unittest.mock import patch
        p = self.file('.claude/projects/a.jsonl'); self.lines(p,[self.claude('one')])
        with patch.dict(os.environ, {'HOME':str(self.home), 'XDG_CACHE_HOME':str(self.home / 'cache-root')}):
            result = c.usage_probe()
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'],10)

    def test_structurally_corrupt_index_rebuilds(self):
        p = self.file('.claude/projects/a.jsonl'); self.lines(p,[self.claude('one')]); self.cache.mkdir()
        (self.cache / 'usage-index.json').write_text('{"version":1,"files":{"bad":{"days":[]}}}')
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'],10)

    def test_claude_dedupe_across_files_and_request_ids(self):
        one = self.claude('same'); two = dict(one, requestId='other')
        self.lines(self.file('.claude/projects/a.jsonl'), [one, two])
        self.lines(self.file('.claude-accounts/work/projects/b.jsonl'), [one, two])
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_codex_copies_share_session_cursor(self):
        meta = {'type':'session_meta', 'payload':{'id':'session-1'}}
        context = {'type':'turn_context', 'payload':{'model':'c'}}
        def count(n): return {'type':'event_msg','timestamp':self.stamp,'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [meta, context, count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [meta, context, count(100), count(150)])
        self.assertEqual(self.scan()['days'][self.day]['codex/c']['input'], 150)
        self.assertEqual(self.scan()['days'][self.day]['codex/c']['input'], 150)

    def test_codex_fork_deduplicates_parent_events(self):
        def meta(ident): return {'type':'session_meta', 'payload':{'id':ident}}
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [meta('parent'), count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [meta('fork'), count(100), count(120)])
        for _ in range(2):
            self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 120)

    def test_file_cap_preserves_existing_files_and_marks_partial(self):
        from unittest.mock import patch
        for name in ('a', 'b', 'c'):
            self.lines(self.file('.claude/projects/' + name + '.jsonl'), [self.claude(name)])
        self.scan()
        with patch.object(c, '_USAGE_FILE_LIMIT', 2):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['reason'], 'too many files')
        self.assertEqual(len(json.loads((self.cache / 'usage-index.json').read_text())['files']), 3)

    def test_discovery_does_not_follow_nested_directory_symlinks(self):
        outside = self.file('outside/a.jsonl'); self.lines(outside, [self.claude('outside')])
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('inside')])
        (self.home / '.claude/projects/link').symlink_to(outside.parent, target_is_directory=True)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 10)

    def test_invalid_hour_values_rebuild_index(self):
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('one')]); self.scan()
        path = self.cache / 'usage-index.json'
        baseline = json.loads(path.read_text())
        for value in (None, {'model': None}, {'model': {'input': -1}}, {'model': {'input': True}}):
            index = json.loads(json.dumps(baseline)); index['hours'][self.day] = value
            path.write_text(json.dumps(index))
            self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 10)

    def test_oversized_tail_and_malformed_usage_lines_are_skipped(self):
        path = self.file('.claude/projects/a.jsonl')
        path.write_bytes(b'x' * (c._USAGE_LINE_LIMIT + 100) + b'"usage"}\n' + b'{"usage": invalid}\n')
        for _ in range(2):
            result = self.scan(limit=1024 * 1024)
        result = self.scan(limit=1024 * 1024)
        self.assertTrue(result['partial']); self.assertEqual(result['skipped'], 2)
        self.assertEqual(self.scan()['skipped'], 2)

    def test_killed_after_first_file_keeps_checkpoint(self):
        import subprocess, sys
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('a')])
        self.lines(self.file('.claude/projects/b.jsonl'), [self.claude('b')])
        code = """import importlib.util, os, sys
spec=importlib.util.spec_from_file_location('c', sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
write=c._usage_write
def stop(path, index):
    write(path, index)
    os._exit(17)
c._usage_write=stop
c._USAGE_CHECKPOINT_BYTES=os.path.getsize(os.path.join(sys.argv[2], '.claude/projects/a.jsonl'))
c.usage_scan(sys.argv[2], sys.argv[3])
"""
        run = subprocess.run([sys.executable, '-c', code, str(Path(c.__file__)), str(self.home), str(self.cache)])
        self.assertEqual(run.returncode, 17)
        saved = json.loads((self.cache / 'usage-index.json').read_text())
        self.assertEqual(len(saved['files']), 1)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_mid_file_read_failure_does_not_double_count(self):
        from unittest.mock import patch
        import builtins
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('one'), self.claude('two')])
        real_open = builtins.open
        class Broken:
            def __init__(self, stream): self.stream, self.reads = stream, 0
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def __getattr__(self, name): return getattr(self.stream, name)
            def readline(self, *args):
                self.reads += 1
                if self.reads == 2: raise OSError('test read error')
                return self.stream.readline(*args)
        def open_file(name, *args, **kwargs):
            stream = real_open(name, *args, **kwargs)
            return Broken(stream) if str(name) == str(path) and args and args[0] == 'rb' else stream
        with patch('builtins.open', side_effect=open_file):
            self.assertTrue(self.scan()['partial'])
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_same_size_replacement_keeps_old_and_counts_new(self):
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        self.scan()
        replacement = self.file('.claude/projects/replacement'); self.lines(replacement, [self.claude('two')])
        self.assertEqual(path.stat().st_size, replacement.stat().st_size)
        os.replace(replacement, path)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_long_line_stays_partial(self):
        path = self.file('.claude/projects/a.jsonl')
        path.write_bytes(b'"usage"' + b'x' * (c._USAGE_LINE_LIMIT + 1) + b'\n')
        self.lines(path, [self.claude('one')], 'a')
        for result in (self.scan(), self.scan()):
            self.assertTrue(result['partial']); self.assertEqual(result['skipped'], 1)
            self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)

    def test_utc_hour_and_migration_and_pruning(self):
        path = self.file('.claude/projects/a.jsonl')
        record = self.claude('one'); record['timestamp'] = self.now.replace(hour=0, minute=30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))).isoformat()
        self.lines(path, [record]); self.cache.mkdir()
        (self.cache / 'usage-index.json').write_text(json.dumps({'version':1, 'files':{}, 'days':{'2020-01-01':{}}}))
        result = self.scan(); hour = c._usage_hour(record['timestamp'])
        self.assertIn(hour, result['days']); self.assertEqual(hour[11:], '22:30')
        path.unlink(); self.scan()
        index = json.loads((self.cache / 'usage-index.json').read_text())
        self.assertEqual(index['files'], {}); self.assertIn(hour, index['hours'])

    def test_walk_and_open_errors_are_partial(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        import builtins
        real_open = builtins.open
        def denied(name, *args, **kwargs):
            if str(name) == str(path): raise PermissionError('denied')
            return real_open(name, *args, **kwargs)
        with patch('builtins.open', side_effect=denied):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['skipped'], 1)
        def broken_walk(root, **kwargs):
            kwargs['onerror'](OSError('walk failed'))
            return iter(())
        with patch.object(c.os, 'walk', side_effect=broken_walk):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertGreater(result['skipped'], 0)

    def test_failed_probe_marks_previous_result_stale(self):
        old = c._probe['usage']; c._probe['usage'] = {'days':{}, 'scanned_at':'2026-01-01T00:00:00Z'}
        self.addCleanup(c._probe.__setitem__, 'usage', old)
        def fail(): raise RuntimeError('failure')
        c._background_probe('usage', fail)
        self.assertTrue(c._probe['usage']['stale'])
        self.assertEqual(c._probe['usage']['scanned_at'], '2026-01-01T00:00:00Z')

    def test_remote_prefix_and_child_scan(self):
        import ast, queue, subprocess, sys, threading, time
        source = Path(c.__file__).read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module == '__future__' for node in ast.walk(tree)))
        self.assertNotIn('__doc__', source)
        shell = (Path(c.__file__).parent / 'shell.qml').read_text()
        self.assertIn('"_SCRIPT_SOURCE = " + JSON.stringify(src) + "\\n" + src', shell)
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('remote')])
        env = dict(os.environ, HOME=str(self.home), XDG_CACHE_HOME=str(self.home / 'remote-cache'))
        proc = subprocess.Popen([sys.executable, '-u', '-', '--remote'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        proc.stdin.write('_SCRIPT_SOURCE = ' + json.dumps(source, ensure_ascii=False) + '\n' + source)
        proc.stdin.close()
        lines = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()
        deadline = time.monotonic() + 40
        found = None
        while time.monotonic() < deadline:
            try: item = json.loads(lines.get(timeout=max(0.1, deadline-time.monotonic())))
            except queue.Empty: break
            if item.get('usage'):
                found = item['usage']; break
        proc.terminate(); proc.wait(timeout=5); proc.stdout.close()
        self.assertIsNotNone(found, 'remote child scan did not return')
        self.assertEqual(found['days'][self.day]['claude/model-a']['input'], 10)

    def test_checkpoint_within_large_file(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('one'), self.claude('two'), self.claude('three')])
        write = c._usage_write
        def stop(index_path, index):
            write(index_path, index)
            raise SystemExit('kill after checkpoint')
        with patch.object(c, '_USAGE_CHECKPOINT_BYTES', 180), patch.object(c, '_usage_write', side_effect=stop):
            with self.assertRaises(SystemExit): self.scan()
        saved = json.loads((self.cache / 'usage-index.json').read_text())
        self.assertGreater(saved['files'][str(path)]['offset'], 0)
        self.assertLess(saved['files'][str(path)]['offset'], path.stat().st_size)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 30)

    def test_old_and_oversized_indexes_are_rebuilt(self):
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        self.scan()
        os.utime(path, (self.now.timestamp()-32*86400,)*2)
        self.scan()
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['files'], {})
        os.utime(path, None)
        with (self.cache / 'usage-index.json').open('wb') as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        result = self.scan()
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)
        self.assertLess((self.cache / 'usage-index.json').stat().st_size, 64 * 1024 * 1024)

    def test_seen_prunes_old_days_and_evicts_oldest_at_cap(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('first')]); self.scan()
        index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text())
        original = next(iter(index['seen']))
        index['seen'][original] = (self.now.date() - datetime.timedelta(days=5)).isoformat()
        index['seen']['expired'] = (self.now.date() - datetime.timedelta(days=36)).isoformat()
        index_path.write_text(json.dumps(index))
        self.lines(path, [self.claude('next'), self.claude('last')], 'a')
        with patch.object(c, '_USAGE_SEEN_LIMIT', 2): result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['reason'], 'dedupe window full')
        index = json.loads(index_path.read_text())
        self.assertEqual(len(index['seen']), 2)
        self.assertNotIn('expired', index['seen']); self.assertNotIn(original, index['seen'])

    def test_same_inode_rewrite_is_recounted(self):
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        self.scan(); inode = path.stat().st_ino
        self.lines(path, [self.claude('two')])
        self.assertEqual(path.stat().st_ino, inode)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_index_exceeding_limit_is_reset_for_rebuild(self):
        from unittest.mock import patch
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('one')])
        with patch.object(c, '_USAGE_INDEX_LIMIT', 200):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['reason'], 'index too large')
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['files'], {})
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 10)

    def test_stat_error_is_partial(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        real_stat = os.stat
        def denied(name, *args, **kwargs):
            if str(name) == str(path): raise PermissionError('denied')
            return real_stat(name, *args, **kwargs)
        with patch.object(c.os, 'stat', side_effect=denied): result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['skipped'], 1)

    def test_warm_scan_does_not_write_and_changes_checkpoint_once(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        self.scan()
        with patch.object(c, '_usage_write', wraps=c._usage_write) as write:
            self.scan(); write.assert_not_called()
            self.lines(path, [self.claude('two')], 'a')
            self.scan(); self.assertEqual(write.call_count, 1)

    def test_time_checkpoint_occurs_during_scan(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one'), self.claude('two')])
        values = iter([0, 31, 31, 31, 31, 31, 31, 31, 31, 31])
        with patch.object(c.time, 'monotonic', side_effect=lambda: next(values, 31)), patch.object(c, '_usage_write', wraps=c._usage_write) as write:
            result = self.scan()
        self.assertGreaterEqual(write.call_count, 2)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 20)

    def test_corrupt_file_fields_reset_without_unbounded_reads(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')])
        self.scan(); index_path = self.cache / 'usage-index.json'
        baseline = json.loads(index_path.read_text())
        for field, value in [('head_len', 10**100), ('offset', -1), ('size', True), ('ino', -1), ('dev', '1'), ('mtime_ns', -1), ('offset', path.stat().st_size + 1)]:
            index = json.loads(json.dumps(baseline)); index['files'][str(path)][field] = value
            index['seen'] = {}; index['hours'] = {}
            index_path.write_text(json.dumps(index))
            result = self.scan()
            self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10, field)

    def test_invalid_session_cursor_resets_file(self):
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type':'session_meta','payload':{'id':'s'}}, {'type':'event_msg','timestamp':self.stamp,'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':10}}}}])
        self.scan(); index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text()); index['sessions']['s']['input_tokens'] = -1; index['hours'] = {}
        index_path.write_text(json.dumps(index))
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 10)

    def test_write_failure_is_partial_and_preserves_existing_index(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')]); self.scan()
        index_path = self.cache / 'usage-index.json'; original = index_path.read_bytes()
        self.lines(path, [self.claude('two')], 'a')
        with patch.object(c, '_usage_write', side_effect=OSError('failure')) as write:
            result = self.scan(); self.assertEqual(write.call_count, 1)
        self.assertTrue(result['partial']); self.assertEqual(result['reason'], 'index write failed')
        self.assertEqual(index_path.read_bytes(), original)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_oversize_prunes_seen_before_reset(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')]); self.scan()
        index_path = self.cache / 'usage-index.json'; index = json.loads(index_path.read_text())
        index['seen'].update({str(i): self.now.date().isoformat() for i in range(100)})
        size_without_extra = len(json.dumps(dict(index, seen={}), separators=(',', ':')).encode())
        with patch.object(c, '_USAGE_INDEX_LIMIT', size_without_extra + 200):
            status = c._usage_write(str(index_path), index)
        self.assertEqual(status, 'evicted')
        saved = json.loads(index_path.read_text()); self.assertTrue(saved['files']); self.assertTrue(saved['hours'])

    def test_long_non_usage_and_late_marker_are_not_skipped(self):
        path = self.file('.claude/projects/a.jsonl')
        path.write_bytes(b'x' * 65536 + b'"usage"' + b'x' * c._USAGE_LINE_LIMIT + b'\n')
        result = self.scan(); self.assertFalse(result['partial']); self.assertEqual(result['skipped'], 0)

    def test_skipped_counts_expire_and_reset_with_file(self):
        path = self.file('.claude/projects/a.jsonl'); path.write_bytes(b'token_count' + b'x' * c._USAGE_LINE_LIMIT + b'\n')
        self.assertEqual(self.scan()['skipped'], 1)
        index_path = self.cache / 'usage-index.json'; index = json.loads(index_path.read_text())
        index['files'][str(path)]['skip_days'] = {'2000-01-01': 1}; index_path.write_text(json.dumps(index))
        self.assertEqual(self.scan()['skipped'], 0)
        path.write_bytes(b'"usage"' + b'x' * c._USAGE_LINE_LIMIT + b'\n')
        self.assertEqual(self.scan()['skipped'], 1)
        self.lines(path, [self.claude('new')])
        self.assertEqual(self.scan()['skipped'], 0)

    def test_usage_emitted_only_when_changed_and_on_reconnect(self):
        sender = c._UsageEmitter(); usage = {'days': {'x': {}}}
        self.assertEqual(sender.filter({'usage': usage})['usage'], usage)
        self.assertNotIn('usage', sender.filter({'usage': usage}))
        usage['days']['x']['model'] = 1
        self.assertEqual(sender.filter({'usage': usage})['usage'], usage)
        self.assertIn('usage', c._UsageEmitter().filter({'usage': usage}))

    def test_zero_usage_does_not_block_later_counted_message(self):
        empty = self.claude('same', {'input_tokens':0})
        self.lines(self.file('.claude/projects/a.jsonl'), [empty, self.claude('same')])
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 10)
