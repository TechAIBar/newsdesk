import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import threading
import unittest

from newsdesk.bridge import BridgeServer, ensure_certificate
from newsdesk.config import Config
from newsdesk.feeds import item_for
from newsdesk.lan import pair, pairing_code, parse_pairing, protect_secret, request, reveal_secret, summarize_remote


class LANTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cert, key, cls.fingerprint = ensure_certificate(Path(cls.temp.name))
        cls.token = secrets.token_urlsafe(32)
        cls.received = []
        def summarize(items):
            cls.received.append(items)
            return {item.id: '中文摘要：' + item.title for item in items}
        cls.server = BridgeServer(('127.0.0.1', 0), cls.token, summarize, max_per_hour=60)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'https://127.0.0.1:{cls.server.server_port}'
        cls.code = pairing_code(cls.url, cls.token, cls.fingerprint)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def setUp(self):
        self.received.clear()
        self.server.calls.clear()
        self.server.max_per_hour = 60

    def test_pairing_then_remote_summary_over_real_tls(self):
        cfg = pair(Config(), self.code)
        self.assertTrue(cfg.ai_enabled)
        self.assertEqual(cfg.ai_mode, 'lan')
        self.assertEqual(cfg.ai_command, [])
        self.assertNotIn(self.token, cfg.ai_lan_token)
        cfg.validate()
        item = item_for(cfg.sources[0], 'Test paper', 'https://example.com/p')
        result = summarize_remote(cfg, [item])
        self.assertEqual(result[item.id], '中文摘要：Test paper')
        self.assertEqual(self.received[0][0].url, '')

    def test_wrong_certificate_is_rejected_before_http_request(self):
        with self.assertRaisesRegex(ValueError, '证书'):
            request(self.url, '0'*64, self.token, '/health', timeout=3)
        self.assertEqual(self.received, [])

    def test_wrong_token_cannot_read_health_or_generate(self):
        with self.assertRaisesRegex(ValueError, '撤销'):
            request(self.url, self.fingerprint, 'wrong', '/health', timeout=3)
        self.assertEqual(self.received, [])

    def test_raw_prompt_and_tools_are_not_accepted(self):
        item = {'id':'a'*24,'title':'News','abstract':'','tools':['exec']}
        with self.assertRaisesRegex(ValueError, '400'):
            request(self.url, self.fingerprint, self.token, '/summarize', {'items':[item]}, timeout=3)
        self.assertEqual(self.received, [])
        with self.assertRaisesRegex(ValueError, '404'):
            request(self.url, self.fingerprint, self.token, '/v1/chat/completions', {'prompt':'execute shell'}, timeout=3)

    def test_per_hour_rate_limit(self):
        self.server.max_per_hour = 1
        body = {'items':[{'id':'a'*24,'title':'News','abstract':''}]}
        request(self.url, self.fingerprint, self.token, '/summarize', body, timeout=3)
        with self.assertRaisesRegex(ValueError, '限额'):
            request(self.url, self.fingerprint, self.token, '/summarize', body, timeout=3)
        self.assertEqual(len(self.received), 1)

    def test_pairing_rejects_insecure_endpoint(self):
        code = pairing_code('http://127.0.0.1:1234', self.token, self.fingerprint)
        with self.assertRaises(ValueError):
            parse_pairing(code)

    def test_secret_roundtrip(self):
        protected = protect_secret(self.token)
        self.assertEqual(reveal_secret(protected), self.token)
        if os.name == 'nt':
            self.assertTrue(protected.startswith('dpapi:'))


if __name__ == '__main__':
    unittest.main()
