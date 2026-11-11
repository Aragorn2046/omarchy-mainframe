import io
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
        self.key = json.dumps(['unit', 'Weekly'], separators=(',', ':'))

    def update(self, percent=40, reset='2027-01-20T00:00:00Z', now=NOW):
        item = {'file':'unit.json', 'raw':''}
        record = {'id':'unit', 'limits':[{'label':'Weekly', 'percent':percent, 'resetsAt':reset, 'extra':'private'}]}
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

    def test_retention_and_key_caps(self):
        sample = lambda t: {'time':t, 'percent':40, 'resetsAt':None}
        data = {json.dumps(['unit', 'Weekly'], separators=(',', ':')): [sample(NOW-9*86400)] + [sample(NOW-5000+i) for i in range(510)]}
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
        with patch('sys.stdout', new_callable=io.StringIO) as output, patch('os.replace', side_effect=OSError('unavailable')):
            runpy.run_path(str(SCRIPT))
        records = json.loads(output.getvalue())
        self.assertEqual(json.loads(records[0]['raw'])['limits'][0]['percent'], 40)

    def test_directory_symlink_is_not_followed(self):
        self.path.unlink()
        self.path.parent.rmdir()
        target = self.root / 'outside'
        target.mkdir()
        self.path.parent.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            self.update()
        self.assertEqual(list(target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
