import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from orq import config, council
from orq.engine import Engine, block_push_env, reset_wait
from orq.journal import event_line
from orq.store import RunStore

ROLES_FAKE = "\n".join(f'[roles.{r}]\nharness = "fake"\nmodel = "script.json"\n'
                       for r in config.ROLES)

PLAN = {"summary": "Criar a.txt.", "questions": []}
EXEC_OK = {"_sh": "echo a >> a.txt && git add -A && git -c user.name=t -c user.email=t@t commit -qm a",
           "status": "done", "summary": "Feito.", "commits": [{"hash": "abc1234", "message": "a"}],
           "checks": [], "pending": []}
APPROVED = {"verdict": "approved", "summary": "ok", "highlights": [], "issues": [], "questions": []}
CHANGES = {"verdict": "changes", "summary": "não", "highlights": [],
           "issues": [{"severity": "alta", "where": "a.txt", "what": "x", "fix": "y"}], "questions": []}
Q = {"id": "nome", "question": "Nome?", "context": "c",
     "options": [{"id": "a", "label": "A", "detail": ""}, {"id": "b", "label": "B", "detail": ""},
                 {"id": "c", "label": "C", "detail": ""}]}


def vote(o):
    return {"option_id": o, "rationale": f"r-{o}"}


def make_queue(tmp_path: Path, script: dict, tasks=("01-a",), extra_toml: str = "",
               intervene: str = "enabled = false") -> config.Config:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    q = tmp_path / "fila"
    q.mkdir()
    for t in tasks:
        (q / f"{t}.md").write_text(f"Tarefa {t}")
    (q / "script.json").write_text(json.dumps(script))
    (q / "orq.toml").write_text(f'{ROLES_FAKE}\n[run]\nrepo = "{repo}"\n[intervene]\n{intervene}\n{extra_toml}')
    return config.load(q)


def engine(tmp_path, cfg) -> Engine:
    s = RunStore(tmp_path / "run")
    s.create(cfg.queue_dir, "2")
    e = Engine(cfg, s)
    e.start_event()
    return e


def types(e: Engine) -> list[str]:
    return [x["type"] for x in e.s.events()]


async def test_aprovada_no_primeiro_ciclo(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}, tasks=("01-a", "02-b"))
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok" and e.s.get("02-b", "result") == "ok"
    assert types(e).count("task_end") == 2 and types(e)[-1] == "run_end"
    assert (cfg.repo / "a.txt").read_text() == "a\na\n"
    md = e.s.journal_path.read_text()
    assert "todas as 2 tarefas ok" in md and "Nada exige atenção." in md


async def test_takeover_depois_de_3_ciclos(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "planner:review": [CHANGES],
                                "reviewer:review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok_takeover"
    execs = [x for x in e.s.events() if x["type"] == "exec"]
    assert [x["cycle"] for x in execs] == [1, 2, 3, 4]
    assert "planejador assumiu" in execs[-1]["actor"]
    assert "[ASSUMIDA PELO PLANEJADOR]" in e.s.journal_path.read_text()


async def test_conselho_desempate_no_plano(tmp_path):
    plan_q = {"summary": "s", "questions": [Q]}
    cfg = make_queue(tmp_path, {"plan": [plan_q, PLAN], "execute": [EXEC_OK], "review": [APPROVED],
                                "voter:vote": [vote("a"), vote("b"), vote("c")], "tiebreak:vote": [vote("b")]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    d = next(x for x in e.s.events() if x["type"] == "decision")
    assert (d["choice"], d["points"]) == ("b", 2.5)
    assert "## Nome? (2,5 pontos)" in (e.s.dir / "01-a" / "decisions.md").read_text()
    upd = next(p for p in (e.s.dir / "01-a" / "calls").glob("plan-update-*.prompt.md"))
    assert "conselho, 2,5 pontos" in upd.read_text()


async def test_duvida_do_executor(tmp_path):
    ask = {**EXEC_OK, "_sh": "true", "status": "needs_decision", "commits": [], "questions": [Q]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [ask, EXEC_OK], "review": [APPROVED],
                                "voter:vote": [vote("c")]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    d = next(x for x in e.s.events() if x["type"] == "decision")
    assert (d["choice"], d["points"]) == ("c", 3)
    ans = next((e.s.dir / "01-a").glob("exec_answers-*.prompt.md")).read_text()
    assert "`c` — C" in ans


async def test_arvore_suja_bloqueia_e_para(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}, tasks=("01-a", "02-b"))
    (cfg.repo / "sujo.txt").write_text("x")
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "blocked"
    assert e.s.get("02-b", "phase") is None  # on_fail = stop


async def test_falha_do_harness(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [{"_error": "fatal", "_message": "boom"}]})
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "failed"
    assert "[ERRO]" in e.s.journal_path.read_text()


async def test_retomada_depois_de_interrupcao(tmp_path):
    slow = {**EXEC_OK, "_sleep": 30}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [slow, EXEC_OK], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    task = asyncio.create_task(e.run())
    for _ in range(100):
        await asyncio.sleep(0.02)
        if e.s.get("01-a", "phase") == "exec":
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert e2.s.get("01-a", "result") == "ok"
    assert types(e2).count("plan") == 1  # o plano não foi refeito


async def test_tarefa_adicionada_durante_a_execucao(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    orig = e.run_task

    async def run_task(f):
        await orig(f)
        if f.stem == "01-a":
            (cfg.queue_dir / "02-nova.md").write_text("nova")

    e.run_task = run_task
    assert await e.run()
    assert e.s.get("02-nova", "result") == "ok"


def test_push_bloqueado(tmp_path):
    remote = tmp_path / "r.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    import os
    env = {**os.environ, **block_push_env(repo)}
    assert subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:main"], env=env,
                          capture_output=True).returncode != 0
    assert subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:main"],
                          capture_output=True).returncode == 0


@pytest.mark.parametrize("votes,n,exp", [("aaa", 3, ("a", 3)), ("bab", 3, ("b", 2)), ("abc", 3, None),
                                         ("aa", 3, ("a", 2)), ("ab", 3, None)])
def test_tally(votes, n, exp):
    assert council.tally([{"option_id": v} for v in votes], n) == exp


def test_reset_wait():
    now = datetime(2026, 9, 26, 22, 0)
    assert reset_wait("limit reached, resets 3am", 1800, now) == 5 * 3600 + 120
    assert reset_wait("resets at 11:30 PM", 1800, now) == 90 * 60 + 120
    assert reset_wait("sem horário", 1800, now) == 1800


# --- verificação determinística ([verify] command) ------------------------------------------------------------------
def verifies(e: Engine) -> list[dict]:
    return [x for x in e.s.events() if x["type"] == "verify"]


async def test_verificacao_passa_e_vai_para_a_revisao(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml='[verify]\ncommand = "echo tudo certo; test -f a.txt"\n')
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok"
    assert [(v["cycle"], v["ok"]) for v in verifies(e)] == [(1, True)]
    assert "tudo certo" in (e.s.dir / "01-a" / "verify-1.log").read_text()
    review = next((e.s.dir / "01-a" / "calls").glob("review-1-*.prompt.md")).read_text()
    assert "echo tudo certo; test -f a.txt" in review and "passou" in review and "tudo certo" in review
    assert "verificação automática: passou" in (e.s.dir / "01-a" / "report.md").read_text()
    assert event_line(verifies(e)[0]).startswith("[VERIFICAÇÃO c1] 01-a: passou")


async def test_verificacao_falha_gasta_um_ciclo_sem_revisao(tmp_path):
    cmd = 'n=$(wc -l < a.txt); echo "linhas: $n"; [ "$n" -ge 2 ]'
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml=f"[verify]\ncommand = '{cmd}'\n")
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok"
    assert [(v["cycle"], v["ok"]) for v in verifies(e)] == [(1, False), (2, True)]
    assert [x["cycle"] for x in e.s.events() if x["type"] == "review"] == [2]
    fix = (e.s.dir / "01-a" / "fix-2.prompt.md").read_text()
    assert "linhas: 1" in fix and "verificação" in fix.lower()


async def test_verificacao_sempre_falha_termina_falhada_depois_do_takeover(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml='[verify]\ncommand = "echo quebrou; false"\n')
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "failed"
    assert [v["cycle"] for v in verifies(e)] == [1, 2, 3, 4]
    assert "review" not in types(e)
    assert "quebrou" in (e.s.dir / "01-a" / "takeover.prompt.md").read_text()
    end = next(x for x in e.s.events() if x["type"] == "task_end")
    assert "verificação" in end["reason"].lower()


async def test_verificacao_com_timeout_conta_como_falha(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml='[loop]\nmax_cycles = 1\n[verify]\ncommand = "sleep 5"\ntimeout = "1s"\n')
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert [(v["ok"], v["timed_out"]) for v in verifies(e)] == [(False, True), (False, True)]


async def test_retomada_na_fase_de_verificacao(tmp_path):
    solto = tmp_path / "solto"
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml=f'[verify]\ncommand = "while [ ! -f {solto} ]; do sleep 0.1; done"\n')
    e = engine(tmp_path, cfg)
    task = asyncio.create_task(e.run())
    for _ in range(200):
        await asyncio.sleep(0.02)
        if e.s.get("01-a", "phase") == "verify":
            break
    assert e.s.get("01-a", "phase") == "verify"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    solto.write_text("")
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert e2.s.get("01-a", "result") == "ok"
    assert types(e2).count("exec") == 1  # a execução não foi refeita
    assert [v["ok"] for v in verifies(e2)] == [True]


# --- árvore limpa no fim da execução --------------------------------------------------------------------------------
EXEC_DIRTY = {**EXEC_OK, "_sh": EXEC_OK["_sh"] + " && echo x > lixo.txt"}
CLEANUP = {**EXEC_OK, "_sh": "rm -f lixo.txt", "commits": [], "summary": "Lixo apagado."}


def notices(e: Engine, kind: str) -> list[dict]:
    return [x for x in e.s.events() if x["type"] == "notice" and x["kind"] == kind]


async def test_arvore_suja_depois_da_execucao_e_arrumada_pelo_executor(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_DIRTY, CLEANUP], "review": [APPROVED]},
                     tasks=("01-a", "02-b"))
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok" and e.s.get("02-b", "result") == "ok"
    assert "lixo.txt" in notices(e, "dirty_tree")[0]["text"]
    clean = next((e.s.dir / "01-a" / "calls").glob("clean-*.prompt.md")).read_text()
    assert "lixo.txt" in clean
    assert e.s.get("01-a", "cycle") == 1  # arrumar não gasta ciclo
    assert "[ÁRVORE SUJA]" in e.s.journal_path.read_text()


async def test_arvore_continua_suja_bloqueia(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_DIRTY, {**CLEANUP, "_sh": "true"}],
                                "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "blocked"
    end = next(x for x in e.s.events() if x["type"] == "task_end")
    assert "lixo.txt" in end["reason"]
    assert "review" not in types(e)


async def test_tarefa_ok_sem_commit_gera_aviso(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [{**EXEC_OK, "_sh": "true", "commits": []}],
                                "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok"
    assert len(notices(e, "no_commits")) == 1
    assert "[SEM COMMIT]" in e.s.journal_path.read_text()


async def test_retomada_na_fase_de_arrumacao(tmp_path):
    slow_clean = {**CLEANUP, "_sleep": 30}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_DIRTY, slow_clean, CLEANUP], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    task = asyncio.create_task(e.run())
    for _ in range(200):
        await asyncio.sleep(0.02)
        if e.s.get("01-a", "phase") == "clean" and list((e.s.dir / "01-a" / "calls").glob("clean-*.prompt.md")):
            break
    assert e.s.get("01-a", "phase") == "clean"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert e2.s.get("01-a", "result") == "ok"
    assert [x["cycle"] for x in e2.s.events() if x["type"] == "exec"] == [1, 1]  # execução + arrumação retomada


# --- custo por tarefa e por papel -----------------------------------------------------------------------------------
async def test_custo_por_tarefa_e_por_papel(tmp_path):
    plan_q = {"summary": "s", "questions": [Q]}
    cfg = make_queue(tmp_path, {"plan": [plan_q, PLAN], "execute": [EXEC_OK], "review": [APPROVED],
                                "voter:vote": [vote("a")]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    # o fake custa US$ 0,01 por chamada: plano + atualização do plano + revisão; 3 votos unânimes; 1 execução
    by = e.s.cost_by()["01-a"]
    assert by == {"planner": 0.03, "voter": 0.03, "executor": 0.01}
    assert e.s.cost() == 0.08  # + o resumo final, fora de tarefa
    end = next(x for x in e.s.events() if x["type"] == "task_end")
    assert end["cost"] == by
    md = (e.s.dir / "01-a" / "report.md").read_text()
    assert "planejador US$ 0.03" in md and "conselho US$ 0.03" in md and "executor US$ 0.01" in md


# --- relatórios -----------------------------------------------------------------------------------------------------
async def test_relatorio_por_tarefa_e_journal_como_resumo(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}, tasks=("01-a", "02-b"))
    e = engine(tmp_path, cfg)
    assert await e.run()
    rep = (e.s.dir / "01-a" / "report.md").read_text()
    assert "## Entrega" in rep and "a.txt" in rep and "1 file changed" in rep
    assert "### Plano" in rep and "Criar a.txt." in rep
    assert "(plan.md)" in rep and "(01-a/plan.md)" not in rep  # link relativo à pasta da tarefa
    end = next(x for x in e.s.events() if x["type"] == "task_end")
    assert len(end["delivery"]["commits"]) == 1
    assert end["delivery"]["numstat"].endswith("\ta.txt")  # +/- por arquivo, para o painel
    assert (e.s.dir / "01-a" / "activity.log").read_text().count("\t") >= 1  # o histórico da tarefa
    md = e.s.journal_path.read_text()
    assert "(01-a/report.md)" in md and "(02-b/report.md)" in md
    assert "### Plano" not in md  # o detalhe fica no report


async def test_resumo_llm_no_fim(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED],
                                "summary": [{"narrative": "A fila criou a.txt ([01-a](01-a/report.md))."}]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    md = e.s.journal_path.read_text()
    assert "## O que foi entregue" in md and "A fila criou a.txt" in md
    req = e.harness("fake").calls[-1]
    assert req.role.name == "planner" and req.read_only
    base = next(x for x in e.s.events() if x["type"] == "task_start")["base"]
    assert base in req.prompt and str(e.s.dir) in req.prompt
    assert types(e)[-2:] == ["run_summary", "run_end"]


async def test_resumo_llm_desligado(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                     extra_toml="[report]\nllm_summary = false\n")
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert "run_summary" not in types(e)


async def test_subagent_em_background_morto_retoma_a_sessao_uma_vez(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [{"_error": "background_killed"}, EXEC_OK],
                                "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "result") == "ok"
    execs = [c for c in e.harness("fake").calls if c.name.startswith("exec-")]
    assert len(execs) == 2 and execs[1].resume and "subagent em background" in execs[1].prompt
    assert any(x.get("kind") == "background_killed" for x in e.s.events() if x["type"] == "notice")


async def test_subagent_em_background_morto_duas_vezes_falha(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [{"_error": "background_killed"}], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "failed"
    assert len([c for c in e.harness("fake").calls if c.name.startswith("exec-")]) == 2


async def test_retry_do_takeover_leva_o_parecer_do_revisor_final(tmp_path):
    """A1: reprovado na revisão independente, o prompt do takeover seguinte traz esse parecer, não o antigo."""
    final = {**CHANGES, "summary": "revisor final reprovou",
             "issues": [{"severity": "alta", "where": "b.txt", "what": "faltou-o-b", "fix": "crie b"}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "planner:review": [CHANGES],
                                "reviewer:review": [final]})
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get("01-a", "result") == "failed"
    takeover = (e.s.dir / "01-a" / "takeover.prompt.md").read_text()
    assert "faltou-o-b" in takeover and "revisor final reprovou" in takeover
    assert "[alta] a.txt: x" not in takeover  # a reprovação do executor (ciclo 3) não é mais a última


async def test_tempo_ativo_no_task_end(tmp_path):
    """A2: active_s soma só as chamadas (aqui, a execução dorme 1,1 s) e nunca passa da parede."""
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [{**EXEC_OK, "_sleep": 1.1}], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    end = next(x for x in e.s.events() if x["type"] == "task_end")
    assert 1 <= end["active_s"] <= end["duration_s"]
    assert e.s.get("01-a", "active_since") is None
