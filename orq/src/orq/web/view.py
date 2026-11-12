"""O que a web mostra, em dict pronto para JSON. Lê o run dir como o painel (tui/model.py). A única escrita é a
do painel: o texto de uma tarefa pendente (set_task_text); o resto das ações vai pela inbox."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from .. import journal
from ..store import RunStore, queue_label, registered_runs, write_atomic
from ..tui import model

# O trilho da barra de estado, na ordem em que uma tarefa passa por ele.
STAGES = ("plano", "conselho", "execução", "verificação", "revisão")
STAGE_OF = {"start": "plano", "plan": "plano", "plan_questions": "conselho", "exec": "execução",
            "exec_answers": "execução", "exec_questions": "conselho", "clean": "execução", "verify": "verificação",
            "review": "revisão", "review_questions": "conselho", "takeover": "execução", "takeover_answers": "execução",
            "takeover_questions": "conselho", "final_clean": "execução", "final_verify": "verificação",
            "final_review": "revisão", "final_review_questions": "conselho"}
TASK_ID_RE = re.compile(r"[0-9][A-Za-z0-9_-]*")


def run_id(run_dir: Path) -> str:
    """Id estável e opaco para a URL: o caminho do run dir não aparece no navegador."""
    return hashlib.sha1(str(Path(run_dir).resolve()).encode()).hexdigest()[:12]


def find_run(rid: str) -> RunStore | None:
    for r in registered_runs(200):
        if run_id(Path(r["run"])) == rid:
            return RunStore(Path(r["run"]))
    return None


def _state(store: RunStore) -> str:
    from ..cli import run_state  # cli importa a web: import tardio
    return run_state(store)


def runs(limit: int = 30) -> list[dict]:
    out = []
    for r in registered_runs(limit):
        store = RunStore(Path(r["run"]))
        st = store.state()
        q = Path(st.get("queue") or r["queue"])
        out.append({"id": run_id(store.dir), "queue": queue_label(q), "run": str(store.dir), "ts": r.get("ts"),
                    "state": _state(store), "done": sum(1 for t in st["tasks"].values() if t.get("result")),
                    "total": len(list(q.glob("[0-9]*.md"))), "ask": bool(st.get("open_ask"))})
    return out


def event_entry(i: int, e: dict, ends: dict) -> dict | None:
    """Um evento para a linha do tempo e para o "desde a última visita". None = evento sem linha (ex.: step)."""
    line = journal.event_line(e)
    if not line:
        return None
    return {"i": i, "ts": e["ts"], "type": e["type"], "task": e.get("task") or "", "kind": e.get("kind"),
            "result": e.get("result"), "points": e.get("points"), "line": line,
            "attention": e["type"] == "notice" and journal.needs_attention(e, ends)}


def events_after(store: RunStore, after: int, limit: int = 500) -> list[dict]:
    events = store.events()
    ends = {e["task"]: e for e in journal.current_events(events) if e["type"] == "task_end"}
    out = [x for i, e in enumerate(events) if i >= after and (x := event_entry(i, e, ends))]
    return out[-limit:]


def _current(st: dict, rows: list[model.TaskRow]) -> dict | None:
    """A tarefa em curso: etapa do trilho e, durante uma chamada, papel, harness e modelo."""
    row = next((r for r in rows if r.glyph in "▶⏸" and st["tasks"].get(r.id, {}).get("phase") not in (None, "done")), None)
    ahead = st.get("plan_ahead") or {}
    if not row and ahead.get("phase") == "draft" and ahead.get("task"):  # rascunho antecipado: a tarefa ainda não começou
        cfg = ((st.get("config") or {}).get("roles") or {}).get("planner", {})
        return {"task": ahead["task"], "phase": "plan", "label": "rascunhando o plano", "stage": "plano", "cycle": 1,
                "role": "planner", "harness": cfg.get("harness"), "model": cfg.get("model"), "since": ahead.get("since")}
    if not row:
        return None
    t = st["tasks"][row.id]
    key = next((k for k in st.get("active_calls") or {} if k.startswith(row.id + ":")), None)
    role = key.split(":")[1] if key else None
    cfg = ((st.get("config") or {}).get("roles") or {}).get(role or "", {})
    return {"task": row.id, "phase": t["phase"], "label": row.status, "stage": STAGE_OF.get(t["phase"], "execução"),
            "cycle": t.get("cycle", 1), "role": role, "harness": cfg.get("harness"), "model": cfg.get("model"),
            "since": t.get("active_since")}


def run_view(store: RunStore, timeline: int = 300) -> dict:
    events = store.events()
    cur = journal.current_events(events)
    st = store.state()
    now = time.time()
    rows = model.task_rows(store, events, now, st)
    rs = next((e for e in cur if e["type"] == "run_start"), {})
    re_ = next((e for e in cur if e["type"] == "run_end"), None)
    ends = {e["task"]: e for e in cur if e["type"] == "task_end"}
    cost_by = st.get("cost_by", {})
    tasks = [{"id": r.id, "title": r.title, "glyph": r.glyph, "status": r.status, "extra": r.extra,
              "phase": st["tasks"].get(r.id, {}).get("phase"), "cycle": st["tasks"].get(r.id, {}).get("cycle"),
              "result": st["tasks"].get(r.id, {}).get("result"), "cost": round(sum(cost_by.get(r.id, {}).values()), 2)}
             for r in rows]
    summary = next((e["text"] for e in reversed(cur) if e["type"] == "run_summary"), None)
    return {
        "id": run_id(store.dir), "queue": rs.get("queue") or queue_label(Path(st["queue"])), "repo": rs.get("repo"),
        "run": str(store.dir), "state": _state(store), "paused": model.paused(cur),
        "started": rs.get("ts"), "ended": re_["ts"] if re_ else None, "result": re_["result"] if re_ else None,
        "eta": model.eta(cur, rows, now, st.get("tasks", {})) if not re_ else None,
        "cost": round(float(st.get("cost") or 0), 2), "cost_partial": bool(st.get("cost_unknown")),
        "roles": {k: rs[k] for k in ("planner", "executor", "voter", "tiebreak") if rs.get(k)},
        "tasks": tasks, "current": _current(st, rows) if not re_ else None, "stages": list(STAGES),
        "ask": st.get("open_ask"), "summary": summary, "n_events": len(events),
        "timeline": [x for i, e in enumerate(events) if (x := event_entry(i, e, ends))][-timeline:],
        "alive": store.engine_alive(), **_operator(st, events),
    }


def _operator(st: dict, events: list[dict]) -> dict:
    """Conversa com o operador: perguntas sem resposta, propostas (aplicada = há ack de comando enviado em nome
    dela) e os últimos acks, para a tela dizer o que o motor respondeu a cada ação."""
    acks = [e for e in events if e["type"] == "control_ack"]
    applied = {a.get("source", "")[len("web:op:"):] for a in acks if a.get("source", "").startswith("web:op:")}
    asked = {a["id"] for a in acks if a.get("source", "").startswith("web")}  # as do painel, o painel já tratou
    return {
        "pending_ops": [{"id": k, "text": v} for k, v in (st.get("pending_ops") or {}).items() if k in asked],
        "ops": [{"id": e["id"], "ts": e["ts"], "text": e.get("text", ""), "reply": e.get("reply", ""),
                 "commands": e.get("commands") or [], "applied": e["id"] in applied}
                for e in events if e["type"] == "operator" and e.get("id") in asked][-10:],
        "acks": [{k: a.get(k) for k in ("id", "command", "ok", "result")} for a in acks[-30:]],
    }


def _read(p: Path) -> str | None:
    try:
        return p.read_text(errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return None


def _decisions(cur: list[dict], tid: str) -> list[dict]:
    """Uma entrada por pergunta do conselho, com a escolha que vale hoje (a do usuário vence a do conselho)."""
    out: dict[str, dict] = {}
    for e in cur:
        if e["type"] == "decision" and e.get("task") == tid:
            out[e["qid"]] = {"qid": e["qid"], "question": e["question"], "options": e.get("options") or [],
                             "choice": e["choice"], "label": e["label"], "why": e.get("why", ""),
                             "points": e.get("points"), "by_user": journal.from_user(e)}
    return list(out.values())


# Depois do rascunho, o que muda a fila ou o que as tarefas anteriores entregam deixa o rascunho para trás.
STALE_COMMANDS = ("/add", "/skip", "/unskip", "/decision")


def draft_state(st: dict, events: list[dict], ids: list[str], tid: str) -> str | None:
    """rascunho · desatualizado · revalidado, ou None (tarefa sem plano antecipado)."""
    d = st["tasks"].get(tid, {}).get("draft")
    if not d:
        return None
    if d == "revalidated":
        return "revalidado"
    at = max((i for i, e in enumerate(events) if e["type"] == "plan" and e.get("task") == tid and e.get("draft")), default=-1)
    before = set(ids[: ids.index(tid)]) if tid in ids else set()
    for e in events[at + 1:]:
        t = e["type"]
        if (t == "control_ack" and e.get("ok") and str(e.get("command", "")).startswith(STALE_COMMANDS)
                or t == "task_end" and e.get("result") not in ("ok", "ok_takeover")
                or t == "plan_edit" and e.get("task") in before
                or t == "notice" and e.get("kind") == "control" and e.get("task") in before | {tid}):
            return "desatualizado"
    return "rascunho"


class TaskError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def set_task_text(store: RunStore, tid: str, text: str) -> None:
    """O /edit do painel, pela web: só tarefa que ainda não começou, e nunca texto vazio."""
    st = store.state()
    f = Path(st["queue"]) / f"{tid}.md"
    if not TASK_ID_RE.fullmatch(tid) or not f.is_file():
        raise TaskError(404, "tarefa não encontrada nesta fila")
    if st["tasks"].get(tid, {}).get("phase"):
        raise TaskError(409, f"{tid} já começou; só tarefa pendente é editada")
    if not isinstance(text, str) or not text.strip():
        raise TaskError(400, "o texto da tarefa não pode ficar vazio")
    write_atomic(f, text.rstrip() + "\n")
    store.notice("control", "Texto da tarefa editado pela web.", tid)


def set_plan_text(store: RunStore, tid: str, text: str) -> None:
    """O dono edita o rascunho do plano: vale como restrição na revalidação (evento plan_edit)."""
    st = store.state()
    plan = store.dir / tid / "plan.md"
    if not TASK_ID_RE.fullmatch(tid) or not (Path(st["queue"]) / f"{tid}.md").is_file():
        raise TaskError(404, "tarefa não encontrada nesta fila")
    if st["tasks"].get(tid, {}).get("phase"):
        raise TaskError(409, f"{tid} já começou; o plano não é mais editado, mande uma instrução")
    if not st["tasks"].get(tid, {}).get("draft"):
        raise TaskError(409, f"{tid} ainda não tem rascunho de plano")
    if not isinstance(text, str) or not text.strip():
        raise TaskError(400, "o plano não pode ficar vazio")
    write_atomic(plan, text.rstrip() + "\n")
    store.event("plan_edit", {"task": tid, "manual": True})


def task_view(store: RunStore, tid: str) -> dict | None:
    st = store.state()
    f = Path(st["queue"]) / f"{tid}.md"
    if not TASK_ID_RE.fullmatch(tid) or not f.is_file():  # o id vira caminho: só nome de tarefa que existe na fila
        return None
    events = store.events()
    cur = journal.current_events(events)
    row = next((r for r in model.task_rows(store, events, state=st) if r.id == tid), None)
    review = next((e for e in reversed(cur) if e["type"] == "review" and e.get("task") == tid), {})
    last = next((e for e in reversed(cur) if e["type"] == "exec" and e.get("task") == tid), {})
    diff = model.task_diff(st, events, tid)
    d = store.dir / tid
    return {
        "id": tid, "title": row.title if row else tid, "status": row.status if row else "", "glyph": row.glyph if row else "",
        "text": f.read_text(errors="replace"), "plan_md": _read(d / "plan.md"), "decisions_md": _read(d / "decisions.md"),
        "report_md": _read(d / "report.md"),
        "validation": review.get("validation") or [], "highlights": review.get("highlights") or [],
        "pending": last.get("pending") or [],
        "decisions": _decisions(cur, tid), "editable": not st["tasks"].get(tid, {}).get("phase"),
        "skipped": st["tasks"].get(tid, {}).get("result") == "skipped",
        "draft": draft_state(st, cur, sorted(p.stem for p in Path(st["queue"]).glob("[0-9]*.md")), tid),
        "steps": [{k: s.get(k) for k in ("label", "kind", "cycle", "dur", "ok", "running", "open", "waited", "tools")}
                  for s in model.task_steps(store, events, tid)] if d.is_dir() else [],
        "diff": {"add": diff.add, "rem": diff.rem, "nfiles": diff.nfiles,
                 "files": [{"add": a, "rem": r, "path": p} for a, r, p in sorted(diff.files, key=lambda x: -(x[0] + x[1]))]}
        if diff else None,
    }
