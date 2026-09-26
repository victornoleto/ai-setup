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
