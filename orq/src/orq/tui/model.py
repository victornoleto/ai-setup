"""O que o painel mostra, lido do run dir (sem Textual: testável). Nada depende de cor: estado por glifo e texto."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.text import Text

from ..context import title
from ..journal import cost_parts, current_events, event_line
from ..store import RunStore

PHASE_LABEL = {"start": "começando", "plan": "planejando", "plan_questions": "conselho do plano",
               "exec": "executando", "exec_answers": "executando", "clean": "arrumando a árvore", "verify": "verificando", "review": "revisando",
               "takeover": "planejador assumiu", "takeover_answers": "planejador assumiu",
               "final_clean": "arrumando a árvore", "final_verify": "verificação final", "final_review": "revisão final"}
RESULT = {"ok": ("✓", "ok"), "ok_takeover": ("✓", "ok, assumida"), "ok_victor": ("✓", "ok, aceita pelo Victor"), "failed": ("✗", "FALHOU"),
          "blocked": ("✗", "BLOQUEADA"), "skipped": ("⊘", "pulada")}


def fmt_dur(s: float | int | None) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s} s" if s < 60 else f"{s // 60} min" if s < 3600 else f"{s // 3600} h {s % 3600 // 60:02d}"


def fmt_hms(s: float | int | None) -> str:
    if s is None:
        return ""
    s = max(0, int(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


@dataclass
class TaskRow:
    id: str
    glyph: str
    status: str
    extra: str
    title: str

    def styled(self, width: int = 60) -> Text:
        """Estado por glifo e intensidade; a cor só reforça (concluída apagada, em curso negrito, esperando inverso)."""
        style = {"✓": "dim", "⊘": "dim", "▶": "bold yellow", "⏸": "reverse bold", "✗": "bold red"}.get(self.glyph, "")
        return Text(self.text(width), style=style)

    def text(self, width: int = 60) -> str:
        head = f"{self.glyph} {self.id}  {self.status}" + (f" · {self.extra}" if self.extra else "")
        return head + "\n    " + self.title[: max(20, width - 4)]


def paused(events: list[dict]) -> bool:
    state = False
    for e in events:
        if e["type"] == "notice" and e["kind"] == "paused":
            state = True
        elif e["type"] == "notice" and e["kind"] in ("resumed", "stopped", "interrupted"):
            state = False
    return state


def task_rows(store: RunStore, events: list[dict], now: float | None = None, state: dict | None = None) -> list[TaskRow]:
    events = current_events(events)
    st = store.state() if state is None else state
    queue = Path(st["queue"])
    ends = {e["task"]: e for e in events if e["type"] == "task_end"}
    is_paused = paused(events)
    now = now or time.time()
    cost_by = st.get("cost_by", {})
    waiting = (st.get("open_ask") or {}).get("task")
    rows = []
    for f in sorted(queue.glob("[0-9]*.md")):
        t = st["tasks"].get(f.stem, {})
        res, phase = t.get("result"), t.get("phase")
        if res in RESULT:
            glyph, status = RESULT[res]
            extra = fmt_hms(ends[f.stem]["duration_s"]) if f.stem in ends else ""
        elif phase and phase != "done":
            glyph = "⏸" if is_paused else "▶"
            status = PHASE_LABEL.get(phase, phase)
            cycle = t.get("cycle", 1)
            if phase in ("exec", "exec_answers", "verify", "review") and cycle:
                status += f" c{cycle}"
            extra = fmt_hms(now - t["started"]) if t.get("started") else ""
        else:
            glyph, status, extra = "·", "pendente", ""
        if f.stem == waiting:
            glyph, status = "⏸", "esperando você"
        cost = sum(cost_by.get(f.stem, {}).values())
        if cost:
            extra += (" · " if extra else "") + f"US$ {cost:.2f}"
        rows.append(TaskRow(f.stem, glyph, status, extra, title(f)))
    return rows


def timeline_line(e: dict) -> str | None:
    line = event_line(e)
    return f"{e['ts'][11:16]} {line}" if line else None


def eta(events: list[dict], rows: list[TaskRow], now: float) -> float | None:
    """Horário previsto de término: média das tarefas terminadas × o que falta (a em curso conta o que sobra)."""
    durs = [e["duration_s"] for e in events if e["type"] == "task_end" and e["result"] != "skipped"]
    pending = sum(1 for r in rows if r.glyph == "·")
    running = [e for e in events if e["type"] == "task_start" and not any(
        x["type"] == "task_end" and x["task"] == e["task"] for x in events)]
    if not durs or not (pending or running):
        return None
    avg = sum(durs) / len(durs)
    left = avg * pending + sum(max(0.0, avg - (now - _epoch(e["ts"]))) for e in running[-1:])
    return now + left


def header(store: RunStore, events: list[dict], rows: list[TaskRow], now: float | None = None,
           state: dict | None = None) -> str:
    events = current_events(events)
    now = now or time.time()
    rs = next((e for e in events if e["type"] == "run_start"), {})
    re_ = next((e for e in events if e["type"] == "run_end"), None)
    done = sum(1 for r in rows if r.glyph in "✓⊘")
    alive = store.engine_alive()
    motor = "terminou" if re_ else ("⏸ pausado" if paused(events) and alive else "rodando" if alive else "parado")
    st = store.state() if state is None else state
    ask = st.get("open_ask")
    if ask and not re_:
        motor = f"⏸ esperando você · {fmt_hms(now - ask['opened'])}"
    clock = fmt_hms((_epoch(re_["ts"]) if re_ else now) - _epoch(rs["ts"])) if rs else ""
    end = eta(events, rows, now) if not re_ else None
    return (f"orq · {rs.get('queue', '?')} · {done}/{len(rows)} tarefas · motor {motor} · {clock}"
            + (f" · termina ~{datetime.fromtimestamp(end):%H:%M}" if end else "")
            + f" · US$ {float(st.get('cost') or 0):.2f} estimado" + (" (parcial)" if st.get("cost_unknown") else ""))


STYLE_BY_TYPE = {"task_start": "bold", "task_end": "bold", "run_start": "bold", "run_end": "bold",
                 "plan": "cyan", "verify": "blue", "review": "magenta", "decision": "yellow",
                 "operator": "italic green", "ask_reply": "italic green", "ask": "reverse bold yellow",
                 "ask_answer": "bold yellow", "notice": "bold red", "run_summary": "italic"}


def line_style(e: dict) -> str:
    """Estilo da linha na timeline. Cada tipo já tem prefixo próprio ([PLANO], [REVISÃO]…): a cor só reforça."""
    return STYLE_BY_TYPE.get(e.get("type", ""), "")


def ask_text(ask: dict) -> Text:
    """O bloco da pergunta aberta: título invertido, opções numeradas, a recomendada marcada por texto e negrito."""
    kind = {"council": "decisão sem unanimidade", "blocked": "bloqueada", "failed": "falhou"}.get(ask["kind"], ask["kind"])
    t = Text()
    t.append(f" [PRECISA DE VOCÊ] {ask['task']} · {kind} \n", style="reverse bold")
    t.append(ask["question"] + "\n", style="bold")
    if ask.get("diagnosis"):
        t.append("Por quê: " + ask["diagnosis"] + "\n")
    for i, o in enumerate(ask["options"], 1):
        rec = o["id"] == ask["recommended"]
        t.append(f" {i}) " + ("★ RECOMENDADA  " if rec else "") + o["label"] + "\n", style="bold yellow" if rec else "")
    if ask.get("reply"):
        t.append("operador: " + ask["reply"] + "\n", style="italic")
    foot = f"responda 1–{len(ask['options'])} ou escreva"
    if ask.get("deadline"):
        foot += f" · segue sozinha com a recomendada às {datetime.fromtimestamp(ask['deadline']):%H:%M}"
    t.append(foot, style="dim")
    return t


def cost_lines(store: RunStore, ref: str = "") -> list[str]:
    """Linhas do /cost: total por papel e cada tarefa (ou só as que começam com `ref`)."""
    by = store.cost_by()
    tasks = sorted(k for k in by if k and k.startswith(ref))
    lines = []
    if not ref:
        total: dict[str, float] = {}
        for roles in by.values():
            for r, v in roles.items():
                total[r] = total.get(r, 0) + v
        lines.append(f"custo estimado · total US$ {store.cost():.2f}: {cost_parts(total) or '—'}")
        if by.get(""):
            lines.append(f"  fora de tarefa: {cost_parts(by[''])}")
    lines += [f"  {k}: US$ {sum(by[k].values()):.2f} · {cost_parts(by[k])}" for k in tasks]
    missing = sum(sum(v.values()) for k, v in store.top("cost_unknown", {}).items() if not ref or k.startswith(ref))
    if missing:
        lines.append(f"total parcial: custo não informado em {missing} tentativa(s)")
    return lines or [f"✗ /cost: nenhuma tarefa '{ref}' com custo"]


class Tail:
    """Lê só o que foi acrescentado a um arquivo desde a última leitura."""

    def __init__(self, path: Path):
        self.path = path
        self.pos = 0

    def read(self) -> list[str]:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                data = fh.read()
        except FileNotFoundError:
            return []
        cut = data.rfind(b"\n") + 1  # só linhas completas
        self.pos += cut
        return data[:cut].decode(errors="replace").splitlines()
