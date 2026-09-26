import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from orq import config, council
from orq.engine import Engine, block_push_env, reset_wait
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


def make_queue(tmp_path: Path, script: dict, tasks=("01-a",), extra_toml: str = "") -> config.Config:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    q = tmp_path / "fila"
    q.mkdir()
    for t in tasks:
        (q / f"{t}.md").write_text(f"Tarefa {t}")
    (q / "script.json").write_text(json.dumps(script))
    (q / "orq.toml").write_text(f'{ROLES_FAKE}\n[run]\nrepo = "{repo}"\n{extra_toml}')
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
