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
        self.day = self.now.date().isoformat()
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
        self.assertEqual(self.scan()['days'][self.day]['claude/model-a']['input'],10)
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
