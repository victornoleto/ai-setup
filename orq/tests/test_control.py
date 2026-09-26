import asyncio

import pytest

from orq.control import Control, find_task, new_task_name, parse

from .test_engine import APPROVED, EXEC_OK, PLAN, Q, engine, make_queue, vote

SCRIPT = {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}


def test_parse():
    assert parse("/add revisar textos --after 02") == ("add", {"after": "02"}, "revisar textos")
    assert parse("/note use X --task=3") == ("note", {"task": "3"}, "use X")
    assert parse("texto livre")[0] == ""


def test_nomes_de_tarefa(tmp_path):
    fs = [tmp_path / n for n in ("01-a.md", "02-b.md", "02a-c.md")]
    assert new_task_name(fs, "Revisar os textos do e-mail agora já", None) == "03-revisar-os-textos-do-e.md"
    assert new_task_name(fs, "x", fs[1]) == "02b-x.md"
    assert find_task(fs, "2").name == "02-b.md" and find_task(fs, "02a-c").name == "02a-c.md"


def ctl(tmp_path, script=SCRIPT, tasks=("01-a", "02-b", "03-c")):
    e = engine(tmp_path, make_queue(tmp_path, script, tasks=tasks))
    return e, e.control


def test_add_skip_unskip_note(tmp_path):
    e, c = ctl(tmp_path)
    assert c.apply("/add Nova coisa --after 01") == (True, "tarefa 01a-nova-coisa criada na fila")
    assert (e.cfg.queue_dir / "01a-nova-coisa.md").read_text() == "Nova coisa\n"
    assert c.apply("/skip 02")[0] and e.s.get("02-b", "result") == "skipped"
    assert c.apply("/unskip 02")[0] and e.s.get("02-b", "phase") is None
    e.s.set("03-c", "phase", "plan")
    assert c.apply("/skip 3")[0] is False
    assert c.apply("/note use a lib X --task 03")[0]
    note = [x for x in e.s.events() if x["type"] == "note"][-1]
    assert (note["text"], note["for_task"]) == ("use a lib X", "03-c")
    assert c.apply("/xyz")[0] is False


async def test_skip_e_add_numa_execucao(tmp_path):
    e, c = ctl(tmp_path)
    e.s.send("/skip 02")
    e.s.send("/add Tarefa extra")
    assert await e.run()
    assert e.s.get("02-b", "result") == "skipped"
    assert e.s.get("04-tarefa-extra", "result") == "ok"
    acks = [x for x in e.s.events() if x["type"] == "control_ack"]
    assert len(acks) == 2 and all(a["ok"] for a in acks)


async def test_pause_resume_stop(tmp_path):
    e, c = ctl(tmp_path, tasks=("01-a",))
    c.poll_interval = 0.02
    e.s.send("/pause")
    run = asyncio.create_task(e.run())
    for _ in range(100):
        await asyncio.sleep(0.02)
        if any(x.get("kind") == "paused" for x in e.s.events()):
            break
    assert e.s.get("01-a", "phase") is None  # parou antes de começar
    e.s.send("/stop")
    assert await asyncio.wait_for(run, 5)
    assert any(x.get("kind") == "stopped" for x in e.s.events())
    assert not any(x["type"] == "run_end" for x in e.s.events())


async def test_decisao_trocada(tmp_path):
    script = {**SCRIPT, "plan": [{"summary": "s", "questions": [Q]}, PLAN], "voter:vote": [vote("a")]}
    e, c = ctl(tmp_path, script, tasks=("01-a", "02-b"))
    orig = e.run_task

    async def run_task(f):
        await orig(f)
        if f.stem == "01-a":
            ok, msg = c.apply("/decision nome b")
            assert ok and "02-b" not in msg and "01aa" not in msg

    e.run_task = run_task
    assert await e.run()
    vd = [x for x in e.s.events() if x["type"] == "decision" and x.get("source") == "victor"][0]
    assert (vd["choice"], vd["label"], vd["points"]) == ("b", "B", None)
    assert e.s.get("01a-ajuste-decisao-nome", "result") == "ok"  # tarefa de ajuste criada e rodada
    assert "[DECISÃO DO VICTOR]" in e.s.journal_path.read_text()
    assert c.apply("/decision nada x")[0] is False


async def test_operador_propoe_sem_aplicar(tmp_path):
    op = {"reply": "Pulo a 02.", "commands": ["/skip 02", "não é comando", "/ask loop"]}
    e, c = ctl(tmp_path, {**SCRIPT, "operator": [op]})
    c.poll_interval = 0.01
    e.s.send("/pause")
    run = asyncio.create_task(e.run())
    await asyncio.sleep(0.1)
    e.s.send("/ask pula a segunda")          # responde mesmo pausado
    for _ in range(100):
        await asyncio.sleep(0.02)
        if any(x["type"] == "operator" for x in e.s.events()):
            break
    ev = next(x for x in e.s.events() if x["type"] == "operator")
    assert ev["commands"] == ["/skip 02"] and ev["reply"] == "Pulo a 02."
    assert e.s.get("02-b", "result") is None  # nada aplicado sem confirmação
    call = next(x for x in e.harness("fake").calls if x.role.name == "operator")
    assert call.read_only and "pula a segunda" in call.prompt and "`01-a` pendente" in call.prompt
    e.s.send("/stop")
    await asyncio.wait_for(run, 5)
