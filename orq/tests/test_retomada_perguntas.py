"""Parar com pergunta do conselho aberta não pode refazer a chamada que perguntou (executor ou revisor)."""
import asyncio
import json

import pytest

from orq.engine import Engine
from orq.store import RunStore

from .test_engine import APPROVED, EXEC_OK, PLAN, Q, engine, make_queue, vote

LENTO = {**vote("c"), "_sleep": 30}


async def _interrompe_no_conselho(e):
    task = asyncio.create_task(e.run())
    for _ in range(300):
        await asyncio.sleep(0.02)
        if any((e.s.dir / "01-a").glob("council/*")):
            break
    else:
        pytest.fail("o conselho não começou")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def _chamadas(e) -> dict:
    return json.loads((e.s.dir / "fake-counts.json").read_text())


async def test_retomada_com_duvida_do_executor_aberta_nao_reexecuta(tmp_path):
    ask = {**EXEC_OK, "_sh": "true", "status": "needs_decision", "commits": [], "questions": [Q]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [ask, EXEC_OK], "review": [APPROVED],
                                "voter:vote": [LENTO, vote("c")]})
    e = engine(tmp_path, cfg)
    await _interrompe_no_conselho(e)
    assert _chamadas(e)["execute"] == 1
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert _chamadas(e2)["execute"] == 2  # a pergunta e, depois da resposta, a execução: nada refeito
    assert any(x["type"] == "decision" for x in e2.s.events())
    assert list((e2.s.dir / "01-a").glob("exec_answers-*.prompt.md"))


async def test_retomada_com_duvida_do_revisor_aberta_nao_revisa_de_novo(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [{**APPROVED, "questions": [Q]}],
                                "voter:vote": [LENTO, vote("c")]})
    e = engine(tmp_path, cfg)
    await _interrompe_no_conselho(e)
    e2 = Engine(cfg, RunStore(e.s.dir))
    assert await e2.run()
    assert _chamadas(e2)["review"] == 1
    assert e2.s.get("01-a", "result") == "ok"


async def test_pergunta_ja_decidida_nao_volta_ao_conselho_na_retomada(tmp_path):
    ask = {**EXEC_OK, "_sh": "true", "status": "needs_decision", "commits": [], "questions": [Q]}
    # a pergunta já foi feita antes da parada; sem votantes no script: voltar ao conselho falharia
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]})
    e = engine(tmp_path, cfg)
    e.s.update_task("01-a", {"phase": "exec_questions", "cycle": 1, "base": "none", "decision_rounds": 1,
                             "partial_answers": {"nome": "- **Nome?** → `c` — C (conselho, 3 pontos)."}})
    (e.s.dir / "01-a").mkdir()
    (e.s.dir / "01-a" / "exec-1.out.json").write_text(json.dumps(ask))
    assert await e.run()
    assert not any(x["type"] == "decision" for x in e.s.events())
    assert "`c` — C" in next((e.s.dir / "01-a").glob("exec_answers-*.prompt.md")).read_text()


async def test_aprovada_com_problema_alto_vira_reprovada(tmp_path):
    torta = {**APPROVED, "issues": [{"severity": "alta", "where": "a.txt", "what": "x", "fix": "y"}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [torta, APPROVED]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert e.s.get("01-a", "cycle") == 2
