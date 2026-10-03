from pathlib import Path

from orq import context

from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue


def test_progress_feito_atual_falta(tmp_path):
    fs = []
    for n, body in (("01-a", "# Seeder do cliente\n..."), ("02-b", "Comando novo"), ("03-c", "\n\n- Coordenadas")):
        (tmp_path / f"{n}.md").write_text(body)
        fs.append(tmp_path / f"{n}.md")
    ev = [{"type": "exec", "task": "01-a", "summary": "Fez o seeder.", "commits": [{"hash": "abcdef1234", "message": "feat: x"}],
           "pending": ["o ng serve da 4201 serve bundle velho", "conferir no CI", "c", "d (quarta: fica de fora)"]},
          {"type": "task_end", "task": "01-a", "result": "ok", "reason": "r"},
          {"type": "note", "ts": "2026-09-26T11:00:00-03:00", "text": "use a lib X", "for_task": ""},
          {"type": "note", "ts": "2026-09-26T11:01:00-03:00", "text": "só da 03", "for_task": "03-c"}]
    p = context.progress(ev, fs, "02-b")
    assert "`02-b` (2 de 3)" in p
    assert "- `01-a` — ok. Fez o seeder. Commits: `abcdef123` feat: x" in p
    assert "  Pendências que ela deixou: o ng serve da 4201 serve bundle velho · conferir no CI · c\n" in p
    assert "quarta" not in p
    assert "- `03-c` — Coordenadas" in p
    assert "(11:00) use a lib X" in p and "só da 03" not in p


async def test_nota_chega_na_sessao_retomada(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}, tasks=("01-a", "02-b"))
    e = engine(tmp_path, cfg)
    orig = e.call

    async def call(t, role, name, *a, **kw):
        if name.startswith("review") and t.id == "01-a":
            e.s.event("note", {"text": "confira o README", "for_task": ""})
        return await orig(t, role, name, *a, **kw)

    e.call = call
    assert await e.run()
    calls = e.harness("fake").calls
    review = next(c for c in calls if c.name.startswith("review") and "01-a" in str(c.calls_dir))
    assert "## Mensagem nova do Victor" in review.prompt and "confira o README" in review.prompt
    plan_b = next(c for c in calls if c.name == "plan" and "02-b" in str(c.calls_dir))
    assert "Mensagem nova" not in plan_b.prompt          # sessão nova: vem pelo PROGRESS
    assert "confira o README" in plan_b.prompt
    assert "- `01-a` — ok." in plan_b.prompt
