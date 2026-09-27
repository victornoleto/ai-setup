"""Harness de teste: nenhuma chamada real. As respostas vêm de um arquivo JSON (o `model` do papel, relativo à
fila) com uma lista por schema; cada chamada consome a próxima da lista daquele schema (a última se repete).

  {"plan": [{"summary": "…", "questions": []}],
   "execute": [{"_sh": "echo oi > a.txt && git add -A && git commit -qm a", "status": "done", …}],
   "review": [{"verdict": "approved", …}], "vote": [{"option_id": "a", "rationale": "…"}]}

`_sh` roda no repositório antes de responder; `_sleep` espera N segundos; `_stream` são linhas para o painel;
`_error` devolve esse erro (limit, transient, fatal…) em vez da resposta."""
from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

from ..config import Role
from .base import CallRequest, CallResult, Harness, OnLine

SCHEMA_KEYS = {"summary": "plan", "status": "execute", "verdict": "review", "option_id": "vote", "reply": "operator", "narrative": "summary", "diagnosis": "ask", "sufficient": "resolve"}


def schema_key(schema: dict) -> str:
    for k in schema.get("required", []):
        if k in SCHEMA_KEYS:
            return SCHEMA_KEYS[k]
    return "other"


class FakeHarness(Harness):
    name = "fake"
    preset_session_ids = True

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir
        self.calls: list[CallRequest] = []

    def _script(self, req: CallRequest) -> dict:
        p = Path(req.role.model)
        if not p.is_absolute():
            p = (self.base_dir or Path.cwd()) / p
        return json.loads(p.read_text())

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        self.calls.append(req)
        if req.session_id and req.on_session:
            req.on_session(req.session_id)
        key = schema_key(req.schema)
        # contador persistido ao lado das chamadas: sobrevive a um `resume`
        counter = req.calls_dir.parent.parent / "fake-counts.json"
        counts = json.loads(counter.read_text()) if counter.exists() else {}
        script = self._script(req)
        seq = script.get(f"{req.role.name}:{key}") or script.get(key) or []
        ck = f"{req.role.name}:{key}" if f"{req.role.name}:{key}" in script else key
        i = counts.get(ck, 0)
        counts[ck] = i + 1
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(json.dumps(counts))
        if not seq and key == "summary":  # resumo final: resposta padrão, para não exigir no script de todo teste
            seq = [{"narrative": "(fake) resumo da execução"}]
        if not seq:
            return CallResult(error="fatal", message=f"fake: sem resposta para {ck}")
        resp = dict(seq[min(i, len(seq) - 1)])
        for line in resp.pop("_stream", [f"(fake) {req.role.name} {req.name}"]):
            on_line(line)
        if resp.get("_sleep"):
            await asyncio.sleep(float(resp.pop("_sleep")))
        if resp.get("_sh"):
            subprocess.run(resp.pop("_sh"), shell=True, cwd=req.cwd, check=False, capture_output=True)
        req.calls_dir.mkdir(parents=True, exist_ok=True)
        (req.calls_dir / f"{req.name}.json").write_text(json.dumps(resp, ensure_ascii=False))
        if resp.get("_error"):
            return CallResult(error=resp["_error"], message=resp.get("_message", resp["_error"]))
        return CallResult(output={k: v for k, v in resp.items() if not k.startswith("_")},
                          session_id=req.session_id or str(uuid.uuid4()), cost=0.01)

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        return ["sh", "-c", 'printf "%s\\n" "$1"', "fake-wizard", prompt]
