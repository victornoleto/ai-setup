"""OpenCode: `opencode run --format json`. Qualquer provedor do opencode, inclusive OpenRouter
(`model = "openrouter/<modelo>"`). Sem flag de schema: o formato vai no prompt, o JSON sai do último bloco da
resposta e é validado com jsonschema (inválido → o motor pede de novo uma vez, na mesma sessão)."""
from __future__ import annotations

import json
import re

import jsonschema

from ..config import Role
from .base import CallRequest, CallResult, Harness, OnLine, classify, clip, run_process, tool_line

SCHEMA_NOTE = """

## Formato da resposta final (obrigatório)

Termine a resposta com **um único** bloco ```json válido por este JSON Schema, sem texto depois dele:

```json
{schema}
```
"""


class OpencodeHarness(Harness):
    name = "opencode"

    def argv(self, req: CallRequest, prompt: str) -> list[str]:
        argv = ["opencode", "run", "--format", "json", "-m", req.role.model, "--dir", str(req.cwd)]
        if req.role.effort and req.role.effort not in ("default", "-"):
            argv += ["--variant", req.role.effort]
        argv += ["--agent", "plan"] if req.read_only else ["--auto"]
        if req.resume and req.session_id:
            argv += ["-s", req.session_id]
        return argv + ["--", prompt]

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        prompt = req.prompt + SCHEMA_NOTE.format(schema=json.dumps(req.schema, ensure_ascii=False, indent=1))
        sid = req.session_id if req.resume else None
        texts: list[str] = []
        errors: list[str] = []
        cost = 0.0

        def on_json(ev: dict):
            nonlocal sid, cost
            sid = ev.get("sessionID") or sid
            part = ev.get("part") or {}
            t = ev.get("type")
            if t == "text":
                texts.append(part.get("text", ""))
            elif t == "step_finish":
                cost += float(part.get("cost") or 0)
            elif t == "error":
                err = ev.get("error") or {}
                data = err.get("data") or {}
                msg = data.get("message") or err.get("name") or "erro"
                errors.append(msg + (" (transient)" if data.get("isRetryable") else "")
                              + (" rate limit" if data.get("statusCode") == 429 else ""))
            for line in render_event(ev, req.thinking):
                on_line(line)

        rc, timed_out, err = await run_process(self.argv(req, prompt), None, req.cwd, req.env, req.timeout,
                                               req.calls_dir / f"{req.name}.stream.jsonl", on_json)
        if timed_out:
            return CallResult(error="timeout", session_id=sid, message="timeout")
        final = texts[-1] if texts else ""
        out = extract_json(final)
        valid = out is not None and is_valid(out, req.schema)
        (req.calls_dir / f"{req.name}.json").write_text(json.dumps({"session_id": sid, "output": out, "valid": valid},
                                                                   ensure_ascii=False))
        if not errors and valid:
            return CallResult(output=out, session_id=sid, cost=cost)
        if errors:
            text = " ".join(errors) + " " + err
            kind = "transient" if "(transient)" in text and not classify(text) else classify(text)
            return CallResult(error=kind or "fatal", session_id=sid, message=clip(text, 300), cost=cost)
        return CallResult(error="no_output", session_id=sid, cost=cost,
                          message=clip(final or f"resposta sem JSON válido (saída {rc})", 300))

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        return ["opencode", "-m", role.model, "--prompt", prompt]


def is_valid(out: dict, schema: dict) -> bool:
    try:
        jsonschema.validate(out, schema)
        return True
    except jsonschema.ValidationError:
        return False


def extract_json(text: str) -> dict | None:
    """O último bloco ```json; sem bloco, o último objeto {...} que for JSON válido."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = blocks[::-1] or []
    if not candidates:
        starts = [m.start() for m in re.finditer(r"\{", text)]
        end = text.rfind("}")
        candidates = [text[s:end + 1] for s in starts if end > s]
    for c in candidates:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return None


def render_event(ev: dict, thinking: bool = False) -> list[str]:
    t, part = ev.get("type"), ev.get("part") or {}
    if t == "text":
        text = re.sub(r"```(?:json)?\s*\{.*?(```|$)", "", part.get("text", ""), flags=re.S)  # o JSON final não vai ao painel
        if extract_json(text.strip()) is not None and text.strip().startswith("{"):
            return []
        return [line for line in text.split("\n") if line.strip()]
    if t == "tool_use":
        st = part.get("state") or {}
        tool = part.get("tool", "")
        name = {"bash": "Bash", "read": "Read", "write": "Write", "edit": "Edit", "grep": "Grep", "glob": "Glob",
                "task": "Task"}.get(tool, tool)
        line = tool_line(name, st.get("input") or {})
        out = ["› " + line] if line else []
        exit_code = (st.get("metadata") or {}).get("exit")
        if st.get("status") == "error" or exit_code not in (0, None):
            out.append("✗ " + clip(st.get("error") or st.get("output"), 200))
        return out
    if t == "reasoning" and thinking:
        return ["(pensando) " + clip(part.get("text"), 300)]
    if t == "error":
        return ["✗ " + clip(((ev.get("error") or {}).get("data") or {}).get("message"), 200)]
    return []
