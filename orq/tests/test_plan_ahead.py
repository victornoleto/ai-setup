"""[plan] ahead: rascunho encadeado dos planos antes da primeira execução, aprovação com prazo, revalidação quando a
tarefa começa, e a edição do dono como restrição."""
import asyncio
import time

from orq import journal
from orq.engine import Engine
from orq.store import RunStore

from .test_engine import APPROVED, EXEC_OK, PLAN, Q, engine, make_queue, types, vote

SCRIPT = {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}
AHEAD = '[plan]\nahead = true\napprove_timeout = "0"\n'
TASKS = ("01-a", "02-b", "03-c")


def calls(e: Engine, tid: str) -> list[str]:
    return [x["call"] for x in e.s.events() if x["type"] == "step" and x["task"] == tid]


async def test_rascunha_todos_os_planos_antes_da_primeira_execucao(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=TASKS, extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    assert await e.run()
    evs = e.s.events()
    first_start = next(i for i, x in enumerate(evs) if x["type"] == "task_start")
    drafts = [x["task"] for x in evs[:first_start] if x["type"] == "plan" and x.get("draft")]
    assert drafts == list(TASKS)
    assert all(e.s.get(t, "result") == "ok" for t in TASKS)
    # cada rascunho recebe os anteriores; a tarefa revalida na mesma sessão em vez de planejar do zero
    p2 = (e.s.dir / "02-b" / "calls" / "plan-draft.prompt.md").read_text()
    assert str(e.s.dir / "01-a" / "plan.md") in p2 and "03-c" not in p2.split("## Seu papel")[1]
    assert calls(e, "02-b")[:2] == ["plan-draft", "plan-revalidate"] and "plan" not in calls(e, "02-b")
    assert e.s.get("02-b", "draft") == "revalidated"
    assert [x.get("revalidated") for x in evs if x["type"] == "plan" and x["task"] == "02-b"] == [None, True]
    assert "ask" not in types(e)  # approve_timeout = 0: sem pergunta


async def test_sem_ahead_nada_muda(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a",))
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert calls(e, "01-a")[0] == "plan" and not e.s.get("01-a", "draft")


async def test_aprovacao_vence_o_prazo_e_a_fila_segue(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a", "02-b"), extra_toml='[plan]\nahead = true\napprove_timeout = "1s"\n')
    e = engine(tmp_path, cfg)
    assert await e.run()
    ask = next(x for x in e.s.events() if x["type"] == "ask")
    assert ask["kind"] == "plans" and ask["recommended"] == "start" and "2 tarefa" in ask["question"]
    assert next(x for x in e.s.events() if x["type"] == "ask_answer")["action"] == "timeout"
    assert e.s.top("open_ask") is None and e.s.get("02-b", "result") == "ok"


async def test_aprovacao_respondida_com_parar_nao_executa(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a",), extra_toml='[plan]\nahead = true\napprove_timeout = "30m"\n')
    e = engine(tmp_path, cfg)
    e.control.poll_interval = 0.05

    async def answer():
        while not e.s.top("open_ask"):
            await asyncio.sleep(0.02)
        e.s.send(f"/answer {e.s.top('open_ask')['id']} 2")

    job = asyncio.create_task(answer())
    assert await e.run()
    await job
    assert "task_start" not in types(e) and any(x.get("kind") == "stopped" for x in e.s.events())
    # orq resume: os planos já foram vistos, a execução começa sem perguntar de novo
    e.s.set_top("control", {"paused": False, "stop": False})  # o que o `orq resume` faz
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert e2.s.get("01-a", "result") == "ok" and types(e2).count("ask") == 1


async def test_duvida_do_rascunho_vai_ao_conselho_antes_da_execucao(tmp_path):
    cfg = make_queue(tmp_path, {**SCRIPT, "plan": [{"summary": "s", "questions": [Q]}, PLAN], "voter:vote": [vote("a")]},
                     tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    assert await e.run()
    evs = e.s.events()
    first_start = next(i for i, x in enumerate(evs) if x["type"] == "task_start")
    assert [x["task"] for x in evs[:first_start] if x["type"] == "decision"] == ["01-a"]
    assert any(c.startswith("plan-update-") for c in calls(e, "01-a"))


async def test_rascunho_que_falha_volta_ao_plano_normal(tmp_path):
    cfg = make_queue(tmp_path, {**SCRIPT, "plan": [{"_error": "fatal"}, PLAN]}, tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert all(e.s.get(t, "result") == "ok" for t in ("01-a", "02-b"))
    assert not e.s.get("02-b", "draft") and "plan" in calls(e, "02-b")
    assert any(x["type"] == "notice" and "rascunho" in x["text"] for x in e.s.events())


async def test_edicao_do_dono_entra_na_revalidacao_como_restricao(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    await e.draft_plans()
    e.s.event("plan_edit", {"task": "02-b", "manual": True})
    e.s.event("plan_edit", {"task": "02-b", "instruction": "use sqlite, não postgres"})
    assert await e.run()
    p = (e.s.dir / "02-b" / "calls" / "plan-revalidate.prompt.md").read_text()
    assert "editou o plano à mão" in p and "use sqlite, não postgres" in p and "`01-a`" in p
    p1 = (e.s.dir / "01-a" / "calls" / "plan-revalidate.prompt.md").read_text()
    assert "sqlite" not in p1


async def test_comando_plan_refaz_o_rascunho(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    await e.draft_plans()
    ok, msg = e.control.apply("/plan 02 troque a ordem dos passos", "c1")
    assert ok and "02-b" in msg
    await asyncio.gather(*e.control.background)
    assert any(x["type"] == "plan_edit" and x["instruction"] == "troque a ordem dos passos" for x in e.s.events())
    redraft = next(c for c in calls(e, "02-b") if c.startswith("plan-redraft-"))
    assert "troque a ordem dos passos" in (e.s.dir / "02-b" / "calls" / f"{redraft}.prompt.md").read_text()
    assert e.control.apply("/plan 09 x", "c2")[0] is False
    assert e.control.apply("/plan 02", "c3")[0] is False
    e.s.update_task("01-a", {"phase": "exec"})
    ok, msg = e.control.apply("/plan 01 x", "c4")
    assert not ok and "já começou" in msg


async def test_comando_plan_sem_rascunho_e_recusado(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a",))
    e = engine(tmp_path, cfg)
    ok, msg = e.control.apply("/plan 01 x", "c1")
    assert not ok and "rascunho" in msg


def test_rascunho_e_revalidacao_contam_como_plano_da_tarefa():
    for name in ("plan-draft", "plan-revalidate", "plan-redraft-101500"):
        kind, _ = journal.call_kind(name)
        assert journal.GROUP[kind] == "plano" and journal.KIND_LABEL[kind].startswith("plano (")


async def test_journal_mostra_o_rascunho_na_tarefa(tmp_path):
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a",), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    assert await e.run()
    report = (e.s.dir / "01-a" / "report.md").read_text()
    assert "### Plano (rascunho)" in report and "### Plano (revalidado)" in report
    assert any("[PLANO · rascunho]" in (journal.event_line(x) or "") for x in e.s.events())


# --- web ----------------------------------------------------------------------------------------------------------
async def test_web_diz_o_estado_do_rascunho(tmp_path):
    from orq.web import view
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    assert view.task_view(e.s, "01-a")["draft"] is None
    await e.draft_plans()
    assert view.task_view(e.s, "02-b")["draft"] == "rascunho"
    e.s.event("control_ack", {"id": "x", "command": "/skip 01", "ok": True, "result": "pulada", "source": "web"})
    assert view.task_view(e.s, "02-b")["draft"] == "desatualizado"
    e.s.set("02-b", "draft", "revalidated")
    assert view.task_view(e.s, "02-b")["draft"] == "revalidado"


async def test_web_edita_o_rascunho_e_registra(tmp_path):
    from orq.web import view
    import pytest
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a", "02-b"), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    with pytest.raises(view.TaskError):
        view.set_plan_text(e.s, "02-b", "x")          # ainda não há rascunho
    await e.draft_plans()
    (e.s.dir / "02-b" / "plan.md").write_text("plano do modelo\n")
    view.set_plan_text(e.s, "02-b", "plano do dono")
    assert (e.s.dir / "02-b" / "plan.md").read_text() == "plano do dono\n"
    assert any(x["type"] == "plan_edit" and x["task"] == "02-b" and x.get("manual") for x in e.s.events())
    e.s.update_task("02-b", {"phase": "exec"})
    with pytest.raises(view.TaskError) as exc:
        view.set_plan_text(e.s, "02-b", "y")
    assert exc.value.status == 409


async def test_web_mostra_a_tarefa_sendo_rascunhada(tmp_path):
    from orq.web import view
    cfg = make_queue(tmp_path, SCRIPT, tasks=("01-a",), extra_toml=AHEAD)
    e = engine(tmp_path, cfg)
    e.s.set_top("plan_ahead", {"phase": "draft", "task": "01-a", "since": time.time()})
    cur = view.run_view(e.s)["current"]
    assert (cur["task"], cur["stage"], cur["label"]) == ("01-a", "plano", "rascunhando o plano")
