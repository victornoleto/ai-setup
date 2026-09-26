"""Conselho: N votantes independentes em paralelo, contagem e desempate.
Pontos: unânime = 3 · maioria = 2 · sem maioria, decidida pelo desempatador = 2,5."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import Engine, Task


def tally(votes: list[dict], n: int) -> tuple[str, float] | None:
    """→ (opção, pontos) ou None (empate: vai ao desempatador)."""
    if not votes:
        return None
    counts = Counter(v["option_id"] for v in votes).most_common()
    top_id, top = counts[0]
    if top == n:
        return top_id, 3
    if top >= 2 and sum(1 for _, c in counts if c == top) == 1:
        return top_id, 2
    return None


def points_label(p) -> str:
    return "2,5" if p == 2.5 else str(int(p))


def valid(vote: dict | None, ids: list[str]) -> bool:
    return bool(vote) and vote.get("option_id") in ids


async def decide(eng: "Engine", t: "Task", source: str, q: dict) -> str | None:
    """Decide uma dúvida; grava o evento e o decisions.md. → a linha de resposta, ou None em falha."""
    from .engine import prompt

    qid = q["id"]
    ids = [o["id"] for o in q["options"]]
    options_md = "\n".join(f"- `{o['id']}` — {o['label']}: {o['detail']}" for o in q["options"])
    d = t.dir / "council" / f"{datetime.now():%H%M%S}-{qid}"
    d.mkdir(parents=True, exist_ok=True)
    n = eng.cfg.voters
    common = dict(VOTERS=n, REPO=eng.cfg.repo, TASK_ID=t.id, PLAN_FILE=t.plan_file, SOURCE=source,
                  TASK=t.text.rstrip("\n"), RULES=eng.rules.rstrip("\n"), QUESTION=q["question"],
                  QCONTEXT=q["context"], OPTIONS=options_md, PROGRESS=eng.progress(t))
    vote_prompt = prompt("vote", **common)
    (d / "vote.md").write_text(vote_prompt)
    eng.s.log(f"conselho: {qid} ({n} votantes)")

    async def one(i: int, suffix: str = "") -> dict | None:
        out, _ = await eng.call(t, "voter", f"vote-{qid}-{i}{suffix}", "vote", vote_prompt)
        return out

    results = await asyncio.gather(*(one(i) for i in range(1, n + 1)))
    votes = []
    for i, v in enumerate(results, 1):
        if not valid(v, ids):
            eng.s.log(f"conselho: voto {i} inválido, nova chamada")
            v = await one(i, "-b")
        if valid(v, ids):
            (d / f"vote-{i}.json").write_text(json.dumps(v, ensure_ascii=False))
            votes.append({"voter": i, "option_id": v["option_id"], "rationale": v["rationale"]})
    if not votes:
        eng.s.notice("error", f"Conselho sem nenhum voto válido para '{qid}'.", t.id)
        return None

    tb_rationale = ""
    res = tally(votes, n)
    if res:
        choice, points = res
    else:
        eng.s.log(f"conselho: sem maioria em {qid}, desempate")
        tb_prompt = prompt("tiebreak", **common, VOTES="\n".join(
            f"- Conselheiro {v['voter']}: `{v['option_id']}` — {v['rationale']}" for v in votes))
        (d / "tiebreak.md").write_text(tb_prompt)
        tb = None
        for suffix in ("", "-b"):
            tb, _ = await eng.call(t, "tiebreak", f"tiebreak-{qid}{suffix}", "vote", tb_prompt)
            if valid(tb, ids):
                break
        if not valid(tb, ids):
            eng.s.notice("error", f"Desempate sem resposta válida para '{qid}'.", t.id)
            return None
        (d / "tiebreak.json").write_text(json.dumps(tb, ensure_ascii=False))
        choice, points, tb_rationale = tb["option_id"], 2.5, tb["rationale"]
    return record(eng, t, source, q, votes, choice, points, tb_rationale)


def record(eng: "Engine", t: "Task", source: str, q: dict, votes: list[dict], choice: str, points, tb: str) -> str:
    label = next(o["label"] for o in q["options"] if o["id"] == choice)
    why = tb or next(v["rationale"] for v in votes if v["option_id"] == choice)
    pts = points_label(points)
    eng.s.event("decision", {"task": t.id, "source": source, "qid": q["id"], "question": q["question"],
                             "context": q["context"], "options": q["options"], "votes": votes, "choice": choice,
                             "label": label, "points": points, "tiebreak": tb, "why": why})
    with open(t.decisions_file, "a") as fh:
        fh.write(f"## {q['question']} ({pts} pontos)\n\nPerguntado por: {source}. Escolha: `{choice}` — {label}.\n\n"
                 f"Por quê: {why}\n\n")
    return f"- **{q['question']}** → `{choice}` — {label} (conselho, {pts} pontos). Por quê: {why}"
