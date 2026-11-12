"""A web lê o mesmo run dir que o painel: visões em dict (view.py) e o servidor HTTP (server.py)."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from orq.store import RunStore, register_run
from orq.web import server, view

from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue

VALIDA = {**APPROVED, "validation": ["Abra a.txt: deve ter a linha `a`."]}


@pytest.fixture
async def run(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [VALIDA]}, tasks=("01-a", "02-b"))
    e = engine(tmp_path, cfg)
    assert await e.run()
    register_run(e.s.dir, cfg.queue_dir)
    return e.s


@pytest.fixture
def web(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    srv.dist = tmp_path / "dist"
    srv.dist.mkdir()
    (srv.dist / "index.html").write_text("<!doctype html><title>orq</title>")
    (srv.dist / "assets").mkdir()
    (srv.dist / "assets" / "app.js").write_text("console.log(1)")
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(path, host=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_port)
        conn.request(method, path, headers={"Host": host} if host else {})
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, r.headers, body

    get.port = srv.server_port
    yield get
    srv.shutdown()
    srv.server_close()


# --- visões -------------------------------------------------------------------------------------------------------
async def test_lista_de_execucoes(run):
    runs = view.runs()
    assert [r["id"] for r in runs] == [view.run_id(run.dir)]
    assert runs[0]["state"] == "terminou" and (runs[0]["done"], runs[0]["total"]) == (2, 2)


async def test_visao_da_execucao(run):
    v = view.run_view(run)
    assert [t["id"] for t in v["tasks"]] == ["01-a", "02-b"]
    assert v["tasks"][0]["result"] == "ok" and v["tasks"][0]["status"] == "ok"
    assert v["state"] == "terminou" and v["ask"] is None and v["current"] is None
    assert v["n_events"] == len(run.events())
    assert any(e["type"] == "task_end" and e["task"] == "02-b" for e in v["timeline"])
    assert v["roles"]["executor"].startswith("fake:")


async def test_visao_da_tarefa(run):
    t = view.task_view(run, "01-a")
    assert t["text"] == "Tarefa 01-a"
    assert "## Entrega" in t["report_md"]
    assert t["validation"] == ["Abra a.txt: deve ter a linha `a`."]
    assert t["diff"]["add"] == 1 and t["diff"]["files"][0]["path"] == "a.txt"
    assert [s["kind"] for s in t["steps"]][:1] == ["plan"]


async def test_tarefa_inexistente(run):
    assert view.task_view(run, "99-nada") is None
    assert view.task_view(run, "../state") is None


def test_tarefa_em_curso_diz_etapa_harness_e_modelo(tmp_path):
    cfg = make_queue(tmp_path, {}, tasks=("01-a",))
    e = engine(tmp_path, cfg)
    e.s.update_task("01-a", {"phase": "exec", "cycle": 2, "started": 1, "active_since": 1})
    e.s.set_top("active_calls", {"01-a:executor:exec-2": {"sid": "s", "resume": False, "account": "1"}})
    cur = view.run_view(e.s)["current"]
    assert (cur["task"], cur["stage"], cur["role"], cur["harness"]) == ("01-a", "execução", "executor", "fake")
    assert cur["model"] == "script.json" and cur["label"] == "executando c2"
    assert [s for s in view.STAGES] == ["plano", "conselho", "execução", "verificação", "revisão"]


def test_eventos_depois_de_um_ponto(tmp_path):
    cfg = make_queue(tmp_path, {}, tasks=("01-a",))
    e = engine(tmp_path, cfg)
    n = len(e.s.events())
    e.s.notice("no_commits", "sem commit", "01-a")
    novos = view.events_after(e.s, n)
    assert [x["kind"] for x in novos] == ["no_commits"] and novos[0]["i"] == n and novos[0]["attention"] is True


# --- servidor -----------------------------------------------------------------------------------------------------
async def test_api_runs_e_run(run, web):
    status, headers, body = web("/api/runs")
    assert status == 200 and json.loads(body)[0]["id"] == view.run_id(run.dir)
    status, _, body = web(f"/api/runs/{view.run_id(run.dir)}")
    assert status == 200 and len(json.loads(body)["tasks"]) == 2
    status, _, body = web(f"/api/runs/{view.run_id(run.dir)}/tasks/01-a")
    assert status == 200 and json.loads(body)["id"] == "01-a"
    status, _, body = web(f"/api/runs/{view.run_id(run.dir)}/journal")
    assert status == 200 and "## Leia primeiro" in json.loads(body)["markdown"]
    status, _, body = web(f"/api/runs/{view.run_id(run.dir)}/events?after=0")
    assert status == 200 and json.loads(body)[0]["type"] == "run_start"


async def test_api_nao_encontrado(run, web):
    assert web("/api/runs/naoexiste")[0] == 404
    assert web(f"/api/runs/{view.run_id(run.dir)}/tasks/99-nada")[0] == 404
    assert web("/api/outra")[0] == 404


def test_host_de_fora_e_recusado(web):
    assert web("/api/runs", host="evil.example")[0] == 403


def test_serve_a_pagina_e_os_assets(web):
    status, headers, body = web("/")
    assert status == 200 and b"<title>orq</title>" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert web("/run/abc/tarefa/01-a")[2] == body          # rota da página: devolve o index
    status, headers, body = web("/assets/app.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert web("/assets/../../etc/passwd")[0] == 404


def test_so_get(web):
    assert web("/api/runs", method="POST")[0] == 405


async def test_stream_avisa_quando_ha_evento_novo(run, web):
    import urllib.request
    url = f"http://127.0.0.1:{web.port}/api/runs/{view.run_id(run.dir)}/stream?after=0"
    with urllib.request.urlopen(url, timeout=5) as r:
        assert r.headers["Content-Type"].startswith("text/event-stream")
        linha = r.readline().decode()
        assert linha.startswith("data: ") and json.loads(linha[6:])["n"] == len(run.events())


# --- CLI ----------------------------------------------------------------------------------------------------------
def test_ensure_web_reusa_servidor_vivo(web, monkeypatch, tmp_path):
    from orq import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cli.web_state_file().parent.mkdir(parents=True)
    cli.web_state_file().write_text(json.dumps({"port": web.port}))
    spawned = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert cli.ensure_web() == web.port and not spawned


def test_ensure_web_sobe_quando_nao_ha_servidor(monkeypatch, tmp_path):
    from orq import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    spawned = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: spawned.append(a[0]))
    monkeypatch.setattr(cli, "web_alive", lambda port: bool(spawned))
    port = cli.ensure_web()
    assert port == server.DEFAULT_PORT and spawned[0][-3:] == ["web", "--no-open", "--port=%d" % port]
