"""events.jsonl → journal.md (o jsonl é a fonte; o .md nunca é editado à mão) e a linha curta de cada evento,
usada no orq.log e na timeline do painel. Etiquetas em texto e negrito: nada depende de cor."""
from __future__ import annotations

import re

RESULT_LABEL = {"ok": "ok", "ok_takeover": "**ok (assumida pelo planejador)**", "failed": "**FALHOU**",
                "blocked": "**BLOQUEADA**", "skipped": "pulada"}
VERDICT_LABEL = {"approved": "aprovada", "changes": "**reprovada**"}
STATUS_LABEL = {"done": "concluída", "needs_decision": "parou com dúvida", "blocked": "**bloqueada**"}
NOTICE_LABEL = {"limit_wait": "LIMITE DE USO", "limit_giveup": "LIMITE DE USO", "account_switch": "TROCA DE CONTA",
                "timeout": "TIMEOUT", "error": "ERRO", "interrupted": "INTERROMPIDO", "resumed": "RETOMADA",
                "retry": "REFEITA", "paused": "PAUSA", "stopped": "PARADA", "control": "AJUSTE",
                "note": "NOTA", "operator": "OPERADOR"}


def esc(v) -> str:
    return re.sub(r"\n+", " ", _s(v).replace("|", "\\|"))


def _s(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def pts(p) -> str:
    if p == 2.5:
        return "2,5"
    if isinstance(p, float) and p.is_integer():
        return str(int(p))
    return _s(p)


def anchor(t: str) -> str:
    return "t-" + re.sub(r"[^a-z0-9]+", "-", t.lower())


def link(t: str) -> str:
    return f"[{t}](#{anchor(t)})"


def dur(s) -> str:
    if s is None:
        return "—"
    return f"{s} s" if s < 60 else f"{s // 60} min"


def result_label(r) -> str:
    return "em andamento" if r is None else RESULT_LABEL.get(r, r)


def verify_label(e: dict) -> str:
    if e["ok"]:
        return "passou"
    return "**estourou o timeout**" if e.get("timed_out") else f"**falhou** (código {e.get('exit')})"


def _hm(ts: str) -> str:
    return ts[0:16].replace("T", " ", 1)


def _last_per_task(evs: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for e in evs:
        groups[e.get("task")] = e
    return [groups[k] for k in sorted(groups, key=lambda x: (x is None, x or ""))]


def _section(e: dict) -> str | None:
    t = e["type"]
    if t == "plan":
        return f"### Plano\n\n{e['summary']}\n\nArquivo: [{e['plan_rel']}]({e['plan_rel']})\n"
    if t == "decision":
        who = "Victor (pelo painel)" if e.get("source") == "victor" else e["source"]
        head = "do Victor" if e.get("points") is None else f"**{pts(e['points'])} pontos**"
        out = f"### Decisão — {esc(e['question'])} ({head})\n\nPerguntado por: {who}. {esc(e.get('context', ''))}\n\n"
        out += "| Opção | Votos |\n|---|---|\n"
        rows = []
        for o in e.get("options", []):
            voters = ", ".join(_s(v["voter"]) for v in e.get("votes", []) if v["option_id"] == o["id"]) or "—"
            chosen = " **← escolhida**" if o["id"] == e["choice"] else ""
            rows.append(f"| `{o['id']}` — {esc(o['label'])}{chosen} | {voters} |")
        out += "\n".join(rows) + "\n\n"
        out += "\n".join(f"- Conselheiro {v['voter']} (`{v['option_id']}`): {esc(v['rationale'])}" for v in e.get("votes", []))
        if e.get("tiebreak"):
            out += f"\n- **Desempate** (`{e['choice']}`): {esc(e['tiebreak'])}"
        if e.get("override"):
            out += f"\n- **Trocada pelo Victor** para `{e['choice']}`: {esc(e.get('why', ''))}"
        return out + "\n"
    if t == "exec":
        out = f"### Ciclo {e['cycle']} — execução ({e['actor']}): {STATUS_LABEL.get(e['status'], e['status'])}\n\n{e['summary']}\n"
        if e.get("commits"):
            out += "\nCommits: " + " · ".join(f"`{c['hash'][0:9]}` {esc(c['message'])}" for c in e["commits"]) + "\n"
        if e.get("checks"):
            out += "\nVerificações:\n" + "\n".join(f"- `{esc(c['command'])}` → {esc(c['result'])}" for c in e["checks"]) + "\n"
        if e.get("pending"):
            out += "\n**Pendente:**\n" + "\n".join(f"- {esc(p)}" for p in e["pending"]) + "\n"
        return out
    if t == "review":
        out = f"### Ciclo {e['cycle']} — revisão ({e['reviewer']}): {VERDICT_LABEL.get(e['verdict'], e['verdict'])}\n\n{e['summary']}\n"
        if e.get("issues"):
            out += "\n| Sev. | Onde | O quê | Correção |\n|---|---|---|---|\n" + "\n".join(
                f"| {i['severity']} | {esc(i['where'])} | {esc(i['what'])} | {esc(i['fix'])} |" for i in e["issues"]) + "\n"
        if e.get("highlights"):
            out += "\n**Destaques:**\n" + "\n".join(f"- {esc(h)}" for h in e["highlights"]) + "\n"
        return out
    if t == "verify":
        return (f"### Ciclo {e['cycle']} — verificação automática: {verify_label(e)}\n\n"
                f"`{esc(e['command'])}` em {dur(e.get('duration_s'))}. Saída: [{e['log_rel']}]({e['log_rel']})\n")
    if t == "notice":
        return f"> **[{NOTICE_LABEL.get(e['kind'], 'AVISO')}]** {esc(e['text'])}\n"
    if t == "task_end":
        return f"### Resultado: {result_label(e['result'])}\n\n{e.get('reason') or ''}\n"
    return None


def render(ev: list[dict]) -> str:
    rs = next((e for e in ev if e["type"] == "run_start"), {})
    re_ = next((e for e in ev if e["type"] == "run_end"), None)
    ts = [e for e in ev if e["type"] == "task_start"]
    te = [e for e in ev if e["type"] == "task_end"]
    last_exec = _last_per_task([e for e in ev if e["type"] == "exec"])
    last_review = _last_per_task([e for e in ev if e["type"] == "review"])

    attn = (
        [f"- **[FALHOU]** {link(e['task'])} — {esc(e.get('reason') or '')}" for e in te if e["result"] == "failed"]
        + [f"- **[BLOQUEIO]** {link(e['task'])} — {esc(e.get('reason') or '')}" for e in te if e["result"] == "blocked"]
        + [f"- **[ASSUMIDA PELO PLANEJADOR]** {link(e['task'])} — o executor não passou na revisão em {rs.get('max_cycles')} ciclos"
           for e in te if e["result"] == "ok_takeover"]
        + [f"- **[DECISÃO {pts(e['points'])} pts]** {link(e['task'])} — {esc(e['question'])} → `{e['choice']}` {esc(e['label'])}"
           for e in ev if e["type"] == "decision" and e.get("points") is not None and e["points"] < 3]
        + [f"- **[DECISÃO DO VICTOR]** {link(e['task'])} — {esc(e['question'])} → `{e['choice']}` {esc(e['label'])}"
           for e in ev if e["type"] == "decision" and e.get("source") == "victor"]
        + [f"- **[PENDENTE]** {link(e['task'])} — {esc(p)}" for e in last_exec for p in e.get("pending") or []]
        + [f"- **[DESTAQUE]** {link(e['task'])} — {esc(h)}" for e in last_review for h in e.get("highlights") or []]
        + [f"- **[{NOTICE_LABEL.get(e['kind'], 'AVISO')}]** " + (f"{link(e['task'])} — " if e.get("task") else "") + esc(e["text"])
           for e in ev if e["type"] == "notice"]
    )

    lines = [
        f"# orq — {rs.get('queue')} — {_hm(rs.get('ts', ''))}",
        "",
        f"Repositório `{rs.get('repo')}` · conta {rs.get('account')} · planejador/revisor {rs.get('planner')} · "
        f"executor {rs.get('executor')} · conselho {rs.get('voters')}× {rs.get('voter')}, desempate {rs.get('tiebreak')} · "
        f"até {rs.get('max_cycles')} ciclos",
        "",
        (f"**Fim:** {_hm(re_['ts'])} — {esc(re_['result'])}. Custo estimado: US$ {re_['cost']}." if re_
         else f"**Em andamento.** Última atualização: {_hm(ev[-1]['ts'])}."),
        "",
        "## Leia primeiro",
        "",
        *(attn or ["Nada exige atenção."]),
        "",
        "## Resumo",
        "",
        "| # | Tarefa | Resultado | Ciclos | Decisões (3 / 2,5 / 2 pts) | Commits | Duração |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ts):
        t = s["task"]
        end = next((e for e in te if e["task"] == t), {})
        cycles = max([e["cycle"] for e in ev if e["type"] == "exec" and e.get("task") == t], default=0)
        d = [e.get("points") for e in ev if e["type"] == "decision" and e.get("task") == t]
        nc = len({c["hash"] for e in ev if e["type"] == "exec" and e.get("task") == t for c in e.get("commits") or []})
        lines.append(f"| {i + 1} | {link(t)} | {result_label(end.get('result'))} | {cycles} | "
                     f"{d.count(3)} / {d.count(2.5)} / {d.count(2)} | {nc} | {dur(end.get('duration_s'))} |")
    lines.append("")
    for i, s in enumerate(ts):
        t = s["task"]
        lines += [f'<a id="{anchor(t)}"></a>', "", f"## Run {i + 1} — {t}", "",
                  f"Início {s['ts'][11:16]} · base `{s['base'][0:9]}` · tarefa: `{s['task_file']}`", ""]
        lines += [sec for e in ev if e.get("task") == t and e["type"] != "task_start" if (sec := _section(e)) is not None]
        lines.append("")
    return "\n".join(lines) + "\n"


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def event_line(e: dict) -> str | None:
    """Uma linha legível por evento (orq.log e timeline). None = evento sem linha."""
    t = e["type"]
    task = e.get("task") or ""
    if t == "run_start":
        return f"▶ execução começou: fila {e.get('queue')}"
    if t == "run_end":
        return f"■ execução terminou: {e.get('result')} · US$ {e.get('cost')}"
    if t == "task_start":
        return f"▶ {task} começou"
    if t == "task_end":
        glyph = {"ok": "✓", "ok_takeover": "✓", "skipped": "⊘"}.get(e["result"], "✗")
        return f"{glyph} {task} terminou: {RESULT_LABEL.get(e['result'], e['result']).replace('**', '')} " \
               f"({dur(e.get('duration_s'))}, {e.get('cycles', 1)} ciclo(s)) — {_clip(e.get('reason', ''), 160)}"
    if t == "plan":
        return f"[PLANO] {task}: {_clip(e['summary'], 300)}"
    if t == "exec":
        extra = f" · {len(e['pending'])} pendência(s)" if e.get("pending") else ""
        return (f"[EXECUÇÃO c{e['cycle']}] {task} ({e['actor']}): {STATUS_LABEL.get(e['status'], e['status']).replace('**', '')}"
                f" · {len(e.get('commits') or [])} commit(s){extra} — {_clip(e['summary'], 200)}")
    if t == "verify":
        return f"[VERIFICAÇÃO c{e['cycle']}] {task}: {verify_label(e).replace('**', '')} · {dur(e.get('duration_s'))}"
    if t == "review":
        n = {s: sum(1 for i in e.get("issues") or [] if i["severity"] == s) for s in ("alta", "media", "baixa")}
        return (f"[REVISÃO c{e['cycle']}] {task}: {VERDICT_LABEL.get(e['verdict'], e['verdict']).replace('**', '')}"
                f" · problemas alta {n['alta']} / média {n['media']} / baixa {n['baixa']}")
    if t == "decision":
        tag = "DECISÃO DO VICTOR" if e.get("source") == "victor" else f"DECISÃO {pts(e['points'])} pts"
        votes = ", ".join(v["option_id"] for v in e.get("votes") or [])
        return f"[{tag}] {task}: {_clip(e['question'], 120)} → `{e['choice']}` {e['label']}" + (f" (votos {votes})" if votes else "")
    if t == "notice":
        return f"[{NOTICE_LABEL.get(e['kind'], 'AVISO')}] " + (f"{task}: " if task else "") + _clip(e["text"], 300)
    if t == "operator":
        n = len(e.get("commands") or [])
        return f"[OPERADOR] {_clip(e.get('reply', ''), 400)}" + (f" ({n} comando(s) propostos)" if n else "")
    if t == "control_ack":
        return f"[AJUSTE] {e.get('command')} → {e.get('result')}"
    return None
