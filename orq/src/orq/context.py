"""Uma sessão nova por tarefa, mas sabendo onde está na fila: o bloco PROGRESS do prompt (o que já foi feito, a
tarefa atual, o que falta) e as mensagens do Victor que ainda não chegaram a uma sessão retomada."""
from __future__ import annotations

import re
from pathlib import Path

from .journal import RESULT_LABEL


def title(f: Path) -> str:
    for line in f.read_text().splitlines():
        s = re.sub(r"^[#>\-*\s]+", "", line).strip()
        if s:
            return s if len(s) <= 110 else s[:109] + "…"
    return "(vazia)"


def applies(ev: dict, task: str) -> bool:
    return not ev.get("for_task") or ev.get("for_task") == task


def victor_messages(events: list[dict], task: str) -> list[str]:
    """Notas e decisões do Victor que valem para a tarefa."""
    out = []
    for e in events:
        if e["type"] == "note" and applies(e, task):
            out.append(f"- ({e['ts'][11:16]}) {e['text']}")
        elif e["type"] == "decision" and e.get("source") == "victor" and e.get("task") == task:
            out.append(f"- ({e['ts'][11:16]}) Decisão trocada pelo Victor: **{e['question']}** → `{e['choice']}` — "
                       f"{e['label']}. {e.get('why', '')}".rstrip())
    return out


def progress(events: list[dict], task_files: list[Path], current: str) -> str:
    ends = {e["task"]: e for e in events if e["type"] == "task_end"}
    execs: dict[str, dict] = {}
    for e in events:
        if e["type"] == "exec":
            execs[e["task"]] = e
    ids = [f.stem for f in task_files]
    pos = ids.index(current) + 1 if current in ids else "?"
    lines = [f"Fila com {len(ids)} tarefa(s); esta é a `{current}` ({pos} de {len(ids)}). As outras rodam em sessões "
             "próprias: faça só esta, sem adiantar nem refazer as outras."]
    done = [i for i in ids if i in ends and i != current]
    if done:
        lines += ["", "Já feito (confira no `git log` se precisar do detalhe):"]
        for i in done:
            e, x = ends[i], execs.get(i, {})
            res = RESULT_LABEL.get(e["result"], e["result"]).replace("**", "")
            summary = re.sub(r"\s+", " ", x.get("summary") or e.get("reason") or "").strip()
            commits = " · ".join(f"`{c['hash'][:9]}` {c['message']}" for c in x.get("commits") or [])
            lines.append(f"- `{i}` — {res}. {summary}" + (f" Commits: {commits}" if commits else ""))
    rest = [f for f in task_files if f.stem not in ends and f.stem != current]
    if rest:
        lines += ["", "Falta depois desta (não adiante):"] + [f"- `{f.stem}` — {title(f)}" for f in rest]
    msgs = victor_messages(events, current)
    if msgs:
        lines += ["", "Mensagens do Victor durante a execução (valem como instrução do dono do projeto):"] + msgs
    return "\n".join(lines)


def inbox_block(msgs: list[str]) -> str:
    return ("\n\n## Mensagem nova do Victor (enviada durante a execução)\n\n" + "\n".join(msgs) +
            "\n\nIsto vale como instrução do dono do projeto e tem prioridade sobre o plano onde houver conflito.\n")
