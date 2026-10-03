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
  orq new <pasta> [--repo DIR]   cria <pasta>/orq/ e abre o wizard (sessão interativa com a skill orq-setup)
  orq check <pasta>              confere a fila antes de rodar
  orq run <pasta> [--repo DIR] [--account N] [--run-dir DIR] [--headless]
  orq resume <run-dir> [--account N] [--retry NN-tarefa]... [--headless]
  orq attach <run-dir>          reabre o painel (q desanexa; a execução continua)
  orq status <run-dir>
  orq send <run-dir> "/add …" | "/skip NN" | "/note …" | "/decision qid opção" | "/pause" | "/resume" | "/stop"
  orq decide "<pergunta>" --option id="rótulo: detalhe" --option id="…" [--context "…"] [--repo DIR]
  orq notify setup | test         ntfy no celular: cria o tópico (~/.config/orq/notify.toml) / manda um teste
  orq selftest

Sem --headless (e num terminal), o motor roda em segundo plano e o painel abre por cima.
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


def load_run_cfg(store: RunStore, args) -> config.Config:
    q = Path(store.top("queue"))
    raw = store.top("config")
    if raw:
        if getattr(args, "account", None):
            raw = config.deep_merge(raw, {"accounts": {"claude": {"default": str(args.account)}}})
        return config.from_raw(raw, q)
    # Runs anteriores ao snapshot: ao menos preserve o repo registrado no início.
    initial = next((e for e in store.events() if e["type"] == "run_start"), {})
    return config.load(q, flags={"repo": initial.get("repo"),
                                 "account": getattr(args, "account", None) or store.top("account")})


def run_engine(cfg: config.Config, store: RunStore, retries=(), resumed=False) -> int:
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

    try:
        with store.engine_lock(cfg.repo):
            known = {p.stem for p in cfg.queue_dir.glob("[0-9]*.md") if p.is_file()}
            if any(tid not in known for tid in retries):
                die("--retry exige o nome exato de uma tarefa existente")
            for tid in dict.fromkeys(retries):
                d = store.dir / tid
                archive = f"{tid}.tentativa-{datetime.now():%Y%m%d%H%M%S%f}"
                if d.exists():
                    d.rename(store.dir / archive)
                store.drop_task(tid)
                if (store.top("open_ask") or {}).get("task") == tid:
                    store.set_top("open_ask", None)
                store.set_top("active_calls", {k: v for k, v in store.top("active_calls", {}).items()
                                               if not k.startswith(tid + ":")})
                store.event("notice", {"kind": "retry", "task": tid, "archive": archive,
                                       "text": f"Tarefa {tid} recomeça do zero (orq resume --retry)."})
            store.set_top("config", cfg.raw)
            if resumed:
                store.set_top("control", {"paused": False, "stop": False})
                store.event("run_resume")
            store.pid_path.write_text(str(os.getpid()))
            try:
                return asyncio.run(main())
            finally:
                store.pid_path.unlink(missing_ok=True)
    except (RuntimeError, config.ConfigError) as exc:
        die(str(exc))


def engine_flags(args) -> list[str]:
    out = []
    for k in ("account", "repo"):
        if getattr(args, k, None):
            out += [f"--{k}", str(getattr(args, k))]
    for tid in getattr(args, "retry", None) or []:
        out += ["--retry", tid]
    if getattr(args, "cmd", None) == "resume":
        out += ["--resumed"]
    return out


def start(store: RunStore, cfg: config.Config, args) -> int:
    """Headless: o motor em primeiro plano. Senão: motor desanexado + painel."""
    if args.headless or not sys.stdout.isatty():
        store.echo = True
        return run_engine(cfg, store, getattr(args, "retry", None) or [], getattr(args, "cmd", None) == "resume")
    import subprocess
    import time
    with open(store.dir / "engine.out", "a") as out:
        subprocess.Popen([sys.executable, "-m", "orq.cli", "_engine", str(store.dir), *engine_flags(args)],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    for _ in range(50):
        if store.engine_alive():
            break
        time.sleep(0.1)
    else:
        ended = any(e["type"] == "run_end" or (e["type"] == "notice" and e.get("kind") in ("stopped", "interrupted"))
                    for e in store.events())
        if not ended:  # morreu ao subir (configuração, regras…): o erro está no engine.out, não no painel
            tail = (store.dir / "engine.out").read_text(errors="replace").strip().splitlines()[-8:]
            die("o motor não subiu" + (":\n  " + "\n  ".join(tail) if tail else f" (ver {store.dir / 'engine.out'})"))
    return attach(store)


def attach(store: RunStore) -> int:
    from .tui.app import run_tui
    run_tui(store.dir)
    if store.engine_alive():
        print(f"O motor segue em segundo plano. Reabra com: orq attach {store.dir}")
    else:
        print(f"Motor parado. journal: {store.journal_path}")
    return 0


def cmd_attach(args) -> int:
    store = RunStore(Path(args.run_dir))
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    return attach(store)


def cmd_engine(args) -> int:
    """Interno: o motor desanexado que o `orq run` sobe."""
    store = RunStore(Path(args.run_dir))
    return run_engine(load_run_cfg(store, args), store, args.retry or [], args.resumed)


def cmd_run(args) -> int:
    if not Path(args.queue).is_dir():
        die("informe a pasta da fila")
    queue_dir = config.resolve_queue_dir(args.queue)
    cfg = load_cfg(queue_dir, args)
    try:
        cfg.rules_text()  # falha aqui, antes de criar o run dir
    except config.ConfigError as e:
        die(str(e))
    run_dir = Path(args.run_dir) if args.run_dir else queue_dir / "runs" / datetime.now().strftime("%Y-%m-%d-%H%M")
    store = RunStore(run_dir)
    try:
        store.create(queue_dir, str(cfg.get("accounts", "claude", "default")))
    except FileExistsError as e:
        die(str(e))
    Engine(cfg, store).start_event()
    store.log(f"run dir: {store.dir}")
    return start(store, cfg, args)


def cmd_resume(args) -> int:
    store = RunStore(Path(args.run_dir))
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    if store.engine_alive():
        die(f"o motor desta execução ainda está rodando; use orq attach {store.dir}")
    cfg = load_run_cfg(store, args)
    return start(store, cfg, args)


def task_status_rows(store: RunStore, queue_dir: Path) -> list[tuple[str, str, str]]:
    tasks = store.state()["tasks"]
    rows = []
    for f in sorted(queue_dir.glob("[0-9]*.md")):
        st = tasks.get(f.stem, {})
        res = st.get("result") or (f"em andamento: {st.get('phase')}" if st.get("phase") else "pendente")
        rows.append((f.stem, res, f"ciclo {st['cycle']}" if st.get("cycle") else ""))
    return rows


def cmd_status(args) -> int:
    store = RunStore(Path(args.run_dir))
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    rows = task_status_rows(store, Path(store.top("queue")))
    w = max((len(r[0]) for r in rows), default=0)
    for tid, res, cyc in rows:
        print(f"{tid:<{w}}  {res:<28}  {cyc}")
    print(f"motor: {'rodando' if store.engine_alive() else 'parado'} · custo US$ {store.cost():.2f}"
          + (" (parcial: há tentativas com custo não informado)" if store.unknown_costs() else ""))
    print(f"journal: {store.journal_path}")
    return 0


def cmd_send(args) -> int:
    import time
    store = RunStore(Path(args.run_dir))
    if not store.exists():
        die(f"não é um run dir: {args.run_dir}")
    cmd = store.send(args.text, source="orq send")
    if not store.engine_alive():
        print("motor parado: o comando fica na caixa de entrada e vale no próximo orq resume")
        return 0
    for _ in range(50):
        ack = next((e for e in store.events() if e["type"] == "control_ack" and e.get("id") == cmd["id"]), None)
        if ack:
            print(("ok: " if ack["ok"] else "recusado: ") + ack["result"])
            return 0 if ack["ok"] else 1
        time.sleep(0.1)
    print("enviado; o motor ainda não respondeu (ver a timeline)")
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


def cmd_new(args) -> int:
    from . import wizard
    try:
        return wizard.new(Path(args.activity), args.repo)
    except config.ConfigError as e:
        die(str(e))


def cmd_check(args) -> int:
    from . import wizard
    if not Path(args.path).is_dir():
        die(f"pasta não existe: {args.path}")
    return wizard.check(Path(args.path))


def cmd_notify(args) -> int:
    from . import notify
    if args.action == "setup":
        cfg = notify.setup()
        print(f"tópico: {cfg['topic']} (servidor {cfg['server']})\n"
              "No app ntfy: + Subscribe to topic → cole o tópico (no Android, ligue Instant delivery).\n"
              f"Configuração em {notify.CONFIG}. Uma notificação de teste foi enviada.")
        return 0
    cfg = notify.load()
    if not cfg:
        die(f"sem {notify.CONFIG}: rode `orq notify setup`")
    ok = notify.publish(cfg, "orq · teste", "Notificação de teste do orq.")
    print("enviada" if ok else "falhou (confira a rede)")
    return 0 if ok else 1


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
    at = sub.add_parser("attach")
    at.add_argument("run_dir")
    en = sub.add_parser("_engine")
    en.add_argument("run_dir")
    en.add_argument("--account")
    en.add_argument("--repo")
    en.add_argument("--retry", action="append")
    en.add_argument("--resumed", action="store_true")
    st = sub.add_parser("status")
    st.add_argument("run_dir")
    d = sub.add_parser("decide")
    d.add_argument("question")
    d.add_argument("--option", action="append", default=[])
    d.add_argument("--context")
    d.add_argument("--repo")
    d.add_argument("--account")
    se = sub.add_parser("send")
    se.add_argument("run_dir")
    se.add_argument("text")
    nw = sub.add_parser("new")
    nw.add_argument("activity")
    nw.add_argument("--repo")
    ck = sub.add_parser("check")
    ck.add_argument("path")
    nt = sub.add_parser("notify")
    nt.add_argument("action", choices=["setup", "test"])
    sub.add_parser("selftest")
    args = p.parse_args(argv)
    handlers = {"run": cmd_run, "resume": cmd_resume, "status": cmd_status, "send": cmd_send, "attach": cmd_attach, "_engine": cmd_engine, "decide": cmd_decide, "new": cmd_new, "check": cmd_check, "notify": cmd_notify,
                "selftest": cmd_selftest}
    if args.cmd not in handlers:
        print(USAGE, end="")
        return 0 if args.cmd is None else 1
    return handlers[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
