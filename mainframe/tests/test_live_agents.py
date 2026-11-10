import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

collect = load('collect')
config = load('config_manager')

class LiveProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'uptime').write_text('1000 0')
        self.home = '/home/example'
    def proc(self, pid, comm, argv, ppid=1, env=b'', tty='/dev/pts/1', cwd='/work/project'):
        path = self.root / str(pid); (path / 'fd').mkdir(parents=True)
        fields = ['S', str(ppid)] + ['0'] * 17 + ['100', '0', '10']
        (path / 'stat').write_text(f'{pid} ({comm}) ' + ' '.join(fields))
        (path / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv) + b'\0')
        if env is not None: (path / 'environ').write_bytes(env)
        if tty is not None: (path / 'fd' / '0').symlink_to(tty)
        if cwd is not None: (path / 'cwd').symlink_to(cwd)
    def scan(self):
        with mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'1'}):
            return collect.agents_probe(str(self.root), self.home, 'linux')
    def test_matching_merging_and_ancestry(self):
        self.proc(10, 'node', ['node', '/lib/node_modules/@openai/codex/bin/codex.js'])
        self.proc(11, 'codex', ['codex'], 10)
        self.proc(12, 'bash', ['bash'], 11)
        self.proc(13, 'claude', ['claude'], 12, tty='/dev/null')
        self.proc(14, 'python3', ['python3', '/usr/bin/aider.py'])
        self.proc(15, 'claude', ['claude', '--type=renderer'])
        self.proc(16, 'codex-linux-sandbox', ['codex-linux-sandbox'])
        self.proc(17, 'codex', ['codex', '--version'])
        self.proc(18, 'codex', ['codex', 'mcp-server'])
        self.proc(19, 'claude', ['claude', 'mcp', 'serve'])
        self.proc(23, '2.1.76', ['/usr/local/bin/claude'])
        sessions = self.scan()['sessions']
        self.assertEqual([s['pid'] for s in sessions], [10, 13, 14, 23])
        self.assertEqual(sessions[1]['parent_pid'], 10)
        self.assertFalse(sessions[1]['interactive'])
        self.assertEqual(sessions[2]['provider'], 'aider')
    def test_rule_table(self):
        examples = [('claude', ['claude']), ('node', ['node', '/lib/@anthropic-ai/claude-code/cli.js']),
                    ('node', ['node', '/lib/@google/gemini-cli/index.js']), ('node', ['node', '/lib/@qwen-code/cli.js']),
                    ('grok', ['grok']), ('cursor-agent', ['cursor-agent']), ('opencode', ['opencode']),
                    ('aider', ['aider']), ('crush', ['crush']), ('amp', ['amp'])]
        self.assertEqual([collect._agent_match(*args) for args in examples],
                         ['claude', 'claude', 'gemini', 'qwen', 'grok', 'cursor-agent', 'opencode', 'aider', 'crush', 'amp'])
        self.assertIsNone(collect._agent_match('node', ['node', '/lib/@openai/codex/cli.js', '--help']))
        self.assertIsNone(collect._agent_match('claude', ['/Applications/Claude.app/Contents/MacOS/claude']))
    def test_codex_app_server_is_not_a_session(self):
        daemon = '/opt/codex/app-server-daemon/releases/current/bin/codex'
        self.proc(30, 'codex', [daemon, '--background'], tty='/dev/null')
        self.proc(31, 'codex', ['codex', 'app-server', '--listen', 'unix://'], 30, tty='/dev/null')
        (self.root / '31' / 'exe').symlink_to(daemon)
        self.assertEqual(self.scan()['sessions'], [])
        self.assertIsNone(collect._agent_match('codex', ['codex', '--quiet', 'app-server-daemon']))
        self.assertIsNone(collect._agent_match('codex', ['codex', '--quiet', 'app-server']))
        self.assertIsNone(collect._agent_match('node', ['node', '/lib/@openai/codex/cli.js', 'app-server']))
    def test_codex_remote_exec_and_children_of_server(self):
        self.proc(40, 'codex', ['codex', 'app-server'])
        self.proc(41, 'codex', ['codex', '--remote', 'unix://socket'], 40)
        self.proc(42, 'codex', ['codex', 'exec', 'task'])
        self.proc(43, 'codex', ['codex', 'app-server-daemon'], 42)
        self.proc(44, 'claude', ['claude'], 43)
        rows = self.scan()['sessions']
        self.assertEqual([row['pid'] for row in rows], [41, 42, 44])
        self.assertTrue(rows[0]['interactive'])
        self.assertIsNone(rows[0]['parent_pid'])
        self.assertEqual(rows[2]['parent_pid'], 42)
    def test_environment_and_privacy(self):
        self.proc(20, 'claude', ['claude'], env=b'ANTHROPIC_API_KEY=never-emit-this\0OTHER=also-private\0')
        self.proc(21, 'codex', ['codex'], env=b'CODEX_HOME=/home/example/.codex-work\0')
        self.proc(22, 'claude', ['claude'], env=None, tty=None, cwd=None)
        rows = self.scan()['sessions']
        self.assertEqual((rows[0]['dir'], rows[0]['billing']), ('~/.claude', 'api'))
        self.assertEqual((rows[1]['dir'], rows[1]['billing']), ('~/.codex-work', 'subscription'))
        self.assertEqual((rows[2]['dir'], rows[2]['billing'], rows[2]['interactive'], rows[2]['project']), (None, None, None, None))
        result = json.dumps(rows)
        self.assertNotIn('never-emit-this', result); self.assertNotIn('also-private', result)
    def test_cap(self):
        for pid in range(100, 357): self.proc(pid, 'grok', ['grok'])
        result = self.scan()
        self.assertEqual(len(result['sessions']), 256); self.assertTrue(result['truncated'])
    def test_darwin(self):
        text = '10 1 ttys001 01:02:03 123 /usr/bin/claude claude\n11 10 ?? 02:10 42 /usr/bin/grok grok\n'
        with mock.patch.object(collect, '_run_text', return_value=text):
            rows = collect.agents_probe(platform='darwin')['sessions']
        self.assertEqual(rows[0]['age_s'], 3723); self.assertEqual(rows[0]['rss'], 123 * 1024)
        self.assertFalse(rows[1]['interactive']); self.assertEqual(rows[1]['parent_pid'], 10)
        self.assertIsNone(rows[0]['dir'])
    def test_background_probe_is_single_flight(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def probe():
            calls.append(1); entered.set(); release.wait(2)
            return {'at': 1, 'sessions': [], 'truncated': False, 'supported': True}
        state = {'storage': [], 'storage_busy': True, 'windows': None}
        with mock.patch.object(collect, '_probe', state), mock.patch.object(collect, 'agents_probe', probe), mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'1', 'MAINFRAME_USAGE_SCAN':'0'}):
            try:
                collect.slow_probes({})
                self.assertTrue(entered.wait(1))
                collect.slow_probes({})
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                for thread in threading.enumerate():
                    if thread is not threading.current_thread() and thread.daemon:
                        thread.join(0.1)
        self.assertTrue(state['agents_live']['supported'])
    def test_disabled_and_failure(self):
        with mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'0'}):
            self.assertFalse(collect.agents_probe(str(self.root))['supported'])
            self.assertIsNone(collect.slow_probes({})['agents_live'])
        self.assertFalse(collect.agents_probe(str(self.root / 'missing'), platform='linux')['supported'])

class Config(unittest.TestCase):
    def test_caps(self):
        for value in (0, 999):
            config.validate('hosts', {'hosts':[{'name':'laptop', 'ssh':'laptop', 'agentCap':value}]})
            config.validate('settings', {'localAgentCap':value})
        for value in (-1, 1000, True, 1.5, '2', None):
            with self.assertRaises(ValueError): config.validate('hosts', {'hosts':[{'name':'laptop', 'ssh':'laptop', 'agentCap':value}]})
            with self.assertRaises(ValueError): config.validate('settings', {'localAgentCap':value})
    def test_accounts(self):
        def validate(mapping): config.validate('hosts', {'hosts':[{'name':'laptop', 'ssh':'laptop', 'agentAccounts':mapping}]})
        validate({'~/.claude-work':'work'})
        for value in ([], None, {'':'work'}, {'relative':'work'}, {'~/.claude':'bad id'}, {str(i):'work' for i in range(33)}):
            with self.assertRaises(ValueError): validate(value)
