"""Kiro CLI: `kiro-cli chat --no-interactive --output-format stream-json` (eventos ACP em JSON Lines), prompt pelo
stdin. Sem flag de schema: o formato vai no prompt e o JSON sai do `finalText` do `runFinished`, validado como no
opencode (inválido → o motor pede de novo uma vez, na mesma sessão). Sessão pelo `sessionId` dos eventos, retomada
com `--resume-id`. Só leitura: só as ferramentas de leitura ficam confiáveis; as outras falham sem travar a chamada.
O gasto vem em créditos do Kiro, não em US$: aparece no painel e em calls/NAME.json, e o CallResult fica sem custo."""
from __future__ import annotations

import json
import re

from ..config import Role
from .base import CallRequest, CallResult, Harness, OnLine, classify, clip, run_process, safe_render, tool_line
from .opencode import SCHEMA_NOTE, extract_json, is_valid

# Ferramentas de leitura do motor v3 (nomes do `usedTools` e do pacote do KAS); nome que não existe é ignorado.
READ_TOOLS = "read_file,fs_read,grep_search,file_search,list_directory,grep,glob"
TOOL_KINDS = {"execute": "Bash", "read": "Read", "edit": "Edit", "search": "Grep", "fetch": "WebFetch"}
THROTTLE_RE = re.compile(r"throttl|too many requests|insufficient credits|out of credits", re.I)


class KiroHarness(Harness):
    name = "kiro"

    def argv(self, req: CallRequest) -> list[str]:
        argv = ["kiro-cli", "chat", "--no-interactive", "--output-format", "stream-json", "--model", req.role.model]
        if req.role.effort and req.role.effort not in ("default", "-"):
            argv += ["--effort", req.role.effort]
        argv.append(f"--trust-tools={READ_TOOLS}" if req.read_only else "--trust-all-tools")
        if req.resume and req.session_id:
            argv += ["--resume-id", req.session_id]
        return argv

    async def call(self, req: CallRequest, on_line: OnLine) -> CallResult:
        prompt = req.prompt + SCHEMA_NOTE.format(schema=json.dumps(req.schema, ensure_ascii=False, indent=1))
        sid = req.session_id if req.resume else None
        final: str | None = None
        errors: list[str] = []
        view = Stream()

        def on_json(ev: dict):
            nonlocal sid, final
            data = ev.get("data") or {}
            if data.get("sessionId") and data["sessionId"] != sid:
                sid = data["sessionId"]
                if req.on_session:
                    req.on_session(sid)
            t = ev.get("type")
            if t == "runFinished":
                final = view.message if data.get("finalTextTruncated") else data.get("finalText")
            elif t == "runError":
                errors.append(str(data.get("message", "")))
            for line in safe_render(view.render, ev, req.thinking):
                on_line(line)

        rc, timed_out, err = await run_process(self.argv(req), prompt, req.cwd, req.env, req.timeout,
                                               req.calls_dir / f"{req.name}.stream.jsonl", on_json)
        if timed_out:
            return CallResult(error="timeout", session_id=sid, message="timeout")
        out = extract_json(final or "")
        valid = out is not None and is_valid(out, req.schema)
        (req.calls_dir / f"{req.name}.json").write_text(json.dumps(
            {"session_id": sid, "output": out, "valid": valid, "credits": round(view.credits, 4)}, ensure_ascii=False))
        if rc == 0 and not errors and valid:
            return CallResult(output=out, session_id=sid)
        if rc != 0 or errors:
            # O stderr do kiro-cli é quase todo log [INFO]: só o resto entra na mensagem e na classificação.
            rest = " ".join(x for x in err.splitlines() if not x.startswith("[INFO]") and "ExperimentalWarning" not in x)
            text = " ".join(errors) + " " + rest
            return CallResult(error=error_kind(text), session_id=sid, message=clip(text, 300) or f"saída {rc}")
        return CallResult(error="no_output", session_id=sid, message=clip(final or "resposta sem JSON válido", 300))

    def interactive_argv(self, role: Role, prompt: str) -> list[str]:
        argv = ["kiro-cli", "chat", "--model", role.model]
        if role.effort and role.effort not in ("default", "-"):
            argv += ["--effort", role.effort]
        return argv + [prompt]


def error_kind(text: str) -> str:
    return classify(text) or ("limit" if THROTTLE_RE.search(text) else "fatal")


def _text(content) -> str:
    if isinstance(content, dict):
        return str(content.get("text", ""))
    if isinstance(content, list):
        return " ".join(_text(c.get("content")) for c in content if isinstance(c, dict))
    return ""


class Stream:
    """O Kiro manda mensagem e raciocínio em fatias: junta as fatias e solta o bloco inteiro no próximo evento de
    outro tipo. `message` guarda a última mensagem, reserva para quando o `finalText` vier cortado."""

    def __init__(self):
        self.kind: str | None = None  # "msg" | "thought": o bloco em montagem
        self.buf = ""
        self.message = ""
        self.credits = 0.0

    def render(self, ev: dict, thinking: bool = False) -> list[str]:
        data = ev.get("data") or {}
        u = data.get("update") or {}
        su = u.get("sessionUpdate")
        kiro = (u.get("_meta") or {}).get("kiro") or {}
        chunk = {"agent_message_chunk": "msg", "agent_thought_chunk": "thought"}.get(su)
        if chunk:
            out = self.flush(thinking) if self.kind not in (None, chunk) else []
            if self.kind != chunk:
                self.kind, self.buf = chunk, ""
                if chunk == "msg":
                    self.message = ""
            text = _text(u.get("content"))
            self.buf += text
            if chunk == "msg":
                self.message += text
            return out
        # Contexto, hooks e foco chegam no meio da mensagem: só ferramenta, fim de turno e fim da execução fecham o bloco.
        if su not in ("tool_call", "tool_call_update") and kiro.get("kind") != "turn_completion" \
                and ev.get("type") not in ("runFinished", "runError"):
            return []
        out = self.flush(thinking)
        if su == "tool_call":
            line = tool_line(TOOL_KINDS.get(u.get("kind"), u.get("title") or "tool"), u.get("rawInput") or {})
            out += ["› " + line] if line else []
        elif su == "tool_call_update" and u.get("status") == "failed":
            out.append("✗ " + clip(_text(u.get("content")) or u.get("title") or "falhou", 200))
        elif kiro.get("kind") == "turn_completion":
            used = sum(float(s.get("usage") or 0) for s in kiro.get("promptTurnSummaries") or [])
            self.credits += used
            if used:
                out.append(f"· {used:.2f} créditos".replace(".", ","))
        elif ev.get("type") == "runError":
            out.append("✗ " + clip(data.get("message"), 200))
        return out

    def flush(self, thinking: bool) -> list[str]:
        kind, text = self.kind, self.buf
        self.kind, self.buf = None, ""
        if kind == "thought":
            return ["(pensando) " + clip(text, 300)] if thinking and text.strip() else []
        if kind != "msg":
            return []
        text = re.sub(r"```(?:json)?\s*\{.*?(```|$)", "", text, flags=re.S).strip()  # o JSON final não vai ao painel
        if text.startswith("{") and extract_json(text) is not None:
            return []
        return [line for line in text.split("\n") if line.strip()]
