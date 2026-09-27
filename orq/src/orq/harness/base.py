"""Interface comum dos harnesses. Cada adaptador monta o argv, lê o stream JSON do CLI e devolve um CallResult;
o laço de tentativas (limite de uso, erro transitório, troca de conta) fica no motor, igual para todos."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Role

LIMIT_RE = re.compile(r"usage limit|limit reached|hit your .*limit|rate.?limit|resets? (at )?[0-9]|quota exceeded", re.I)
TRANSIENT_RE = re.compile(r"overloaded|\b529\b|\b5[0-9][0-9] |timed? ?out|ECONNRESET|network|temporarily unavailable", re.I)
SESSION_EXISTS_RE = re.compile(r"already (in use|exists)", re.I)


@dataclass
class CallRequest:
    role: Role
    name: str                 # nome da chamada (arquivos em calls/NAME.*)
    prompt: str
    schema: dict
    cwd: Path
    calls_dir: Path
    read_only: bool           # conselho e operador: só leitura
    session_id: str | None    # sessão a retomar (resume) ou id pré-definido para a nova (claude)
    resume: bool
    timeout: int              # segundos
    env: dict = field(default_factory=dict)   # acrescentado ao ambiente (bloqueio de push, conta)
    account_dir: str | None = None
    thinking: bool = False
    on_session: Callable[[str], None] | None = None


@dataclass
class CallResult:
    output: dict | None = None
    session_id: str | None = None
    cost: float | None = None  # None = não informado pelo harness, distinto de custo zero
    error: str | None = None  # None | limit | transient | timeout | session_exists | no_output | fatal
    message: str = ""


OnLine = Callable[[str], None]


class Harness:
    name = "base"
    preset_session_ids = False  # True: o motor escolhe o id da sessão nova (claude --session-id)

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        raise NotImplementedError

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        """argv da sessão interativa do wizard."""
        raise NotImplementedError


def classify(text: str) -> str | None:
    if SESSION_EXISTS_RE.search(text):
        return "session_exists"
    if LIMIT_RE.search(text):
        return "limit"
    if TRANSIENT_RE.search(text):
        return "transient"
    return None


def clip(s, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def shorten_paths(s: str, cwd: Path, run_dir: Path | None) -> str:
    if run_dir:
        s = s.replace(str(run_dir) + "/", "run/")
    return s.replace(str(cwd) + "/", "")


def tool_line(name: str, inp: dict) -> str | None:
    """Uma ferramenta chamada, em uma linha (mesma forma para todos os harnesses)."""
    inp = inp or {}
    if name in ("Bash", "shell", "bash", "command_execution"):
        return "$ " + clip(inp.get("command") or inp.get("cmd") or "", 220)
    if name in ("Read", "Write", "Edit", "NotebookEdit", "read", "write", "edit"):
        return f"{name} {inp.get('file_path') or inp.get('filePath') or inp.get('path') or inp.get('notebook_path') or ''}"
    if name in ("Grep", "Glob", "grep", "glob"):
        return f"{name} {inp.get('pattern', '')}" + (f" em {inp['path']}" if inp.get("path") else "")
    if name in ("Agent", "Task", "task"):
        return f"subagente: {inp.get('description', '')}"
    if name == "Skill":
        return f"skill {inp.get('skill', '')}"
    if name in ("TodoWrite", "StructuredOutput", "todowrite"):
        return None
    return f"{name} {clip(json.dumps(inp, ensure_ascii=False), 120)}"


_active: set[asyncio.subprocess.Process] = set()


def kill_all() -> None:
    """Encerra os processos filhos (grupo inteiro): usado na interrupção do motor."""
    for p in list(_active):
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


async def run_process(argv: list[str], stdin_text: str | None, cwd: Path, env: dict, timeout: int,
                      raw_path: Path, on_json: Callable[[dict], None]) -> tuple[int, bool, str]:
    """Roda o CLI, grava o stream cru em raw_path e passa cada linha JSON a on_json.
    → (código de saída, estourou o timeout?, fim do stderr)."""
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    err_path = raw_path.with_suffix(".err")
    with open(err_path, "w") as err_fh:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env={**os.environ, **env}, start_new_session=True,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=err_fh, limit=64 * 1024 * 1024)
        _active.add(proc)
        timed_out = False

        async def pump():
            if stdin_text is not None:
                proc.stdin.write(stdin_text.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            with open(raw_path, "w") as raw:
                async for line in proc.stdout:
                    s = line.decode(errors="replace")
                    raw.write(s)
                    raw.flush()
                    try:
                        ev = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(ev, dict):
                        # O callback também persiste a sessão: erro de disco não pode sumir.
                        on_json(ev)
            return await proc.wait()

        try:
            rc = await asyncio.wait_for(pump(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            rc = await proc.wait()
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # O pai pode sair antes de um descendente: sempre encerre o grupo ao fim da tolerância.
            try:
                await asyncio.wait_for(proc.wait(), 1)
            except asyncio.TimeoutError:
                pass
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
            raise
        finally:
            _active.discard(proc)
    return rc, timed_out, err_path.read_text(errors="replace")[-2000:]
