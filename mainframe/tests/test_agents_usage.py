import json
import itertools
import io
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'agents_usage.py'

class UsageFilesTest(unittest.TestCase):
    def test_depth_limit_precedes_json_parser_and_ignores_string_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = root / 'state/omarchy/agents/usage'
            cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True); cache.mkdir(parents=True)
            deep = '[' * 129 + '0' + ']' * 129
            (usage / 'deep.json').write_text(deep)
            (cache / 'deep-cache.json').write_text(deep)
            normal = json.dumps({'id': 'valid', 'text': '\\"' + '[' * 200 + '}' * 200})
            (usage / 'normal.json').write_text(normal)
            at_limit = '[' * 128 + '0' + ']' * 128
            (usage / 'limit.json').write_text(at_limit)
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            loads = json.loads
            def parse(raw, *args, **kwargs):
                self.assertNotEqual(raw, deep, 'deep record reached the JSON parser')
                return loads(raw, *args, **kwargs)
            with patch.dict(os.environ, env, clear=True), patch('json.loads', side_effect=parse), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            files = {item['file']: item['raw'] for item in json.loads(output.getvalue())}
            self.assertEqual(files['deep.json'], '')
            self.assertEqual(files['deep-cache.json'], '')
            self.assertEqual(files['normal.json'], normal)
            self.assertEqual(files['limit.json'], at_limit)

    def test_nested_and_oversized_records_do_not_stop_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            (usage / 'deep.json').write_text('[' * 100000 + ']' * 100000)
            (usage / 'large.json').write_bytes(b'x' * (256 * 1024 + 1))
            (usage / 'ok.json').write_text('{"id":"valid"}')
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            files = {item['file']: item['raw'] for item in json.loads(result.stdout)}
            self.assertEqual(files['deep.json'], '')
            self.assertEqual(files['large.json'], '')
            self.assertEqual(json.loads(files['ok.json'])['id'], 'valid')

    def test_only_first_64_json_files_are_read_in_each_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in (root / 'state/omarchy/agents/usage', root / 'cache/mainframe/agents'):
                directory.mkdir(parents=True)
                for i in reversed(range(65)):
                    (directory / f'{i:02}.json').write_text('{')
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            records = json.loads(result.stdout)
            self.assertEqual(len(records), 128)
            self.assertNotIn('64.json', [item['file'] for item in records])

    def test_realpath_is_computed_once_per_distinct_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True); cache.mkdir(parents=True)
            for i in range(4):
                for directory in (usage, cache):
                    (directory / f'{i}.json').write_text(json.dumps({'id': str(i), 'provider': 'claude', 'dir': str(root / 'shared'), 'name': str(i)}))
            realpath = os.path.realpath
            calls = []
            def count(path, *args, **kwargs):
                calls.append(path)
                return realpath(path, *args, **kwargs)
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            loads = json.loads
            with patch.dict(os.environ, env, clear=True), patch('os.path.realpath', side_effect=count), \
                 patch('json.loads', wraps=loads) as parse, patch('sys.stdout', new_callable=io.StringIO):
                runpy.run_path(str(SCRIPT), run_name='__main__')
            self.assertEqual(len(calls), len(set(calls)))
            self.assertEqual(parse.call_count, 8)

    def test_unconfigured_records_merge_transitively_in_every_order(self):
        records = [
            {'id': 'a', 'name': 'One', 'provider': 'example', 'updatedAt': '1'},
            {'id': 'b', 'name': 'Two', 'provider': 'example', 'updatedAt': '2'},
            {'id': 'a', 'name': 'Two', 'provider': 'example', 'updatedAt': '3'},
        ]
        runner = '''import os, runpy, sys
real_scandir = os.scandir
class Ordered:
    def __init__(self, path): self.entries = real_scandir(path)
    def __enter__(self): return iter(sorted(self.entries.__enter__(), key=lambda entry: entry.name))
    def __exit__(self, *args): return self.entries.__exit__(*args)
os.scandir = Ordered
runpy.run_path(sys.argv[1], run_name="__main__")
'''
        for order in itertools.permutations(records):
            with self.subTest(order=[(r['id'], r['name']) for r in order]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
                for index, record in enumerate(order):
                    (usage / f'{index}.json').write_text(json.dumps(record))
                env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
                result = subprocess.run(['python3', '-c', runner, str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
                self.assertEqual([json.loads(item['raw']) for item in json.loads(result.stdout)], [records[2]])

    def test_newer_omarchy_records_collapse_with_configured_accounts(self):
        for stale_first in (True, False):
            with self.subTest(stale_first=stale_first), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                usage = root / 'state/omarchy/agents/usage'
                cache = root / 'cache/mainframe/agents'
                usage.mkdir(parents=True)
                cache.mkdir(parents=True)
                alice_dir = root / '.claude'
                bob_dir = root / '.claude-accounts/bob'
                alice_dir.mkdir()
                bob_dir.mkdir(parents=True)
                (alice_dir / 'projects').mkdir()
                (bob_dir / 'projects').symlink_to(alice_dir / 'projects', target_is_directory=True)
                stale = {'id': 'claude', 'name': 'Claude Code', 'updatedAt': '2026-10-29', 'data': 'stale'}
                alice = {'id': 'claude-alice', 'name': 'Omarchy Alice', 'updatedAt': '2026-11-02T12:05:00', 'data': 'newer'}
                first = [stale, alice] if stale_first else [alice, stale]
                for record in first + [
                    {'id': 'claude-bob', 'name': 'Omarchy Bob', 'updatedAt': '2026-11-02T12:05:00'},
                    {'id': 'codex', 'name': 'Omarchy Codex', 'updatedAt': '2026-11-02T12:05:00'},
                ]:
                    (usage / (record['id'] + '.json')).write_text(json.dumps(record))
                configured = [
                    {'id': 'claude-alice', 'name': 'alice@', 'provider': 'claude', 'dir': str(alice_dir), 'configHash': 'alice-hash'},
                    {'id': 'claude-bob', 'name': 'bob@', 'provider': 'claude', 'dir': str(bob_dir), 'configHash': 'bob-hash'},
                    {'id': 'codex', 'name': 'Codex', 'provider': 'codex', 'dir': str(root / '.codex'), 'configHash': 'codex-hash'},
                ]
                for record in configured:
                    record.update(updatedAt='2026-11-02T12:00:00', data='older')
                    (cache / (record['id'] + '.json')).write_text(json.dumps(record))
                env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
                result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
                records = [json.loads(item['raw']) for item in json.loads(result.stdout)]
                self.assertEqual(len(records), 3)
                by_name = {record['name']: record for record in records}
                self.assertEqual(set(by_name), {'alice@', 'bob@', 'Codex'})
                for record in configured:
                    for key in ('id', 'name', 'provider', 'dir', 'configHash'):
                        self.assertEqual(by_name[record['name']][key], record[key])
                self.assertEqual(by_name['alice@']['data'], 'newer')
                self.assertEqual(by_name['bob@']['sharedStatsWith'], 'alice@')
                self.assertTrue(by_name['bob@']['sharedProjectsFolder'])

    def test_configured_anchors_prefer_id_over_other_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True); cache.mkdir(parents=True)
            for ident, name, directory in [('claude-a', 'Personal', '/a'), ('claude-b', 'Work', '/b')]:
                (cache / (ident + '.json')).write_text(json.dumps({'id': ident, 'name': name, 'dir': directory, 'updatedAt': '2020', 'data': ident}))
            (usage / 'new.json').write_text(json.dumps({'id': 'claude-a', 'name': 'Work', 'updatedAt': '2021', 'data': 'new'}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            records = sorted((json.loads(item['raw']) for item in json.loads(result.stdout)), key=lambda r: r['id'])
            self.assertEqual([(r['id'], r['name'], r['dir'], r['data']) for r in records], [('claude-a', 'Personal', '/a', 'new'), ('claude-b', 'Work', '/b', 'claude-b')])

    def test_omarchy_accounts_merge_without_cross_account_directory_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = root / 'state/omarchy/agents/usage'
            cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True); cache.mkdir(parents=True)
            for ident, name in [('claude-alice', 'alice@'), ('claude-bob', 'bob@'), ('claude', 'Claude')]:
                (usage / (ident + '.json')).write_text(json.dumps({'id': ident, 'name': name, 'updatedAt': '2026-01-01'}))
            expected = [
                {'id': 'claude-alice', 'name': 'alice@', 'provider': 'claude', 'dir': str(root / '.claude'), 'updatedAt': '2026-01-01', 'copy': 'mainframe'},
                {'id': 'claude-bob', 'name': 'bob@', 'provider': 'claude', 'dir': str(root / '.claude-accounts/x'), 'updatedAt': '2026-01-01', 'copy': 'mainframe'},
            ]
            for record in expected:
                (cache / (record['id'] + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(sorted((json.loads(item['raw']) for item in json.loads(result.stdout)), key=lambda d: d['id']), expected)

    def test_shared_projects_are_marked_only_for_matching_realpaths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cache = root / 'cache/mainframe/agents'; cache.mkdir(parents=True)
            first = root / 'first'; second = root / 'second'; third = root / 'third'
            for directory in (first, second, third): directory.mkdir()
            (first / 'projects').mkdir(); (second / 'projects').symlink_to(first / 'projects', target_is_directory=True); (third / 'projects').mkdir()
            for ident in ('first', 'second', 'third'):
                (cache / (ident + '.json')).write_text('{}')
            paths = sorted(cache.iterdir())
            for path, (ident, name, directory) in zip(paths, [('first', 'alice@', first), ('second', 'bob@', second), ('third', 'other@', third)]):
                path.write_text(json.dumps({'id': ident, 'name': name, 'provider': 'claude', 'dir': str(directory), 'recentDays': [{'date':'2026-11-01','messageCount':1}, {'date':'2026-11-02','messageCount':1 if ident != 'third' else 2}], 'modelUsage': {'m': {'inputTokens': 1000000}}}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            records = [json.loads(item['raw']) for item in json.loads(result.stdout)]
            self.assertEqual([(r['name'], r.get('sharedStatsWith')) for r in records], [('alice@', None), ('bob@', 'alice@'), ('other@', None)])
            self.assertEqual(['sharedStatsWith' in r for r in records], [False, True, False])
            self.assertTrue(records[1]['sharedProjectsFolder'])

    def test_embedded_nul_in_directory_does_not_abort_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cache = root / 'cache/mainframe/agents'; cache.mkdir(parents=True)
            (cache / 'a.json').write_text(json.dumps({'id':'a', 'provider':'claude', 'dir':'a\u0000b'}))
            (cache / 'b.json').write_text(json.dumps({'id':'b', 'provider':'claude', 'dir':'/valid'}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(sorted(json.loads(item['raw'])['id'] for item in json.loads(result.stdout)), ['a', 'b'])

    def test_malformed_cache_fields_do_not_abort_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = root / 'state/omarchy/agents/usage'
            cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True)
            cache.mkdir(parents=True)
            (usage / 'old.json').write_text(json.dumps({'id':'shared', 'provider':'claude', 'name':'Existing', 'updatedAt':'2026-01-01'}))
            (cache / 'bad-dir.json').write_text(json.dumps({'id':'bad-dir', 'provider':'claude', 'dir':5}))
            (cache / 'bad-time.json').write_text(json.dumps({'id':'shared', 'provider':'claude', 'name':'Existing', 'updatedAt':7}))
            (cache / 'valid.json').write_text(json.dumps({'id':'valid', 'provider':'codex', 'name':'Valid account'}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            records = [json.loads(item['raw']) for item in json.loads(result.stdout)]
            self.assertEqual(next((r['id'], r['name']) for r in records if r.get('id') == 'valid'), ('valid', 'Valid account'))
            self.assertEqual(next(r['updatedAt'] for r in records if r.get('id') == 'shared'), '2026-01-01')

    def test_accounts_with_different_providers_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / 'cache/mainframe/agents'
            cache.mkdir(parents=True)
            (cache / 'claude.json').write_text(json.dumps({'id':'claude', 'name':'Work', 'dir':'/same'}))
            (cache / 'codex.json').write_text(json.dumps({'id':'codex', 'provider':'CODEX', 'name':'Work', 'dir':'/same'}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(sorted(json.loads(item['raw'])['id'] for item in json.loads(result.stdout)), ['claude', 'codex'])

    def test_string_timestamp_wins_over_non_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = root / 'state/omarchy/agents/usage'
            cache = root / 'cache/mainframe/agents'
            usage.mkdir(parents=True)
            cache.mkdir(parents=True)
            (usage / 'old.json').write_text(json.dumps({'id':'account', 'provider':'claude', 'updatedAt':7}))
            (cache / 'new.json').write_text(json.dumps({'id':'account', 'provider':'CLAUDE', 'updatedAt':'2026-01-01'}))
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual([json.loads(item['raw'])['updatedAt'] for item in json.loads(result.stdout)], ['2026-01-01'])

    def test_regular_and_unreadable_files_are_isolated_from_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = root / 'state/omarchy/agents/usage'
            usage.mkdir(parents=True)
            (usage / 'ok.json').write_text('{"name":"Agent"}')
            (usage / 'broken.json').write_text('{')
            secret = root / 'outside'
            secret.write_text('not a usage report')
            (usage / 'link.json').symlink_to(secret)
            (usage / 'ignored.txt').write_text('ignore')
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            files = {item['file']: item['raw'] for item in json.loads(result.stdout)}
            self.assertEqual(files, {'ok.json':'{"name":"Agent"}', 'broken.json':'{', 'link.json':''})

    def test_usage_directory_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / 'state/omarchy/agents'
            parent.mkdir(parents=True)
            target = root / 'outside'
            target.mkdir()
            (target / 'file.json').write_text('{"secret":"do not read"}')
            (parent / 'usage').symlink_to(target, target_is_directory=True)
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [])


class SharedHistoryTest(unittest.TestCase):
    def test_same_folder_is_shared_with_small_different_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cache = root / 'cache/mainframe/agents'; cache.mkdir(parents=True)
            for i in range(2):
                record = {'id':str(i), 'name':'Account ' + str(i), 'provider':'claude',
                          'dir':str(root / 'account'), 'modelUsage':{'m':{'inputTokens':i + 1}}}
                (cache / (str(i) + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            data = [json.loads(item['raw']) for item in json.loads(result.stdout)]
            self.assertEqual(data[1]['sharedStatsWith'], 'Account 0')
            self.assertTrue(data[1]['sharedProjectsFolder'])

    def test_identical_history_without_directories_is_shared_per_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            for i, provider in enumerate(('claude', 'claude', 'codex')):
                record = {'id':'item-' + str(i), 'name':'Account ' + str(i), 'provider':provider,
                          'recentDays':[{'date':'2026-11-01','messageCount':4}, {'date':'2026-11-02','messageCount':1}], 'modelUsage':{'model':{'inputTokens':1000000}}}
                (usage / (str(i) + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            data = [json.loads(x['raw']) for x in json.loads(result.stdout)]
            self.assertEqual(data[1]['sharedStatsWith'], 'Account 0')
            self.assertNotIn('sharedStatsWith', data[2])

    def test_small_or_different_histories_are_not_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            days = [{'date':'2026-11-01','messageCount':1}, {'date':'2026-11-02','messageCount':1}]
            variants = [(days, 999999), (days, 999999), (days[:1], 1000000), (days[:1], 1000000),
                        (days, 1000000), ([days[0], {'date':'2026-11-02','messageCount':2}], 1000000),
                        (days, 1000001)]
            for i, (recent, count) in enumerate(variants):
                record = {'id':str(i), 'name':str(i), 'provider':'codex', 'recentDays':recent, 'modelUsage':{'m':{'inputTokens':count}}}
                if i == 0: record['sharedStatsWith'] = 'stale'
                (usage / (str(i) + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertTrue(all('sharedStatsWith' not in json.loads(item['raw']) for item in json.loads(result.stdout)))

    def test_idle_histories_are_not_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            for i in range(2):
                record = {'id':str(i), 'name':'Account ' + str(i), 'provider':'claude',
                          'recentDays':[{'date':'2026-11-01', 'messageCount':0}], 'modelUsage':{}}
                (usage / (str(i) + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertTrue(all('sharedStatsWith' not in json.loads(item['raw']) for item in json.loads(result.stdout)))

    def test_shared_history_with_only_model_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); usage = root / 'state/omarchy/agents/usage'; usage.mkdir(parents=True)
            for i in range(2):
                record = {'id':str(i), 'name':'Account ' + str(i), 'provider':'codex', 'modelUsage':{'m':{'inputTokens':10}}}
                (usage / (str(i) + '.json')).write_text(json.dumps(record))
            env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            data = [json.loads(item['raw']) for item in json.loads(result.stdout)]
            self.assertNotIn('sharedStatsWith', data[1])

if __name__ == '__main__':
    unittest.main()
