"""Regressões de retomada e fronteiras do motor, sem serviços externos."""
import asyncio
import json
import os
import signal
import sys

import pytest

from orq import council, notify
from orq.config import Role
from orq.harness.base import CallRequest, run_process
from orq.harness.codex import CodexHarness
from orq.store import RunStore
from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue


def test_resume_cli_preserva_repo_e_configuracao(tmp_path, monkeypatch):
    from orq import cli
    from argparse import Namespace
    cfg = make_queue(tmp_path, {"plan": [PLAN]})
    e = engine(tmp_path, cfg)
    # A fila foi editada depois da criação; resume deve usar o snapshot original.
    (cfg.queue_dir / "orq.toml").write_text('[run]\nrepo = "/outro-repo"\n')
    received = []
    monkeypatch.setattr(cli, "start", lambda store, actual, args: received.append(actual) or 0)
    cli.cmd_resume(Namespace(run_dir=str(e.s.dir), account=None, retry=[], headless=True))
    assert received[0].repo == cfg.repo
    assert received[0].roles["executor"].harness == "fake"


async def test_retomada_recupera_id_da_chamada_interrompida(tmp_path):
    from orq.engine import Engine
    cfg = make_queue(tmp_path, {"plan": [{**PLAN, "_sleep": 30}, PLAN]})
    e = engine(tmp_path, cfg)
    t = e.make_task(e.task_files()[0])
    job = asyncio.create_task(e.call(t, "planner", "plan", "plan", "planeje"))
    while not e.harness("fake").calls:
        await asyncio.sleep(0.001)
    first = e.harness("fake").calls[0].session_id
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    resumed = Engine(cfg, RunStore(e.s.dir))
    await resumed.call(t, "planner", "plan", "plan", "planeje")
    req = resumed.harness("fake").calls[0]
    assert req.session_id == first


def test_lock_impede_duas_execucoes_no_mesmo_repo(tmp_path):
    cfg = make_queue(tmp_path, {})
    a, b = RunStore(tmp_path / "a"), RunStore(tmp_path / "b")
    a.create(cfg.queue_dir, "2")
    b.create(cfg.queue_dir, "2")
    with a.engine_lock(cfg.repo):
        with pytest.raises(RuntimeError, match="rodando"):
            with b.engine_lock(cfg.repo):
                pytest.fail("segundo motor adquiriu lock")
    with b.engine_lock(cfg.repo):
        pass


async def test_opcao_parar_preserva_pergunta_para_resume(tmp_path):
    from orq import intervene
    from orq.control import StopRun
    from orq.engine import Problem
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    t = e.make_task(e.task_files()[0])
    p = Problem("blocked", "impedimento", "exec")
    ask = intervene.fallback_ask(t.id, p)
    intervene.open_(e, ask)
    e.s.send(f"/answer {ask['id']} 3")
    with pytest.raises(StopRun):
        await intervene.failure(e, t, p, ask)
    assert e.s.top("open_ask")["id"] == ask["id"]


async def test_stop_interrompe_espera_por_quota(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [{"_error": "limit"}, PLAN]})
    e = engine(tmp_path, cfg)
    e.control.poll_interval = 0.01
    job = asyncio.create_task(e.run())
    while not any(x.get("kind") == "limit_wait" for x in e.s.events()):
        await asyncio.sleep(0.001)
    e.s.send("/stop")
    try:
        await asyncio.wait_for(job, 0.5)
    except asyncio.TimeoutError:
        pytest.fail("/stop não interrompeu a espera por quota")
    assert len(e.harness("fake").calls) == 1


def test_retry_invalida_resultados_antigos(tmp_path):
    from orq import journal
    from orq.tui import model
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    e.s.event("task_start", {"task": "01-a", "base": "abc", "task_file": "f"})
    e.s.event("task_end", {"task": "01-a", "result": "failed", "reason": "erro antigo", "duration_s": 5})
    e.s.event("run_end", {"result": "falhou", "cost": 0})
    e.s.notice("retry", "Tarefa recomeça", "01-a")
    e.s.event("run_resume")
    events = e.s.events()
    assert "**Fim:**" not in journal.render(events)
    assert "erro antigo" not in journal.render_task(events, "01-a")
    assert "motor terminou" not in model.header(e.s, events, model.task_rows(e.s, events))
    e.s.event("task_start", {"task": "01-a", "base": "def", "task_file": "f"})
    e.s.event("task_end", {"task": "01-a", "result": "ok", "reason": "corrigido", "duration_s": 8})
    e.s.event("run_end", {"result": "todas ok", "cost": 1})
    assert "todas ok" in journal.render(e.s.events())
    assert "corrigido" in journal.render_task(e.s.events(), "01-a")
    assert len([x for x in e.s.events() if x["type"] == "task_end"]) == 2


@pytest.mark.parametrize("command", ["/add trabalho novo", "/note instrução"])
def test_comando_reentregue_nao_duplica_efeito(tmp_path, command):
    from orq.engine import Engine
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    first = e.control.apply(command, "cmd-1")
    again = Engine(cfg, RunStore(e.s.dir)).control.apply(command, "cmd-1")
    assert again == first
    assert len(e.task_files()) == (2 if command.startswith("/add") else 1)
    assert len([x for x in e.s.events() if x["type"] == "note"]) == (1 if command.startswith("/note") else 0)


def test_resposta_confirmada_sobrevive_a_queda(tmp_path):
    from orq.engine import Engine
    from orq import intervene
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    ask = intervene.new_ask("01-a", "blocked", "exec", "q", "d", [], "")
    intervene.open_(e, ask)
    e.s.send(f"/answer {ask['id']} 2")
    e.control.drain()
    resumed = Engine(cfg, RunStore(e.s.dir))
    assert resumed.control.answers[ask["id"]] == "2"


async def test_custo_inclui_tentativas_com_erro(tmp_path):
    from orq.harness.base import CallResult
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    e.retry_delay = 0

    class BillingHarness:
        preset_session_ids = False

        def __init__(self):
            self.results = iter([CallResult(error="transient", cost=0.4), CallResult(output=PLAN, cost=0.6)])

        async def call(self, req, on_line):
            return next(self.results)

    e.harnesses["fake"] = BillingHarness()
    await e.call(None, "planner", "plan", "plan", "p")
    assert e.s.cost() == 1.0


async def test_custo_desconhecido_aparece_no_painel(tmp_path):
    from orq.harness.base import CallResult
    from orq.tui import model
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)

    class UnknownCostHarness:
        preset_session_ids = False

        async def call(self, req, on_line):
            return CallResult(output=PLAN)

    e.harnesses["fake"] = UnknownCostHarness()
    await e.call(None, "planner", "plan", "plan", "p")
    assert "parcial" in model.header(e.s, e.s.events(), [])
    assert "não informado" in " ".join(model.cost_lines(e.s))


def test_notificacao_leva_so_o_titulo_nunca_a_mensagem(tmp_path, monkeypatch):
    e = engine(tmp_path, make_queue(tmp_path, {}))
    e.notifier = {"server": "https://invalid", "topic": "dummy"}
    sent = []
    monkeypatch.setattr(notify, "publish", lambda *args, **kw: sent.append(args) or True)
    e.notify("orq fila · 04-x precisa de você", "arquivo /secret/foo.py")
    assert sent[-1][1] == "orq fila · 04-x precisa de você"
    assert "/secret/foo.py" not in repr(sent)


def test_cache_de_estado_evitar_releituras_e_observar_escrita_externa(tmp_path, monkeypatch):
    from pathlib import Path
    s = RunStore(tmp_path / "run")
    s.create(tmp_path, "2")
    original = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        if path == s.state_path:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    for _ in range(10):
        snapshot = s.state()
        snapshot["account"] = "mutação local"
    assert len(reads) <= 1
    assert s.top("account") == "2"
    RunStore(s.dir).set_top("account", "1")
    assert s.top("account") == "1"


def test_eventos_incompletos_so_aparecem_quando_terminam(tmp_path):
    s = RunStore(tmp_path / "run")
    s.create(tmp_path, "2")
    with s.events_path.open("a") as f:
        f.write('{"type":"note","text":"primeiro"}')
    assert s.events() == []
    with s.events_path.open("a") as f:
        f.write('\n{"type":"note","text":"segundo"}\n')
    assert [x["text"] for x in s.events()] == ["primeiro", "segundo"]
    s.events()[0]["text"] = "mutação"
    assert s.events()[0]["text"] == "primeiro"


def test_queda_apos_criar_tarefa_antes_do_recibo_nao_duplica(tmp_path, monkeypatch):
    from orq.engine import Engine
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    real = e.s.set_top

    class Crash(BaseException):
        pass

    def crash(key, value):
        if key == "command_results":
            raise Crash
        real(key, value)

    monkeypatch.setattr(e.s, "set_top", crash)
    with pytest.raises(Crash):
        e.control.apply("/add nova tarefa", "cmd-crash")
    recovered = Engine(cfg, RunStore(e.s.dir))
    assert recovered.control.apply("/add nova tarefa", "cmd-crash")[0]
    assert len(e.task_files()) == 2


def test_resume_legado_recupera_repo_do_evento(tmp_path):
    from argparse import Namespace
    from orq.cli import load_run_cfg
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    e.s.set_top("config", None)
    (cfg.queue_dir / "orq.toml").write_text('[run]\nrepo="/outro"\n')
    assert load_run_cfg(e.s, Namespace(account=None)).repo == cfg.repo


def test_cli_real_run_resume_retry_com_fila_externa(tmp_path):
    import subprocess
    from orq import journal
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]})
    config_file = cfg.queue_dir / "orq.toml"
    config_file.write_text(config_file.read_text().replace(str(cfg.repo), ""))
    run = tmp_path / "external-run"
    result = subprocess.run([sys.executable, "-m", "orq.cli", "run", str(cfg.queue_dir),
                             "--repo", str(cfg.repo), "--run-dir", str(run), "--headless"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    config_file.write_text('[run]\nrepo="/repo-inexistente"\n')
    result = subprocess.run([sys.executable, "-m", "orq.cli", "resume", str(run),
                             "--retry", "01-a", "--headless"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    s = RunStore(run)
    assert (cfg.repo / "a.txt").read_text() == "a\na\n"
    assert s.get("01-a", "result") == "ok"
    assert len(list(run.glob("01-a.tentativa-*/report.md"))) == 1
    assert len([e for e in journal.current_events(s.events()) if e["type"] == "task_end"]) == 1
    assert "Tentativas anteriores" in s.journal_path.read_text()


async def test_erro_ao_persistir_stream_encerra_processo(tmp_path):
    pids = []

    def broken_event(ev):
        pids.append(ev["pid"])
        raise OSError("disco indisponível")

    child = "import os,time,json; print(json.dumps({'pid':os.getpid()}),flush=True); time.sleep(10)"
    with pytest.raises(OSError, match="disco"):
        await run_process([sys.executable, "-c", child], None, tmp_path, {}, 1, tmp_path / "raw", broken_event)
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


def test_journal_retry_mantem_tabela_contigua(tmp_path):
    from orq import journal
    e = engine(tmp_path, make_queue(tmp_path, {}))
    e.s.event("notice", {"kind": "retry", "task": "01-a", "text": "retry", "archive": "01-a.old"})
    e.s.event("task_start", {"task": "01-a", "base": "abc", "task_file": "f"})
    e.s.event("run_end", {"result": "ok", "cost": 0, "cost_unknown": 1})
    lines = journal.render(e.s.events()).splitlines()
    idx = lines.index("|---|---|---|---|---|---|---|---|")
    assert lines[idx + 1].startswith("| 1 |")


def test_codex_resume_preserva_somente_leitura(tmp_path):
    req = CallRequest(Role("operator", "codex", "test", "low"), "call", "p", {},
                      tmp_path, tmp_path, True, "thread-1", True, 10)
    argv = CodexHarness().argv(req, "schema.json")
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert 'sandbox_mode="read-only"' in argv


def test_conselho_exige_maioria_absoluta():
    assert council.tally([{"option_id": x} for x in "aabcd"], 5) is None


def test_notificacao_nao_publica_texto_do_projeto():
    ask = {"id": "a123", "task": "cliente-secreto", "question": "/private/repo falhou",
           "recommended": "a", "options": [{"id": "a", "label": "senha-123"}]}
    payload = notify.ask_payload({"server": "https://invalid", "topic": "dummy"}, "cliente-secreto", ask)
    encoded = json.dumps(payload)
    assert payload["title"] == "orq cliente-secreto · cliente-secreto precisa de você"  # fila e tarefa: decisão do Victor
    assert all(s not in encoded for s in ("/private/repo", "senha-123"))
    assert payload["actions"][0]["body"] == "a123 1"


def test_inbox_so_avanca_depois_da_confirmacao(tmp_path):
    s = RunStore(tmp_path / "run")
    s.create(tmp_path, "2")
    first = s.send("/note primeira")
    second = s.send("/note segunda")
    assert s.take_inbox() == [first, second]
    assert RunStore(s.dir).take_inbox() == [first, second]
    s.ack_inbox(first)
    assert RunStore(s.dir).take_inbox() == [second]


async def test_cancelamento_encerra_processo_que_ignora_term(tmp_path):
    ready = asyncio.Event()
    pids = []

    def event(ev):
        pids.append(ev["pid"])
        ready.set()

    child = ("import os,signal,time,json; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
             "print(json.dumps({'pid':os.getpid()}),flush=True); time.sleep(30)")
    task = asyncio.create_task(run_process([sys.executable, "-c", child], None, tmp_path, {}, 10,
                                          tmp_path / "raw", event))
    await asyncio.wait_for(ready.wait(), 5)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pids[0], 0)
    finally:
        try:
            os.kill(pids[0], signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_lock_do_motor_tolera_a_checagem_do_painel(tmp_path):
    import fcntl
    import subprocess
    import threading
    import time
    from orq.store import RunStore
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    s = RunStore(tmp_path / "run")
    s.dir.mkdir()
    fh = open(s.dir / "engine.lock", "a")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # o painel no meio do engine_alive()
    threading.Thread(target=lambda: (time.sleep(0.2), fh.close()), daemon=True).start()
    with s.engine_lock(tmp_path / "repo"):
        assert s.engine_alive()


def test_run_sem_arquivo_de_regras_falha_antes_de_criar_o_run_dir(tmp_path):
    from argparse import Namespace
    from orq import cli
    cfg = make_queue(tmp_path, {"plan": [PLAN]})
    toml = cfg.queue_dir / "orq.toml"
    toml.write_text(toml.read_text().replace("[run]\n", '[run]\nrules_file = "nao-existe.md"\n'))
    run = tmp_path / "run-x"
    with pytest.raises(SystemExit):
        cli.cmd_run(Namespace(queue=str(cfg.queue_dir), repo=None, account=None, run_dir=str(run), headless=True))
    assert not run.exists()


def test_motor_que_nao_sobe_nao_abre_o_painel(tmp_path, monkeypatch, capsys):
    import subprocess
    from argparse import Namespace
    from orq import cli
    cfg = make_queue(tmp_path, {"plan": [PLAN]})
    e = engine(tmp_path, cfg)
    (e.s.dir / "engine.out").write_text("Traceback…\norq.config.ConfigError: papel executor: falta model\n")

    class Dead:  # o motor "sobe" e morre antes de pegar o lock
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(subprocess, "Popen", Dead)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None) if hasattr(cli, "time") else None
    monkeypatch.setattr(cli, "attach", lambda store: pytest.fail("abriu o painel sobre motor morto"))
    with pytest.raises(SystemExit):
        cli.start(e.s, cfg, Namespace(headless=False, cmd="run", retry=None, account=None, repo=None))
    assert "falta model" in capsys.readouterr().err


async def test_registro_de_execucoes_e_comandos_sem_run_dir(tmp_path, capsys):
    from argparse import Namespace
    from orq import cli
    from orq.store import registered_runs
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]})
    e = engine(tmp_path, cfg)  # create() registra
    assert [r["run"] for r in registered_runs()] == [str(e.s.dir)]
    RunStore(tmp_path / "decide").create(cfg.queue_dir, "2", register=False)  # orq decide não polui a lista
    old = RunStore(tmp_path / "antiga")
    old.create(cfg.queue_dir, "2")
    assert [r["run"] for r in registered_runs()] == [str(old.dir), str(e.s.dir)]
    assert await e.run()
    assert cli.cmd_runs(Namespace(limit=10)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("parada") and lines[1].endswith(str(old.dir))
    assert lines[2].startswith("terminou") and "1/1" in lines[2] and " fila " in lines[2]
    assert cli.cmd_status(Namespace(run_dir=None)) == 0  # sem run dir: a mais recente (nenhuma viva)
    out = capsys.readouterr()
    assert str(old.dir) in out.err and "motor: parado" in out.out
    (old.dir / "state.json").unlink()  # run dir apagado some da lista
    assert [r["run"] for r in registered_runs()] == [str(e.s.dir)]
    assert cli.main(["send", "/pause"]) == 0
    assert "caixa de entrada" in capsys.readouterr().out
    assert e.s.take_inbox()[-1]["text"] == "/pause"
