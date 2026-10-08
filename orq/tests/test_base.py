import subprocess
from pathlib import Path

import pytest

from orq import config, journal
from orq.store import RunStore, read_jsonl

from .conftest import FIXTURES


def test_journal_igual_ao_do_jq():
    ev = read_jsonl(FIXTURES / "events.jsonl")
    assert journal.render(ev) == (FIXTURES / "journal.expected.md").read_text()


def test_journal_etiquetas():
    md = journal.render(read_jsonl(FIXTURES / "events.jsonl"))
    assert md.count("- **[FALHOU]** [02-dificil]") == 1
    assert "DECISÃO 2,5 pts" in md
    assert md.count("### [0") == 2  # uma entrada curta por tarefa, com link para o report
    ev = read_jsonl(FIXTURES / "events.jsonl")
    assert any("md \\| é melhor" in journal.render_task(ev, t) for t in ("01-hello", "02-dificil"))
    assert journal.render_task(ev, "02-dificil").startswith("# 02-dificil — **FALHOU**")


def test_event_line_sem_cor():
    ev = read_jsonl(FIXTURES / "events.jsonl")
    lines = [journal.event_line(e) for e in ev]
    assert any(l and l.startswith("[DECISÃO 2 pts]") for l in lines)
    assert any(l and l.startswith("✗ 02-dificil terminou: FALHOU") for l in lines)


@pytest.mark.parametrize("v,s", [("4h", 14400), ("30m", 1800), ("90s", 90), ("120", 120)])
def test_duracao(v, s):
    assert config.parse_duration(v) == s


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_queue_conf_legado(tmp_path):
    q = _repo(tmp_path) / "fila"
    q.mkdir()
    (q / "01-a.md").write_text("x")
    (q / "regras.md").write_text("regra")
    (q / "queue.conf").write_text('# c\nORQ_RULES_FILE=regras.md\nORQ_ACCOUNT=1\nORQ_EXECUTOR_MODEL="claude-x"\nORQ_VOTERS=5\n')
    c = config.load(q)
    assert c.rules_text() == "regra"
    assert c.roles["planner"].account == "1"
    assert c.roles["executor"].model == "claude-x"
    assert c.voters == 5
    assert c.repo == tmp_path.resolve()


def test_camadas_toml_env_flag(tmp_path, monkeypatch):
    act = _repo(tmp_path) / "atividade"
    (act / "orq").mkdir(parents=True)
    (act / "orq" / "orq.toml").write_text('[roles.executor]\nharness = "codex"\nmodel = "gpt-x"\n')
    q = config.resolve_queue_dir(act)
    assert q == act / "orq"
    monkeypatch.setenv("ORQ_MAX_CYCLES", "7")
    c = config.load(q, flags={"account": "1"})
    assert c.roles["executor"].harness == "codex" and c.roles["executor"].effort == "high"
    assert c.max_cycles == 7
    assert c.roles["planner"].account == "1"


def test_atividade_com_documentos_numerados_usa_a_fila_orq(tmp_path):
    act = tmp_path / "atividade"
    (act / "orq").mkdir(parents=True)
    (act / "00-contexto.md").write_text("doc da atividade, não é tarefa")
    (act / "orq" / "orq.toml").write_text("")
    (act / "orq" / "01-tarefa.md").write_text("tarefa")
    assert config.resolve_queue_dir(act) == act / "orq"
    assert config.resolve_queue_dir(act / "orq") == act / "orq"


def test_harness_invalido(tmp_path):
    (tmp_path / "orq.toml").write_text('[roles.voter]\nharness = "gpt"\n')
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_store_evento_estado_inbox(tmp_path):
    s = RunStore(tmp_path / "run")
    s.create(tmp_path, "2")
    s.event("run_start", {"queue": "q", "repo": "/r", "max_cycles": 3})
    s.event("task_start", {"task": "01-a", "base": "abc", "task_file": "f"})
    assert (s.dir / "journal.md").read_text().startswith("# orq — q")
    s.set("01-a", "phase", "plan")
    assert s.get("01-a", "phase") == "plan" and s.get("01-a", "x", "d") == "d"
    s.send("/note oi")
    s.send("/pause")
    pending = s.take_inbox()
    assert [c["text"] for c in pending] == ["/note oi", "/pause"]
    for cmd in pending:
        s.ack_inbox(cmd)
    assert s.take_inbox() == []
    s.add_cost(1.5); s.add_cost(0.25)
    assert s.top("cost") == 1.75
    assert "01-a começou" in (s.dir / "orq.log").read_text()


def test_intervencao_padrao(tmp_path):
    (tmp_path / "orq.toml").write_text("")
    c = config.load(tmp_path)
    assert c.intervene is True
    assert c.intervene_seconds("decision_timeout") == 3600 and c.intervene_seconds("reminder") == 7200
    (tmp_path / "orq.toml").write_text('[intervene]\nenabled = false\ndecision_timeout = "5s"\n')
    c = config.load(tmp_path)
    assert c.intervene is False and c.intervene_seconds("decision_timeout") == 5
    assert journal.RESULT_LABEL["ok_victor"] == "**ok (aceita pelo Victor)**"


def test_linhas_da_intervencao():
    ask = {"type": "ask", "ts": "2026-09-26T10:00:00-03:00", "id": "q1", "task": "04-x", "kind": "blocked",
           "question": "E agora?", "diagnosis": "d", "options": [{"id": "1", "label": "Tentar"}], "recommended": "1"}
    ans = {"type": "ask_answer", "ts": "2026-09-26T10:05:00-03:00", "id": "q1", "task": "04-x", "kind": "blocked",
           "question": "E agora?", "action": "retry", "note": "use Y", "answer": "1"}
    rep = {"type": "ask_reply", "ts": "2026-09-26T10:03:00-03:00", "id": "q1", "task": "04-x", "text": "Falta X."}
    assert journal.event_line(ask) == "[PRECISA DE VOCÊ] 04-x: E agora?"
    assert journal.event_line(ans) == "[INTERVENÇÃO] 04-x: retry — use Y"
    assert journal.event_line(rep) == "[OPERADOR] 04-x: Falta X."
    assert journal.event_line({**ans, "kind": "council"}) is None  # o evento decision já conta
    md = journal.render([{"type": "run_start", "ts": ask["ts"]}, ask, ans])
    assert "- **[INTERVENÇÃO]** [04-x](04-x/report.md) — E agora? → retry: use Y" in md
    task = journal.render_task([ask, rep, ans], "04-x")
    assert "### Pergunta ao Victor" in task and "**← recomendada**" in task and "**Resposta do Victor:** 1" in task


def test_stream_com_horario_e_historico_da_tarefa(tmp_path):
    import re
    s = RunStore(tmp_path / "run")
    s.create(tmp_path, "2")
    s.stream("  [plan] › $ ls")
    s.stream("  [exec-1] texto", task="01-a")
    s.log("exec-1: claude · m", task="01-a")
    lines = s.stream_path.read_text().splitlines()
    assert re.fullmatch(r"── \d\d/\d\d/\d{4} ──", lines[0])  # 1ª linha do processo: a data
    assert re.fullmatch(r"\d\d:\d\d:\d\d   \[plan\] › \$ ls", lines[1]) and len(lines) == 3
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d   \[exec-1\] texto$", s.log_path.read_text(), re.M)
    act = (s.dir / "01-a" / "activity.log").read_text().splitlines()
    assert [a.split("\t", 2)[1:] for a in act] == [["0", "  [exec-1] texto"], ["0", "exec-1: claude · m"]]
    s.event("task_start", {"task": "01-a", "base": "abc", "task_file": "f"})
    s.stream("  [exec-1] depois", task="01-a")
    assert (s.dir / "01-a" / "activity.log").read_text().splitlines()[-1].split("\t")[1] == "1"
    assert act[0].split("\t")[0][:4].isdigit() and "T" in act[0].split("\t")[0]
    assert not (s.dir / "plan").exists()
