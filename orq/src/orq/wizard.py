"""`orq new <atividade>`: cria <atividade>/orq/ com os modelos e abre o harness do papel wizard, em sessão
interativa, com a skill orq-setup. `orq check`: confere a fila antes de rodar."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config, harness as harness_mod
from .context import title
from .engine import render

BIN = {"claude": "claude", "codex": "codex", "opencode": "opencode"}
BIG_TASK = 6000


def scaffold(activity: Path, repo: Path) -> Path:
    """Cria <atividade>/orq/ com orq.toml e regras.md dos modelos (sem sobrescrever)."""
    q = activity / "orq"
    q.mkdir(parents=True, exist_ok=True)
    d = config.ORQ_HOME / "defaults"
    if not (q / "orq.toml").exists():
        shutil.copy(d / "orq.toml", q / "orq.toml")
    if not (q / "regras.md").exists():
        (q / "regras.md").write_text(render((d / "regras.md").read_text(), REPO=repo, ACTIVITY=activity))
    return q


def wizard_prompt(activity: Path, q: Path, cfg: config.Config) -> str:
    roles = "; ".join(f"{n}: {r.label()}" for n, r in cfg.roles.items() if n not in ("wizard", "operator"))
    exists = sorted(p.name for p in q.glob("[0-9]*.md"))
    state = (f"A fila já tem {len(exists)} tarefa(s) ({', '.join(exists)}): revise com o Victor em vez de começar do zero."
             if exists else "A fila ainda não tem tarefas.")
    return (f"Use a skill orq-setup para montar a fila do orq.\n\nAtividade (contexto): {activity}\nFila (destino): {q}\n"
            f"Repositório: {cfg.repo}\n{state}\nPadrão dos papéis (orq.toml global): {roles}.\n\n"
            "Comece lendo a pasta da atividade e as instruções do repositório; depois, uma pergunta por vez.")


def new(activity: Path, repo_flag: str | None = None) -> int:
    activity = activity.resolve()
    activity.mkdir(parents=True, exist_ok=True)
    repo = Path(repo_flag).resolve() if repo_flag else (config.git_toplevel(activity) or Path.cwd())
    q = scaffold(activity, repo)
    cfg = config.load(q, flags={"repo": str(repo) if repo_flag else None})
    role = cfg.roles["wizard"]
    h = harness_mod.make(role.harness, q)
    env = dict(os.environ)
    if role.harness == "claude":
        env["CLAUDE_CONFIG_DIR"] = cfg.account_dir(role.account)
    print(f"orq new: {q}\nwizard: {role.label()} (interativo). Ao sair, rode: orq check {activity}\n")
    rc = subprocess.call(h.interactive_argv(role, wizard_prompt(activity, q, cfg)), cwd=cfg.repo, env=env)
    if rc == 0 and any(q.glob("[0-9]*.md")):
        print()
        return check(activity)
    return rc


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def inspect(path: Path) -> Report:
    r = Report()
    q = config.resolve_queue_dir(path)
    try:
        cfg = config.load(q)
    except config.ConfigError as e:
        r.errors.append(f"config: {e}")
        return r
    tasks = sorted(q.glob("[0-9]*.md"))
    if not tasks:
        r.errors.append(f"nenhuma tarefa (NN-nome.md) em {q}")
    for t in tasks:
        body = t.read_text()
        if not body.strip():
            r.errors.append(f"{t.name} está vazia")
        elif len(body) > BIG_TASK:
            r.warnings.append(f"{t.name} tem {len(body)} caracteres: dividir para conquistar (duas tarefas?)")
        if "<…>" in body:
            r.warnings.append(f"{t.name} ainda tem marcador <…> do modelo")
    try:
        rules = cfg.rules_text()
        if "<branch>" in rules or "<o que" in rules or "<comandos" in rules:
            r.warnings.append("regras.md ainda tem marcadores <…> do modelo")
    except config.ConfigError as e:
        r.errors.append(str(e))
    if cfg.verify_command:
        r.info.append(f"verificação automática: `{cfg.verify_command}` (timeout {cfg.get('verify', 'timeout', default='30m')})")
    else:
        r.warnings.append("sem [verify] command: o revisor roda a suíte por conta própria a cada ciclo (caro). No orq.toml "
                          'da fila: [verify] command = "make test" (ou o comando curto que vale para toda tarefa)')
    for name, role in cfg.roles.items():
        if role.harness in BIN and not shutil.which(BIN[role.harness]):
            (r.errors if name != "wizard" else r.warnings).append(f"papel {name}: `{BIN[role.harness]}` não está no PATH")
    if not config.git_toplevel(cfg.repo):
        r.errors.append(f"{cfg.repo} não é um repositório git")
    else:
        rel = os.path.relpath(q, cfg.repo)
        if not rel.startswith(".."):
            ignored = subprocess.run(["git", "-C", str(cfg.repo), "check-ignore", "-q", rel]).returncode == 0
            if not ignored:
                r.warnings.append(f"a fila ({rel}) está dentro do repositório e não é ignorada pelo git: os arquivos "
                                  "dela (e runs/) sujam a árvore e bloqueiam a primeira tarefa")
        dirty = subprocess.run(["git", "-C", str(cfg.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        if dirty.strip():
            r.warnings.append("árvore suja agora: a primeira tarefa fica bloqueada se continuar assim")
        branch = subprocess.run(["git", "-C", str(cfg.repo), "branch", "--show-current"], capture_output=True,
                                text=True).stdout.strip()
        r.info.append(f"repositório {cfg.repo} · branch {branch or '(destacada)'}")
    for name in ("planner", "executor", "reviewer", "voter", "tiebreak"):
        role = cfg.roles[name]
        extra = f" ×{role.count}" if name == "voter" else ""
        r.info.append(f"{name}: {role.label()}{extra}" + (f" · conta {role.account}" if role.harness == "claude" else ""))
    r.info += [f"{t.stem} — {title(t)}" for t in tasks]
    return r


def check(path: Path) -> int:
    r = inspect(path)
    for line in r.info:
        print(f"  {line}")
    for w in r.warnings:
        print(f"AVISO  {w}")
    for e in r.errors:
        print(f"ERRO   {e}")
    if r.errors:
        print("fila com erro: corrija antes de rodar")
        return 1
    print(f"ok. Rode: orq run {path}")
    return 0
