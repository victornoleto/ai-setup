"""orq — fila de tarefas para agentes de código. Documentação: ~/.ai-setup/orq/README.md"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import config
from .engine import Engine, Task
from .harness.base import kill_all
from .store import RunStore

USAGE = """\
Uso:
  orq run <pasta> [--repo DIR] [--account N] [--run-dir DIR] [--headless]
  orq resume <run-dir> [--account N] [--retry NN-tarefa]... [--headless]
  orq status <run-dir>
  orq decide "<pergunta>" --option id="rótulo: detalhe" --option id="…" [--context "…"] [--repo DIR]
  orq selftest

<pasta>: a pasta da atividade (com orq/ dentro) ou a própria fila (NN-nome.md + orq.toml ou queue.conf).
"""


def die(msg: str) -> None:
    print(f"orq: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_cfg(queue_dir: Path, args) -> config.Config:
    try:
        return config.load(queue_dir, flags={"account": getattr(args, "account", None), "repo": getattr(args, "repo", None)})
    except config.ConfigError as e:
        die(str(e))


def run_engine(cfg: config.Config, store: RunStore) -> int:
    """O motor em primeiro plano: roda a fila até o fim ou até um sinal."""
    async def main() -> int:
        eng = Engine(cfg, store)
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
        try:
            return 0 if await eng.run() else 1
        except asyncio.CancelledError:
            kill_all()
            store.notice("interrupted", f"Execução interrompida (sinal). Continue com: orq resume {store.dir}")
            return 130

    store.pid_path.write_text(str(os.getpid()))
    try:
        return asyncio.run(main())
    finally:
        store.pid_path.unlink(missing_ok=True)


def cmd_run(args) -> int:
    if not Path(args.queue).is_dir():
        die("informe a pasta da fila")
    queue_dir = config.resolve_queue_dir(args.queue)
    cfg = load_cfg(queue_dir, args)
    run_dir = Path(args.run_dir) if args.run_dir else queue_dir / "runs" / datetime.now().strftime("%Y-%m-%d-%H%M")
    store = RunStore(run_dir, echo=True)
    try:
        store.create(queue_dir, str(cfg.get("accounts", "claude", "default")))
    except FileExistsError as e:
        die(str(e))
    Engine(cfg, store).start_event()
    store.log(f"run dir: {store.dir}")
    return run_engine(cfg, store)


def cmd_resume(args) -> int:
    store = RunStore(Path(args.run_dir), echo=True)
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    for tid in args.retry or []:
        # a tarefa recomeça do zero (o que ela já commitou fica; o plano novo parte do HEAD atual)
        store.drop_task(tid)
        d = store.dir / tid
        if d.exists():
            d.rename(store.dir / f"{tid}.tentativa-{datetime.now():%H%M%S}")
        store.notice("retry", f"Tarefa {tid} recomeça do zero (orq resume --retry).", tid)
    cfg = load_cfg(Path(store.top("queue")), args)
    store.notice("resumed", "Execução retomada.")
    return run_engine(cfg, store)


def task_status_rows(store: RunStore, queue_dir: Path) -> list[tuple[str, str, str]]:
    tasks = store.state()["tasks"]
    rows = []
    for f in sorted(queue_dir.glob("[0-9]*.md")):
        st = tasks.get(f.stem, {})
        res = st.get("result") or (f"em andamento: {st.get('phase')}" if st.get("phase") else "pendente")
        rows.append((f.stem, res, f"ciclo {st.get('cycle', 1)}" if st else ""))
    return rows


def cmd_status(args) -> int:
    store = RunStore(Path(args.run_dir))
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    rows = task_status_rows(store, Path(store.top("queue")))
    w = max((len(r[0]) for r in rows), default=0)
    for tid, res, cyc in rows:
        print(f"{tid:<{w}}  {res:<28}  {cyc}")
    print(f"motor: {'rodando' if store.engine_alive() else 'parado'} · custo US$ {store.top('cost', 0):.2f}")
    print(f"journal: {store.journal_path}")
    return 0


def cmd_decide(args) -> int:
    if not args.question or len(args.option) < 2:
        die('uso: orq decide "<pergunta>" --option a="…" --option b="…"')
    cfg = load_cfg(Path.cwd(), args)
    store = RunStore(Path(tempfile.mkdtemp(prefix="orq-decide-")))
    store.create(Path.cwd(), str(cfg.get("accounts", "claude", "default")))
    options = []
    for o in args.option:
        oid, _, rest = o.partition("=")
        options.append({"id": oid, "label": rest.split(":")[0], "detail": rest})
    q = {"id": "decide", "question": args.question, "context": args.context or "(sem contexto)", "options": options}
    eng = Engine(cfg, store)
    eng.rules = "(nenhuma)"
    d = store.dir / "decide"
    d.mkdir()
    t = Task(id="decide", file=d, dir=d, text="(decisão avulsa)", plan_file=Path("(nenhum)"), decisions_file=d / "decisions.md")
    r = cfg.roles
    store.event("run_start", {"queue": "decide", "repo": str(cfg.repo), "account": r["voter"].account, "planner": "-",
                              "executor": "-", "voter": r["voter"].label(), "tiebreak": r["tiebreak"].label(),
                              "voters": cfg.voters, "max_cycles": 0})
    from . import council
    ans = asyncio.run(council.decide(eng, t, "linha de comando", q))
    print(ans or "o conselho não decidiu")
    print(f"detalhes: {store.journal_path}", file=sys.stderr)
    return 0 if ans else 1


def cmd_selftest(args) -> int:
    import subprocess
    return subprocess.call([sys.executable, "-m", "pytest", "-q", str(config.ORQ_HOME / "tests")])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orq", usage=USAGE, add_help=False)
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("queue")
    r.add_argument("--repo")
    r.add_argument("--account")
    r.add_argument("--run-dir")
    r.add_argument("--headless", action="store_true")
    rs = sub.add_parser("resume")
    rs.add_argument("run_dir")
    rs.add_argument("--account")
    rs.add_argument("--retry", action="append")
    rs.add_argument("--headless", action="store_true")
    st = sub.add_parser("status")
    st.add_argument("run_dir")
    d = sub.add_parser("decide")
    d.add_argument("question")
    d.add_argument("--option", action="append", default=[])
    d.add_argument("--context")
    d.add_argument("--repo")
    d.add_argument("--account")
    sub.add_parser("selftest")
    args = p.parse_args(argv)
    handlers = {"run": cmd_run, "resume": cmd_resume, "status": cmd_status, "decide": cmd_decide,
                "selftest": cmd_selftest}
    if args.cmd not in handlers:
        print(USAGE, end="")
        return 0 if args.cmd is None else 1
    return handlers[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
