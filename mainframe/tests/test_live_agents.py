import importlib.util
import json
import os
import subprocess
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
        env = mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'1', 'MAINFRAME_USAGE_SCAN':'0'})
        env.start()
        self.addCleanup(env.stop)
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
        self.proc(14, 'python3', ['python3', '-m', 'aider'])
        self.proc(15, 'claude', ['claude', '--type=renderer'])
        self.proc(16, 'codex-linux-sandbox', ['codex-linux-sandbox'])
        self.proc(17, 'codex', ['codex', '--version'])
        self.proc(18, 'codex', ['codex', 'mcp-server'])
        self.proc(19, 'claude', ['claude', 'mcp', 'serve'])
        self.proc(23, '2.1.76', ['/usr/local/bin/claude'])
        self.proc(24, 'amp', ['amp'])
        sessions = self.scan()['sessions']
        self.assertEqual([s['pid'] for s in sessions], [10, 13, 14, 23])
        self.assertEqual(sessions[1]['parent_pid'], 10)
        self.assertFalse(sessions[1]['interactive'])
        self.assertEqual(sessions[2]['provider'], 'aider')
    def test_rule_table(self):
        examples = [('claude', ['claude']), ('node', ['node', '/lib/node_modules/@anthropic-ai/claude-code/cli.js']),
                    ('node', ['node', '/lib/node_modules/@google/gemini-cli/index.js']), ('node', ['node', '/lib/node_modules/@qwen-code/qwen-code/cli.js']),
                    ('grok', ['grok']), ('cursor-agent', ['cursor-agent']), ('opencode', ['opencode']),
                    ('aider', ['aider']), ('crush', ['crush'])]
        self.assertEqual([collect._agent_match(*args) for args in examples],
                         ['claude', 'claude', 'gemini', 'qwen', 'grok', 'cursor-agent', 'opencode', 'aider', 'crush'])
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
    def test_claude_helper_modes_are_not_sessions(self):
        for arg in ('--claude-in-chrome-mcp', '--chrome-native-host', 'browser-mcp', '--other-mcp', 'mcp', 'daemon'):
            with self.subTest(arg=arg):
                self.assertIsNone(collect._agent_match('claude', ['claude', arg]))
                self.assertIsNone(collect._agent_match('node', ['node', '/lib/node_modules/@anthropic-ai/claude-code/cli.js', arg]))
        self.assertEqual(collect._agent_match('claude', ['claude', 'hello']), 'claude')
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
        text = '10 1 ttys001 1-01:02:03 123 /usr/bin/claude\n11 10 ?? 02:10 42 /usr/bin/grok\ngarbage\n12 1 ?? 01:00 1 /Applications/A Path/claude\n13 1 ?? 00:20 2 /usr/bin/node\n14 1 ?? 00:10 3 /usr/bin/node\n'
        args = "10 claude ask user's question\n11 grok 'unbalanced\n12 /Applications/A Path/claude prompt\n13 node /Users/u/Agent Tools/node_modules/@google/gemini-cli/dist/index.js\n14 node /Users/u/Agent Tools/cursor-agent/versions/v1/index.js\ngarbage\n"
        with mock.patch.object(collect, '_run_tracked', side_effect=[text, args]):
            rows = collect.agents_probe(home=self.home, platform='darwin')['sessions']
        def expected(pid, provider, interactive, age, rss, parent=None):
            return {'pid':pid, 'provider':provider, 'interactive':interactive, 'dir':None, 'billing':None,
                    'project':None, 'age_s':age, 'rss':rss * 1024, 'parent_pid':parent}
        self.assertEqual(rows, [expected(10, 'claude', True, 90123, 123), expected(11, 'grok', False, 130, 42, 10),
                                expected(12, 'claude', False, 60, 1), expected(13, 'gemini', False, 20, 2),
                                expected(14, 'cursor-agent', False, 10, 3)])
    def test_background_probe_is_single_flight(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def probe():
            calls.append(1); entered.set(); release.wait(2)
            return {'at': 1, 'sessions': [], 'truncated': False, 'supported': True}
        state = {'storage': [], 'storage_busy': True, 'windows': None}
        threads = []
        real_thread = threading.Thread
        def capture_thread(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread
        with mock.patch.object(collect, '_probe', state), mock.patch.object(collect, 'agents_probe', probe), mock.patch.object(collect, 'storage_probe'), mock.patch.object(collect, 'windows_probe'), mock.patch.object(collect.threading, 'Thread', side_effect=capture_thread), mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'1', 'MAINFRAME_USAGE_SCAN':'0'}):
            try:
                collect.slow_probes({})
                self.assertTrue(entered.wait(1))
                collect.slow_probes({})
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                self.assertEqual(len(threads), 1)
                threads[0].join(3)
                self.assertFalse(threads[0].is_alive())
        self.assertTrue(state['agents_live']['supported'])
    def test_interpreter_paths_and_native_parent(self):
        for path in ('/x/codex/node_modules/.bin/vitest', '/x/aider/bench/run.py', '/x/claude/mcp/server.js'):
            self.assertIsNone(collect._agent_match('node', ['node', path]))
        self.assertIsNone(collect._agent_match('python3', ['python3', '/x/aider/bench/run.py']))
        for package, provider in (('@anthropic-ai/claude-code', 'claude'), ('@openai/codex', 'codex'), ('@google/gemini-cli', 'gemini'), ('@qwen-code/qwen-code', 'qwen')):
            self.assertEqual(collect._agent_match('node', ['node', '/x/node_modules/' + package + '/cli.js']), provider)
        self.assertEqual(collect._agent_match('node', ['node', '/x/cursor-agent/versions/v1/index.js']), 'cursor-agent')
        self.assertIsNone(collect._agent_match('amp', ['amp']))
        self.assertEqual(collect._agent_match('python3', ['python3', '-m', 'aider']), 'aider')
        self.assertEqual(collect._agent_match('python3', ['python3', '-u', '-m', 'aider']), 'aider')
        self.proc(50, 'node', ['node', '/x/node_modules/@openai/codex/cli.js'])
        self.proc(51, 'codex', ['codex'], 50)
        self.proc(52, 'codex', ['codex'])
        self.proc(53, 'codex', ['codex'], 52)
        rows = self.scan()['sessions']
        self.assertEqual([row['pid'] for row in rows], [50, 52])

    def test_denied_details_and_other_uid(self):
        self.proc(60, 'claude', ['claude'])
        real_open, real_readlink = open, os.readlink
        def denied_open(path, *args, **kwargs):
            if str(path).endswith('/environ'): raise PermissionError(13, 'denied')
            return real_open(path, *args, **kwargs)
        def denied_link(path, *args, **kwargs):
            if str(path).endswith(('/fd/0', '/cwd')): raise PermissionError(13, 'denied')
            return real_readlink(path, *args, **kwargs)
        with mock.patch('builtins.open', side_effect=denied_open), mock.patch.object(collect.os, 'readlink', side_effect=denied_link):
            row = self.scan()['sessions'][0]
        self.assertEqual((row['dir'], row['billing'], row['interactive'], row['project']), (None, None, None, None))
        with mock.patch.object(collect.os, 'getuid', return_value=os.getuid() + 1):
            row = self.scan()['sessions'][0]
        self.assertEqual((row['dir'], row['billing']), (None, None))

    def test_darwin_empty_and_failure(self):
        for side_effect in (['', ''], ['1 0 ?? 01:00 1 claude', ''], OSError('ps failed'), subprocess.TimeoutExpired('ps', 4), subprocess.CalledProcessError(1, 'ps'), RuntimeError('unexpected')):
            with mock.patch.object(collect, '_run_tracked', side_effect=side_effect):
                result = collect.agents_probe(home=self.home, platform='darwin')
            self.assertFalse(result['supported'])
            self.assertEqual(result['sessions'], [])

    def test_options_interpreters_and_launchers(self):
        gemini = '/x/node_modules/@google/gemini-cli/dist/index.js'
        self.assertEqual(collect._agent_match('node', ['node', '--require', '/tmp/pre.cjs', gemini]), 'gemini')
        self.assertIsNone(collect._agent_match('node', ['node', '--require', gemini, 'other.js']))
        self.assertIsNone(collect._agent_match('python3.12', ['python3.12', '-W', 'aider', '-X', 'aider', '-c', 'aider']))
        self.assertIsNone(collect._agent_match('codex', ['codex', '-c', 'model=x', 'app-server']))
        self.proc(70, 'nodejs', ['nodejs', gemini])
        self.proc(71, 'node', ['node', gemini], 70)
        self.proc(72, 'python3.12', ['python3.12', '-X', 'dev', '-m', 'aider'])
        self.proc(73, 'claude', ['/bin/sh', '/bin/claude'])
        self.proc(74, 'claude', ['claude'], 73)
        self.proc(75, 'sh', ['/bin/sh', '/bin/claude'])
        self.proc(76, 'node', ['node', '/x/node_modules/@anthropic-ai/claude-code/cli.js'], 75)
        self.proc(77, 'claude', ['claude'])
        self.proc(78, 'bash', ['bash'], 77)
        self.proc(79, 'claude', ['claude'], 78)
        rows = self.scan()['sessions']
        self.assertEqual([row['pid'] for row in rows], [70, 72, 73, 75, 77, 79])
        self.assertEqual(rows[-1]['parent_pid'], 77)

    def test_interpreter_selects_only_the_script(self):
        for pid, agent in enumerate(('claude', 'codex'), 90):
            self.proc(pid, 'python3', ['python3', '/some/path/mux-helper.py', 'mcp', '--pool', 'mcp',
                                       '--host', 'remote', '--', '/remote/path/relay-server.py', agent])
        self.proc(92, 'node', ['node', 'script.js', '--agent', 'claude'])
        self.proc(93, 'python3', ['python3', '-m', 'aider'])
        self.assertEqual([(row['pid'], row['provider']) for row in self.scan()['sessions']], [(93, 'aider')])
        gemini = '/x/node_modules/@google/gemini-cli/dist/index.js'
        for option in ('-r', '--require', '--import', '--loader', '--experimental-loader'):
            with self.subTest(option=option):
                self.assertEqual(collect._agent_match('node', ['node', option, '/tmp/pre.cjs', gemini]), 'gemini')
                self.assertIsNone(collect._agent_match('node', ['node', option, gemini, 'script.js']))
        for option in ('-c', '-e', '--eval', '-p', '--print'):
            with self.subTest(option=option):
                self.assertIsNone(collect._agent_match('node', ['node', option, gemini]))
        self.assertIsNone(collect._agent_match('python3', ['python3', '-m', 'other', 'aider']))
        self.assertIsNone(collect._agent_match('python3', ['python3', '-m']))

    def test_undecodable_paths_are_utf8(self):
        self.proc(80, 'claude', ['claude'], env=b'CLAUDE_CONFIG_DIR=/home/example/.claude-\xff\0', cwd=None)
        os.symlink(b'/work/project-\xff', os.fsencode(self.root / '80' / 'cwd'))
        row = self.scan()['sessions'][0]
        self.assertEqual(row['dir'], '~/.claude-\ufffd')
        self.assertEqual(row['project'], 'project-\ufffd')
        json.dumps(row, ensure_ascii=False).encode('utf-8')

    def test_live_emitter_only_emits_new_generation(self):
        emitter = collect._UsageEmitter()
        sample = {'agents_live': {'at':1}, '_agents_live_generation':1}
        self.assertIn('agents_live', emitter.filter(sample))
        self.assertNotIn('agents_live', emitter.filter(sample))
        self.assertIn('agents_live', emitter.filter(dict(sample, _agents_live_generation=2)))

    def test_disabled_and_failure(self):
        with mock.patch.dict(os.environ, {'MAINFRAME_AGENTS_SCAN':'0'}):
            state = {'windows':None, 'storage':[], 'storage_busy':True, 'windows_busy':True}
            with mock.patch.object(collect, '_probe', state), mock.patch.object(collect, 'storage_probe'), mock.patch.object(collect, 'windows_probe'):
                self.assertFalse(collect.agents_probe(str(self.root), self.home)['supported'])
                self.assertNotIn('agents_live', collect._UsageEmitter().filter(collect.slow_probes({})))
        self.assertFalse(collect.agents_probe(str(self.root / 'missing'), self.home, platform='linux')['supported'])
        with mock.patch.object(collect.os, 'scandir', side_effect=PermissionError('unreadable')):
            result = self.scan()
        self.assertFalse(result['supported'])
        self.assertEqual(result['sessions'], [])
        with mock.patch.object(collect, '_agent_linux', side_effect=RuntimeError('unexpected')):
            result = self.scan()
        self.assertFalse(result['supported'])
        self.assertEqual(result['sessions'], [])

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
        for value in ([], None, {'':'work'}, {'relative':'work'}, {'~':'work'}, {'~/.claude':'bad id'}, {str(i):'work' for i in range(33)}):
            with self.assertRaises(ValueError): validate(value)
