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
import subprocess
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
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
    for line in path.read_text().splitlines(keepends=True):
        if line.endswith("\n") and line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # linha no meio da escrita
    return out


def active_seconds(task_state: dict, now: float | None = None) -> float:
    """Tempo ativo acumulado de uma tarefa, incluindo a chamada em curso."""
    total = float(task_state.get("active_s") or 0)
    since = task_state.get("active_since")
    return total + (max(0.0, (now or time.time()) - float(since)) if since else 0.0)


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
        self._state_stamp = None
        self._state_cache = None
        self._event_stamp = None
        self._event_pos = 0
        self._event_cache = []

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
                evs = self.events()
                write_atomic(self.journal_path, journal.render(evs))
                if ev.get("task") and (self.dir / ev["task"]).is_dir():
                    write_atomic(self.dir / ev["task"] / "report.md", journal.render_task(evs, ev["task"]))
            except Exception as exc:  # o jsonl continua intacto; o journal é derivado
                self.log(f"aviso: falha ao renderizar o journal: {exc}")
        return ev

    def notice(self, kind: str, text: str, task: str = "") -> None:
        self.event("notice", {"task": task, "kind": kind, "text": text})

    def events(self) -> list[dict]:
        if not self.events_path.exists():
            self._event_stamp, self._event_pos, self._event_cache = None, 0, []
            return []
        stat = self.events_path.stat()
        stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if stamp != self._event_stamp:
            if self._event_stamp and (stamp[0] != self._event_stamp[0] or stamp[1] <= self._event_stamp[1]):
                self._event_pos, self._event_cache = 0, []
            with self.events_path.open("rb") as fh:
                fh.seek(self._event_pos)
                data = fh.read()
            cut = data.rfind(b"\n") + 1
            for line in data[:cut].splitlines():
                try:
                    self._event_cache.append(json.loads(line))
                except (ValueError, UnicodeDecodeError):
                    pass
            self._event_pos += cut
            self._event_stamp = stamp
        return deepcopy(self._event_cache)

    # --- estado -----------------------------------------------------------------------------------
    def state(self) -> dict:
        stat = self.state_path.stat()
        stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if stamp != self._state_stamp:
            self._state_cache = json.loads(self.state_path.read_text())
            self._state_stamp = stamp
        return deepcopy(self._state_cache)

    def _save(self, st: dict) -> None:
        write_atomic(self.state_path, json.dumps(st, indent=1, ensure_ascii=False))

    def get(self, task: str, key: str, default=None):
        v = self.state()["tasks"].get(task, {}).get(key)
        return default if v in (None, "") else v

    def set(self, task: str, key: str, value) -> None:
        self.update_task(task, {key: value})

    def update_task(self, task: str, values: dict) -> None:
        st = self.state()
        st["tasks"].setdefault(task, {}).update(values)
        self._save(st)

    def top(self, key: str, default=None):
        return self.state().get(key, default)

    def set_top(self, key: str, value) -> None:
        st = self.state()
        st[key] = value
        self._save(st)

    # --- tempo ativo ---------------------------------------------------------------------------------
    # Parede ≠ trabalho: a espera pelo Victor e o motor parado não contam. Ativo = chamadas e verificações.
    def active_start(self, task: str) -> None:
        if task:
            self.update_task(task, {"active_since": time.time()})

    def active_stop(self, task: str) -> None:
        if not task:
            return
        st = self.state()
        t = st["tasks"].setdefault(task, {})
        since = t.pop("active_since", None)
        if since:
            t["active_s"] = round(float(t.get("active_s") or 0) + max(0.0, time.time() - float(since)), 1)
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

    def cost_by(self) -> dict[str, dict[str, float]]:
        """Custo estimado por tarefa e por papel ("" = fora de tarefa, como o operador)."""
        return self.state().get("cost_by", {})

    def add_cost(self, usd: float | None, task: str = "", role: str = "") -> None:
        with locked(self.lock_path):
            st = self.state()
            if usd is None:
                unknown = st.setdefault("cost_unknown", {}).setdefault(task, {})
                unknown[role] = unknown.get(role, 0) + 1
            usd = float(usd or 0)
            st["cost"] = round(float(st.get("cost", 0)) + usd, 4)
            if role:
                by = st.setdefault("cost_by", {}).setdefault(task, {})
                by[role] = round(by.get(role, 0) + usd, 4)
            self._save(st)

    def unknown_costs(self) -> int:
        return sum(sum(roles.values()) for roles in self.top("cost_unknown", {}).values())

    # --- inbox ------------------------------------------------------------------------------------
    def send(self, text: str, source: str = "painel") -> dict:
        cmd = {"id": f"{time.time_ns():x}", "ts": now_iso(), "text": text, "source": source}
        with locked(self.inbox_path.with_suffix(".lock")):
            with open(self.inbox_path, "a") as fh:
                fh.write(json.dumps(cmd, ensure_ascii=False) + "\n")
        return cmd

    def take_inbox(self) -> list[dict]:
        """Comandos pendentes; ler não confirma entrega."""
        cmds = read_jsonl(self.inbox_path)
        off = int(self.top("inbox_offset", 0))
        return cmds[off:]

    def ack_inbox(self, cmd: dict) -> None:
        pending = self.take_inbox()
        if pending and pending[0]["id"] == cmd["id"]:
            self.set_top("inbox_offset", int(self.top("inbox_offset", 0)) + 1)

    # --- processo ---------------------------------------------------------------------------------
    @contextmanager
    def engine_lock(self, repo: Path):
        git_dir = subprocess.run(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        handles = []
        try:
            for path in (self.dir / "engine.lock", Path(git_dir) / "orq.lock"):
                fh = open(path, "a")
                handles.append(fh)
                # engine_alive() testa o lock por um instante (painel a cada 500 ms): tolera essa colisão
                for attempt in range(20):
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if attempt == 19:
                            raise RuntimeError("já há um motor rodando nesta execução ou árvore de trabalho") from None
                        time.sleep(0.05)
            yield
        finally:
            for fh in reversed(handles):
                fh.close()

    def engine_alive(self) -> bool:
        lock = self.dir / "engine.lock"
        if lock.exists():
            with open(lock, "a") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                return False
        try:
            pid = int(self.pid_path.read_text())
            os.kill(pid, 0)
            return True
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False
