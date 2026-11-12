"""Servidor HTTP da interface web do orq. Um para todas as execuções registradas, só em 127.0.0.1.
Lê os run dirs (view.py) e serve a página compilada de orq/web/dist. As ações (POST) viram comando na inbox do
motor, como o `orq send`: só com Origin local e o token que a página recebe ao ser servida."""
from __future__ import annotations

import hmac
import json
import mimetypes
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..config import ORQ_HOME
from ..tui.model import Tail
from . import view

DEFAULT_PORT = 49390
DIST = ORQ_HOME / "web" / "dist"
# Plano, report e stream são texto escrito por modelo: a página sanitiza o markdown, e a CSP impede que uma
# imagem ou um link no texto faça o navegador buscar algo fora desta máquina.
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
RUN_RE = re.compile(r"/api/runs/([0-9a-f]{12})(?:/(.*))?")
# O que a página pode mandar ao motor. /edit não entra: o texto de tarefa pendente tem rota própria.
COMMANDS = ("add", "skip", "unskip", "note", "decision", "plan", "pause", "resume", "stop", "ask", "answer")
MAX_BODY = 64_000
MAX_TEXT = 20_000


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # sem log por requisição: a página consulta o tempo todo
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        port = self.server.server_port
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed

    def do_POST(self) -> None:
        """Um comando daqui dirige agentes sem supervisão. Host barra DNS rebinding; Origin e token barram outra
        aba do navegador (ela não lê a página, então não tem o token); JSON evita formulário simples."""
        port = self.server.server_port
        self.close_connection = True  # resposta de erro pode sair sem ler o corpo
        if not self._host_ok():
            return self._json(403, {"error": f"Host não permitido: abra http://127.0.0.1:{port}/"})
        if self.headers.get("Origin") not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return self._json(403, {"error": "origem não permitida"})
        token = getattr(self.server, "token", "")
        if not token or not hmac.compare_digest(self.headers.get("X-Orq-Token", "").encode(), token.encode()):
            return self._json(403, {"error": "token inválido: recarregue a página"})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"error": "envie application/json"})
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 0 < size <= MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(size))
        except ValueError:
            return self._json(400, {"error": "corpo inválido"})
        try:
            self._action(urlsplit(self.path).path, body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._json(500, {"error": f"erro interno ({type(exc).__name__}): {exc}"})

    def _action(self, path: str, body) -> None:
        m = RUN_RE.fullmatch(path)
        store = view.find_run(m.group(1)) if m else None
        if not store:
            return self._json(404, {"error": "execução não encontrada: confira `orq runs`"})
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return self._json(400, {"error": "falta o campo text"})
        rest, text = m.group(2) or "", body["text"]
        if len(text) > MAX_TEXT:
            return self._json(400, {"error": f"texto longo demais (máximo {MAX_TEXT} caracteres)"})
        if rest == "send":
            cmd = re.match(r"/(\w+)", text.strip())
            if not cmd or cmd.group(1).lower() not in COMMANDS:
                return self._json(400, {"error": "comando não aceito pela web: " + ", ".join("/" + c for c in COMMANDS)})
            op = body.get("op")
            if op is not None and not (isinstance(op, str) and re.fullmatch(r"[0-9a-f]{1,32}", op)):
                return self._json(400, {"error": "proposta inválida"})
            sent = store.send(text.strip(), source=f"web:op:{op}" if op else "web")
            return self._json(200, {"id": sent["id"], "alive": store.engine_alive()})
        mt = re.fullmatch(r"tasks/([^/]+)/(text|plan)", rest)
        if mt:
            try:
                (view.set_task_text if mt.group(2) == "text" else view.set_plan_text)(store, mt.group(1), text)
            except view.TaskError as exc:
                return self._json(exc.status, {"error": str(exc)})
            return self._json(200, {"ok": True})
        self._json(404, {"error": f"rota não encontrada: {path}"})

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": f"Host não permitido: abra http://127.0.0.1:{self.server.server_port}/"})
        parts = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        try:
            if parts.path.startswith("/api/"):
                self._api(parts.path, params)
            else:
                self._static(parts.path)
        except (BrokenPipeError, ConnectionResetError):
            pass  # a aba fechou
        except Exception as exc:
            self._json(500, {"error": f"erro interno ({type(exc).__name__}): {exc}"})

    # --- API --------------------------------------------------------------------------------------------------
    def _api(self, path: str, params: dict) -> None:
        if path == "/api/ping":
            return self._json(200, {"orq": True})
        if path == "/api/runs":
            return self._json(200, view.runs())
        m = RUN_RE.fullmatch(path)
        store = view.find_run(m.group(1)) if m else None
        if not store:
            return self._json(404, {"error": "execução não encontrada: confira `orq runs`"})
        rest = m.group(2) or ""
        if rest == "":
            return self._json(200, view.run_view(store))
        if rest == "journal":
            md = store.journal_path.read_text(errors="replace") if store.journal_path.exists() else ""
            return self._json(200, {"markdown": md})
        if rest == "events":
            return self._json(200, view.events_after(store, int(params.get("after", 0))))
        if rest == "stream":
            return self._stream(store, params.get("task", ""))
        if rest.startswith("tasks/"):
            task = view.task_view(store, rest[len("tasks/"):])
            return self._json(200, task) if task else self._json(404, {"error": "tarefa não encontrada nesta fila"})
        self._json(404, {"error": f"rota não encontrada: {path}"})

    def _stream(self, store, task: str) -> None:
        """SSE: um aviso quando há evento novo ou o estado muda (a página busca o resto) e, com `task`, as linhas
        novas do activity.log dela. Um comentário a cada 15 s mantém a conexão viva."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        tail = Tail(store.dir / task / "activity.log") if view.TASK_ID_RE.fullmatch(task) else None
        if tail:
            tail.read()  # só o que chegar depois de abrir: o histórico vem do report
        last, beat = None, time.monotonic()

        def emit(obj: dict) -> None:
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        while True:
            stat = store.state_path.stat()
            stamp = (len(store.events()), stat.st_mtime_ns, store.engine_alive())
            if stamp != last:
                last = stamp
                emit({"n": stamp[0], "alive": stamp[2]})
            lines = tail.read() if tail else []
            if lines:
                emit({"activity": [ln.split("\t", 2)[-1] for ln in lines]})
            if time.monotonic() - beat > 15:
                beat = time.monotonic()
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
            time.sleep(1)

    # --- página -----------------------------------------------------------------------------------------------
    def _static(self, path: str) -> None:
        dist = getattr(self.server, "dist", DIST)
        if path.startswith("/assets/"):
            f = (dist / path.lstrip("/")).resolve()
            if dist.resolve() not in f.parents or not f.is_file():
                return self._json(404, {"error": "arquivo não encontrado"})
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        index = dist / "index.html"  # qualquer outra rota é da página (a navegação é dela)
        if not index.is_file():
            return self._send(503, "orq web: falta orq/web/dist (rode `npm run build` em orq/web)".encode(),
                              "text/plain; charset=utf-8")
        meta = f'<meta name="orq-token" content="{getattr(self.server, "token", "")}">'.encode()
        html = index.read_bytes()
        html = html.replace(b"<head>", b"<head>" + meta, 1) if b"<head>" in html else meta + html
        self._send(200, html, "text/html; charset=utf-8")


def serve(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.token = secrets.token_urlsafe(32)  # vale enquanto o servidor vive; a página recarregada recebe o novo
    srv.daemon_threads = True  # conexões SSE abertas não seguram o encerramento
    return srv
