import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mcp


class Handler(BaseHTTPRequestHandler):
    reply = None
    last_headers = None
    last_body = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        Handler.last_headers = self.headers
        Handler.last_body = json.loads(body)
        payload = json.dumps(Handler.reply).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class TestMcpCall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_success(self):
        Handler.reply = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps({"path": "a.md", "title": "A"})}
                ]
            },
        }
        result = mcp.call(
            "memory_read_page",
            {"workspace": "default", "project": "hoobot", "path": "a.md"},
            url=self.url,
        )
        self.assertEqual(result, {"path": "a.md", "title": "A"})
        self.assertEqual(Handler.last_body["method"], "tools/call")
        self.assertEqual(Handler.last_body["params"]["name"], "memory_read_page")
        self.assertEqual(
            Handler.last_body["params"]["arguments"],
            {"workspace": "default", "project": "hoobot", "path": "a.md"},
        )

    def test_jsonrpc_error(self):
        Handler.reply = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32602,
                "message": "project 'nao-existe' not found in workspace 'default'",
            },
        }
        with self.assertRaises(mcp.McpError) as ctx:
            mcp.call("memory_read_page", {"project": "nao-existe"}, url=self.url)
        self.assertIn("nao-existe", str(ctx.exception))

    def test_is_error(self):
        Handler.reply = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]},
        }
        with self.assertRaises(mcp.McpError) as ctx:
            mcp.call("memory_read_page", {}, url=self.url)
        self.assertIn("boom", str(ctx.exception))

    def test_accept_header_sent(self):
        Handler.reply = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": json.dumps({"ok": True})}]},
        }
        mcp.call("memory_read_page", {}, url=self.url)
        self.assertEqual(
            Handler.last_headers["Accept"], "application/json, text/event-stream"
        )
        self.assertEqual(Handler.last_headers["Content-Type"], "application/json")

    def test_connection_refused(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with self.assertRaises(mcp.McpError) as ctx:
            mcp.call("memory_read_page", {}, url=f"http://127.0.0.1:{port}/mcp")
        self.assertEqual(
            str(ctx.exception),
            "ai-memory fora do ar em 127.0.0.1:49374 → docker start ai-memory",
        )


if __name__ == "__main__":
    unittest.main()
