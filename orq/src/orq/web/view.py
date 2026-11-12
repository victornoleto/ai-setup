"""O que a web mostra, em dict pronto para JSON. Lê o run dir como o painel (tui/model.py), sem escrever nada."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from .. import journal
from ..store import RunStore, queue_label, registered_runs
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
    }


def _read(p: Path) -> str | None:
    try:
        return p.read_text(errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return None


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
        "steps": [{k: s.get(k) for k in ("label", "kind", "cycle", "dur", "ok", "running", "open", "waited", "tools")}
                  for s in model.task_steps(store, events, tid)] if d.is_dir() else [],
        "diff": {"add": diff.add, "rem": diff.rem, "nfiles": diff.nfiles,
                 "files": [{"add": a, "rem": r, "path": p} for a, r, p in sorted(diff.files, key=lambda x: -(x[0] + x[1]))]}
        if diff else None,
    }
