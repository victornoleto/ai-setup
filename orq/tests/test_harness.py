import json
import os

from orq.harness import claude, codex, opencode
from orq.harness.base import classify

from .conftest import FIXTURES


def lines(path, render):
    out = []
    for raw in path.read_text().splitlines():
        out += render(json.loads(raw))
    return out


def test_codex_stream_e_resposta():
    evs = [json.loads(x) for x in (FIXTURES / "codex.jsonl").read_text().splitlines()]
    assert evs[0]["type"] == "thread.started" and evs[0]["thread_id"]
    shown = lines(FIXTURES / "codex.jsonl", codex.render_event)
    assert "› $ ls" in shown
    last = [e["item"]["text"] for e in evs if e.get("item", {}).get("type") == "agent_message"][-1]
    assert codex.parse_json(last) == {"option_id": "a", "rationale": "teste"}


def test_opencode_stream_e_json():
    shown = lines(FIXTURES / "opencode.jsonl", opencode.render_event)
    assert shown == ["› $ ls"]
    assert opencode.extract_json('bla\n```json\n{"a": 1}\n```\nfim') == {"a": 1}
    assert opencode.extract_json('texto {"option_id": "b", "rationale": "x"}') == {"option_id": "b", "rationale": "x"}
    assert opencode.extract_json("nada") is None
    ev = {"type": "text", "part": {"text": 'Pronto.\n```json\n{\n  "a": [\n  ],\n  "b": 1\n}\n```'}}
    assert opencode.render_event(ev) == ["Pronto."]
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    assert opencode.is_valid({"a": 1}, schema) and not opencode.is_valid({"a": "x"}, schema)


def test_argv_por_acesso(tmp_path):
    from orq.config import Role
    from orq.harness.base import CallRequest
    role = Role("executor", "codex", "gpt-x", "low")
    req = CallRequest(role=role, name="n", prompt="p", schema={}, cwd=tmp_path, calls_dir=tmp_path, read_only=True,
                      session_id=None, resume=False, timeout=10)
    assert ["-s", "read-only"] == codex.CodexHarness().argv(req, "f")[-5:-3]
    req.read_only, req.resume, req.session_id = False, True, "th1"
    a = codex.CodexHarness().argv(req, "f")
    assert a[:3] == ["codex", "exec", "resume"] and a[-2:] == ["th1", "-"]
    a = opencode.OpencodeHarness().argv(req, "p")
    assert "--auto" in a and a[a.index("-s") + 1] == "th1" and a[-2:] == ["--", "p"]
    req.read_only, req.resume = True, False
    assert "--permission-mode" in claude.ClaudeHarness().argv(req)


def test_classify():
    assert classify("You've hit your usage limit, resets 3am") == "limit"
    assert classify("Error: 529 overloaded") == "transient"
    assert classify("Session ID x is already in use") == "session_exists"
    assert classify("syntax error") is None


def test_claude_nega_subagent_em_background(tmp_path):
    import subprocess
    import sys
    from orq.config import Role
    from orq.harness.base import CallRequest
    req = CallRequest(role=Role("executor", "claude", "m", "high"), name="n", prompt="p", schema={}, cwd=tmp_path,
                      calls_dir=tmp_path, read_only=False, session_id=None, resume=False, timeout=10)
    a = claude.ClaudeHarness().argv(req)
    hook = json.loads(a[a.index("--settings") + 1])["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Agent|Task"
    script = claude.Path(claude.__file__).with_name("no_background_agent.py")

    def run(tool_input):
        return subprocess.run([sys.executable, str(script)], input=json.dumps({"tool_input": tool_input}),
                              capture_output=True, text=True)
    bg = run({"prompt": "x", "run_in_background": True})
    assert bg.returncode == 2 and "primeiro plano" in bg.stderr
    assert run({"prompt": "x", "run_in_background": False}).returncode == 0
    assert run({"prompt": "x"}).returncode == 0


async def test_claude_subagent_morto_no_fim_nao_vale_como_saida(tmp_path, monkeypatch):
    from orq.config import Role
    from orq.harness.base import CallRequest
    result = {"type": "result", "session_id": "s1", "is_error": False, "total_cost_usd": 1.5,
              "structured_output": {"status": "blocked"}, "subagent_stats": {"killed": {"system": 1}}}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(f"#!/bin/sh\ncat >/dev/null\necho '{json.dumps(result)}'\n")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    req = CallRequest(role=Role("executor", "claude", "m", "high"), name="n", prompt="p", schema={}, cwd=tmp_path,
                      calls_dir=tmp_path, read_only=False, session_id="s1", resume=False, timeout=10)
    res = await claude.ClaudeHarness().call(req, lambda line: None)
    assert res.error == "background_killed" and res.output is None and res.session_id == "s1" and res.cost == 1.5


def test_claude_render_system_em_texto():
    ev = {"type": "system", "subtype": "permission_denied", "session_id": "s1",
          "message": "Dangerous rm operation detected: 'x'\n\nThis command changes directories before the removal"}
    shown = claude.render_event(ev)
    assert len(shown) == 1 and shown[0].startswith("✗ permission_denied: Dangerous rm operation detected")
    assert claude.render_event({"type": "system", "subtype": "init", "session_id": "s1"}) == []
