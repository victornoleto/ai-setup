import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import config
import monitor
import store

OK = {"plan": "pro", "notes": [], "rows": [
    {"label": "Sessão (5h)", "used": 59.0, "resets_at": "2026-11-17T23:10:00+00:00"},
    {"label": "Semana", "used": 6.0, "resets_at": "2026-11-24T16:00:00+00:00"},
]}


class TestConfig(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(text)
        f.close()
        return f.name

    def test_example_is_valid(self):
        cfg = config.load(Path(monitor.HERE / "config.example.toml"))
        self.assertEqual(sorted(cfg["accounts"]), ["claude", "claude2"])
        self.assertEqual(cfg["interval_seconds"], 300)

    def test_rejects_short_interval(self):
        p = self.write('interval_seconds = 5\n[accounts.c]\ntype = "codex"\n')
        with self.assertRaisesRegex(ValueError, "interval_seconds"):
            config.load(p)

    def test_rejects_unknown_type(self):
        p = self.write('[accounts.k]\ntype = "kiro"\n')
        with self.assertRaisesRegex(ValueError, "desconhecido"):
            config.load(p)

    def test_claude_needs_config_dir(self):
        p = self.write('[accounts.c]\ntype = "claude"\n')
        with self.assertRaisesRegex(ValueError, "config_dir"):
            config.load(p)


class TestStoreAndServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = {"db": Path(cls.tmp.name) / "u.db", "accounts": {"claude": {}, "claude2": {}}}
        fake = lambda accounts: {"claude": OK, "claude2": {"error": "token expirado"}}
        cls.collected = monitor.collect_once(cls.cfg, collect=fake)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), monitor.make_handler(cls.cfg["db"]))
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path, host=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, body

    def test_collect_writes_rows_and_errors(self):
        n, errors = self.collected
        self.assertEqual(n, 3)  # 2 janelas do claude + 1 linha de erro do claude2
        self.assertEqual(errors, {"claude2": "token expirado"})

    def test_meta(self):
        status, body = self.get("/api/meta")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"accounts": ["claude", "claude2"], "windows": ["Semana", "Sessão (5h)"]})

    def test_samples_filters(self):
        _, body = self.get("/api/samples?account=claude&window=Semana")
        rows = json.loads(body)
        self.assertEqual([(r["account"], r["window"], r["used"]) for r in rows], [("claude", "Semana", 6.0)])
        _, body = self.get("/api/samples?from=2000-01-01&to=2000-01-02")
        self.assertEqual(json.loads(body), [])

    def test_bad_date_is_400(self):
        status, _ = self.get("/api/samples?from=ontem")
        self.assertEqual(status, 400)

    def test_rejects_foreign_host_and_post(self):
        self.assertEqual(self.get("/api/meta", host="evil.com")[0], 403)
        self.assertEqual(self.get("/api/meta", method="POST")[0], 405)


if __name__ == "__main__":
    unittest.main()
