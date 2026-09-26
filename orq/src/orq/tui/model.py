"""O que o painel mostra, lido do run dir (sem Textual: testável). Nada depende de cor: estado por glifo e texto."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..context import title
from ..journal import event_line
from ..store import RunStore

PHASE_LABEL = {"start": "começando", "plan": "planejando", "plan_questions": "conselho do plano",
               "exec": "executando", "exec_answers": "executando", "verify": "verificando", "review": "revisando",
               "takeover": "planejador assumiu", "takeover_answers": "planejador assumiu",
               "final_verify": "verificação final", "final_review": "revisão final"}
RESULT = {"ok": ("✓", "ok"), "ok_takeover": ("✓", "ok, assumida"), "failed": ("✗", "FALHOU"),
          "blocked": ("✗", "BLOQUEADA"), "skipped": ("⊘", "pulada")}


def fmt_dur(s: float | int | None) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s} s" if s < 60 else f"{s // 60} min" if s < 3600 else f"{s // 3600} h {s % 3600 // 60:02d}"


@dataclass
class TaskRow:
    id: str
    glyph: str
    status: str
    extra: str
    title: str

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


def task_rows(store: RunStore, events: list[dict], now: float | None = None) -> list[TaskRow]:
    st = store.state()
    queue = Path(st["queue"])
    ends = {e["task"]: e for e in events if e["type"] == "task_end"}
    is_paused = paused(events)
    now = now or time.time()
    rows = []
    for f in sorted(queue.glob("[0-9]*.md")):
        t = st["tasks"].get(f.stem, {})
        res, phase = t.get("result"), t.get("phase")
        if res in RESULT:
            glyph, status = RESULT[res]
            extra = fmt_dur(ends[f.stem]["duration_s"]) if f.stem in ends else ""
        elif phase and phase != "done":
            glyph = "⏸" if is_paused else "▶"
            status = PHASE_LABEL.get(phase, phase)
            cycle = t.get("cycle", 1)
            if phase in ("exec", "exec_answers", "verify", "review") and cycle:
                status += f" c{cycle}"
            extra = fmt_dur(now - t["started"]) if t.get("started") else ""
        else:
            glyph, status, extra = "·", "pendente", ""
        rows.append(TaskRow(f.stem, glyph, status, extra, title(f)))
    return rows


def timeline_line(e: dict) -> str | None:
    line = event_line(e)
    return f"{e['ts'][11:16]} {line}" if line else None


def header(store: RunStore, events: list[dict], rows: list[TaskRow]) -> str:
    rs = next((e for e in events if e["type"] == "run_start"), {})
    done = sum(1 for r in rows if r.glyph in "✓⊘")
    ended = any(e["type"] == "run_end" for e in events)
    alive = store.engine_alive()
    motor = "terminou" if ended else ("⏸ pausado" if paused(events) and alive else "rodando" if alive else "parado")
    cost = store.cost()
    return f"orq · {rs.get('queue', '?')} · {done}/{len(rows)} tarefas · motor {motor} · US$ {cost:.2f}"


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
