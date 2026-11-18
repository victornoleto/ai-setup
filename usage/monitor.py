"""ai-usage-monitor: coleta o uso dos harness num intervalo, grava em SQLite e serve o histórico.

Uso: ai-usage-monitor [--config PATH] collect | run | serve | install
  collect  uma coleta agora
  run      coleta a cada interval_seconds e serve a página (o que o serviço systemd roda)
  serve    só a página
  install  cria o config (se faltar) e liga o serviço systemd de usuário
"""
import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import collectors
import config
import store

HERE = Path(__file__).parent
INDEX = HERE / "static" / "index.html"
UNIT = "ai-usage-monitor.service"
CSP = ("default-src 'none'; script-src 'unsafe-inline' https://cdnjs.cloudflare.com; "
       "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")


def collect_once(cfg, collect=collectors.collect):
    results = collect(cfg["accounts"])
    db = store.connect(cfg["db"])
    try:
        n = store.insert_snapshot(db, int(time.time()), results)
    finally:
        db.close()
    errors = {k: v["error"] for k, v in results.items() if "error" in v}
    for name, err in errors.items():
        print(f"ERRO {name}: {err}", file=sys.stderr, flush=True)
    return n, errors


def collect_loop(cfg):
    while True:
        try:
            collect_once(cfg)
        except Exception as e:  # uma coleta quebrada não derruba o serviço nem a página
            print(f"ERRO na coleta: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(cfg["interval_seconds"])


def make_handler(db_path, interval=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _host_ok(self):  # defesa contra DNS rebinding
            port = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _not_allowed(self):
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed

        def do_GET(self):
            if not self._host_ok():
                self._json(403, {"error": f"Host não permitido → abra http://127.0.0.1:{self.server.server_port}/"})
                return
            parts = urlsplit(self.path)
            q = parse_qs(parts.query)
            try:
                if parts.path == "/":
                    self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
                    return
                db = store.connect(db_path)
                try:
                    if parts.path == "/api/meta":
                        self._json(200, store.meta(db) | ({"interval_seconds": interval} if interval else {}))
                    elif parts.path == "/api/samples":
                        one = lambda k: (q.get(k) or [None])[0] or None
                        self._json(200, store.query(db, q.get("account", []), one("window"), one("from"), one("to")))
                    else:
                        self._json(404, {"error": f"rota não encontrada: {parts.path}"})
                finally:
                    db.close()
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"erro interno ({type(e).__name__}): {e}"})

    return Handler


def serve(cfg):
    server = ThreadingHTTPServer(("127.0.0.1", cfg["port"]), make_handler(cfg["db"], cfg["interval_seconds"]))
    print(f"ai-usage-monitor em http://127.0.0.1:{cfg['port']}/", flush=True)
    server.serve_forever()


def install(config_path):
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE / "config.example.toml", config_path)
        print(f"config criado: {config_path} (edite as contas e o intervalo)")
    config.load(config_path)  # falha aqui, não no serviço, se o config estiver errado
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    text = (HERE / UNIT).read_text().replace("@CONFIG@", str(config_path))
    (unit_dir / UNIT).write_text(text)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT], check=True)
    subprocess.run(["systemctl", "--user", "restart", UNIT], check=True)
    print(f"serviço ligado: systemctl --user status {UNIT}")


def main():
    p = argparse.ArgumentParser(prog="ai-usage-monitor", description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=config.DEFAULT_PATH)
    p.add_argument("command", choices=["collect", "run", "serve", "install"])
    args = p.parse_args()
    if args.command == "install":
        install(args.config)
        return 0
    cfg = config.load(args.config)
    if args.command == "collect":
        n, errors = collect_once(cfg)
        print(f"{n} linhas gravadas em {cfg['db']}")
        return 1 if errors else 0
    if args.command == "run":
        threading.Thread(target=collect_loop, args=(cfg,), daemon=True).start()
    serve(cfg)


if __name__ == "__main__":
    sys.exit(main())
