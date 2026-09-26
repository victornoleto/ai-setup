import asyncio
import time

from orq import intervene

from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue

OPTS = [{"id": "a", "label": "A", "detail": "", "action": "retry", "note": "n-a"},
        {"id": "b", "label": "B", "detail": "", "action": "skip", "note": ""}]


async def until(cond, n=300):
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condição não veio")


def eng(tmp_path):
    return engine(tmp_path, make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                                       intervene="enabled = true"))


async def test_resposta_pelo_answer(tmp_path):
    e = eng(tmp_path)
    ask = intervene.new_ask("01-a", "failed", "exec", "E agora?", "d", OPTS, "a")
    job = asyncio.create_task(intervene.wait(e, ask))
    await until(lambda: (e.s.top("open_ask") or {}).get("id") == ask["id"])
    e.s.send("/answer velho 1")
    e.s.send(f"/answer {ask['id']} 2")
    assert await job == "2"
    acks = [x for x in e.s.events() if x["type"] == "control_ack"]
    assert [a["ok"] for a in acks] == [False, True]
    assert intervene.match_option(ask, "2")["id"] == "b" and intervene.match_option(ask, "a")["id"] == "a"
    assert intervene.match_option(ask, "talvez") is None
    intervene.close(e, ask, action="skip")
    assert e.s.top("open_ask") is None and [x["type"] for x in e.s.events()][-1] == "ask_answer"


async def test_prazo_vencido(tmp_path):
    e = eng(tmp_path)
    ask = intervene.new_ask("01-a", "council", "plan_questions", "Q?", "d", OPTS, "a", deadline=time.time() + 0.2)
    assert await intervene.wait(e, ask) is None


async def test_resposta_pelo_ntfy(tmp_path, monkeypatch):
    e = eng(tmp_path)
    e.notifier = {"server": "https://ntfy.sh", "topic": "t"}
    monkeypatch.setattr(intervene.notify, "publish", lambda *a, **k: True)
    ask = intervene.new_ask("01-a", "failed", "exec", "E agora?", "d", OPTS, "a")
    monkeypatch.setattr(intervene.notify, "poll", lambda cfg, since: ([f"{ask['id']} 1"], "m9"))
    assert await asyncio.wait_for(intervene.wait(e, ask), 5) == "1"
    assert any(x.get("source") == "ntfy" for x in e.s.events() if x["type"] == "control_ack")
    assert ask["since"] == "m9"  # a próxima leitura continua de onde parou


# --- conselho sem unanimidade -----------------------------------------------------------------------------------------
from .test_engine import Q, vote  # noqa: E402

COUNCIL = {"plan": [{"summary": "s", "questions": [Q]}, PLAN], "execute": [EXEC_OK], "review": [APPROVED],
           "voter:vote": [vote("a"), vote("a"), vote("b")]}


async def test_conselho_2_pts_pergunta_e_victor_escolhe(tmp_path):
    e = engine(tmp_path, make_queue(tmp_path, COUNCIL, intervene="enabled = true"))
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    ask = e.s.top("open_ask")
    assert ask["kind"] == "council" and ask["recommended"] == "a" and len(ask["options"]) == 3
    e.s.send(f"/answer {ask['id']} 2")
    assert await job
    decs = [x for x in e.s.events() if x["type"] == "decision"]
    assert (decs[-1]["source"], decs[-1]["choice"]) == ("victor", "b")
    upd = next((e.s.dir / "01-a" / "calls").glob("plan-update-*.prompt.md")).read_text()
    assert "decisão do Victor" in upd


async def test_conselho_sem_resposta_segue_com_a_escolha(tmp_path):
    e = engine(tmp_path, make_queue(tmp_path, COUNCIL, intervene='enabled = true\ndecision_timeout = "1s"'))
    assert await e.run()
    assert [x.get("kind") for x in e.s.events() if x["type"] == "notice"].count("decision_no_victor") == 1
    assert "[DECISÃO SEM VICTOR]" in e.s.journal_path.read_text()
    assert e.s.top("open_ask") is None
    upd = next((e.s.dir / "01-a" / "calls").glob("plan-update-*.prompt.md")).read_text()
    assert "`a`" in upd and "não respondeu" in upd


async def test_conselho_unanime_nao_pergunta(tmp_path):
    script = {**COUNCIL, "voter:vote": [vote("a")]}
    e = engine(tmp_path, make_queue(tmp_path, script, intervene="enabled = true"))
    assert await asyncio.wait_for(e.run(), 10)
    assert "ask" not in [x["type"] for x in e.s.events()]


# --- bloqueio e falha ---------------------------------------------------------------------------------------------------
import pytest  # noqa: E402

ASK_OUT = {"question": "O executor travou. E agora?", "diagnosis": "Faltou a lib X.",
           "options": [{"id": "1", "label": "Tentar de novo usando a lib Y", "detail": "", "action": "retry",
                        "note": "use a lib Y"},
                       {"id": "2", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                       {"id": "3", "label": "Parar a fila", "detail": "", "action": "stop", "note": ""}],
           "recommended": "1"}
BLOCKED = {**EXEC_OK, "_sh": "true", "status": "blocked", "commits": [], "summary": "Sem a lib X."}


async def answer_when_open(e, text):
    await until(lambda: e.s.top("open_ask"))
    e.s.send(f"/answer {e.s.top('open_ask')['id']} {text}")


async def test_bloqueio_retry_com_nota(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED, EXEC_OK], "review": [APPROVED],
                                "ask": [ASK_OUT]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "1")
    assert await job and e.s.get("01-a", "result") == "ok"
    execs = [c for c in e.harness("fake").calls if c.name.startswith("exec-")]
    assert "use a lib Y" in execs[-1].prompt
    assert [x["action"] for x in e.s.events() if x["type"] == "ask_answer"] == ["retry"]


async def test_operador_falhou_usa_opcoes_padrao(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED],
                                "ask": [{"_error": "fatal"}]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    assert [o["action"] for o in e.s.top("open_ask")["options"]] == ["retry", "skip", "stop"]
    await answer_when_open(e, "2")
    assert await job and e.s.get("01-a", "result") == "skipped"


async def test_accept_fecha_como_ok_victor(tmp_path):
    out = {**ASK_OUT, "options": [*ASK_OUT["options"][:2], {"id": "3", "label": "Aceitar", "detail": "",
                                                              "action": "accept", "note": ""}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED], "ask": [out]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "3")
    assert await job and e.s.get("01-a", "result") == "ok_victor"


async def test_resume_com_pergunta_aberta_nao_chama_o_operador(tmp_path):
    from orq.engine import Engine
    from orq.store import RunStore
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED, EXEC_OK], "review": [APPROVED],
                                "ask": [ASK_OUT]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    e2 = Engine(cfg, RunStore(e.s.dir))
    job2 = asyncio.create_task(e2.run())
    await answer_when_open(e2, "1")
    assert await job2 and e2.s.get("01-a", "result") == "ok"
    assert not [c for c in e2.harness("fake").calls if c.name.startswith("intervene-")]


# --- texto livre --------------------------------------------------------------------------------------------------------
def res(**kw):
    return {"sufficient": True, "reply": "ok", "option_id": "", "action": "", "note": "", "follow_up": None, **kw}


async def test_texto_livre_insuficiente_vira_nova_pergunta(tmp_path):
    follow = {"question": "Pular ou parar?", "diagnosis": "d", "recommended": "1",
              "options": [{"id": "1", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                          {"id": "2", "label": "Parar", "detail": "", "action": "stop", "note": ""},
                          {"id": "3", "label": "Tentar", "detail": "", "action": "retry", "note": ""}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED], "ask": [ASK_OUT],
                                "resolve": [res(sufficient=False, reply="Preciso saber mais.", follow_up=follow)]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "sei lá, vê aí")
    await until(lambda: (e.s.top("open_ask") or {}).get("question") == "Pular ou parar?")
    assert e.s.top("open_ask")["reply"] == "Preciso saber mais."
    await answer_when_open(e, "1")
    assert await job and e.s.get("01-a", "result") == "skipped"


async def test_texto_livre_suficiente_vira_acao(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED, EXEC_OK], "review": [APPROVED],
                                "ask": [ASK_OUT], "resolve": [res(action="retry", note="instale a lib X antes")]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "instala a X e tenta de novo")
    assert await job and e.s.get("01-a", "result") == "ok"
    execs = [c for c in e.harness("fake").calls if c.name.startswith("exec-")]
    assert "instale a lib X antes" in execs[-1].prompt


async def test_texto_livre_suficiente_no_conselho(tmp_path):
    cfg = make_queue(tmp_path, {**COUNCIL, "resolve": [res(option_id="c")]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "vai de C, é mais simples")
    assert await job
    assert [x for x in e.s.events() if x["type"] == "decision"][-1]["choice"] == "c"
