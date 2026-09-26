"""Intervenção do Victor: a fila pausa, avisa (painel e ntfy) e espera a resposta a uma pergunta com opções. A
pergunta aberta mora em state.json (open_ask): sobrevive a um `orq resume`."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from . import council as council_mod, notify
from .council import points_label
from .control import StopRun

if TYPE_CHECKING:
    from .engine import Engine, Task

POLL_S = 15
ACTIONS = ("retry", "replan", "accept", "skip", "stop")


def new_ask(task: str, kind: str, phase: str, question: str, diagnosis: str, options: list[dict],
            recommended: str, deadline: float | None = None) -> dict:
    return {"id": f"{time.time_ns():x}"[-8:], "task": task, "kind": kind, "phase": phase, "question": question,
            "diagnosis": diagnosis, "options": options, "recommended": recommended, "deadline": deadline,
            "rounds": 0, "opened": time.time(), "reply": ""}


def match_option(ask: dict, text: str) -> dict | None:
    t = text.strip()
    if t.isdigit() and 1 <= int(t) <= len(ask["options"]):
        return ask["options"][int(t) - 1]
    return next((o for o in ask["options"] if o["id"] == t), None)


def open_(eng: "Engine", ask: dict) -> None:
    """Grava a pergunta, registra o evento e avisa. Reabrir a mesma (resume) não repete o aviso."""
    if (eng.s.top("open_ask") or {}).get("id") == ask["id"]:
        return
    eng.s.set_top("open_ask", ask)
    eng.s.event("ask", {k: ask[k] for k in ("id", "task", "kind", "question", "diagnosis", "options", "recommended")})
    if eng.notifier:
        p = notify.ask_payload(eng.notifier, eng.queue_name(), ask)
        eng.notify(p["title"], p["message"], p["priority"], p["actions"])
    else:
        notify.desktop(f"{ask['task']} precisa de você: {ask['question']}")


async def wait(eng: "Engine", ask: dict) -> str | None:
    """Espera a resposta (painel, `orq send` ou ntfy). → o texto, ou None se o prazo venceu."""
    open_(eng, ask)
    ctl = eng.control
    since, next_poll, last_remind = str(int(ask["opened"])), 0.0, time.time()
    while True:
        ctl.drain()
        if ctl.stop:
            raise StopRun
        if ask["id"] in ctl.answers:
            return ctl.answers.pop(ask["id"])
        now = time.time()
        if ask.get("deadline") and now >= ask["deadline"]:
            return None
        if eng.notifier and now >= next_poll:
            msgs, since = await asyncio.to_thread(notify.poll, eng.notifier, since)
            for m in msgs:
                eng.s.send(f"/answer {m}", source="ntfy")
            next_poll = now + POLL_S
            continue  # a resposta do ntfy entra já no próximo drain
        if not ask.get("deadline") and now - last_remind >= eng.cfg.intervene_seconds("reminder"):
            eng.notify(f"orq · lembrete: {ask['task']} ainda precisa de você", notify.clip(ask["question"], 200), 4)
            last_remind = now
        ctl.resumed.clear()
        try:
            await asyncio.wait_for(ctl.resumed.wait(), ctl.poll_interval)
        except asyncio.TimeoutError:
            pass


def close(eng: "Engine", ask: dict, **answer) -> None:
    eng.s.set_top("open_ask", None)
    eng.s.event("ask_answer", {"id": ask["id"], "task": ask["task"], "kind": ask["kind"],
                               "question": ask["question"], **answer})


async def council(eng: "Engine", t: "Task", dec: dict, ask: dict | None = None) -> str:
    """Decisão com 2 ou 2,5 pts: pergunta ao Victor; sem resposta no prazo, fica a do conselho. → linha do prompt."""
    votes = ", ".join(v["option_id"] for v in dec.get("votes") or [])
    ask = ask or new_ask(t.id, "council", eng.s.get(t.id, "phase"), dec["question"],
                         f"Conselho sem unanimidade ({points_label(dec['points'])} pts; votos {votes}). "
                         f"Escolheu `{dec['choice']}` — {dec['label']}: {dec.get('why', '')}",
                         [{**o, "action": "", "note": ""} for o in dec["options"]], dec["choice"],
                         deadline=time.time() + eng.cfg.intervene_seconds("decision_timeout"))
    ask["qid"] = dec["qid"]
    while True:
        text = await wait(eng, ask)
        if text is None:
            close(eng, ask, timeout=True, choice=dec["choice"])
            eng.s.notice("decision_no_victor", f"Sem resposta: segue com `{dec['choice']}` — {dec['label']}.", t.id)
            eng.notify(f"orq · {t.id}: a decisão seguiu sem você", notify.clip(dec["question"], 200))
            return (f"- **{dec['question']}** → `{dec['choice']}` — {dec['label']} (conselho, "
                    f"{points_label(dec['points'])} pontos; o Victor não respondeu no prazo).")
        opt = match_option(ask, text)
        choice, label = (opt["id"], opt["label"]) if opt else ("victor", text)
        close(eng, ask, choice=choice, answer=text)
        return council_mod.record_victor(eng.s, t.id, dec, choice, label, "Escolhida pelo Victor.")
