"""O que o painel mostra, lido do run dir (sem Textual: testável). Nada depende de cor: estado por glifo e texto."""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.text import Text

from ..context import title
from ..journal import _section, call_kind, cost_parts, current_events, event_line, flow, mark, step_label, steps
from ..store import RunStore, active_seconds

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
            extra = fmt_hms(ends[f.stem].get("active_s", ends[f.stem]["duration_s"])) if f.stem in ends else ""
        elif phase and phase != "done":
            glyph = "⏸" if is_paused else "▶"
            status = PHASE_LABEL.get(phase, phase)
            cycle = t.get("cycle", 1)
            if phase in ("exec", "exec_answers", "verify", "review") and cycle:
                status += f" c{cycle}"
            extra = fmt_hms(active_seconds(t, now)) if t.get("started") else ""  # ativo: a espera não corre
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


def eta(events: list[dict], rows: list[TaskRow], now: float, tasks: dict | None = None) -> float | None:
    """Horário previsto de término: média do tempo ativo das tarefas terminadas × o que falta (a em curso conta o
    que sobra). Tempo ativo, não de parede: a espera pelo Victor não entra na média nem no que já correu."""
    durs = [e.get("active_s", e["duration_s"]) for e in events if e["type"] == "task_end" and e["result"] != "skipped"]
    pending = sum(1 for r in rows if r.glyph == "·")
    running = [r.id for r in rows if r.glyph in "▶⏸"]
    if not durs or not (pending or running):
        return None
    avg = sum(durs) / len(durs)
    left = avg * pending + sum(max(0.0, avg - active_seconds((tasks or {}).get(t, {}), now)) for t in running[-1:])
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
    end = eta(events, rows, now, st.get("tasks", {})) if not re_ else None
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


@dataclass
class Diff:
    """+/- de código de uma tarefa. `files` vazio: run antiga, só o total (do `git diff --stat`)."""
    add: int
    rem: int
    nfiles: int
    files: list[tuple[int, int, str]] = field(default_factory=list)

    @classmethod
    def from_numstat(cls, text: str) -> "Diff":
        files = []
        for line in (text or "").splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:  # binário vem como "-\t-"
                files.append((int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if parts[1].isdigit() else 0,
                              parts[2]))
        return cls(sum(f[0] for f in files), sum(f[1] for f in files), len(files), files)

    @classmethod
    def from_stat(cls, text: str) -> "Diff | None":
        m = re.search(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?", text or "")
        return cls(int(m[2] or 0), int(m[3] or 0), int(m[1])) if m else None

    def summary(self) -> str:
        return f"+{self.add} −{self.rem} · {self.nfiles} arq"


def task_diff(st: dict, events: list[dict], tid: str) -> Diff | None:
    """Terminada: a entrega gravada no task_end. Em curso: `git diff --numstat <base>` ao vivo (inclui o não
    commitado; arquivo novo não rastreado só entra depois do commit)."""
    events = current_events(events)
    end = next((e for e in reversed(events) if e["type"] == "task_end" and e["task"] == tid), None)
    if end:
        d = end.get("delivery") or {}
        return Diff.from_numstat(d["numstat"]) if "numstat" in d else Diff.from_stat(d.get("stat", ""))
    start = next((e for e in reversed(events) if e["type"] == "task_start" and e["task"] == tid), None)
    repo = ((st.get("config") or {}).get("run") or {}).get("repo")
    if not start or start.get("base") in (None, "none") or not repo:
        return None
    r = subprocess.run(["git", "-C", repo, "diff", "--numstat", start["base"]], capture_output=True, text=True)
    return Diff.from_numstat(r.stdout) if r.returncode == 0 else None


def task_head(row: TaskRow | None, diff: Diff | None) -> Text:
    """Topo do modal da tarefa: estado e o +/- por arquivo (maior mudança primeiro)."""
    t = Text()
    if row:
        t.append(row.text(200) + "\n", style="bold")
    if diff is None:
        t.append("código: nenhuma entrega registrada", style="dim")
        return t
    t.append(f"código: {diff.summary()}\n", style="bold")
    for a, r, path in sorted(diff.files, key=lambda f: -(f[0] + f[1])):
        t.append(f"  +{a:<5} −{r:<5} {path}\n")
    if not diff.files and diff.nfiles:
        t.append("  (run antiga: sem detalhe por arquivo)", style="dim")
    return t


def task_history(store: RunStore, events: list[dict], tid: str) -> list[tuple[str, Text]]:
    """O fluxo de uma tarefa → [(horário, texto)]: eventos (com o detalhe do journal, horário vazio na continuação)
    e o activity.log (stream e início de cada chamada), cada linha depois dos eventos que já existiam ao gravá-la."""
    cur = {id(e) for e in current_events(events)}
    items = [((i, 0), e["ts"], Text(line, style=line_style(e)), _section(e) if e["type"] != "task_start" else None)
             for i, e in enumerate(events) if id(e) in cur and e.get("task") == tid and (line := event_line(e))]
    try:
        act = (store.dir / tid / "activity.log").read_text().splitlines()
    except FileNotFoundError:
        act = []
    for a in act:
        ts, n, line = (a.split("\t", 2) + ["", ""])[:3]
        if n.isdigit():
            items.append(((int(n) - 1, 1), ts, Text(line.strip()), None))
    items.sort(key=lambda x: x[0])
    out = []
    for _, ts, text, body in items:
        out.append((f"{datetime.fromisoformat(ts):%d/%m %H:%M:%S}", text))
        for line in (body or "").splitlines()[2:]:  # sem o título "### …", que repete a linha
            if line.strip():
                out.append(("", Text(line, style="dim")))
    return out


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


# --- tempo por etapa ------------------------------------------------------------------------------------------------
BUILD_RE = re.compile(r"\bng (build|test)\b|vitest|\bnpm\b|\bnpx\b|\bmake\b|pytest|verify\.sh")
_split_cache: dict[tuple[str, int], dict[str, int]] = {}


def _tool_cat(name: str, inp: dict) -> str:
    if name == "Bash":
        cmd = inp.get("command") or ""
        return "playwright" if "playwright" in cmd else "build/test" if BUILD_RE.search(cmd) else "outros comandos"
    if name in ("Read", "Write", "Edit", "MultiEdit", "Grep", "Glob", "NotebookEdit"):
        return "leitura/edição"
    return "subagente" if name in ("Agent", "Task") else name


def tool_split(path: Path) -> dict[str, int]:
    """Segundos por ferramenta numa chamada do claude, pelo `timestamp` de cada tool_use e do tool_result; "modelo"
    é o resto (gerando). Sem arquivo ou sem timestamp (codex, opencode): {}."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        return {}
    if key in _split_cache:
        return _split_cache[key]
    pend, tools, first, last = {}, {}, None, None
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or not e.get("timestamp"):
            continue
        ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
        first, last = first if first is not None else ts, ts
        msg = e.get("message")
        for c in (msg.get("content") or []) if isinstance(msg, dict) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                pend[c.get("id")] = (ts, _tool_cat(c.get("name", ""), c.get("input") or {}))
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in pend:
                t0, cat = pend.pop(c["tool_use_id"])
                tools[cat] = tools.get(cat, 0) + ts - t0
    out = {}
    if first is not None:
        out = {"modelo": round(last - first - sum(tools.values()))}
        out.update({k: round(v) for k, v in sorted(tools.items(), key=lambda x: -x[1])})
    _split_cache[key] = out
    return out


def _steps_from_calls(calls: Path) -> list[dict]:
    """Run sem evento step: uma etapa por calls/<nome>.json (fim = mtime, duração = duration_ms); votos e desempate
    do mesmo qid viram um conselho."""
    out, councils = [], {}
    for f in calls.glob("*.json"):
        try:
            ms = json.loads(f.read_text()).get("duration_ms")
        except (ValueError, OSError, AttributeError):
            continue
        if not ms:
            continue
        end = f.stat().st_mtime
        kind, cycle = call_kind(f.stem)
        if kind == "council":
            qid = re.sub(r"^(vote|tiebreak)-|-\d+(-b)?$|-b$", "", f.stem)
            c = councils.setdefault(qid, {"label": "conselho", "kind": "council", "cycle": None, "start": end, "end": 0,
                                          "ok": None})
            c["start"], c["end"] = min(c["start"], end - ms / 1000), max(c["end"], end)
            continue
        out.append({"label": step_label(kind, cycle), "kind": kind, "cycle": cycle, "start": end - ms / 1000,
                    "dur": ms / 1000, "call": f.stem, "ok": None})
    for c in councils.values():
        c["dur"] = c.pop("end") - c["start"]
        out.append(c)
    return out


def task_steps(store: RunStore, events: list[dict], tid: str, now: float | None = None) -> list[dict]:
    """Etapas da tarefa para o modal: os eventos (ou, em run antiga, os calls/), a divisão por ferramenta de cada
    chamada e a etapa em curso, com o relógio correndo."""
    now = now or time.time()
    st = steps(events, tid)
    if not any(s.get("call") for s in st):
        st = sorted(_steps_from_calls(store.dir / tid / "calls") + [s for s in st if s["kind"] in ("verify", "wait")],
                    key=lambda x: x["start"])
    verdicts = {e["cycle"]: e.get("verdict") == "approved" for e in events if e["type"] == "review" and e.get("task") == tid}
    for s in st:
        if s["kind"] == "review" and s.get("cycle") in verdicts:
            s["ok"] = verdicts[s["cycle"]]
        if s.get("call"):
            s["tools"] = tool_split(store.dir / tid / "calls" / f"{s['call']}.stream.jsonl")
        if s.get("open"):
            s["dur"] = now - s["start"]
    t = store.state()["tasks"].get(tid, {})
    if t.get("active_since") and t.get("phase") not in (None, "done"):
        phase, cycle = t["phase"], t.get("cycle", 1)
        st.append({"label": PHASE_LABEL.get(phase, phase) + (f" c{cycle}" if phase in ("exec", "verify", "review") else ""),
                   "kind": "running", "start": float(t["active_since"]), "dur": now - float(t["active_since"]),
                   "ok": None, "running": True})
    return st


def _bar(frac: float, width: int = 24) -> str:
    eighths = round(max(0.0, min(1.0, frac)) * width * 8)
    full, rest = divmod(eighths, 8)
    return "█" * full + ("▏▎▍▌▋▊▉"[rest - 1] if rest else "") or "▏"


def steps_text(st: list[dict]) -> Text:
    """Fluxo e uma linha por etapa: duração, barra proporcional ao tempo ativo e a divisão por ferramenta. Estado
    por glifo e texto (✓ ✗ ▶), nada por cor."""
    t = Text()
    if not st:
        t.append("etapas: nenhuma registrada ainda", style="dim")
        return t
    work = [s for s in st if s["kind"] != "wait"]
    total = sum(s["dur"] or 0 for s in work) or 1
    wait = sum(s["dur"] or 0 for s in st if s["kind"] == "wait")
    t.append("fluxo: " + flow(st) + "\n", style="bold")
    t.append(f"ativo {fmt_dur(total)}" + (f" · espera {fmt_dur(wait)}" if wait else "") + "\n")
    for s in st:
        lead = "▶ " if s.get("running") or s.get("open") else "  "
        label = f"{lead}{s['label']}{mark(s)}"[:22].ljust(22)
        when = (fmt_hms(s["dur"]) if s.get("running") else fmt_dur(s["dur"])).rjust(8)
        if s["kind"] == "wait":
            t.append(f"{label} {when}  (fora do ativo)\n", style="dim")
            continue
        frac = (s["dur"] or 0) / total
        tools = " · ".join(f"{k} {fmt_dur(v)}" for k, v in (s.get("tools") or {}).items() if v >= 1)
        extra = "  em curso" if s.get("running") else (f"  {tools}" if tools else "")
        if s.get("waited"):
            extra += f" · limite/erro {fmt_dur(s['waited'])}"
        t.append(f"{label} {when}  {_bar(frac).ljust(25)} {round(frac * 100):>3}%{extra}\n",
                 style="bold" if s.get("running") else "")
    return t
