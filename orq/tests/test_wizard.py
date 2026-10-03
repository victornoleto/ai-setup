import subprocess

from orq import wizard

from .test_engine import ROLES_FAKE


def repo_with_activity(tmp_path, ignore=True):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if ignore:
        (repo / ".gitignore").write_text("/docs/.local/\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i",
                    "--allow-empty"], check=True)
    act = repo / "docs/.local/specs/mod/card"
    act.mkdir(parents=True)
    (act / "notion.md").write_text("# Card\n")
    return repo, act


def test_scaffold_e_check(tmp_path, capsys):
    repo, act = repo_with_activity(tmp_path)
    q = wizard.scaffold(act, repo)
    assert (q / "orq.toml").exists() and f"`{repo}`" in (q / "regras.md").read_text()
    (q / "orq.toml").write_text(ROLES_FAKE + '[run]\nrules_file = "regras.md"\n')
    r = wizard.inspect(act)
    assert "nenhuma tarefa (NN-nome.md) em" in r.errors[0]
    assert any("marcadores" in w for w in r.warnings)
    (q / "01-a.md").write_text("Faça A. Pronto quando: A existe.")
    (q / "02-b.md").write_text("x" * 7000)
    r = wizard.inspect(act)
    assert not r.errors
    assert any("02-b.md tem 7000" in w for w in r.warnings)
    assert any(w.startswith("02-b.md não diz quando está pronta") for w in r.warnings)
    assert not any(w.startswith("01-a.md não diz") for w in r.warnings)
    (q / "regras.md").write_text("- Branch: `feat/x`. Confira.\n")
    r = wizard.inspect(act)
    assert any("pede a branch `feat/x`" in w for w in r.warnings) and not any("marcadores" in w for w in r.warnings)
    current = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    (q / "regras.md").write_text(f"- Branch: `{current}`.\n")
    assert not any("pede a branch" in w for w in wizard.inspect(act).warnings)
    assert not any("não é ignorada" in w for w in r.warnings)
    assert any(line.startswith("01-a — Faça A.") for line in r.info)
    assert any(w.startswith("sem [verify] command") for w in r.warnings)
    assert wizard.check(act) == 0 and "orq run" in capsys.readouterr().out
    (q / "orq.toml").write_text(ROLES_FAKE + '[run]\nrules_file = "regras.md"\n[verify]\ncommand = "make test"\n')
    r = wizard.inspect(act)
    assert not any("[verify]" in w for w in r.warnings)
    assert any(line.startswith("verificação automática: `make test`") for line in r.info)


def test_fila_nao_ignorada_avisa(tmp_path):
    repo, act = repo_with_activity(tmp_path, ignore=False)
    q = wizard.scaffold(act, repo)
    (q / "orq.toml").write_text(ROLES_FAKE)
    (q / "01-a.md").write_text("a")
    assert any("não é ignorada" in w for w in wizard.inspect(act).warnings)


def test_new_abre_o_wizard(tmp_path, monkeypatch, capfd):
    repo, act = repo_with_activity(tmp_path)
    q = act / "orq"
    q.mkdir()
    (q / "orq.toml").write_text(ROLES_FAKE)  # o harness fake só imprime o prompt
    assert wizard.new(act) == 0
    out = capfd.readouterr().out
    assert "Use a skill orq-setup" in out and f"Fila (destino): {q}" in out and "ainda não tem tarefas" in out
    assert (q / "regras.md").exists()
