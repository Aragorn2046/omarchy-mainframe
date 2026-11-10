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
        from unittest.mock import patch
        env = {k: v for k, v in os.environ.items() if k != 'MAINFRAME_USAGE_SCAN' and not k.startswith('XDG_') and k not in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME')}
        env['MAINFRAME_AGENTS_SCAN'] = '0'
        env_patch = patch.dict(os.environ, env, clear=True)
        env_patch.start(); self.addCleanup(env_patch.stop)
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
    def test_codex_same_totals_different_last_turn(self):
        def record(delta):
            return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':100}, 'last_token_usage':{'input_tokens':delta}}}}
        for name, delta in [('one', 10), ('two', 20)]:
            self.lines(self.file('.codex/sessions/' + name + '.jsonl'), [record(delta)])
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 200)

    def test_model_name_and_count_bounds(self):
        records = []
        for i in range(27):
            record = self.claude('id-' + str(i), {'input_tokens':i + 1})
            record['message']['model'] = 'model-%02d-' % i + 'x' * 80
            records.append(record)
        self.lines(self.file('.claude/projects/a.jsonl'), records)
        models = self.scan()['days'][self.day]
        self.assertEqual(len(models), 25)
        self.assertTrue(all(len(name.split('/', 1)[1]) <= 64 for name in models))
        self.assertEqual(models['claude/other']['input'], 25 + 26 + 27)
        self.assertEqual(sum(v['input'] for v in models.values()), sum(range(1, 28)))

    def test_index_memory_error_rebuilds(self):
        from unittest.mock import patch
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('one')]); self.scan()
        index_text = (self.cache / 'usage-index.json').read_text()
        loads = json.loads
        def parse(text, *args, **kwargs):
            if text == index_text: raise MemoryError
            return loads(text, *args, **kwargs)
        with patch.object(c.json, 'loads', side_effect=parse):
            result = self.scan()
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['version'], 8)

    def test_unchanged_file_not_opened_but_mtime_change_is_fingerprinted(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl'); self.lines(path, [self.claude('one')]); self.scan()
        real_open = os.open
        opened = []
        def track(name, *args, **kwargs):
            if str(name) == str(path): opened.append(name)
            return real_open(name, *args, **kwargs)
        with patch.object(c.os, 'open', side_effect=track):
            self.assertFalse(self.scan(limit=1)['partial'])
        self.assertEqual(opened, [])
        st = path.stat(); os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000000))
        with patch.object(c.os, 'open', side_effect=track), patch.object(c.hashlib, 'sha1', wraps=c.hashlib.sha1) as digest:
            self.scan()
        self.assertEqual(len(opened), 1)
        self.assertGreaterEqual(digest.call_count, 2)

    def test_unchanged_partial_file_resumes_without_fingerprint(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        path.write_bytes(b'x' * 1000 + b'\n')
        self.assertTrue(self.scan(limit=20)['partial'])
        with patch.object(c.hashlib, 'sha1', wraps=c.hashlib.sha1) as digest:
            self.scan(limit=20)
        digest.assert_not_called()

    def test_additional_roots_and_realpath_deduplication(self):
        from unittest.mock import patch
        paths = ['.claude/projects/a.jsonl', '.config/claude/projects/b.jsonl', 'custom-claude/projects/c.jsonl', '.codex/sessions/d.jsonl', 'custom-codex/sessions/e.jsonl']
        for i, path in enumerate(paths):
            if i < 3: self.lines(self.file(path), [self.claude('id-' + str(i))])
            else: self.lines(self.file(path), [{'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':i}, 'last_token_usage':{'input_tokens':i}}}}])
        with patch.dict(os.environ, {'HOME':str(self.home), 'CLAUDE_CONFIG_DIR':str(self.home / 'custom-claude'), 'CODEX_HOME':str(self.home / 'custom-codex')}):
            result = self.scan()
            self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 30)
            self.assertEqual(result['days'][self.day]['codex/unknown']['input'], 7)
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR':str(self.home / '.claude')}):
                self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 30)

    def test_seen_trim_threshold(self):
        from unittest.mock import patch
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('one')]); self.scan()
        path = self.cache / 'usage-index.json'; index = json.loads(path.read_text())
        day = self.now.date().isoformat()
        index['seen'] = {str(i):day for i in range(11)}; path.write_text(json.dumps(index))
        with patch.object(c, '_USAGE_SEEN_LIMIT', 10):
            self.assertFalse(self.scan()['partial'])
            index = json.loads(path.read_text()); self.assertEqual(len(index['seen']), 11)
            index['seen']['extra'] = day; path.write_text(json.dumps(index))
            self.assertTrue(self.scan()['partial'])
        self.assertEqual(len(json.loads(path.read_text())['seen']), 10)

    def test_first_failed_probe_is_visible(self):
        from unittest.mock import patch
        probe = {'usage':None}
        def fail(): raise RuntimeError('failed to scan')
        with patch.object(c, '_probe', probe): c._background_probe('usage', fail)
        self.assertEqual(probe['usage'], {'days':{}, 'error':'failed to scan', 'stale':True})
        self.assertEqual(probe['usage_snapshot'][1], 1)

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

    def test_growth_during_scan_stops_at_recorded_size(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        first = (json.dumps(self.claude('one')) + '\n').encode()
        second = (json.dumps(self.claude('two')) + '\n').encode()
        third = (json.dumps(self.claude('three')) + '\n').encode()
        split = len(second) // 2
        path.write_bytes(first + second[:split])
        snapshot_size = path.stat().st_size
        real_fdopen = os.fdopen
        read_offsets = []
        appended = False

        class GrowingStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def __getattr__(self, name): return getattr(self.stream, name)
            def readline(self, *args):
                nonlocal appended
                read_offsets.append(self.stream.tell())
                if not appended:
                    with path.open('ab') as out: out.write(second[split:] + third)
                    appended = True
                return self.stream.readline(*args)

        def open_file(fd, *args, **kwargs):
            stream = real_fdopen(fd, *args, **kwargs)
            return GrowingStream(stream) if args and args[0] == 'rb' else stream

        with patch.object(c.os, 'fdopen', side_effect=open_file):
            result = self.scan()
        cursor = json.loads((self.cache / 'usage-index.json').read_text())['files'][str(path)]
        self.assertEqual(cursor['size'], snapshot_size)
        self.assertLessEqual(cursor['offset'], cursor['size'])
        self.assertEqual(cursor['offset'], snapshot_size)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)
        read_offsets.clear()
        with patch.object(c.os, 'fdopen', side_effect=open_file):
            result = self.scan()
        self.assertEqual(read_offsets[0], snapshot_size)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 30)

    def test_old_file_and_partial_resume(self):
        old = self.file('.claude/projects/old.jsonl'); self.lines(old,[self.claude('old')]); os.utime(old,(self.now.timestamp()-32*86400,)*2)
        p = self.file('.claude/projects/new.jsonl'); self.lines(p,[self.claude('new')])
        result = self.scan(limit=p.stat().st_size + 25); self.assertTrue(result['partial'])
        for _ in range(30):
            result = self.scan(limit=2 * p.stat().st_size + 25)
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

    def test_claude_repeated_snapshots_keep_largest_values(self):
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('same', {'input_tokens':10, 'output_tokens':1, 'cache_read_input_tokens':20})])
        self.scan()
        self.lines(path, [self.claude('same', {'input_tokens':5, 'output_tokens':100, 'cache_read_input_tokens':30}),
                          self.claude('same', {'input_tokens':15, 'output_tokens':2, 'cache_read_input_tokens':1})], 'a')
        for _ in range(2):
            result = self.scan()['days'][self.day]['claude/model-a']
            self.assertEqual((result['input'], result['output'], result['cache_read']), (15, 100, 30))

    def test_codex_warm_scan_reads_no_header_bytes(self):
        from unittest.mock import patch
        self.lines(self.file('.codex/sessions/a.jsonl'), [{'type':'session_meta', 'payload':{'id':'s'}}])
        self.scan()
        fdopen = c.os.fdopen
        header_bytes = []
        class TrackedStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def __getattr__(self, name): return getattr(self.stream, name)
            def readline(self, *args):
                data = self.stream.readline(*args)
                header_bytes.append(len(data))
                return data
        def tracked(fd, mode, *args, **kwargs):
            stream = fdopen(fd, mode, *args, **kwargs)
            return TrackedStream(stream) if mode == 'rb' else stream
        with patch.object(c.os, 'fdopen', side_effect=tracked):
            self.scan()
        self.assertEqual(sum(header_bytes), 0)

    def test_codex_reads_obey_budget_and_resume(self):
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type':'session_meta', 'payload':{'id':'s', 'padding':'x' * 100}},
                          {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':10}}}}])
        self.assertTrue(self.scan(limit=path.stat().st_size + 25)['partial'])
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['files'][str(path)]['offset'], 25)
        for _ in range(30):
            result = self.scan(limit=2 * path.stat().st_size + 25)
            if not result['partial']: break
        self.assertFalse(result['partial'])
        self.assertEqual(result['days'][self.day]['codex/unknown']['input'], 10)

    def test_codex_copies_share_session_cursor(self):
        meta = {'type':'session_meta', 'payload':{'id':'session-1'}}
        context = {'type':'turn_context', 'payload':{'model':'c'}}
        def count(n): return {'type':'event_msg','timestamp':self.stamp,'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [meta, context, count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [meta, context, count(100), count(150)])
        self.assertEqual(self.scan()['days'][self.day]['codex/c']['input'], 150)
        self.assertEqual(self.scan()['days'][self.day]['codex/c']['input'], 150)

    def test_codex_fork_deduplicates_parent_events(self):
        def meta(ident, parent=None): return {'type':'session_meta', 'payload':{'id':ident, 'forked_from_id':parent}}
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [meta('parent'), count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [meta('fork', 'parent'), count(100), count(120)])
        for _ in range(2):
            self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 120)

    def test_parent_and_fork_advance_in_either_order(self):
        def meta(ident, parent=None): return {'type': 'session_meta', 'payload': {'id': ident, 'forked_from_id': parent}}
        def count(n): return {'type': 'event_msg', 'timestamp': self.stamp, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': n}}}}
        for parent_name, fork_name in (('a', 'b'), ('b', 'a')):
            with self.subTest(parent_first=parent_name == 'a'), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / '.codex/sessions'; root.mkdir(parents=True)
                self.lines(root / (parent_name + '.jsonl'), [meta('parent'), count(100), count(200)])
                self.lines(root / (fork_name + '.jsonl'), [meta('fork', 'parent'), count(100), count(120)])
                for _ in range(2):
                    result = c.usage_scan(home, str(home / 'cache'), now=self.now)
                    self.assertEqual(result['days'][self.day]['codex/unknown']['input'], 220)

    def test_parent_and_fork_continue_after_initial_scan(self):
        def count(n): return {'type': 'event_msg', 'timestamp': self.stamp, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': n}}}}
        parent = self.file('.codex/sessions/a.jsonl')
        fork = self.file('.codex/sessions/b.jsonl')
        self.lines(parent, [{'type': 'session_meta', 'payload': {'id': 'parent'}}, count(100)])
        self.lines(fork, [{'type': 'session_meta', 'payload': {'id': 'fork', 'forked_from_id': 'parent'}}, count(100)])
        self.scan()
        self.lines(parent, [count(200)], 'a')
        self.lines(fork, [count(120)], 'a')
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 220)

    def test_replaced_codex_file_starts_a_new_cursor(self):
        def count(n): return {'type': 'event_msg', 'timestamp': self.stamp, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': n}}}}
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type': 'session_meta', 'payload': {'id': 'first'}}, count(100)])
        self.scan()
        replacement = self.file('.codex/sessions/replacement')
        self.lines(replacement, [{'type': 'session_meta', 'payload': {'id': 'second'}}, count(30)])
        os.replace(replacement, path)
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 130)

    def test_long_codex_ids_are_not_retained(self):
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type': 'session_meta', 'payload': {'id': 's' * 129, 'forked_from_id': 'p' * 129}}])
        self.scan()
        index = (self.cache / 'usage-index.json').read_text()
        self.assertNotIn('s' * 129, index)
        self.assertNotIn('p' * 129, index)

    def test_codex_independent_sessions_with_different_totals(self):
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [{'type':'session_meta', 'payload':{'id':'one'}}, count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [{'type':'session_meta', 'payload':{'id':'two'}}, count(110)])
        for _ in range(2):
            self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 210)

    def test_codex_multigeneration_copies_in_reverse_order(self):
        def meta(ident, parent=None): return {'type':'session_meta', 'payload':{'session_id':ident, 'forked_from_id':parent, 'parent_thread_id':'unrelated'}}
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [meta('grandchild', 'child'), count(100)])
        self.lines(self.file('.codex/sessions/b.jsonl'), [meta('child', 'parent'), count(100)])
        self.lines(self.file('.codex/sessions/c.jsonl'), [meta('parent'), count(100)])
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 100)

    def test_codex_parent_appears_after_child(self):
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        child = self.file('.codex/sessions/a.jsonl')
        self.lines(child, [{'type':'session_meta', 'payload':{'id':'child', 'forked_from_id':'parent'}}, count(100)])
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 100)
        parent = self.file('.codex/sessions/b.jsonl')
        self.lines(parent, [{'type':'session_meta', 'payload':{'id':'parent', 'forked_from_id':'grandparent'}}, count(100)])
        for _ in range(2):
            self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 100)

    def test_codex_fork_copy_with_new_timestamp(self):
        def count(stamp): return {'type':'event_msg', 'timestamp':stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':100}}}}
        self.lines(self.file('.codex/sessions/a.jsonl'), [{'type':'session_meta', 'payload':{'id':'parent'}}, count(self.stamp)])
        later = (self.now + datetime.timedelta(minutes=1)).isoformat()
        self.lines(self.file('.codex/sessions/b.jsonl'), [{'type':'session_meta', 'payload':{'id':'fork', 'forked_from_id':'parent'}}, count(later)])
        result = self.scan()
        self.assertEqual(sum(counts.get('input', 0) for models in result['days'].values() for counts in models.values()), 100)

    def test_old_index_versions_are_rebuilt(self):
        path = self.file('.codex/sessions/a.jsonl')
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(path, [count(100), count(200)])
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 200)
        index_path = self.cache / 'usage-index.json'
        for version in (6, 7):
            index = json.loads(index_path.read_text()); index['version'] = version
            index_path.write_text(json.dumps(index))
            self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 200)
            self.assertEqual(json.loads(index_path.read_text())['version'], 8)

    def test_legacy_header_scan_is_removed(self):
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type':'session_meta', 'payload':{'id':'session'}}])
        self.scan()
        index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text()); index['files'][str(path)]['header_scan'] = {'root':'old'}
        index_path.write_text(json.dumps(index))
        self.assertFalse(self.scan()['partial'])
        self.assertNotIn('header_scan', json.loads(index_path.read_text())['files'][str(path)])

    def test_unchanged_file_fingerprints_obey_budget(self):
        from unittest.mock import patch
        for i in range(12):
            self.lines(self.file(f'.claude/projects/{i:02}.jsonl'), [self.claude(str(i))])
        self.scan()
        total = sum(p.stat().st_size for p in (self.home / '.claude/projects').glob('*.jsonl'))
        with patch.object(c, '_USAGE_LIMIT', 1):
            result = self.scan(limit=c._USAGE_LIMIT)
        self.assertFalse(result['partial'])
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 120)
        self.assertGreater(total, 1)

    def test_oversized_claude_assistant_line_with_usage_at_end(self):
        path = self.file('.claude/projects/a.jsonl')
        record = self.claude('oversized')
        record['message']['content'] = 'x' * (c._USAGE_LINE_LIMIT + 100)
        record['message']['usage'] = record['message'].pop('usage')
        self.lines(path, [record])
        self.assertIn(b'"usage"', path.read_bytes()[-65536:])
        result = self.scan()
        self.assertTrue(result['partial'])
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['days'], {})

    def test_missing_codex_cursor_replays_before_new_event(self):
        path = self.file('.codex/sessions/a.jsonl')
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(path, [{'type':'session_meta', 'payload':{'id':'s'}}, count(100)])
        self.scan()
        index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text()); del index['sessions'][str(path)]
        index_path.write_text(json.dumps(index))
        self.lines(path, [count(120)], 'a')
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 120)

    def test_missing_codex_file_state_replays_before_new_event(self):
        path = self.file('.codex/sessions/a.jsonl')
        def count(n): return {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':n}}}}
        self.lines(path, [{'type':'session_meta', 'payload':{'id':'s'}}, count(100)])
        self.scan()
        index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text()); del index['files'][str(path)]['session']
        index_path.write_text(json.dumps(index))
        self.lines(path, [count(120)], 'a')
        self.assertEqual(self.scan()['days'][self.day]['codex/unknown']['input'], 120)

    def test_codex_partial_line_resumes_before_first_cursor(self):
        path = self.file('.codex/sessions/a.jsonl')
        self.lines(path, [{'type':'session_meta', 'payload':{'id':'s'}}, {'type':'event_msg', 'timestamp':self.stamp, 'payload':{'type':'token_count', 'info':{'total_token_usage':{'input_tokens':100}}}}])
        self.assertTrue(self.scan(limit=path.stat().st_size + 25)['partial'])
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['files'][str(path)]['offset'], 25)
        for _ in range(30):
            result = self.scan(limit=2 * path.stat().st_size + 25)
            if not result['partial']: break
        self.assertFalse(result['partial'])
        self.assertEqual(result['days'][self.day]['codex/unknown']['input'], 100)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFO')
    def test_fifo_jsonl_is_skipped_without_blocking(self):
        import subprocess, sys
        os.mkfifo(self.file('.claude/projects/x.jsonl'))
        code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('c',sys.argv[1]); c=importlib.util.module_from_spec(s); s.loader.exec_module(c); c.usage_scan(sys.argv[2],sys.argv[3])"
        subprocess.run([sys.executable, '-c', code, str(Path(c.__file__)), str(self.home), str(self.cache)], check=True, timeout=5)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFO')
    def test_fifo_index_does_not_block(self):
        import subprocess, sys
        self.cache.mkdir()
        os.mkfifo(self.cache / 'usage-index.json')
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('one')])
        code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('c',sys.argv[1]); c=importlib.util.module_from_spec(s); s.loader.exec_module(c); c.usage_scan(sys.argv[2],sys.argv[3])"
        subprocess.run([sys.executable, '-c', code, str(Path(c.__file__)), str(self.home), str(self.cache)], check=True, timeout=5)
        self.assertEqual(json.loads((self.cache / 'usage-index.json').read_text())['hours'][self.day]['claude/model-a']['input'], 10)

    def test_entry_cap_counts_directories_and_non_jsonl_files(self):
        from unittest.mock import patch
        self.file('.claude/projects/a/ignored.txt').write_text('x')
        self.file('.claude/projects/b/ignored.txt').write_text('x')
        with patch.object(c, '_USAGE_FILE_LIMIT', 2):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['reason'], 'too many files')

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

    def test_nested_usage_record_is_skipped_before_parsing(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        deep = '{"usage":' + '[' * 128 + '0' + ']' * 128 + '}'
        normal = self.claude('valid')
        normal['text'] = '\\"' + '[' * 200 + '}' * 200
        path.write_bytes(deep.encode() + b'\n' + json.dumps(normal).encode() + b'\n')
        loads = json.loads
        def parse(raw, *args, **kwargs):
            self.assertNotEqual(raw, deep, 'deep record reached the JSON parser')
            return loads(raw, *args, **kwargs)
        with patch.object(c.json, 'loads', side_effect=parse):
            result = self.scan()
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)

    def test_nested_usage_index_is_rebuilt_before_parsing(self):
        from unittest.mock import patch
        self.lines(self.file('.claude/projects/a.jsonl'), [self.claude('valid')])
        self.cache.mkdir()
        deep = '[' * 129 + '0' + ']' * 129
        (self.cache / 'usage-index.json').write_text(deep)
        depth_ok = c._usage_json_depth_ok
        loads = json.loads
        checked = []
        def check(text):
            result = depth_ok(text)
            checked.append((text, result))
            return result
        def parse(text, *args, **kwargs):
            self.assertNotEqual(text, deep, 'deep index reached the JSON parser')
            return loads(text, *args, **kwargs)
        with patch.object(c, '_usage_json_depth_ok', side_effect=check), \
                patch.object(c.json, 'loads', side_effect=parse), \
                patch.object(c.json, 'load', side_effect=AssertionError('unexpected json.load')):
            result = self.scan()
        self.assertIn((deep, False), checked)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)

    def test_bomless_utf16_usage_line_is_skipped(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        record = self.claude('utf16')
        # Ensure the byte-level marker is present in an otherwise valid UTF-16LE record.
        record['text'] = ''.join(chr(int.from_bytes(pair, 'little')) for pair in
                                 (b'to', b'ke', b'n_', b'co', b'un', b't '))
        encoded = json.dumps(record, ensure_ascii=False).encode('utf-16le')
        self.assertIn(b'token_count', encoded)
        path.write_bytes(encoded + b'\n' + json.dumps(self.claude('valid')).encode() + b'\n')
        loads = json.loads
        def parse(text, *args, **kwargs):
            self.assertNotEqual(text, encoded, 'UTF-16 record reached the JSON parser as bytes')
            return loads(text, *args, **kwargs)
        with patch.object(c.json, 'loads', side_effect=parse):
            result = self.scan()
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['days'][self.day]['claude/model-a']['input'], 10)

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
        run = subprocess.run([sys.executable, '-c', code, str(Path(c.__file__)), str(self.home), str(self.cache)], timeout=60)
        self.assertEqual(run.returncode, 17)
        saved = json.loads((self.cache / 'usage-index.json').read_text())
        self.assertEqual(len(saved['files']), 1)
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 20)

    def test_mid_file_read_failure_does_not_double_count(self):
        from unittest.mock import patch
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('one'), self.claude('two')])
        real_fdopen = os.fdopen
        class Broken:
            def __init__(self, stream): self.stream, self.reads = stream, 0
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def __getattr__(self, name): return getattr(self.stream, name)
            def readline(self, *args):
                self.reads += 1
                if self.reads == 2: raise OSError('test read error')
                return self.stream.readline(*args)
        def open_file(fd, *args, **kwargs):
            stream = real_fdopen(fd, *args, **kwargs)
            return Broken(stream) if args and args[0] == 'rb' else stream
        with patch.object(c.os, 'fdopen', side_effect=open_file):
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
        real_open = os.open
        def denied(name, *args, **kwargs):
            if str(name) == str(path): raise PermissionError('denied')
            return real_open(name, *args, **kwargs)
        with patch.object(c.os, 'open', side_effect=denied):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertEqual(result['skipped'], 1)
        with patch.object(c.os, 'scandir', side_effect=OSError('walk failed')):
            result = self.scan()
        self.assertTrue(result['partial']); self.assertGreater(result['skipped'], 0)

    def test_failed_probe_marks_previous_result_stale(self):
        old = c._probe['usage']; c._probe['usage'] = {'days':{}, 'scanned_at':'2026-01-01T00:00:00Z'}
        self.addCleanup(c._probe.__setitem__, 'usage', old)
        def fail(): raise RuntimeError('failure')
        c._background_probe('usage', fail)
        self.assertTrue(c._probe['usage']['stale'])
        self.assertEqual(c._probe['usage']['scanned_at'], '2026-01-01T00:00:00Z')

    def test_usage_probe_environment_switch(self):
        from unittest.mock import patch
        for value, expected in ((None, True), ('1', True), ('0', False), ('other', True)):
            with self.subTest(value=value):
                env = {'MAINFRAME_AGENTS_SCAN': '0'}
                if value is not None: env['MAINFRAME_USAGE_SCAN'] = value
                probe = {'storage': [], 'storage_at': 100, 'storage_busy': False,
                         'windows': None, 'windows_at': 100, 'windows_busy': False,
                         'usage': None, 'usage_at': 0, 'usage_busy': False}
                with patch.dict(os.environ, env, clear=True), patch.object(c, '_probe', probe), \
                     patch.object(c, '_probe_started', 0), patch.object(c.time, 'monotonic', return_value=100), \
                     patch.object(c.threading, 'Thread') as thread:
                    sample = c.slow_probes({'wsl': False})
                self.assertIsNone(sample['usage'])
                self.assertEqual(thread.called, expected)
                if expected:
                    self.assertEqual(thread.call_args.kwargs['args'], ('usage', c.usage_probe))
                    thread.return_value.start.assert_called_once_with()
                self.assertEqual(probe['usage_busy'], expected)

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
        self.assertIn('dedupe_evicted_at', index)
        with patch.object(c, '_USAGE_SEEN_LIMIT', 2):
            self.assertTrue(self.scan()['partial'])
            later = self.now + datetime.timedelta(days=30)
            self.assertFalse(c.usage_scan(self.home, str(self.cache), now=later)['partial'])

    def test_old_claude_dedupe_entries_migrate(self):
        path = self.file('.claude/projects/a.jsonl')
        self.lines(path, [self.claude('one')]); self.scan()
        index_path = self.cache / 'usage-index.json'
        index = json.loads(index_path.read_text())
        key = next(iter(index['seen']))
        index['seen'][key] = {'day': self.now.date().isoformat(), 'tokens': {'input': 10}}
        index_path.write_text(json.dumps(index))
        self.lines(path, [self.claude('one', {'input_tokens': 12})], 'a')
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 12)
        self.assertIsInstance(json.loads(index_path.read_text())['seen'][key], list)

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
        index = json.loads(index_path.read_text()); index['sessions'][str(path)]['input_tokens'] = -1; index['hours'] = {}
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
        self.assertIn('dedupe_evicted_at', saved)
        self.assertTrue(self.scan()['partial'])

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
        self.assertEqual(sender.filter({'usage': usage, '_usage_generation': 1})['usage'], usage)
        self.assertNotIn('usage', sender.filter({'usage': {'different': True}, '_usage_generation': 1}))
        self.assertEqual(sender.filter({'usage': usage, '_usage_generation': 2})['usage'], usage)
        self.assertIn('usage', c._UsageEmitter().filter({'usage': usage, '_usage_generation': 2}))

    def test_zero_usage_does_not_block_later_counted_message(self):
        empty = self.claude('same', {'input_tokens':0})
        self.lines(self.file('.claude/projects/a.jsonl'), [empty, self.claude('same')])
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'], 10)
