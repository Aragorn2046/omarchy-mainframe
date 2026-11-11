import io
import datetime
import fcntl
import json
import os
from pathlib import Path
import runpy
import stat
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'agents_usage.py'
NOW = 1800000000


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.getcwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'state'), 'XDG_CACHE_HOME': str(self.root / 'cache')})
        self.env.start()
        self.addCleanup(self.env.stop)
        with patch('sys.stdout', new_callable=io.StringIO), patch('time.time', return_value=NOW):
            self.module = runpy.run_path(str(SCRIPT))
        self.path = self.root / 'state/mainframe/usage-history.json'
        self.key = json.dumps(['unit.json', 'unit', 'Weekly', 0], separators=(',', ':'))

    def update(self, percent=40, reset='2027-01-20T00:00:00Z', now=NOW, updated=None):
        item = {'file':'unit.json', 'raw':''}
        record = {'id':'unit', 'limits':[{'label':'Weekly', 'percent':percent, 'resetsAt':reset, 'extra':'private'}]}
        if updated is not None:
            record['updatedAt'] = updated
        self.module['_update_usage_history']([(item, record)], now)
        return json.loads(item['raw'])['limits'][0]['history']

    def read(self):
        return json.loads(self.path.read_text())

    def test_append_and_heartbeat_and_minimal_fields(self):
        self.assertEqual(self.update(), [[NOW, 40]])
        self.assertEqual(self.update(now=NOW+599), [[NOW, 40]])
        self.assertEqual(self.update(now=NOW+600), [[NOW, 40], [NOW+600, 40]])
        self.assertEqual(len(self.update(percent=41, now=NOW+601)), 3)
        self.assertEqual(len(self.update(percent=41, reset=None, now=NOW+602)), 4)
        for sample in self.read()[self.key]:
            self.assertEqual(set(sample), {'time', 'percent', 'resetsAt'})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_window_reset_by_time_or_drop(self):
        self.update()
        self.assertEqual(self.update(percent=34, now=NOW+1), [[NOW+1, 34]])
        self.assertEqual(self.update(percent=35, reset='2027-01-20T03:00:00Z', now=NOW+2), [[NOW+2, 35]])
        self.assertEqual(len(self.update(percent=35, reset='2027-01-20T03:30:00Z', now=NOW+3)), 2)

    def test_updated_time_prevents_stale_samples_and_resets(self):
        stamp = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        self.assertEqual(self.update(now=NOW, updated=stamp(NOW-60)), [[NOW-60, 40]])
        self.assertEqual(self.update(percent=30, now=NOW+3600, updated=stamp(NOW-60)), [[NOW-60, 40]])
        self.assertEqual(self.update(percent=30, now=NOW+3601, updated=stamp(NOW-120)), [[NOW-60, 40]])
        self.assertEqual(self.update(now=NOW+3602, updated=stamp(NOW+539)), [[NOW-60, 40]])
        self.assertEqual(self.update(now=NOW+3603, updated=stamp(NOW+540)), [[NOW-60, 40], [NOW+540, 40]])
        self.assertEqual(self.update(percent=41, now=NOW+3604, updated=stamp(NOW+541)), [[NOW-60, 40], [NOW+540, 40], [NOW+541, 41]])

    def test_retention_and_key_caps(self):
        sample = lambda t: {'time':t, 'percent':40, 'resetsAt':None}
        data = {self.key: [sample(NOW-9*86400)] + [sample(NOW-5000+i) for i in range(510)]}
        for i in range(130):
            data[str(i)] = [sample(NOW-20000+i)]
        self.path.write_text(json.dumps(data))
        history = self.update(reset=None)
        saved = self.read()
        self.assertEqual(len(saved), 128)
        self.assertNotIn('0', saved)
        self.assertEqual(len(saved[self.key]), 500)
        self.assertEqual(len(history), 200)
        self.assertTrue(all(s['time'] >= NOW-8*86400 for samples in saved.values() for s in samples))

    def test_corrupt_oversized_and_symlink(self):
        for content in ('{', 'x' * (512*1024+1)):
            self.path.write_text(content)
            self.assertEqual(self.update(), [[NOW, 40]])
        target = self.root / 'outside'
        target.write_text('untouched')
        self.path.unlink()
        self.path.symlink_to(target)
        self.update()
        self.assertEqual(target.read_text(), 'untouched')
        self.assertFalse(self.path.is_symlink())
        self.assertIn(self.key, self.read())

    def test_failure_does_not_break_output(self):
        usage = self.root / 'state/omarchy/agents/usage'
        usage.mkdir(parents=True)
        (usage / 'unit.json').write_text(json.dumps({'id':'unit', 'limits':[{'label':'Weekly','percent':40}]}))
        with patch('sys.stdout', new_callable=io.StringIO) as output, patch('os.replace', side_effect=RuntimeError('unavailable')):
            runpy.run_path(str(SCRIPT))
        records = json.loads(output.getvalue())
        self.assertEqual(json.loads(records[0]['raw'])['limits'][0]['percent'], 40)

    def test_directory_symlink_is_not_followed(self):
        self.path.unlink(missing_ok=True)
        (self.path.parent / 'usage-history.lock').unlink()
        self.path.parent.rmdir()
        target = self.root / 'outside'
        target.mkdir()
        self.path.parent.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            self.update()
        self.assertEqual(list(target.iterdir()), [])

    def test_symlinked_state_ancestor_and_directory_permissions(self):
        state = self.root / 'state'
        link = self.root / 'state-link'
        link.symlink_to(state, target_is_directory=True)
        self.path.parent.chmod(0o777)
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(link)}):
            self.assertEqual(self.update(), [[NOW, 40]])
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_foreign_owned_directory_skips_history(self):
        original = os.fstat
        def foreign(fd):
            info = original(fd)
            if stat.S_ISDIR(info.st_mode):
                fields = list(info)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return info
        with patch('os.fstat', side_effect=foreign):
            with self.assertRaises(PermissionError):
                self.update()
        self.assertFalse(self.path.exists())

    def test_lock_timeout_does_not_change_output_or_file(self):
        self.update()
        before = self.path.read_bytes()
        item = {'file':'unit.json', 'raw':'original'}
        record = {'id':'unit', 'limits':[{'label':'Weekly','percent':45}]}
        with open(self.path.parent / 'usage-history.lock', 'rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.module['_update_usage_history']([(item, record)], NOW+1)
        self.assertEqual(item['raw'], 'original')
        self.assertEqual(self.path.read_bytes(), before)

    def test_history_rejects_nonfinite_and_invalid_samples(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            self.path.write_text('{"bad": [{"time": ' + value + '}]}')
            self.assertEqual(self.update(), [[NOW, 40]])
            self.assertNotIn('bad', self.read())
        self.path.write_text(json.dumps({self.key: [
            {'time':str(NOW-1), 'percent':40, 'resetsAt':None},
            {'time':NOW-1, 'percent':'40', 'resetsAt':None},
            {'time':NOW-1, 'percent':40, 'resetsAt':'123'}]}))
        self.assertEqual(self.update(), [[NOW, 40]])

    def test_history_repairs_oversized_integers(self):
        huge = 10 ** 400
        invalid = [dict(time=huge, percent=40, resetsAt=None),
                   dict(time=NOW-1, percent=huge, resetsAt=None),
                   dict(time=NOW-1, percent=40, resetsAt=huge)]
        self.path.write_text(json.dumps({self.key: invalid}))
        self.assertEqual(self.update(), [[NOW, 40]])
        self.assertEqual(self.read()[self.key], [dict(time=NOW, percent=40, resetsAt=self.module['_history_reset']('2027-01-20T00:00:00Z'))])

    def test_nonfinite_record_preserves_raw_and_does_not_add_history(self):
        for number in (float('nan'), float('inf'), float('-inf')):
            raw = json.dumps({'id':'unit', 'limits':[{'label':'Weekly','percent':40}], 'other':number})
            item = {'file':'unit.json', 'raw':raw}
            self.module['_update_usage_history']([(item, json.loads(raw))], NOW)
            self.assertEqual(item['raw'], raw)
        usage = self.root / 'state/omarchy/agents/usage'
        usage.mkdir(parents=True)
        (usage / 'unit.json').write_text(raw)
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            runpy.run_path(str(SCRIPT))
        self.assertEqual(json.loads(output.getvalue())[0]['raw'], raw)

    def test_source_and_occurrence_separate_series(self):
        records = []
        for filename, percent in [('first.json', 30), ('second.json', 40)]:
            records.append(({'file':filename, 'raw':''}, {'id':'same', 'limits':[{'label':'Weekly','percent':percent}, {'label':'Weekly','percent':percent+1}]}))
        self.module['_update_usage_history'](records, NOW)
        self.assertEqual(len(self.read()), 4)
        self.assertEqual([[x['history'] for x in json.loads(item['raw'])['limits']] for item, _ in records], [[[[NOW,30]], [[NOW,31]]], [[[NOW,40]], [[NOW,41]]]])

    def test_large_history_is_trimmed_under_read_cap_and_read_back(self):
        sample = lambda t: {'time':t, 'percent':40, 'resetsAt':None}
        large = {str(i): [sample(NOW-500+j) for j in range(500)] for i in range(128)}
        self.path.write_text('{}')
        real_loads = json.loads
        def load_large(value, *args, **kwargs):
            return large if value == '{}' and 'parse_constant' in kwargs else real_loads(value, *args, **kwargs)
        with patch('json.loads', side_effect=load_large):
            self.update()
        self.assertLessEqual(self.path.stat().st_size, 512 * 1024)
        saved = self.read()
        self.assertTrue(saved)
        self.update(now=NOW+1)
        self.assertTrue(set(saved).issubset(self.read()))

    def test_unchanged_history_is_not_replaced(self):
        self.update()
        self.path.chmod(0o666)
        with patch('os.replace', side_effect=AssertionError('unexpected rewrite')):
            self.update(now=NOW+1)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)


if __name__ == '__main__':
    unittest.main()
