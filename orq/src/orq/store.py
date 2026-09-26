"""Run dir: a única interface entre o motor e o painel.

  events.jsonl  motor → painel: um evento por linha (fonte do journal.md e da timeline)
  state.json    fase, ciclo e sessões de cada tarefa (o que o `resume` lê)
  stream.log    o stream normalizado dos harnesses (metade direita do painel)
  orq.log       o log corrido: linhas de evento + stream
  inbox.jsonl   painel → motor: um comando por linha
  engine.pid    pid do motor enquanto roda
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import journal


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


@contextmanager
def locked(path: Path):
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # linha no meio da escrita
    return out


class RunStore:
    def __init__(self, run_dir: Path, echo: bool = False):
        self.dir = Path(run_dir).resolve()
        self.echo = echo  # headless: log também no stderr
        self.events_path = self.dir / "events.jsonl"
        self.state_path = self.dir / "state.json"
        self.stream_path = self.dir / "stream.log"
        self.log_path = self.dir / "orq.log"
        self.inbox_path = self.dir / "inbox.jsonl"
        self.pid_path = self.dir / "engine.pid"
        self.journal_path = self.dir / "journal.md"
        self.notes_path = self.dir / "notes.md"
        self.lock_path = self.dir / "events.lock"

    # --- criação ---------------------------------------------------------------------------------
    def create(self, queue_dir: Path, account: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            raise FileExistsError(f"{self.dir} já tem uma execução; use orq resume")
        write_atomic(self.state_path, json.dumps(
            {"queue": str(queue_dir), "account": account, "tasks": {}, "inbox_offset": 0, "cost": 0.0}, indent=1))
        self.events_path.write_text("")

    def exists(self) -> bool:
        return self.state_path.is_file()

    # --- log e stream -----------------------------------------------------------------------------
    def log(self, msg: str) -> None:
        line = f"{datetime.now():%F %T} {msg}"
        if self.echo:
            print(line, file=sys.stderr, flush=True)
        with open(self.log_path, "a") as fh:
            fh.write(line + "\n")

    def stream(self, line: str) -> None:
        if self.echo:
            print(line, file=sys.stderr, flush=True)
        with open(self.stream_path, "a") as fh:
            fh.write(line + "\n")
        with open(self.log_path, "a") as fh:
            fh.write(line + "\n")

    # --- eventos ----------------------------------------------------------------------------------
    def event(self, type_: str, data: dict | None = None) -> dict:
        ev = {**(data or {}), "type": type_, "ts": now_iso()}
        line = journal.event_line(ev)
        if line:
            self.log(line)
        with locked(self.lock_path):
            with open(self.events_path, "a") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            try:
                write_atomic(self.journal_path, journal.render(self.events()))
            except Exception as exc:  # o jsonl continua intacto; o journal é derivado
                self.log(f"aviso: falha ao renderizar o journal: {exc}")
        return ev

    def notice(self, kind: str, text: str, task: str = "") -> None:
        self.event("notice", {"task": task, "kind": kind, "text": text})

    def events(self) -> list[dict]:
        return read_jsonl(self.events_path)

    # --- estado -----------------------------------------------------------------------------------
    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def _save(self, st: dict) -> None:
        write_atomic(self.state_path, json.dumps(st, indent=1, ensure_ascii=False))

    def get(self, task: str, key: str, default=None):
        v = self.state()["tasks"].get(task, {}).get(key)
        return default if v in (None, "") else v

    def set(self, task: str, key: str, value) -> None:
        st = self.state()
        st["tasks"].setdefault(task, {})[key] = value
        self._save(st)

    def top(self, key: str, default=None):
        return self.state().get(key, default)

    def set_top(self, key: str, value) -> None:
        st = self.state()
        st[key] = value
        self._save(st)

    def drop_task(self, task: str) -> None:
        st = self.state()
        st["tasks"].pop(task, None)
        self._save(st)

    def cost(self) -> float:
        st = self.state()
        if "cost" not in st and (self.dir / "cost").exists():  # run do orq em bash
            return float((self.dir / "cost").read_text() or 0)
        return float(st.get("cost", 0) or 0)

    def add_cost(self, usd: float) -> None:
        with locked(self.lock_path):
            st = self.state()
            st["cost"] = round(float(st.get("cost", 0)) + float(usd or 0), 4)
            self._save(st)

    # --- inbox ------------------------------------------------------------------------------------
    def send(self, text: str, source: str = "painel") -> dict:
        cmd = {"id": f"{time.time_ns():x}", "ts": now_iso(), "text": text, "source": source}
        with locked(self.inbox_path.with_suffix(".lock")):
            with open(self.inbox_path, "a") as fh:
                fh.write(json.dumps(cmd, ensure_ascii=False) + "\n")
        return cmd

    def take_inbox(self) -> list[dict]:
        """Comandos ainda não lidos; avança o offset em state.json."""
        cmds = read_jsonl(self.inbox_path)
        off = int(self.top("inbox_offset", 0))
        if off < len(cmds):
            self.set_top("inbox_offset", len(cmds))
        return cmds[off:]

    # --- processo ---------------------------------------------------------------------------------
    def engine_alive(self) -> bool:
        try:
            pid = int(self.pid_path.read_text())
            os.kill(pid, 0)
            return True
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False
