import base64
import gzip
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from newsdesk.bootstrap import make_command, make_service_command, runtime_path
from newsdesk.config import Config
from newsdesk.feeds import item_for
from newsdesk.lan import pair, parse_pairing, request, summarize_remote


def unpack(command):
    encoded = re.search(r"Buffer\.from\('([A-Za-z0-9+/=]+)'", command).group(1)
    return gzip.decompress(base64.b64decode(encoded)).decode('utf8')


class CommandTests(unittest.TestCase):
    def test_one_line_has_complete_runtime_and_only_safe_shell_characters(self):
        command = make_command('192.168.1.20', 18800, "C:/a'&$(calc); test/openclaw.mjs", True)
        self.assertNotIn('\n', command)
        self.assertNotIn('$(calc)', command)
        self.assertTrue(command.startswith('node -e "'))
        self.assertLess(len(command), 30000)
        source = unpack(command)
        options = json.loads(source.split('=', 1)[1].split(';\n', 1)[0])
        self.assertEqual(options['host'], '192.168.1.20')
        self.assertEqual(options['port'], 18800)
        self.assertTrue(options['rotate'])
        self.assertEqual(options['mode'], 'gateway')
        self.assertTrue(options['autostart'])
        self.assertEqual(options['command'], "C:/a'&$(calc); test/openclaw.mjs")
        self.assertTrue(source.endswith(runtime_path().read_text(encoding='utf8')))

    def test_invalid_network_inputs_do_not_make_a_command(self):
        for host in ['0.0.0.0', '8.8.8.8', 'https://192.168.1.2', '192.168.1.2; calc', 'bad']:
            with self.assertRaises(ValueError):
                make_command(host)
        with self.assertRaises(ValueError):
            make_command(port=80)
        with self.assertRaises(ValueError):
            make_command(mode='invalid')
        with self.assertRaises(ValueError):
            make_service_command('delete-everything')


FAKE_CLI = r'''
const fs = require('fs');
const args = process.argv.slice(2);
const stateFile = process.env.FAKE_OPENCLAW_STATE;
if (process.env.FAKE_OPENCLAW_CALLS) fs.appendFileSync(process.env.FAKE_OPENCLAW_CALLS, JSON.stringify(args)+'\n');
function out(value) { console.log(JSON.stringify(value)); }
if (args[0] === '--version') console.log('OpenClaw fixture');
else if (args[0] === 'agent' && args[1] === '--help') {
  console.log(process.env.FAKE_LEGACY ? '--agent --session-id' : '--agent --session-key --session-id');
} else if (args[0] === 'agent') {
  if (args[args.indexOf('--agent')+1] !== 'main' || args.includes('--deliver')) {
    console.error('Error: only main may be used without delivery'); process.exit(4);
  }
  if (args.includes('--local') && !process.env.FAKE_ALLOW_LOCAL) {
    console.error('Error: Gateway owns state directory; --local requires exclusive ownership'); process.exit(5);
  }
  const selector=process.env.FAKE_LEGACY ? '--session-id' : '--session-key';
  if (!args.includes(selector)) { console.error('Error: wrong session selector'); process.exit(6); }
  if (selector === '--session-key' && !args[args.indexOf(selector)+1].startsWith('agent:main:newsdesk-')) process.exit(6);
  if (process.env.FAKE_OPENCLAW_FAIL) {
    out({ok:false,error:{message:'No API key found for provider fixture. token=fixture-secret-token'}});
    console.error('Error: authorization failed. Authorization: Bearer sk-fixture-secret-key');
    process.exit(7);
  }
  const message=args[args.indexOf('--message')+1];
  const marker='资料：\n'.replace('\\n','\n');
  const start=message.indexOf('资料：');
  let text='OK';
  if (start>=0) {
    const items=JSON.parse(message.slice(start+3).trim());
    text=JSON.stringify(items.map(i=>({id:i.id,summary:'中文摘要：'+i.title})));
  }
  out({status:'ok',result:{payloads:[{text}]}});
} else { console.error('Error: creating or changing agents is forbidden in this fixture'); process.exit(9); }
'''


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for host command integration tests')
class BootstrapIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.fake = cls.directory / 'fake openclaw.cjs'
        cls.fake.write_text(FAKE_CLI, encoding='utf8')
        cls.state_file = cls.directory / 'openclaw-config.json'
        cls.original_state = json.dumps({'entries': {'main': {'model': 'existing/model', 'tools': {'allow': ['read']}},
                                                       'newsdesk': {'workspace': 'keep-existing-data'}}})
        cls.state_file.write_text(cls.original_state, encoding='utf8')
        cls.calls_file = cls.directory / 'calls.jsonl'
        cls.env = dict(os.environ, USERPROFILE=str(cls.directory), HOME=str(cls.directory),
                       FAKE_OPENCLAW_STATE=str(cls.state_file), FAKE_OPENCLAW_CALLS=str(cls.calls_file))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.command = make_command('127.0.0.1', cls.port, str(cls.fake), autostart=False)
        javascript = cls.command[len('node -e "'):-1]
        cls.process = subprocess.Popen([shutil.which('node'), '-e', javascript], env=cls.env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8',
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        lines = queue.Queue()
        def reader():
            for line in cls.process.stdout:
                lines.put(line.strip())
        cls.reader = threading.Thread(target=reader, daemon=True)
        cls.reader.start()
        try:
            deadline = time.monotonic() + 20
            cls.code = ''
            messages = []
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=0.2)
                    if line.startswith('ND1-'):
                        cls.code = line
                        break
                    messages.append(line)
                except queue.Empty:
                    if cls.process.poll() is not None:
                        break
            if not cls.code:
                raise AssertionError('Command did not produce pairing code: ' + '\n'.join(messages))
            cls.info = parse_pairing(cls.code)
            # The installer must exit while its detached HTTPS service remains usable.
            if cls.process.wait(timeout=5) != 0:
                raise AssertionError('Installer did not exit successfully')
        except Exception:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            cls.process.stdout.close()
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.manage('stop')
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.reader.join(timeout=2)
        cls.process.stdout.close()
        cls.temp.cleanup()

    @classmethod
    def manage(cls, action):
        command = make_service_command(action)
        result = subprocess.run([shutil.which('node'), '-e', command[len('node -e "'):-1]], env=cls.env,
                                capture_output=True, encoding='utf8', errors='replace', timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

    def test_exact_generated_command_authorizes_then_serves_tls_summary(self):
        self.assertEqual(self.process.poll(), 0, 'The pairing command must already have exited')
        cfg = pair(Config(), self.code)
        item = item_for(cfg.sources[0], 'A & $(ignored) research', 'https://example.com/research')
        result = summarize_remote(cfg, [item])
        self.assertEqual(result[item.id], '中文摘要：A & $(ignored) research')
        self.assertEqual(self.state_file.read_text(encoding='utf8'), self.original_state)
        calls = [json.loads(line) for line in self.calls_file.read_text(encoding='utf8').splitlines()]
        self.assertTrue(all(call[0] in ('--version', 'agent') for call in calls))
        turns = [call for call in calls if '--message' in call]
        self.assertGreaterEqual(len(turns), 2)
        self.assertTrue(all(call[call.index('--agent')+1] == 'main' and '--local' not in call for call in turns))
        sessions = [call[call.index('--session-key')+1] for call in turns]
        self.assertEqual(len(sessions), len(set(sessions)))
        self.assertEqual(cfg.ai_agent, 'main')

    def test_node_service_refuses_invalid_token_and_general_agent_requests(self):
        info = self.info
        with self.assertRaisesRegex(ValueError, '撤销'):
            request(info['url'], info['fingerprint'], 'wrong-token', '/health')
        with self.assertRaisesRegex(ValueError, '404'):
            request(info['url'], info['fingerprint'], info['token'], '/v1/chat/completions', {'prompt':'arbitrary'})
        with self.assertRaisesRegex(ValueError, '400'):
            request(info['url'], info['fingerprint'], info['token'], '/summarize',
                    {'items':[{'id':'a'*24,'title':'bad','abstract':'','tools':['exec']}]})
        with self.assertRaisesRegex(ValueError, '撤销'):
            request(info['url'], info['fingerprint'], info['token'], '/__newsdesk/stop', {})
        self.assertEqual(request(info['url'], info['fingerprint'], info['token'], '/health')['scope'], 'summarize')

    def test_stop_and_start_preserve_pairing_without_reauthorizing_model(self):
        calls_before = self.calls_file.read_text(encoding='utf8')
        self.assertIn('stopped', self.manage('stop'))
        self.assertIn('stopped', self.manage('status'))
        with self.assertRaises(OSError):
            pair(Config(), self.code)
        self.assertIn('running', self.manage('start'))
        self.assertIn('running', self.manage('status'))
        self.assertEqual(pair(Config(), self.code).ai_agent, 'main')
        self.assertEqual(self.calls_file.read_text(encoding='utf8'), calls_before)

    def test_changed_tls_fingerprint_stops_pairing(self):
        with self.assertRaisesRegex(ValueError, '证书'):
            request(self.info['url'], '0'*64, self.info['token'], '/health')

    @unittest.skipUnless(os.name == 'nt', 'PowerShell parsing test')
    def test_same_one_line_is_accepted_by_windows_powershell(self):
        # Re-running the literal command in a fresh terminal must reuse the running service and pairing.
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',self.command],
                                env=self.env, capture_output=True, encoding='utf8', errors='replace', timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.code, result.stdout)


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class BootstrapFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fake = self.directory / 'openclaw.cjs'
        self.fake.write_text(FAKE_CLI, encoding='utf8')
        self.env = dict(os.environ, USERPROFILE=str(self.directory), HOME=str(self.directory))
        self.addCleanup(self.stop_if_installed)

    def stop_if_installed(self):
        service = self.directory / '.newsdesk-node-bridge' / 'service.cjs'
        if service.exists():
            subprocess.run([shutil.which('node'), str(service), '--stop'], env=self.env, capture_output=True,
                           timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def node(self, script, *args, env=None):
        return subprocess.run([shutil.which('node'), '-e', script, str(runtime_path()), *args],
                              env=env or self.env, capture_output=True, encoding='utf8', errors='replace', timeout=15,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def test_failed_model_test_names_stage_exit_reason_and_redacts_credentials(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = make_command('127.0.0.1', port, str(self.fake), autostart=False)
        result = self.node(command[len('node -e "'):-1], env=dict(self.env, FAKE_OPENCLAW_FAIL='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[model connection test] exit 7', result.stderr)
        self.assertIn('No API key found', result.stderr)
        self.assertIn('models status --agent main', result.stderr)
        self.assertNotIn('fixture-secret-token', result.stderr)
        self.assertNotIn('sk-fixture-secret-key', result.stderr)
        self.assertFalse((self.directory / '.newsdesk-node-bridge' / 'service.json').exists())
        self.assertNotIn('ND1-', result.stdout)

    def test_legacy_cli_without_session_key_and_explicit_local_mode(self):
        script = "require(process.argv[1]).authorize([process.execPath,process.argv[2]],'local').catch(e=>{console.error(e.message);process.exitCode=1})"
        result = self.node(script, str(self.fake), env=dict(self.env, FAKE_LEGACY='1', FAKE_ALLOW_LOCAL='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Testing main via local', result.stdout)

    def test_cli_timeout_is_distinguished_from_nonzero_exit(self):
        script = "require(process.argv[1]).cli([process.execPath],['-e','setTimeout(()=>{},5000)'],100,'timeout fixture').catch(e=>{console.error(e.message);process.exitCode=1})"
        result = self.node(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[timeout fixture] timeout after 0.1s', result.stderr)

    def test_redaction_removes_environment_secrets_urls_and_json_tokens(self):
        script = r'''const r=require(process.argv[1]); console.log(r.redact('Error: key '+process.env.TEST_API_KEY+' url https://user:pass@host/path?secret=yes {"access_token":"fixture-json-token"}'));'''
        result = self.node(script, env=dict(self.env, TEST_API_KEY='fixture-env-secret'))
        self.assertEqual(result.returncode, 0, result.stderr)
        for secret in ('fixture-env-secret', 'fixture-json-token', 'user:pass', 'secret=yes'):
            self.assertNotIn(secret, result.stdout)

    def test_unrelated_listener_is_preserved_and_reports_upgrade_step(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            command = make_command('127.0.0.1', sock.getsockname()[1], str(self.fake), autostart=False)
            result = self.node(command[len('node -e "'):-1])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('occupied', result.stderr)
            self.assertIn('Ctrl+C', result.stderr)
            self.assertFalse((self.directory / '.newsdesk-node-bridge' / 'service.json').exists())
            self.assertGreater(sock.getsockname()[1], 0)

    def test_upgrade_keeps_existing_certificate_and_pairing_token(self):
        script = r'''const r=require(process.argv[1]),fs=require('fs'),p=require('path'); const d=p.join(require('os').homedir(),'.newsdesk-node-bridge'); fs.mkdirSync(d); r.certificate(d); fs.writeFileSync(p.join(d,'access-token.txt'),'a'.repeat(43));'''
        result = self.node(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = self.directory / '.newsdesk-node-bridge'
        certificate = (directory / 'certificate.pem').read_bytes()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = make_command('127.0.0.1', port, str(self.fake), autostart=False)
        result = self.node(command[len('node -e "'):-1])
        self.assertEqual(result.returncode, 0, result.stderr)
        code = next(line for line in result.stdout.splitlines() if line.startswith('ND1-'))
        self.assertEqual(parse_pairing(code)['token'], 'a'*43)
        self.assertEqual((directory / 'certificate.pem').read_bytes(), certificate)
        self.assertEqual(pair(Config(), code).ai_agent, 'main')
        # A previous terminal's environment secrets must not be persisted in service.json.
        settings = json.loads((directory / 'service.json').read_text(encoding='utf8'))
        self.assertTrue(set(settings['environment']) <= {'PATH','Path','OPENCLAW_CONFIG_PATH','OPENCLAW_STATE_DIR','OPENCLAW_PROFILE'})

    def test_autostart_formats_escape_paths_and_do_not_require_shell_interpolation(self):
        directory = str(self.directory / "space & dollar$ 'quote'% dir")
        script = "const r=require(process.argv[1]); console.log(JSON.stringify(['win32','linux','darwin'].map(p=>r.autostartSpec(p,process.argv[2],process.execPath,process.argv[2]))))"
        result = self.node(script, directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        windows, linux, mac = json.loads(result.stdout)
        self.assertTrue(windows['content'].startswith('\ufeff'))
        self.assertIn('-WindowStyle Hidden', base64.b64decode(windows['args'][-1]).decode('utf-16le'))
        self.assertIn("''quote''", windows['content'])
        self.assertIn('$$', linux['content'])
        self.assertIn('%%', linux['content'])
        self.assertIn('&amp;', mac['content'])
        self.assertIn('--service', mac['content'])

    def test_rotation_restarts_background_service_and_revokes_only_old_token(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        codes = []
        for rotate in (False, True):
            command = make_command('127.0.0.1', port, str(self.fake), rotate=rotate, autostart=False)
            result = self.node(command[len('node -e "'):-1])
            self.assertEqual(result.returncode, 0, result.stderr)
            codes.append(next(line for line in result.stdout.splitlines() if line.startswith('ND1-')))
        first, second = map(parse_pairing, codes)
        self.assertEqual(first['fingerprint'], second['fingerprint'])
        self.assertNotEqual(first['token'], second['token'])
        with self.assertRaisesRegex(ValueError, '撤销'):
            pair(Config(), codes[0])
        self.assertEqual(pair(Config(), codes[1]).ai_agent, 'main')

    @unittest.skipUnless(os.name == 'nt', 'Windows terminal lifecycle test')
    def test_fresh_install_from_powershell_exits_and_background_survives(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = make_command('127.0.0.1', port, str(self.fake), autostart=False)
        # A file also bounds cleanup if a broken implementation leaks a stdout pipe handle.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                    env=self.env, stdout=output, stderr=subprocess.STDOUT, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            output.seek(0)
            text = output.read().decode('utf8', errors='replace')
        self.assertEqual(result.returncode, 0, text)
        code = next(line for line in text.splitlines() if line.startswith('ND1-'))
        cfg = pair(Config(), code)
        item = item_for(cfg.sources[0], 'After terminal close', 'https://example.com/closed')
        self.assertEqual(summarize_remote(cfg, [item])[item.id], '中文摘要：After terminal close')


if __name__ == '__main__':
    unittest.main()
