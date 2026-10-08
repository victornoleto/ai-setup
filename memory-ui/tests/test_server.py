import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import mcp
import server
import wiki


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_patch = patch.object(server.Handler, "log_message", lambda *a: None)
        cls.log_patch.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.log_patch.stop()

    def get(self, path, host=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Host": host} if host else {}
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        status, headers_out = resp.status, resp.headers
        conn.close()
        return status, headers_out, body

    def test_index(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(b"memory-ui", body)
        self.assertIn(b"marked/12.0.2/marked.min.js", body)
        self.assertIn(b"dompurify/3.1.6/purify.min.js", body)

    def test_projects(self):
        with patch("wiki.list_projects", return_value=[{"name": "hoobot", "pages": 3}]) as call:
            status, headers, body = self.get("/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body), [{"name": "hoobot", "pages": 3}])
        call.assert_called_once_with()

    def test_pages(self):
        with patch("wiki.list_pages", return_value=[{"path": "a.md"}]) as call:
            status, headers, body = self.get("/api/pages?project=hoobot")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{"path": "a.md"}])
        call.assert_called_once_with("hoobot")

    def test_page(self):
        reply = {"path": "decisions/x.md", "title": "X", "body": "...", "frontmatter": {}}
        with patch("mcp.call", return_value=reply) as call:
            status, headers, body = self.get(
                "/api/page?project=hoobot&path=decisions/x.md"
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), reply)
        call.assert_called_once_with(
            "memory_read_page",
            {"workspace": "default", "project": "hoobot", "path": "decisions/x.md"},
        )

    def test_search_global(self):
        reply = {
            "hits": [],
            "global_hits": [
                {
                    "workspace_name": "default",
                    "project_name": "hoobot",
                    "path": "a.md",
                    "title": "A",
                    "snippet": "...",
                    "rank": 1,
                }
            ],
        }
        with patch("mcp.call", return_value=reply) as call:
            status, headers, body = self.get("/api/search?q=sanctum")
        self.assertEqual(status, 200)
        call.assert_called_once_with(
            "memory_query", {"query": "sanctum", "global": True, "limit": 50}
        )
        self.assertEqual(
            json.loads(body),
            [{"project": "hoobot", "path": "a.md", "title": "A", "snippet": "..."}],
        )

    def test_search_project(self):
        reply = {"hits": [{"path": "a.md", "title": "A", "snippet": "...", "rank": 1}]}
        with patch("mcp.call", return_value=reply) as call:
            status, headers, body = self.get("/api/search?q=sanctum&project=hoobot")
        self.assertEqual(status, 200)
        call.assert_called_once_with(
            "memory_query",
            {"query": "sanctum", "workspace": "default", "project": "hoobot", "limit": 50},
        )
        self.assertEqual(
            json.loads(body),
            [{"project": "hoobot", "path": "a.md", "title": "A", "snippet": "..."}],
        )

    def test_handoffs(self):
        reply = {"handoffs": [{"id": "1"}]}
        with patch("mcp.call", return_value=reply) as call:
            status, headers, body = self.get("/api/handoffs?project=hoobot")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), reply)
        call.assert_called_once_with(
            "memory_handoff_list", {"workspace": "default", "project": "hoobot"}
        )

    def test_missing_param(self):
        cases = [
            ("/api/pages", "wiki.list_projects"),
            ("/api/page?project=hoobot", "mcp.call"),
            ("/api/search", "mcp.call"),
        ]
        for path, _ in cases:
            with self.subTest(path=path):
                with patch("mcp.call") as mcp_call, patch(
                    "wiki.list_pages"
                ) as pages_call:
                    status, headers, body = self.get(path)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))
                mcp_call.assert_not_called()
                pages_call.assert_not_called()

    def test_host_rejected(self):
        with patch("wiki.list_projects") as call:
            status, headers, body = self.get(
                "/api/projects", host=f"evil.com:{self.port}"
            )
        self.assertEqual(status, 403)
        self.assertIn("error", json.loads(body))
        call.assert_not_called()

        with patch("wiki.list_projects") as call:
            status, headers, body = self.get("/api/projects", host="evil.com")
        self.assertEqual(status, 403)
        call.assert_not_called()

    def test_host_localhost_accepted(self):
        with patch("wiki.list_projects", return_value=[]):
            status, headers, body = self.get(
                "/api/projects", host=f"localhost:{self.port}"
            )
        self.assertEqual(status, 200)

    def test_method_not_allowed(self):
        status, headers, body = self.get("/api/projects", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET")

    def test_mcp_error(self):
        with patch(
            "mcp.call",
            side_effect=mcp.McpError(
                "ai-memory fora do ar … → docker start ai-memory"
            ),
        ):
            status, headers, body = self.get("/api/page?project=hoobot&path=a.md")
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"], "ai-memory fora do ar … → docker start ai-memory"
        )

    def test_wiki_error(self):
        with patch(
            "wiki.list_projects",
            side_effect=wiki.WikiError("container ai-memory parado → docker start ai-memory"),
        ):
            status, headers, body = self.get("/api/projects")
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"],
            "container ai-memory parado → docker start ai-memory",
        )

    def test_unknown_route(self):
        status, headers, body = self.get("/static/index.html")
        self.assertEqual(status, 404)

        status, headers, body = self.get("/../server.py")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
