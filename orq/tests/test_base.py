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
    assert "md \\| é melhor" in md
    assert md.count("## Run ") == 2


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
    assert [c["text"] for c in s.take_inbox()] == ["/note oi", "/pause"]
    assert s.take_inbox() == []
    s.add_cost(1.5); s.add_cost(0.25)
    assert s.top("cost") == 1.75
    assert "01-a começou" in (s.dir / "orq.log").read_text()
