"""Claude Code: `claude -p --output-format stream-json --json-schema`, conta por CLAUDE_CONFIG_DIR."""
from __future__ import annotations

import json

from ..config import Role
from .base import CallRequest, CallResult, Harness, OnLine, classify, clip, run_process, tool_line


class ClaudeHarness(Harness):
    name = "claude"
    preset_session_ids = True

    def argv(self, req: CallRequest) -> list[str]:
        perm = ["--permission-mode", "plan"] if req.read_only else ["--dangerously-skip-permissions"]
        sess = ["--resume", req.session_id] if req.resume else (["--session-id", req.session_id] if req.session_id else [])
        return ["claude", "-p", *perm, *sess, "--model", req.role.model, "--effort", req.role.effort,
                "-n", f"orq:{req.name}", "--output-format", "stream-json", "--verbose",
                "--json-schema", json.dumps(req.schema)]

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        env = dict(req.env)
        if req.account_dir:
            env["CLAUDE_CONFIG_DIR"] = req.account_dir
        result: dict = {}

        def on_json(ev: dict):
            nonlocal result
            if ev.get("session_id") and req.on_session:
                req.on_session(ev["session_id"])
            if ev.get("type") == "result":
                result = ev
            for line in render_event(ev, req.thinking):
                on_line(line)

        raw = req.calls_dir / f"{req.name}.stream.jsonl"
        rc, timed_out, err = await run_process(self.argv(req), req.prompt, req.cwd, env, req.timeout, raw, on_json)
        (req.calls_dir / f"{req.name}.json").write_text(json.dumps(result, ensure_ascii=False))
        cost = float(result["total_cost_usd"]) if result.get("total_cost_usd") is not None else None
        if timed_out:
            return CallResult(error="timeout", message="timeout", cost=cost)
        sid = result.get("session_id") or req.session_id
        if rc == 0 and result.get("is_error") is False and result.get("structured_output") is not None:
            return CallResult(output=result["structured_output"], session_id=sid, cost=cost)
        text = f"{result.get('result') or ''} {err}"
        if rc == 0 and result and result.get("structured_output") is None and not result.get("is_error"):
            return CallResult(error="no_output", session_id=sid, message=clip(text, 300),
                              cost=cost)
        return CallResult(error=classify(text) or "fatal", session_id=sid if result else None,
                          message=clip(text, 300) or f"saída {rc}", cost=cost)

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        return ["claude", "--model", role.model, "--effort", role.effort, prompt]


def render_event(e: dict, thinking: bool = False) -> list[str]:
    """Evento do stream-json → linhas legíveis (texto do modelo, ferramentas, erros de ferramenta)."""
    out = []
    t = e.get("type")
    content = (e.get("message") or {}).get("content") or []
    if t == "assistant":
        for c in content:
            if c.get("type") == "text":
                out += [l for l in c.get("text", "").split("\n") if l.strip()]
            elif c.get("type") == "tool_use":
                line = tool_line(c.get("name", ""), c.get("input") or {})
                if line:
                    out.append("› " + line)
            elif c.get("type") == "thinking" and thinking:
                out.append("(pensando) " + clip(c.get("thinking"), 300))
    elif t == "user" and isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                body = c.get("content")
                if isinstance(body, list):
                    body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                out.append("✗ " + clip(body, 200))
    return out
