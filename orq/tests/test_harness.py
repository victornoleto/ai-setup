import json
import os

from orq.harness import claude, codex, kiro, opencode
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


def test_render_que_quebra_nao_derruba_a_chamada():
    from orq.harness.base import safe_render

    def quebra(ev, thinking=False):
        raise KeyError("x")
    assert safe_render(quebra, {"type": "y"}) == ['✗ render falhou (KeyError): {"type": "y"}']
    assert safe_render(codex.render_event, {"type": "turn.failed", "error": "texto"})[0].startswith("✗ render falhou")


async def test_codex_turn_failed_com_error_em_texto(tmp_path, monkeypatch):
    from orq.config import Role
    from orq.harness.base import CallRequest
    ev = {"type": "turn.failed", "error": "falhou em texto"}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex").write_text(f"#!/bin/sh\ncat >/dev/null\necho '{json.dumps(ev)}'\nexit 1\n")
    (bin_dir / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    req = CallRequest(role=Role("executor", "codex", "m", "low"), name="n", prompt="p", schema={}, cwd=tmp_path,
                      calls_dir=tmp_path, read_only=False, session_id=None, resume=False, timeout=10)
    res = await codex.CodexHarness().call(req, lambda line: None)
    assert res.error == "fatal" and "falhou em texto" in res.message


def _kiro_req(tmp_path, **kw):
    from orq.config import Role
    from orq.harness.base import CallRequest
    base = dict(role=Role("executor", "kiro", "claude-sonnet-5.5", "high"), name="n", prompt="p",
                schema={"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
                cwd=tmp_path, calls_dir=tmp_path, read_only=False, session_id=None, resume=False, timeout=10)
    return CallRequest(**{**base, **kw})


def _kiro_chunk(kind, text):
    return {"type": "sessionUpdate", "data": {"sessionId": "s", "update": {"sessionUpdate": kind,
                                                                           "content": {"type": "text", "text": text}}}}


def test_kiro_stream():
    view = kiro.Stream()
    shown = lines(FIXTURES / "kiro.jsonl", view.render)
    assert shown == ["› $ ls", "› Read /repo/a.txt", "› Edit /repo/b.txt", "· 0,03 créditos"]
    assert view.message == '{"a": "conteudo-a"}' and round(view.credits, 2) == 0.03
    v = kiro.Stream()
    evs = [_kiro_chunk("agent_thought_chunk", "pensa"), _kiro_chunk("agent_message_chunk", "Pronto.\n```json\n{\"a\": 1}"),
           _kiro_chunk("agent_message_chunk", "\n```"), {"type": "runFinished", "data": {}}]
    assert sum((v.render(e, True) for e in evs), []) == ["(pensando) pensa", "Pronto."]


def test_kiro_argv(tmp_path):
    req = _kiro_req(tmp_path, read_only=True)
    a = kiro.KiroHarness().argv(req)
    assert a[:5] == ["kiro-cli", "chat", "--no-interactive", "--output-format", "stream-json"]
    assert a[a.index("--model") + 1] == "claude-sonnet-5.5" and a[a.index("--effort") + 1] == "high"
    assert any(x.startswith("--trust-tools=read_file") for x in a) and "--trust-all-tools" not in a
    req.read_only, req.resume, req.session_id = False, True, "sess_1"
    a = kiro.KiroHarness().argv(req)
    assert "--trust-all-tools" in a and a[-2:] == ["--resume-id", "sess_1"]


def _fake_kiro(tmp_path, monkeypatch, events, rc=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stream = tmp_path / "kiro-stream.jsonl"
    stream.write_text("".join(json.dumps(e) + "\n" for e in events))
    (bin_dir / "kiro-cli").write_text(
        f"#!/bin/sh\ncat >/dev/null\necho '[INFO] kas.server.starting' >&2\ncat '{stream}'\nexit {rc}\n")
    (bin_dir / "kiro-cli").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


async def test_kiro_call_resposta_e_sessao(tmp_path, monkeypatch):
    fim = {"type": "runFinished", "data": {"sessionId": "sess_x", "status": "success",
                                           "finalText": "Feito.\n```json\n{\"a\": 1}\n```", "finalTextTruncated": False}}
    _fake_kiro(tmp_path, monkeypatch, [{"type": "runStarted", "data": {}}, _kiro_chunk("agent_message_chunk", "x"), fim])
    seen = []
    res = await kiro.KiroHarness().call(_kiro_req(tmp_path, on_session=seen.append), lambda line: None)
    assert res.output == {"a": 1} and res.session_id == "sess_x" and res.error is None
    assert seen == ["s", "sess_x"]


async def test_kiro_call_erros(tmp_path, monkeypatch):
    msg = ("The model 'x' is not available. (code -32000): "
           '{"errorType":"InvalidModelError","retryErrorType":"CLIENT_ERROR"}')
    _fake_kiro(tmp_path, monkeypatch, [{"type": "runError", "data": {"sessionId": "s1", "message": msg}}], rc=1)
    res = await kiro.KiroHarness().call(_kiro_req(tmp_path), lambda line: None)
    assert res.error == "fatal" and "not available" in res.message and "[INFO]" not in res.message
    assert kiro.error_kind("ThrottlingException: Too many requests") == "limit"
    assert kiro.error_kind("Error: 529 overloaded") == "transient"
    fim = {"type": "runFinished", "data": {"sessionId": "s2", "finalText": "sem json", "finalTextTruncated": False}}
    _fake_kiro(tmp_path, monkeypatch, [fim])
    res = await kiro.KiroHarness().call(_kiro_req(tmp_path), lambda line: None)
    assert res.error == "no_output" and res.session_id == "s2"


async def _claude_falso(tmp_path, monkeypatch, result: dict, rc: int):
    from orq.config import Role
    from orq.harness.base import CallRequest
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(f"#!/bin/sh\ncat >/dev/null\necho '{json.dumps(result)}'\nexit {rc}\n")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    req = CallRequest(role=Role("executor", "claude", "m", "high"), name="n", prompt="p", schema={}, cwd=tmp_path,
                      calls_dir=tmp_path, read_only=False, session_id="s1", resume=False, timeout=10)
    return await claude.ClaudeHarness().call(req, lambda line: None)


async def test_claude_texto_do_modelo_nao_vira_limite_de_uso(tmp_path, monkeypatch):
    """Tarefa que fala de rate limit ou de rede e falha: o erro é fatal, não espera de horas."""
    res = await _claude_falso(tmp_path, monkeypatch, {
        "type": "result", "session_id": "s1", "is_error": False,
        "result": "Implementei o rate limit; o teste de network timed out resets at 3"}, rc=1)
    assert res.error == "fatal"


async def test_claude_erro_do_cli_continua_classificado(tmp_path, monkeypatch):
    res = await _claude_falso(tmp_path, monkeypatch, {
        "type": "result", "session_id": "s1", "is_error": True, "result": "Usage limit reached, resets 3am"}, rc=1)
    assert res.error == "limit"
