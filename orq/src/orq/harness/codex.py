"""Codex CLI: `codex exec --json --output-schema`, sessão pelo thread_id do evento thread.started."""
from __future__ import annotations

import json
import re

from ..config import Role
from .base import CallRequest, CallResult, Harness, OnLine, classify, clip, run_process, tool_line


class CodexHarness(Harness):
    name = "codex"

    def argv(self, req: CallRequest, schema_file: str) -> list[str]:
        common = ["--json", "--output-schema", schema_file, "-m", req.role.model,
                  "-c", f"model_reasoning_effort={req.role.effort}", "--skip-git-repo-check"]
        if req.resume:
            return ["codex", "exec", "resume", *common, "--dangerously-bypass-approvals-and-sandbox", req.session_id, "-"]
        access = ["-s", "read-only"] if req.read_only else ["--dangerously-bypass-approvals-and-sandbox"]
        return ["codex", "exec", *common, *access, "-C", str(req.cwd), "-"]

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        schema_file = req.calls_dir / f"{req.name}.schema.json"
        schema_file.parent.mkdir(parents=True, exist_ok=True)
        schema_file.write_text(json.dumps(req.schema))
        sid = req.session_id if req.resume else None
        last_msg: str | None = None
        errors: list[str] = []

        def on_json(ev: dict):
            nonlocal sid, last_msg
            t = ev.get("type")
            if t == "thread.started":
                sid = ev.get("thread_id") or sid
            elif t == "error":
                errors.append(str(ev.get("message", "")))
            elif t == "turn.failed":
                errors.append(str((ev.get("error") or {}).get("message", "")))
            elif t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                last_msg = ev["item"].get("text", "")
            for line in render_event(ev, req.thinking):
                on_line(line)

        rc, timed_out, err = await run_process(self.argv(req, str(schema_file)), req.prompt, req.cwd, req.env,
                                               req.timeout, req.calls_dir / f"{req.name}.stream.jsonl", on_json)
        if timed_out:
            return CallResult(error="timeout", session_id=sid, message="timeout")
        out = parse_json(last_msg)
        (req.calls_dir / f"{req.name}.json").write_text(json.dumps({"session_id": sid, "output": out}, ensure_ascii=False))
        if rc == 0 and out is not None:
            return CallResult(output=out, session_id=sid)
        text = " ".join(errors) + " " + err
        if rc == 0 and not errors:
            return CallResult(error="no_output", session_id=sid, message=clip(last_msg or "resposta vazia", 300))
        return CallResult(error=classify(text) or "fatal", session_id=sid, message=clip(text, 300) or f"saída {rc}")

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        return ["codex", "-m", role.model, "-c", f"model_reasoning_effort={role.effort}", prompt]


def parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


def render_event(ev: dict, thinking: bool = False) -> list[str]:
    t, item = ev.get("type"), ev.get("item") or {}
    it = item.get("type")
    if t == "item.started" and it == "command_execution":
        cmd = re.sub(r"^/bin/(ba)?sh -lc ", "", item.get("command", "")).strip("'\"")
        return ["› " + tool_line("Bash", {"command": cmd})]
    if t != "item.completed":
        if t in ("error", "turn.failed"):
            return ["✗ " + clip(ev.get("message") or (ev.get("error") or {}).get("message"), 200)]
        return []
    if it == "agent_message":
        text = item.get("text", "")
        return [] if parse_json(text) is not None else [line for line in text.split("\n") if line.strip()]
    if it == "command_execution" and item.get("exit_code") not in (0, None):
        return [f"✗ exit {item.get('exit_code')}: " + clip(item.get("aggregated_output"), 200)]
    if it == "file_change":
        return [f"› Edit {c.get('path', '')}" for c in item.get("changes") or []]
    if it == "mcp_tool_call":
        return [f"› {item.get('server', '')}.{item.get('tool', '')}"]
    if it == "web_search":
        return [f"› busca: {item.get('query', '')}"]
    if it == "reasoning" and thinking:
        return ["(pensando) " + clip(item.get("text"), 300)]
    return []
