"""O laço de uma tarefa: plano → (conselho) → execução → revisão → correção … → takeover → revisão final.
Cada fase é gravada em state.json antes de rodar; `orq resume` recomeça da fase em curso, retomando as sessões.
Porte fiel do loop.sh; as tentativas, a espera no limite de uso e a troca de conta valem para todo harness."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import context, council, harness as harness_mod
from .config import ORQ_HOME, Config
from .control import Control, StopRun
from .harness.base import CallRequest, Harness, shorten_paths
from .store import RunStore

OK_RESULTS = ("ok", "ok_takeover", "skipped")


def render(template: str, **kv) -> str:
    """Troca {{KEY}} pelo valor, literal."""
    for k, v in kv.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def prompt(name: str, **kv) -> str:
    return render((ORQ_HOME / "prompts" / f"{name}.md").read_text(), **kv).rstrip("\n") + "\n"


def schema(name: str) -> dict:
    return json.loads((ORQ_HOME / "schemas" / f"{name}.json").read_text())


def block_push_env(repo: Path) -> dict:
    """`git push` bloqueado nos processos filhos: pushurl inválido para cada remote, por GIT_CONFIG_*."""
    r = subprocess.run(["git", "-C", str(repo), "remote"], capture_output=True, text=True)
    i = int(os.environ.get("GIT_CONFIG_COUNT", "0") or 0)
    env = {}
    for remote in r.stdout.split():
        env[f"GIT_CONFIG_KEY_{i}"] = f"remote.{remote}.pushurl"
        env[f"GIT_CONFIG_VALUE_{i}"] = "blocked://orq-sem-push"
        i += 1
    env["GIT_CONFIG_COUNT"] = str(i)
    return env


def reset_wait(text: str, poll_s: int, now: datetime | None = None) -> int:
    """Segundos até o reset citado na mensagem ('resets 3am', 'resets at 3:30 PM'); sem horário, poll_s."""
    m = re.search(r"resets? (?:at )?(\d{1,2})(?::(\d{2}))? ?(am|pm)?", text, re.I)
    if not m:
        return poll_s
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return poll_s
    now = now or datetime.now()
    target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds()) + 120


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


@dataclass
class Task:
    id: str
    file: Path
    dir: Path
    text: str
    plan_file: Path
    decisions_file: Path
    base_prompt: str = ""


class TaskEnded(Exception):
    """A tarefa terminou (resultado já gravado); o laço volta para a fila."""


class Engine:
    retry_delay = 120  # erro transitório: espera antes de tentar de novo

    def __init__(self, cfg: Config, store: RunStore):
        self.cfg = cfg
        self.s = store
        self.rules = cfg.rules_text()
        self.harnesses: dict[str, Harness] = {}
        self.git_env: dict = {}
        self.stream_mode = str(cfg.get("ui", "stream", default="main"))
        self.thinking = bool(cfg.get("ui", "thinking", default=False))
        self.handled: set[str] = set()   # tarefas por que o laço já passou nesta execução
        self.control = Control(self)

    # --- infraestrutura -----------------------------------------------------------------------------
    def harness(self, name: str) -> Harness:
        if name not in self.harnesses:
            self.harnesses[name] = harness_mod.make(name, self.cfg.queue_dir)
        return self.harnesses[name]

    def task_files(self) -> list[Path]:
        return sorted(p for p in self.cfg.queue_dir.glob("[0-9]*.md") if p.is_file())

    def make_task(self, f: Path) -> Task:
        tid = f.stem
        d = self.s.dir / tid
        (d / "calls").mkdir(parents=True, exist_ok=True)
        return Task(id=tid, file=f, dir=d, text=f.read_text(), plan_file=d / "plan.md", decisions_file=d / "decisions.md")

    def base_prompt(self, t: Task) -> str:
        return prompt("_base", REPO=self.cfg.repo, TASK_ID=t.id, TASK=t.text.rstrip("\n"), RULES=self.rules.rstrip("\n"),
                      PROGRESS=self.progress(t))

    def progress(self, t: Task) -> str:
        return context.progress(self.s.events(), self.task_files(), t.id)

    def with_inbox(self, t: Task | None, sid: str | None, resume: bool, text: str) -> str:
        """Sessão retomada: acrescenta o que o Victor mandou desde o último prompt dela. Sessão nova já recebe
        tudo pelo PROGRESS."""
        if not (t and resume and sid):
            return text
        seen = int(self.s.top("sessions", {}).get(sid, 0))  # nº de eventos quando a sessão recebeu o último prompt
        msgs = context.victor_messages(self.s.events()[seen:], t.id)
        return text + context.inbox_block(msgs) if msgs else text

    def mark_session(self, sid: str | None, seen: int) -> None:
        if sid:
            sessions = self.s.top("sessions", {})
            sessions[sid] = seen
            self.s.set_top("sessions", sessions)

    async def checkpoint(self, t: Task | None) -> None:
        """Ponto seguro entre duas chamadas: pausa e parada pedidas pelo painel valem aqui."""
        await self.control.checkpoint()

    def on_line_for(self, role: str, name: str):
        silent = self.stream_mode == "none" or (self.stream_mode == "main" and role in ("voter", "tiebreak"))
        if silent:
            return lambda line: None
        return lambda line: self.s.stream(f"  [{name}] {shorten_paths(line, self.cfg.repo, self.s.dir)}")

    async def call(self, t: Task | None, role_name: str, name: str, schema_name: str, prompt_text: str,
                   sid: str | None = None, resume: bool = False, gate: bool = True) -> tuple[dict | None, str | None]:
        """Uma chamada a um papel, com as tentativas. → (saída estruturada ou None, id da sessão)."""
        role = self.cfg.roles[role_name]
        h = self.harness(role.harness)
        account = role.account
        calls_dir = (t.dir if t else self.s.dir / "operator") / "calls"
        calls_dir.mkdir(parents=True, exist_ok=True)
        (calls_dir / f"{name}.prompt.md").write_text(prompt_text)
        if not resume and not sid and h.preset_session_ids:
            sid = str(uuid.uuid4())
        waited, tries, asked_again = 0, 0, False
        limit_s = self.cfg.seconds("limit_max_wait")
        tid = t.id if t else ""
        if gate:  # o operador responde mesmo com a execução pausada
            await self.checkpoint(t)
        while True:
            tries += 1
            seen = len(self.s.events())
            full_prompt = self.with_inbox(t, sid, resume, prompt_text)
            acc = f" · conta {account}" if role.harness == "claude" else ""
            self.s.log(f"{name}: {role.harness}{acc} · {role.model} · effort {role.effort} · "
                       f"{'resume' if resume else 'new'} {(sid or '-')[:8]}")
            req = CallRequest(role=role, name=name, prompt=full_prompt, schema=schema(schema_name), cwd=self.cfg.repo,
                              calls_dir=calls_dir, read_only=role_name in ("voter", "tiebreak", "operator"),
                              session_id=sid, resume=resume, timeout=self.cfg.seconds("call_timeout"),
                              env=self.git_env, thinking=self.thinking,
                              account_dir=self.cfg.account_dir(account) if role.harness == "claude" else None)
            res = await h.call(req, self.on_line_for(role_name, name))
            self.mark_session(res.session_id or sid, seen)
            if res.error is None:
                self.s.add_cost(res.cost)
                return res.output, res.session_id or sid
            if res.error == "timeout":
                self.s.notice("timeout", f"{name} passou de {self.cfg.get('time', 'call_timeout')} e foi encerrada.", tid)
                return None, sid
            if res.error == "session_exists" and not resume:
                resume = True  # retomada depois de uma queda: a sessão "nova" já existe
                continue
            if res.error == "limit":
                fb = self.cfg.fallback_account
                if role.harness == "claude" and fb and fb != account:
                    self.s.notice("account_switch", f"Limite de uso na conta {account} em {name}; trocando para a conta {fb}.", tid)
                    account = fb  # resume funciona entre contas: projects/ é compartilhado
                    continue
                wait_s = reset_wait(res.message, self.cfg.seconds("limit_poll"))
                if waited + wait_s > limit_s:
                    self.s.notice("limit_giveup", f"Limite de uso em {name}; a espera passaria de "
                                  f"{self.cfg.get('time', 'limit_max_wait')}. Chamada abandonada.", tid)
                    return None, sid
                self.s.notice("limit_wait", f"Limite de uso em {name} ({role.harness}); esperando {wait_s // 60} min.", tid)
                await asyncio.sleep(wait_s)
                waited += wait_s
                if not resume and res.session_id:
                    resume, sid = True, res.session_id
                continue
            if res.error == "transient" and tries < 5:
                self.s.log(f"{name}: erro transitório (tentativa {tries}), nova tentativa em {self.retry_delay} s")
                await asyncio.sleep(self.retry_delay)
                if not resume and res.session_id:
                    resume, sid = True, res.session_id
                continue
            if res.error == "no_output" and not asked_again and res.session_id:
                self.s.log(f"{name}: resposta sem saída estruturada; retomando a sessão uma vez")
                asked_again, resume, sid = True, True, res.session_id
                prompt_text = "Responda de novo, preenchendo a saída estruturada do schema pedido.\n"
                continue
            self.s.notice("error", f"{name} falhou ({res.error}): {res.message}", tid)
            return None, sid

    # --- fila ---------------------------------------------------------------------------------------
    def start_event(self) -> None:
        r = self.cfg.roles
        self.s.event("run_start", {
            "queue": self.cfg.queue_dir.parent.name if self.cfg.queue_dir.name == "orq" else self.cfg.queue_dir.name,
            "repo": str(self.cfg.repo), "account": str(self.cfg.get("accounts", "claude", "default")),
            "planner": r["planner"].label(), "executor": r["executor"].label(), "voter": r["voter"].label(),
            "tiebreak": r["tiebreak"].label(), "voters": self.cfg.voters, "max_cycles": self.cfg.max_cycles})

    async def run(self) -> bool:
        self.git_env = block_push_env(self.cfg.repo)
        if not self.task_files():
            raise SystemExit(f"orq: fila sem tarefas (NN-nome.md) em {self.cfg.queue_dir}")
        poller = asyncio.create_task(self.control.loop())
        try:
            return await self._run_queue()
        except StopRun:
            self.s.notice("stopped", f"Execução parada pelo painel. Continue com: orq resume {self.s.dir}")
            return True
        finally:
            poller.cancel()

    async def _run_queue(self) -> bool:
        failed, stop = 0, False
        while not stop:
            await self.checkpoint(None)
            todo = [f for f in self.task_files() if f.stem not in self.handled]  # relida a cada tarefa: /add entra aqui
            if not todo:
                break
            f = todo[0]
            self.handled.add(f.stem)
            if self.s.get(f.stem, "phase") != "done":
                self.s.log(f"=== tarefa: {f.name}")
                await self.run_task(f)
            if self.s.get(f.stem, "result") not in OK_RESULTS:
                failed += 1
                if self.cfg.on_fail == "stop":
                    stop = True
                    self.s.log("on_fail = stop: a fila para aqui")
        self.control.drain()
        n = len(self.task_files())
        if stop:
            summary = f"parada na tarefa que falhou ({failed} com problema)"
        elif failed:
            summary = f"{failed} tarefa(s) com problema"
        else:
            summary = f"todas as {n} tarefas ok"
        cost = f"{self.s.cost():.4f}"
        self.s.event("run_end", {"result": summary, "cost": cost})
        self.s.log(f"fim: {summary} · journal: {self.s.journal_path}")
        notify(f"Fila terminou: {summary}")
        return failed == 0

    # --- tarefa -------------------------------------------------------------------------------------
    async def run_task(self, f: Path) -> None:
        t = self.make_task(f)
        try:
            await self._run_task(t)
        except TaskEnded:
            pass

    def end(self, t: Task, result: str, reason: str):
        started = self.s.get(t.id, "started", int(time.time()))
        self.s.set(t.id, "phase", "done")
        self.s.set(t.id, "result", result)
        self.s.event("task_end", {"task": t.id, "result": result, "reason": reason,
                                  "duration_s": int(time.time()) - int(started), "cycles": self.s.get(t.id, "cycle", 1)})
        raise TaskEnded

    async def _run_task(self, t: Task) -> None:
        s = self.s
        repo = self.cfg.repo
        phase = s.get(t.id, "phase", "start")
        if phase == "done":
            return
        while True:
            t.base_prompt = self.base_prompt(t)  # refeito a cada fase: o PROGRESS muda com a fila
            s.set(t.id, "phase", phase)
            cycle = s.get(t.id, "cycle", 1)
            psid = s.get(t.id, "planner_sid")

            if phase == "start":
                dirty = git(repo, "status", "--porcelain")
                if dirty:
                    s.set(t.id, "started", int(time.time()))
                    self.end(t, "blocked", "Árvore de trabalho suja antes de começar: " + " ".join(dirty.splitlines()[:5]))
                base = git(repo, "rev-parse", "HEAD") or "none"
                s.set(t.id, "base", base)
                s.set(t.id, "started", int(time.time()))
                s.set(t.id, "cycle", 1)
                s.event("task_start", {"task": t.id, "base": base, "task_file": str(t.file)})
                phase = "plan"

            elif phase == "plan":
                out, sid = await self.call(t, "planner", "plan", "plan",
                                           prompt("plan", BASE=t.base_prompt, PLAN_FILE=t.plan_file))
                if out is None:
                    self.end(t, "failed", "O planejamento falhou (ver orq.log).")
                s.set(t.id, "planner_sid", sid)
                (t.dir / "plan.out.json").write_text(json.dumps(out, ensure_ascii=False))
                s.event("plan", {"task": t.id, "summary": out["summary"], "plan_rel": f"{t.id}/plan.md"})
                phase = "plan_questions"

            elif phase == "plan_questions":
                out = json.loads((t.dir / "plan.out.json").read_text())
                rc, answers = await self.resolve_questions(t, "planejador", out)
                if rc == 1:
                    phase = "exec"
                elif rc == 2:
                    self.end(t, "failed", "O conselho não decidiu uma dúvida do plano.")
                else:
                    out, _ = await self.call(t, "planner", f"plan-update-{hms()}", "plan",
                                             prompt("plan_update", ANSWERS=answers, PLAN_FILE=t.plan_file), psid, resume=True)
                    if out is None:
                        self.end(t, "failed", "A atualização do plano falhou.")
                    (t.dir / "plan.out.json").write_text(json.dumps(out, ensure_ascii=False))  # volta a conferir perguntas

            elif phase == "exec":
                esid = s.get(t.id, "exec_sid")
                if not s.get(t.id, "next_exec_prompt"):
                    p = t.dir / "exec.prompt.md"
                    p.write_text(prompt("execute", BASE=t.base_prompt, PLAN_FILE=t.plan_file, DECISIONS_FILE=t.decisions_file))
                    s.set(t.id, "next_exec_prompt", str(p))
                    s.set(t.id, "exec_mode", "new")
                resume = s.get(t.id, "exec_mode", "new") == "resume"
                out, sid = await self.call(t, "executor", f"exec-{cycle}-{hms()}", "execute",
                                           Path(s.get(t.id, "next_exec_prompt")).read_text(), esid, resume=resume)
                if out is None:
                    self.end(t, "failed", f"A execução (ciclo {cycle}) falhou.")
                s.set(t.id, "exec_sid", sid)
                s.set(t.id, "exec_mode", "resume")
                (t.dir / f"exec-{cycle}.out.json").write_text(json.dumps(out, ensure_ascii=False))
                self.exec_event(t, out, cycle, f"executor, {self.cfg.roles['executor'].label()}")
                phase = await self.after_exec(t, out, "exec_answers", "review")

            elif phase == "exec_answers":
                p = t.dir / f"exec_answers-{hms()}.prompt.md"
                p.write_text(prompt("exec_answers", ANSWERS=(t.dir / "answers.last").read_text(),
                                    DECISIONS_FILE=t.decisions_file))
                s.set(t.id, "next_exec_prompt", str(p))
                phase = "exec"

            elif phase == "review":
                report = _read(t.dir / f"exec-{cycle}.out.json", "{}")
                verdict, review_md = await self.review(t, "planner", psid, True, report, "executor", cycle)
                if verdict == "approved":
                    self.end(t, "ok", f"Aprovada pelo revisor no ciclo {cycle}.")
                if cycle < self.cfg.max_cycles:
                    cycle += 1
                    s.set(t.id, "cycle", cycle)
                    p = t.dir / f"fix-{cycle}.prompt.md"
                    p.write_text(prompt("fix", CYCLE=cycle - 1, MAX_CYCLES=self.cfg.max_cycles, REVIEW=review_md))
                    s.set(t.id, "next_exec_prompt", str(p))
                    phase = "exec"
                else:
                    (t.dir / "takeover.prompt.md").write_text(
                        prompt("takeover", MAX_CYCLES=self.cfg.max_cycles, REVIEW=review_md))
                    phase = "takeover"

            elif phase == "takeover":
                out, _ = await self.call(t, "planner", f"takeover-{hms()}", "execute",
                                         (t.dir / "takeover.prompt.md").read_text(), psid, resume=True)
                if out is None:
                    self.end(t, "failed", "O takeover do planejador falhou.")
                (t.dir / "takeover.out.json").write_text(json.dumps(out, ensure_ascii=False))
                self.exec_event(t, out, cycle + 1, f"planejador assumiu, {self.cfg.roles['planner'].label()}")
                phase = await self.after_exec(t, out, "takeover_answers", "final_review")

            elif phase == "takeover_answers":
                (t.dir / "takeover.prompt.md").write_text(prompt(
                    "exec_answers", ANSWERS=(t.dir / "answers.last").read_text(), DECISIONS_FILE=t.decisions_file))
                phase = "takeover"

            elif phase == "final_review":
                rsid = s.get(t.id, "final_review_sid")
                report = _read(t.dir / "takeover.out.json", "{}")
                verdict, _ = await self.review(t, "reviewer", rsid, bool(rsid), report,
                                               "planejador, depois de assumir", cycle + 1, sid_key="final_review_sid")
                if verdict == "approved":
                    self.end(t, "ok_takeover", f"O executor não passou em {self.cfg.max_cycles} ciclos; "
                                               "o planejador assumiu e um revisor novo aprovou.")
                self.end(t, "failed", "Nem o takeover do planejador passou na revisão independente.")
            else:
                raise RuntimeError(f"fase desconhecida: {phase}")

    def exec_event(self, t: Task, out: dict, cycle: int, actor: str) -> None:
        self.s.event("exec", {"task": t.id, "cycle": cycle, "actor": actor, **{
            k: out.get(k) for k in ("status", "summary", "commits", "checks", "pending")}})

    async def after_exec(self, t: Task, out: dict, answers_phase: str, nxt: str) -> str:
        status = out.get("status")
        if status == "blocked":
            self.end(t, "blocked", out.get("summary", ""))
        if status == "needs_decision":
            rc, answers = await self.resolve_questions(t, "executor", out)
            if rc == 0:
                (t.dir / "answers.last").write_text(answers)
                return answers_phase
            if rc == 2:
                self.end(t, "failed", "O conselho não decidiu uma dúvida do executor.")
        return nxt

    async def review(self, t: Task, role: str, sid: str | None, resume: bool, report: str, actor: str, cycle: int,
                     sid_key: str | None = None) -> tuple[str, str]:
        out, new_sid = await self.call(t, role, f"review-{cycle}-{hms()}", "review", prompt(
            "review", BASE=t.base_prompt, PLAN_FILE=t.plan_file, DECISIONS_FILE=t.decisions_file,
            BASE_SHA=self.s.get(t.id, "base"), ACTOR=actor, CYCLE=cycle, EXEC_REPORT=report), sid, resume=resume)
        if out is None:
            self.end(t, "failed", f"A revisão (ciclo {cycle}) falhou.")
        if sid_key:
            self.s.set(t.id, sid_key, new_sid)
        if self.cfg.get("test", "force_changes") and role == "planner":
            out["verdict"] = "changes"
            out.setdefault("issues", []).append({"severity": "media", "where": "(teste)",
                                                 "what": "reprovação forçada por test.force_changes", "fix": "nada"})
        (t.dir / f"review-{cycle}.out.json").write_text(json.dumps(out, ensure_ascii=False))
        who = f"planejador, {self.cfg.roles['planner'].label()}" if role == "planner" \
            else f"revisor em sessão nova, {self.cfg.roles['reviewer'].label()}"
        self.s.event("review", {"task": t.id, "cycle": cycle, "reviewer": who, **{
            k: out.get(k) for k in ("verdict", "summary", "highlights", "issues")}})
        rc, answers = await self.resolve_questions(t, "revisor", out)
        if rc == 2:
            self.end(t, "failed", "O conselho não decidiu uma dúvida do revisor.")
        md = f"Resumo: {out.get('summary', '')}\n\nProblemas:\n" + "\n".join(
            f"- [{i['severity']}] {i['where']}: {i['what']} → {i['fix']}" for i in out.get("issues") or [])
        if rc == 0:
            md += "\n\nDecisões do conselho sobre as dúvidas do revisor:\n" + answers
        return out.get("verdict", "changes"), md

    async def resolve_questions(self, t: Task, source: str, out: dict) -> tuple[int, str]:
        """0 = havia perguntas e todas decididas · 1 = nenhuma pergunta · 2 = falha."""
        qs = out.get("questions") or []
        if not qs:
            return 1, ""
        rounds = self.s.get(t.id, "decision_rounds", 0) + 1
        self.s.set(t.id, "decision_rounds", rounds)
        if rounds > self.cfg.max_decision_rounds:
            self.s.notice("error", f"Passou de {self.cfg.max_decision_rounds} rodadas de conselho: laço de dúvidas.", t.id)
            return 2, ""
        answers = ""
        for q in qs:
            a = await council.decide(self, t, source, q)
            if a is None:
                return 2, ""
            answers += a + "\n"
        return 0, answers


def hms() -> str:
    return datetime.now().strftime("%H%M%S")


def _read(p: Path, default: str) -> str:
    return p.read_text() if p.exists() else default


def notify(msg: str) -> None:
    if (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and subprocess.run(
            ["sh", "-c", "command -v notify-send"], capture_output=True).returncode == 0:
        subprocess.run(["notify-send", "orq", msg], capture_output=True)
