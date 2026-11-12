"""O que o dono lê para validar: journal, report por tarefa, `orq review` e `orq status`."""
from orq import cli, journal

from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue

VALIDA = {**APPROVED, "validation": ["Abra a.txt: deve ter a linha `a`."], "highlights": ["a.txt cresce a cada ciclo"]}
TS = "2026-11-12T10:00:00-03:00"


def _ev(type_, **kv):
    return {"type": type_, "ts": TS, **kv}


def _eventos_com_ruido():
    return [
        _ev("run_start", queue="q", repo="/r", max_cycles=3),
        _ev("task_start", task="01-a", repo="/r", base="abc", task_file="/q/01-a.md"),
        _ev("notice", kind="paused", text="Execução pausada."),
        _ev("notice", kind="resumed", text="Execução retomada."),
        _ev("notice", kind="limit_wait", text="Limite de uso; esperando 10 min.", task="01-a"),
        _ev("notice", kind="error", text="exec-1 falhou (transient): 529", task="01-a"),
        _ev("notice", kind="no_commits", text="A tarefa terminou ok sem nenhum commit.", task="01-a"),
        _ev("task_end", task="01-a", repo="/r", result="ok", reason="Aprovada.", duration_s=60, cycles=1, delivery={}),
        _ev("task_start", task="02-b", repo="/r", base="abc", task_file="/q/02-b.md"),
        _ev("notice", kind="error", text="plan falhou (fatal): boom", task="02-b"),
        _ev("task_end", task="02-b", repo="/r", result="failed", reason="O planejamento falhou.", duration_s=5, cycles=1,
            delivery={}),
    ]


def test_leia_primeiro_so_tem_o_que_pede_acao():
    md = journal.render(_eventos_com_ruido())
    topo, operacao = md.split("## Operação")
    leia = topo.split("## Leia primeiro")[1].split("## Resumo")[0]
    assert "SEM COMMIT" in leia and "boom" in leia          # exige conferência; erro de tarefa que falhou
    for ruido in ("pausada", "retomada", "esperando 10 min", "529"):  # erro superado: a tarefa terminou ok
        assert ruido not in leia and ruido in operacao


async def test_report_da_tarefa_abre_com_entrega_e_como_validar(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [VALIDA]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    report = (e.s.dir / "01-a" / "report.md").read_text()
    pos = [report.index(h) for h in ("## Entrega", "## Como validar", "## Destaques da revisão", "## Histórico")]
    assert pos == sorted(pos)
    assert "Abra a.txt: deve ter a linha `a`." in report
    assert "Abra a.txt" in e.s.journal_path.read_text()


async def test_orq_review_lista_o_que_conferir(tmp_path, capsys):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [VALIDA]})
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert cli.main(["review", str(e.s.dir)]) == 0
    out = capsys.readouterr().out
    assert "01-a" in out and "1 commit" in out
    assert "Abra a.txt: deve ter a linha `a`." in out
    assert f"git -C {cfg.repo} diff" in out


def test_orq_status_mostra_a_pergunta_aberta(tmp_path, capsys):
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    e.s.set_top("open_ask", {"id": "ab12cd34", "task": "01-a", "kind": "failed", "question": "Refazer ou pular?",
                             "diagnosis": "O plano falhou.", "recommended": "retry",
                             "options": [{"id": "retry", "label": "Refazer"}, {"id": "skip", "label": "Pular"}]})
    assert cli.main(["status", str(e.s.dir)]) == 0
    out = capsys.readouterr().out
    assert "Refazer ou pular?" in out and "1. Refazer (recomendada)" in out and "2. Pular" in out
    assert f'orq send {e.s.dir} "/answer ab12cd34 1"' in out
