"""Servidor HTTP somente leitura da GUI do ai-memory."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import mcp
import wiki

INDEX = Path(__file__).parent / "static" / "index.html"
DEFAULT_PORT = 49380


class _Missing(Exception):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        port = self.server.server_port
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _not_allowed(self) -> None:
        if not self._host_ok():
            self._json(403, {"error": "Host não permitido → abra http://127.0.0.1:" + str(self.server.server_port) + "/"})
            return
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed

    def do_GET(self) -> None:
        if not self._host_ok():
            self._json(403, {"error": "Host não permitido → abra http://127.0.0.1:" + str(self.server.server_port) + "/"})
            return

        parts = urlsplit(self.path)
        path = parts.path
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}

        def required(name: str) -> str:
            value = params.get(name)
            if not value:
                raise _Missing(name)
            return value

        try:
            if path == "/":
                body = INDEX.read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
            elif path == "/api/projects":
                self._json(200, wiki.list_projects())
            elif path == "/api/pages":
                project = required("project")
                self._json(200, wiki.list_pages(project))
            elif path == "/api/page":
                project = required("project")
                page_path = required("path")
                result = mcp.call(
                    "memory_read_page",
                    {"workspace": mcp.WORKSPACE, "project": project, "path": page_path},
                )
                self._json(200, result)
            elif path == "/api/search":
                query = required("q")
                project = params.get("project")
                if project:
                    result = mcp.call(
                        "memory_query",
                        {
                            "query": query,
                            "workspace": mcp.WORKSPACE,
                            "project": project,
                            "limit": 50,
                        },
                    )
                    hits = [
                        {
                            "project": project,
                            "path": h["path"],
                            "title": h["title"],
                            "snippet": h["snippet"],
                        }
                        for h in result.get("hits", [])
                    ]
                else:
                    result = mcp.call(
                        "memory_query", {"query": query, "global": True, "limit": 50}
                    )
                    hits = [
                        {
                            "project": h["project_name"],
                            "path": h["path"],
                            "title": h["title"],
                            "snippet": h["snippet"],
                        }
                        for h in result.get("global_hits", [])
                    ]
                self._json(200, hits)
            elif path == "/api/handoffs":
                project = required("project")
                result = mcp.call(
                    "memory_handoff_list", {"workspace": mcp.WORKSPACE, "project": project}
                )
                self._json(200, result)
            else:
                self._json(404, {"error": f"rota não encontrada: {path}"})
        except _Missing as e:
            self._json(400, {"error": f"parâmetro obrigatório ausente: {e.name}"})
        except (mcp.McpError, wiki.WikiError) as e:
            self._json(502, {"error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
