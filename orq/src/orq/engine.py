"""O laço de uma tarefa: plano → (conselho) → execução → revisão → correção … → takeover → revisão final.
Com `[plan] ahead`, antes da primeira execução o planejador rascunha o plano de todas as tarefas, em ordem, o dono
aprova (com prazo) e cada tarefa revalida o próprio rascunho quando começa.
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

from . import context, council, harness as harness_mod, intervene, notify
from .config import ORQ_HOME, Config, ConfigError, parse_duration
from .control import Control, StopRun
from .journal import OK_USER
from .harness.base import CallRequest, Harness, run_process, shorten_paths
from .store import RunStore, active_seconds, now_iso, queue_label

OK_RESULTS = ("ok", "ok_takeover", OK_USER, "skipped")


def render(template: str, **kv) -> str:
    """Troca {{KEY}} pelo valor, literal."""
    for k, v in kv.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def prompt(name: str, **kv) -> str:
    return render((ORQ_HOME / "prompts" / f"{name}.md").read_text(), **kv).rstrip("\n") + "\n"


def schema(name: str) -> dict:
    return json.loads((ORQ_HOME / "schemas" / f"{name}.json").read_text())


PUSH_URL_PREFIXES = ("https://", "http://", "ssh://", "git://", "git+ssh://", "file://", "git@", "/", "./", "../", "~")


def block_push_env(repo: Path | list[Path]) -> dict:
    """`git push` bloqueado nos processos filhos, por GIT_CONFIG_*: pushurl inválido para cada remote e, para
    `git push <url>`, toda URL de push reescrita (pushInsteadOf) para um protocolo que não existe. O fetch não muda.
    É trava contra o reflexo do agente, não contra quem limpa o ambiente de propósito: isso é do sandbox."""
    repos = [repo] if isinstance(repo, Path) else repo
    remotes = set()
    for path in repos:
        r = subprocess.run(["git", "-C", str(path), "remote"], capture_output=True, text=True, check=True)
        remotes.update(r.stdout.split())
    i = int(os.environ.get("GIT_CONFIG_COUNT", "0") or 0)
    env = {}
    for remote in sorted(remotes):
        env[f"GIT_CONFIG_KEY_{i}"] = f"remote.{remote}.pushurl"
        env[f"GIT_CONFIG_VALUE_{i}"] = "blocked://orq-sem-push"
        i += 1
    for prefix in PUSH_URL_PREFIXES:
        env[f"GIT_CONFIG_KEY_{i}"] = "url.blocked://orq-sem-push/.pushInsteadOf"
        env[f"GIT_CONFIG_VALUE_{i}"] = prefix
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
    cfg: Config | None = None


class Problem(Exception):
    """A tarefa não consegue seguir sozinha. Com [intervene], vira pergunta ao usuário; sem, encerra a tarefa."""

    def __init__(self, result: str, reason: str, phase: str):
        super().__init__(reason)
        self.result, self.reason, self.phase = result, reason, phase


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
        self.redrafts: dict[str, asyncio.Task] = {}  # /plan em curso, por tarefa: a revalidação espera
        self.control = Control(self)
        self.notifier = notify.load()  # None: sem ~/.config/orq/notify.toml, só o notify-send

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
        cfg = self.cfg.task_config(tid)
        saved_repo = self.s.get(tid, "repo")
        if saved_repo and saved_repo != str(cfg.repo):
            raise ConfigError(f"repositório da tarefa {tid} mudou: {saved_repo} → {cfg.repo}")
        return Task(cfg=cfg, id=tid, file=f, dir=d, text=f.read_text(), plan_file=d / "plan.md", decisions_file=d / "decisions.md")

    def task_config(self, t: Task | None) -> Config:
        return (t.cfg or self.cfg.task_config(t.id)) if t else self.cfg

    def task_env(self, t: Task | None) -> dict:
        return {**self.git_env, "ORQ_TASK_ID": t.id if t else "",
                "ORQ_TASK_REPO": str(self.task_config(t).repo),
                "ORQ_QUEUE_DIR": str(self.cfg.queue_dir), "ORQ_RUN_DIR": str(self.s.dir)}

    def base_prompt(self, t: Task) -> str:
        return prompt("_base", REPO=self.task_config(t).repo, TASK_ID=t.id, TASK=t.text.rstrip("\n"), RULES=self.task_config(t).rules_text().rstrip("\n"),
                      PROGRESS=self.progress(t))

    def progress(self, t: Task) -> str:
        return context.progress(self.s.events(), self.task_files(), t.id)

    def with_inbox(self, t: Task | None, sid: str | None, resume: bool, text: str) -> str:
        """Sessão retomada: acrescenta o que o usuário mandou desde o último prompt dela. Sessão nova já recebe
        tudo pelo PROGRESS."""
        if not (t and resume and sid):
            return text
        seen = int(self.s.top("sessions", {}).get(sid, 0))  # nº de eventos quando a sessão recebeu o último prompt
        msgs = context.user_messages(self.s.events()[seen:], t.id)
        return text + context.inbox_block(msgs) if msgs else text

    def mark_session(self, sid: str | None, seen: int) -> None:
        if sid:
            sessions = self.s.top("sessions", {})
            sessions[sid] = seen
            self.s.set_top("sessions", sessions)

    async def checkpoint(self, t: Task | None) -> None:
        """Ponto seguro entre duas chamadas: pausa e parada pedidas pelo painel valem aqui."""
        await self.control.checkpoint()

    def on_line_for(self, role: str, name: str, task: str = ""):
        silent = self.stream_mode == "none" or (self.stream_mode == "main" and role in ("voter", "tiebreak"))
        if silent:
            return lambda line: None
        return lambda line: self.s.stream(f"  [{name}] {shorten_paths(line, self.cfg.repo, self.s.dir)}", task)

    async def call(self, t: Task | None, role_name: str, name: str, schema_name: str, prompt_text: str,
                   sid: str | None = None, resume: bool = False, gate: bool = True, read_only: bool = False) -> tuple[dict | None, str | None]:
        """Uma chamada a um papel, com as tentativas. → (saída estruturada ou None, id da sessão)."""
        role = self.cfg.roles[role_name]
        h = self.harness(role.harness)
        account = role.account
        calls_dir = (t.dir if t else self.s.dir / role_name) / "calls"
        calls_dir.mkdir(parents=True, exist_ok=True)
        (calls_dir / f"{name}.prompt.md").write_text(prompt_text)
        tid = t.id if t else ""
        key = f"{tid}:{role_name}:{re.sub(r'-[0-9]{6}$', '', name)}"
        active = self.s.top("active_calls", {}).get(key)
        if active:
            sid, resume = active["sid"], active["resume"]
            account = active.get("account", account)
        if not resume and not sid and h.preset_session_ids:
            sid = str(uuid.uuid4())

        def save_session(new_sid: str | None, can_resume: bool = True):
            record = {"sid": new_sid, "resume": can_resume, "account": account}
            calls = self.s.top("active_calls", {})
            if calls.get(key) != record:
                calls[key] = record
                self.s.set_top("active_calls", calls)

        def finish(output, result_sid):
            calls = self.s.top("active_calls", {})
            calls.pop(key, None)
            self.s.set_top("active_calls", calls)
            if tid and role_name not in ("voter", "tiebreak"):  # o conselho grava uma etapa só (council.decide)
                self.s.event("step", {"task": tid, "role": role_name, "call": name, "started": started_iso,
                                      "duration_s": round(time.time() - t0, 1), "waited_s": waited + retried,
                                      "tries": tries, "cost": round(cost_sum, 4), "ok": output is not None})
            return output, result_sid

        save_session(sid, resume)
        t0, started_iso, retried, cost_sum = time.time(), now_iso(), 0, 0.0
        waited, tries, asked_again = 0, 0, False
        limit_s = self.cfg.seconds("limit_max_wait")
        while True:
            if gate:  # o operador (gate=False) responde mesmo com a execução pausada
                await self.checkpoint(t)
            tries += 1
            seen = len(self.s.events())
            full_prompt = self.with_inbox(t, sid, resume, prompt_text)
            acc = f" · conta {account}" if role.harness == "claude" else ""
            self.s.log(f"{name}: {role.harness}{acc} · {role.model} · effort {role.effort} · "
                       f"{'resume' if resume else 'new'} {(sid or '-')[:8]}", tid)
            req = CallRequest(role=role, name=name, prompt=full_prompt, schema=schema(schema_name), cwd=self.task_config(t).repo,
                              calls_dir=calls_dir, read_only=read_only or role_name in ("voter", "tiebreak", "operator"),
                              session_id=sid, resume=resume, timeout=self.cfg.seconds("call_timeout"),
                              env=self.task_env(t), thinking=self.thinking, sandbox=role.sandbox == "home",
                              on_session=save_session,
                              account_dir=self.cfg.claude_config_env(account) if role.harness == "claude" else None)
            self.s.active_start(tid)
            try:
                res = await h.call(req, self.on_line_for(role_name, name, tid))
            finally:
                self.s.active_stop(tid)
            self.s.add_cost(res.cost, tid, role_name)
            cost_sum += res.cost or 0
            if res.session_id:
                save_session(res.session_id)
            self.mark_session(res.session_id or sid, seen)
            if res.error is None:
                return finish(res.output, res.session_id or sid)
            if res.error == "timeout":
                self.s.notice("timeout", f"{name} passou de {self.cfg.get('time', 'call_timeout')} e foi encerrada.", tid)
                return finish(None, res.session_id or sid)
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
                    return finish(None, res.session_id or sid)
                self.s.notice("limit_wait", f"Limite de uso em {name} ({role.harness}); esperando {wait_s // 60} min.", tid)
                if wait_s >= 1800:
                    self.notify(f"orq {self.queue_name()} · limite de uso", f"{name}: esperando {wait_s // 60} min.")
                await self.wait_retry(wait_s, t, gate)
                waited += wait_s
                if not resume and res.session_id:
                    resume, sid = True, res.session_id
                continue
            if res.error == "transient" and tries < 5:
                self.s.log(f"{name}: erro transitório (tentativa {tries}), nova tentativa em {self.retry_delay} s")
                await self.wait_retry(self.retry_delay, t, gate)
                retried += self.retry_delay
                if not resume and res.session_id:
                    resume, sid = True, res.session_id
                continue
            if res.error == "no_output" and not asked_again and res.session_id:
                self.s.log(f"{name}: resposta sem saída estruturada; retomando a sessão uma vez")
                asked_again, resume, sid = True, True, res.session_id
                prompt_text = "Responda de novo, preenchendo a saída estruturada do schema pedido.\n"
                continue
            if res.error == "background_killed" and not asked_again and (res.session_id or sid):
                self.s.notice("background_killed", f"{name}: {res.message}; retomando a sessão uma vez", tid)
                asked_again, resume, sid = True, True, res.session_id or sid
                prompt_text = ("A sessão anterior terminou com um subagent em background, que foi encerrado sem "
                               "terminar: o resultado dele se perdeu. Confira `git status` e `git log`, termine você "
                               "mesmo, em primeiro plano, e só então devolva a saída estruturada.\n")
                continue
            self.s.notice("error", f"{name} falhou ({res.error}): {res.message}", tid)
            return finish(None, res.session_id or sid)

    async def wait_retry(self, seconds: float, t: Task | None, gate: bool) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if gate:
                await self.checkpoint(t)
            elif self.control.stop:
                raise StopRun
            await asyncio.sleep(min(self.control.poll_interval, max(0, end - time.monotonic())))

    # --- fila ---------------------------------------------------------------------------------------
    def queue_name(self) -> str:
        return queue_label(self.cfg.queue_dir)

    def notify(self, title: str, message: str, priority: int = 3, actions=()) -> None:
        """notify-send no desktop e, com notify.toml, ntfy no celular. Falha de rede só vai para o log."""
        notify.desktop(f"{title}: {message}")
        # ntfy.sh é público: o título (só fila, tarefa e palavras fixas) sai; a mensagem, texto livre, fica no desktop
        external_message = "Consulte o painel para ver o resultado e os detalhes da execução."
        if self.notifier and not notify.publish(self.notifier, title, external_message, priority, actions=actions):
            self.s.log("aviso: o ntfy não respondeu (a execução segue)")

    def start_event(self) -> None:
        self.s.set_top("config", self.cfg.raw)
        r = self.cfg.roles
        self.s.event("run_start", {
            "queue": self.queue_name(),
            "repo": str(self.cfg.repo), "account": str(self.cfg.get("accounts", "claude", "default")),
            "planner": r["planner"].label(), "executor": r["executor"].label(), "voter": r["voter"].label(),
            "tiebreak": r["tiebreak"].label(), "voters": self.cfg.voters, "max_cycles": self.cfg.max_cycles})

    async def run(self) -> bool:
        self.git_env = block_push_env(self.cfg.repos)
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
            jobs = list(self.control.background)
            for job in jobs:
                job.cancel()
            await asyncio.gather(poller, *jobs, return_exceptions=True)

    # --- planos antecipados ([plan] ahead) ------------------------------------------------------------
    def drafted(self) -> list[Path]:
        return [f for f in self.task_files() if self.s.get(f.stem, "draft")]

    async def draft_plans(self) -> None:
        """Rascunho encadeado: um plano por tarefa pendente, em ordem, cada um lendo os anteriores. Depois, a
        aprovação do dono. Rascunho que falha não derruba nada: dali em diante as tarefas planejam na hora delas."""
        if not self.cfg.get("plan", "ahead", default=False):
            return
        stage = (self.s.top("plan_ahead") or {}).get("phase")
        if stage == "done":
            return
        if stage != "approve":
            for f in self.task_files():
                if self.s.get(f.stem, "phase") or self.s.get(f.stem, "draft"):
                    continue
                await self.checkpoint(None)
                self.s.set_top("plan_ahead", {"phase": "draft", "task": f.stem, "since": time.time()})
                if not await self.draft(self.make_task(f)):
                    self.s.notice("error", "O rascunho do plano falhou; esta tarefa e as seguintes planejam quando "
                                  "começarem (ver orq.log).", f.stem)
                    break
        self.s.set_top("plan_ahead", {"phase": "approve"})
        try:
            await self.approve_plans()
        except StopRun:  # parar na aprovação também conta como visto: o resume começa a executar
            self.s.set_top("plan_ahead", {"phase": "done"})
            raise
        self.s.set_top("plan_ahead", {"phase": "done"})

    async def draft(self, t: Task) -> bool:
        s = self.s
        t.base_prompt = self.base_prompt(t)
        prev = "\n".join(f"- `{f.stem}`: {s.dir / f.stem / 'plan.md'}" for f in self.drafted()) \
            or "(nenhum: esta é a primeira tarefa da fila)"
        before = self.repo_mark(t)
        out, sid = await self.call(t, "planner", "plan-draft", "plan",
                                   prompt("plan_draft", BASE=t.base_prompt, PLAN_FILE=t.plan_file, PREVIOUS=prev))
        if out is None:
            return False
        self.warn_if_wrote(t, "O planejador", before)
        s.set(t.id, "planner_sid", sid)
        while True:  # dúvidas do rascunho vão ao conselho (e ao dono) já aqui, antes de a fila andar
            rc, answers = await self.resolve_questions(t, "planejador", out)
            if rc == 1:
                break
            if rc == 2:
                return False
            out, _ = await self.call(t, "planner", f"plan-update-{hms()}", "plan",
                                     prompt("plan_update", ANSWERS=answers, PLAN_FILE=t.plan_file), sid, resume=True)
            s.set(t.id, "partial_answers", None)
            if out is None:
                return False
        s.update_task(t.id, {"draft": "draft", "decision_rounds": 0})
        s.event("plan", {"task": t.id, "summary": out["summary"], "plan_rel": f"{t.id}/plan.md", "draft": True})
        return True

    async def approve_plans(self) -> None:
        timeout = parse_duration(self.cfg.get("plan", "approve_timeout", default="30m"))
        drafted = self.drafted()
        if not timeout or not drafted:
            return
        ask = self.s.top("open_ask") or {}
        if ask.get("kind") != "plans":  # resume com a pergunta aberta: a mesma, com o prazo que ela já tinha
            ask = intervene.new_ask(
                drafted[0].stem, "plans", "plan", f"Planos de {len(drafted)} tarefa(s) prontos. Começar a execução?",
                "Leia e ajuste os planos na interface web (aba Plano de cada tarefa) antes de responder. "
                "Sem resposta, a execução começa sozinha no prazo.",
                [{"id": "start", "label": "Começar a execução"},
                 {"id": "stop", "label": "Parar a fila para eu revisar com calma (orq resume continua)"}],
                "start", deadline=time.time() + timeout)
        text = await intervene.wait(self, ask)
        opt = intervene.match_option(ask, text) if text else None
        if text and not opt:  # texto livre: vale como nota para todas as tarefas, e a fila começa
            self.s.event("note", {"text": text, "for_task": "", "command_id": f"ask-{ask['id']}"})
        intervene.close(self, ask, action="timeout" if text is None else (opt or {"id": "start"})["id"],
                        note="" if opt or text is None else text)
        if opt and opt["id"] == "stop":
            raise StopRun

    def plan_edits(self, t: Task) -> str:
        lines = []
        for e in self.s.events():
            if e["type"] == "plan_edit" and e.get("task") == t.id:
                lines.append(f"- ({e['ts'][11:16]}) " + (f"Instrução do dono: {e['instruction']}" if e.get("instruction") else
                             "O dono editou o plano à mão: o texto que está no arquivo é dele."))
        return "\n".join(lines) or "(nenhum)"

    def revalidate_prompt(self, t: Task) -> str:
        return prompt("plan_revalidate", PLAN_FILE=t.plan_file, TASK=t.text.rstrip("\n"), PROGRESS=self.progress(t),
                      EDITS=self.plan_edits(t))

    def launch_redraft(self, tid: str) -> None:
        """/plan: o planejador refaz o rascunho em segundo plano (só escreve o arquivo do plano). Pedidos para a
        mesma tarefa rodam em fila: a sessão é uma só."""
        prev = self.redrafts.get(tid)

        async def job():
            if prev:
                await asyncio.gather(prev, return_exceptions=True)
            f = next((f for f in self.task_files() if f.stem == tid), None)
            if not f or self.s.get(tid, "phase"):
                return  # a tarefa começou antes: a instrução entra na revalidação (plan_edits)
            t = self.make_task(f)
            out, _ = await self.call(t, "planner", f"plan-redraft-{hms()}", "plan", self.revalidate_prompt(t),
                                     self.s.get(tid, "planner_sid"), resume=True, gate=False)
            if out is None:
                self.s.notice("error", "O planejador não refez o rascunho; a instrução vale na revalidação.", tid)
                return
            # dúvida nova aqui não vai ao conselho: a revalidação, quando a tarefa começar, a levanta de novo
            self.s.event("plan", {"task": tid, "summary": out["summary"], "plan_rel": f"{tid}/plan.md", "draft": True,
                                  "revised": True})

        task = asyncio.get_running_loop().create_task(job())
        self.redrafts[tid] = task
        self.control.background.add(task)
        task.add_done_callback(self.control.background.discard)

    async def _run_queue(self) -> bool:
        failed, stop = 0, False
        await self.draft_plans()
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
        skipped = sum(1 for f in self.task_files() if self.s.get(f.stem, "result") == "skipped")
        if stop:
            summary = f"parada na tarefa que falhou ({failed} com problema)"
        elif failed:
            summary = f"{failed} tarefa(s) com problema"
        elif skipped:
            summary = f"{n - skipped} tarefa(s) ok, {skipped} pulada(s)"
        else:
            summary = f"todas as {n} tarefas ok"
        if self.cfg.get("report", "llm_summary", default=True) and any(e["type"] == "task_end" for e in self.s.events()):
            await self.summarize()
        cost = f"{self.s.cost():.4f}"
        by_role: dict[str, float] = {}
        for roles in self.s.cost_by().values():
            for r, v in roles.items():
                by_role[r] = round(by_role.get(r, 0) + v, 4)
        self.s.event("run_end", {"result": summary, "cost": cost, "cost_by_role": by_role,
                                 "cost_unknown": self.s.unknown_costs()})
        self.s.log(f"fim: {summary} · journal: {self.s.journal_path}")
        self.notify(f"orq {self.queue_name()} terminou", summary)
        return failed == 0

    async def summarize(self) -> None:
        """Resumo final escrito pelo planejador (sessão nova, só leitura); falhou, fica o resumo determinístico."""
        base = next((e["base"] for e in self.s.events() if e["type"] == "task_start"
                     and e.get("repo", str(self.cfg.repo)) == str(self.cfg.repo)), "HEAD")
        out, _ = await self.call(None, "planner", f"summary-{hms()}", "summary", prompt(
            "summary", REPO=self.cfg.repo, RUN_DIR=self.s.dir, BASE=base) +
            "\nRepositórios e bases por tarefa (use cada SHA apenas no respectivo repositório):\n" +
            "\n".join(f"{e['task']}: {e.get('repo', str(self.cfg.repo))} base {e['base']}"
                      for e in self.s.events() if e["type"] == "task_start"), read_only=True)
        if out is None:
            self.s.notice("error", "O resumo final (LLM) falhou; o journal segue com o resumo determinístico.")
            return
        self.s.event("run_summary", {"text": out["narrative"]})

    # --- tarefa -------------------------------------------------------------------------------------
    async def run_task(self, f: Path) -> None:
        t = self.make_task(f)
        try:
            await self._run_task(t)
        except TaskEnded:
            pass

    def end(self, t: Task, result: str, reason: str):
        started = self.s.get(t.id, "started", int(time.time()))
        base = self.s.get(t.id, "base")
        delivery = {"commits": git(self.task_config(t).repo, "log", "--oneline", f"{base}..HEAD").splitlines(),
                    "stat": git(self.task_config(t).repo, "diff", "--stat", f"{base}..HEAD"),
                    "numstat": git(self.task_config(t).repo, "diff", "--numstat", f"{base}..HEAD")} if base and base != "none" else {}
        if result in OK_RESULTS and result != "skipped" and git(self.task_config(t).repo, "rev-parse", "HEAD") == base:
            self.s.notice("no_commits", "A tarefa terminou ok sem nenhum commit: confira se era isso mesmo.", t.id)
        self.s.update_task(t.id, {"phase": "done", "result": result})
        self.s.event("task_end", {"task": t.id, "repo": str(self.task_config(t).repo), "result": result, "reason": reason,
                                  "duration_s": int(time.time()) - int(started), "cycles": self.s.get(t.id, "cycle", 1),
                                  "active_s": int(self.s.get(t.id, "active_s", 0) or 0),
                                  "cost": self.s.cost_by().get(t.id, {}), "delivery": delivery,
                                  "cost_unknown": sum(self.s.top("cost_unknown", {}).get(t.id, {}).values())})
        raise TaskEnded

    async def _run_task(self, t: Task) -> None:
        s = self.s
        repo = self.task_config(t).repo
        s.set(t.id, "repo", str(repo))
        phase = s.get(t.id, "phase", "start")
        if phase == "done":
            return
        if s.get(t.id, "active_since"):  # queda no meio de uma chamada: o tempo até aqui não foi trabalho
            s.set(t.id, "active_since", None)
        while True:
            open_ = s.top("open_ask") or {}
            if open_.get("task") == t.id and open_.get("kind") in ("failed", "blocked"):  # resume: mesma pergunta
                phase = await self.problem(t, Problem(open_["kind"], open_.get("reason", ""), open_["phase"]), ask=open_)
            try:
                t.base_prompt = self.base_prompt(t)  # refeito a cada fase: o PROGRESS muda com a fila
                s.set(t.id, "phase", phase)
                over = self.over_budget(t)
                if over and not s.get(t.id, "budget_asked"):
                    s.set(t.id, "budget_asked", True)  # pergunta uma vez por tarefa; retry segue sem perguntar de novo
                    raise Problem("failed", over, phase)
                cycle = s.get(t.id, "cycle", 1)
                psid = s.get(t.id, "planner_sid")

                if phase == "start":
                    dirty = git(repo, "status", "--porcelain")
                    if dirty:
                        s.set(t.id, "started", int(time.time()))
                        raise Problem("blocked", "Árvore de trabalho suja antes de começar: " + " ".join(dirty.splitlines()[:5]), "start")
                    base = git(repo, "rev-parse", "HEAD") or "none"
                    s.set(t.id, "base", base)
                    s.set(t.id, "started", int(time.time()))
                    s.set(t.id, "cycle", 1)
                    s.event("task_start", {"task": t.id, "repo": str(repo), "base": base, "task_file": str(t.file)})
                    phase = "plan"

                elif phase == "plan":
                    if t.id in self.redrafts:  # /plan ainda rodando na mesma sessão: espera terminar
                        await asyncio.gather(self.redrafts.pop(t.id), return_exceptions=True)
                    before = self.repo_mark(t)
                    out, revalidated = None, False
                    if s.get(t.id, "draft") and psid:  # rascunho antecipado: a mesma sessão confere e atualiza
                        out, sid = await self.call(t, "planner", "plan-revalidate", "plan", self.revalidate_prompt(t),
                                                   psid, resume=True)
                        revalidated = out is not None
                        if not revalidated:
                            s.notice("error", "A revalidação do rascunho falhou; planejando do zero.", t.id)
                    if out is None:
                        out, sid = await self.call(t, "planner", "plan", "plan",
                                                   prompt("plan", BASE=t.base_prompt, PLAN_FILE=t.plan_file))
                    if out is None:
                        raise Problem("failed", "O planejamento falhou (ver orq.log).", "plan")
                    self.warn_if_wrote(t, "O planejador", before)
                    s.update_task(t.id, {"planner_sid": sid, "draft": "revalidated" if revalidated else None})
                    self.save_out(t, "plan.out.json", out)
                    s.event("plan", {"task": t.id, "summary": out["summary"], "plan_rel": f"{t.id}/plan.md",
                                     **({"revalidated": True} if revalidated else {})})
                    phase = "plan_questions"

                elif phase == "plan_questions":
                    out = json.loads((t.dir / "plan.out.json").read_text())
                    rc, answers = await self.resolve_questions(t, "planejador", out)
                    if rc == 1:
                        phase = "exec"
                    elif rc == 2:
                        raise Problem("failed", "O conselho não decidiu uma dúvida do plano.", "plan_questions")
                    else:
                        out, _ = await self.call(t, "planner", f"plan-update-{hms()}", "plan",
                                                 prompt("plan_update", ANSWERS=answers, PLAN_FILE=t.plan_file), psid, resume=True)
                        if out is None:
                            raise Problem("failed", "A atualização do plano falhou.", "plan_questions")
                        self.save_out(t, "plan.out.json", out)  # volta a conferir perguntas

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
                        raise Problem("failed", f"A execução (ciclo {cycle}) falhou.", "exec")
                    s.set(t.id, "exec_sid", sid)
                    s.set(t.id, "exec_mode", "resume")
                    self.save_out(t, f"exec-{cycle}.out.json", out)
                    self.exec_event(t, out, cycle, f"executor, {self.cfg.roles['executor'].label()}")
                    phase = "exec_questions"

                elif phase == "exec_questions":  # fase própria: `resume` com pergunta aberta não reexecuta
                    out = json.loads(_read(t.dir / f"exec-{cycle}.out.json", "{}"))
                    phase = await self.after_exec(t, out, "exec_answers", "clean")

                elif phase == "exec_answers":
                    p = t.dir / f"exec_answers-{hms()}.prompt.md"
                    p.write_text(prompt("exec_answers", ANSWERS=(t.dir / "answers.last").read_text(),
                                        DECISIONS_FILE=t.decisions_file))
                    s.set(t.id, "next_exec_prompt", str(p))
                    phase = "exec"

                elif phase == "clean":
                    await self.clean(t, cycle, "executor", s.get(t.id, "exec_sid"))
                    phase = "verify"

                elif phase == "verify":
                    ok, verify_md = await self.verify(t, cycle)
                    phase = "review" if ok else self.reject(t, cycle, verify_md)

                elif phase == "review":
                    report = _read(t.dir / f"exec-{cycle}.out.json", "{}")
                    await self.review(t, "planner", psid, True, report, "executor", cycle)
                    phase = "review_questions"

                elif phase == "review_questions":
                    verdict, review_md = await self.review_outcome(t, "planner", cycle)
                    if verdict == "approved":
                        self.end(t, "ok", f"Aprovada pelo revisor no ciclo {cycle}.")
                    phase = self.reject(t, cycle, review_md)

                elif phase == "takeover":
                    out, _ = await self.call(t, "planner", f"takeover-{hms()}", "execute",
                                             (t.dir / "takeover.prompt.md").read_text(), psid, resume=True)
                    if out is None:
                        raise Problem("failed", "O takeover do planejador falhou.", "takeover")
                    self.save_out(t, "takeover.out.json", out)
                    self.exec_event(t, out, cycle + 1, f"planejador assumiu, {self.cfg.roles['planner'].label()}")
                    phase = "takeover_questions"

                elif phase == "takeover_questions":
                    out = json.loads(_read(t.dir / "takeover.out.json", "{}"))
                    phase = await self.after_exec(t, out, "takeover_answers", "final_clean")

                elif phase == "takeover_answers":
                    (t.dir / "takeover.prompt.md").write_text(prompt(
                        "exec_answers", ANSWERS=(t.dir / "answers.last").read_text(), DECISIONS_FILE=t.decisions_file))
                    phase = "takeover"

                elif phase == "final_clean":
                    await self.clean(t, cycle + 1, "planner", psid)
                    phase = "final_verify"

                elif phase == "final_verify":
                    ok, verify_md = await self.verify(t, cycle + 1)
                    if not ok:
                        self.retake(t, verify_md)
                        raise Problem("failed", "A verificação automática falhou depois de o planejador assumir "
                                                f"(ver {t.id}/verify-{cycle + 1}.log).", "takeover")
                    phase = "final_review"

                elif phase == "final_review":
                    rsid = s.get(t.id, "final_review_sid")
                    report = _read(t.dir / "takeover.out.json", "{}")
                    await self.review(t, "reviewer", rsid, bool(rsid), report,
                                      "planejador, depois de assumir", cycle + 1, sid_key="final_review_sid")
                    phase = "final_review_questions"

                elif phase == "final_review_questions":
                    verdict, review_md = await self.review_outcome(t, "reviewer", cycle + 1)
                    if verdict == "approved":
                        self.end(t, "ok_takeover", f"O executor não passou em {self.cfg.max_cycles} ciclos; "
                                                   "o planejador assumiu e um revisor novo aprovou.")
                    self.retake(t, review_md)
                    raise Problem("failed", "Nem o takeover do planejador passou na revisão independente.", "takeover")
                else:
                    raise RuntimeError(f"fase desconhecida: {phase}")
            except Problem as p:
                phase = await self.problem(t, p)

    async def problem(self, t: Task, p: Problem, ask: dict | None = None) -> str:
        """Sem intervenção: encerra a tarefa como antes. Com: pergunta ao usuário e aplica a ação escolhida.
        → a fase seguinte."""
        if not self.cfg.intervene:
            self.end(t, p.result, p.reason)
        action, note = await intervene.failure(self, t, p, ask)
        if note:
            self.s.event("note", {"text": note, "for_task": t.id})
        if action == "retry":
            self.s.set(t.id, "decision_rounds", 0)
            return p.phase
        if action == "replan":
            for k in ("exec_sid", "next_exec_prompt", "exec_mode", "final_review_sid"):
                self.s.set(t.id, k, None)
            self.s.set(t.id, "cycle", 1)
            self.s.set(t.id, "decision_rounds", 0)
            return "plan"
        if action == "accept":
            self.end(t, OK_USER, f"Aceita pelo usuário. {p.reason}")
        if action == "skip":
            self.end(t, "skipped", f"Pulada pelo usuário. {p.reason}")
        raise StopRun

    def over_budget(self, t: Task) -> str | None:
        """Motivo, se a tarefa passou do tempo ativo ou a execução do custo configurados em [loop]."""
        limit = self.cfg.max_task_seconds
        active = active_seconds(self.s.state()["tasks"].get(t.id, {}))
        if limit and active > limit:
            return (f"A tarefa passou do orçamento de tempo ativo ({self.cfg.get('loop', 'max_task_time')}): "
                    f"{int(active) // 60} min em chamadas e verificações, sem terminar.")
        cost_limit = self.cfg.max_run_cost
        if cost_limit and self.s.cost() > cost_limit:
            return (f"A execução passou do orçamento de custo (US$ {cost_limit:.2f}): US$ {self.s.cost():.2f} "
                    "estimados até aqui.")
        return None

    def reject(self, t: Task, cycle: int, why_md: str) -> str:
        """Entrega reprovada (revisão ou verificação): próximo ciclo do executor ou, no último, o takeover."""
        if cycle < self.cfg.max_cycles:
            self.s.set(t.id, "cycle", cycle + 1)
            p = t.dir / f"fix-{cycle + 1}.prompt.md"
            p.write_text(prompt("fix", CYCLE=cycle, MAX_CYCLES=self.cfg.max_cycles, REVIEW=why_md))
            self.s.set(t.id, "next_exec_prompt", str(p))
            return "exec"
        self.retake(t, why_md)
        return "takeover"

    def retake(self, t: Task, why_md: str) -> None:
        """O prompt do (próximo) takeover leva sempre a última reprovação: a do executor ou, depois de o planejador
        assumir, a da verificação ou do revisor independente (um `retry` do usuário refaz com esse parecer)."""
        (t.dir / "takeover.prompt.md").write_text(prompt("takeover", MAX_CYCLES=self.cfg.max_cycles, REVIEW=why_md))

    async def clean(self, t: Task, cycle: int, role: str, sid: str | None) -> None:
        """Árvore suja depois da execução: quem executou tem uma chance de arrumar (sem gastar ciclo); senão, bloqueia."""
        dirty = git(self.task_config(t).repo, "status", "--porcelain")
        if not dirty:
            return
        again = "clean" if role == "executor" else "final_clean"
        self.s.notice("dirty_tree", "Arquivos sem commit depois da execução: " + " ".join(dirty.splitlines()[:10]), t.id)
        out, _ = await self.call(t, role, f"clean-{hms()}", "execute", prompt("clean", FILES=dirty), sid, resume=True)
        if out is None:
            raise Problem("failed", "A arrumação da árvore depois da execução falhou.", again)
        who = "executor" if role == "executor" else "planejador"
        self.exec_event(t, out, cycle, f"{who}, {self.cfg.roles[role].label()}, arrumando a árvore")
        dirty = git(self.task_config(t).repo, "status", "--porcelain")
        if dirty:
            raise Problem("blocked", "A árvore continuou suja depois da arrumação: " + " ".join(dirty.splitlines()[:5]),
                          again)

    def repo_mark(self, t: Task) -> tuple[str, str]:
        repo = self.task_config(t).repo
        return git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")

    def warn_if_wrote(self, t: Task, who: str, before: tuple[str, str]) -> None:
        """Plano e revisão só leem; a regra está no prompt, não numa trava. Mexeu no repo: aviso no journal."""
        after = self.repo_mark(t)
        if after != before:
            what = "commitou" if after[0] != before[0] else "deixou arquivos alterados: " + " ".join(after[1].splitlines()[:5])
            self.s.notice("readonly_wrote", f"{who} alterou o repositório numa fase que só deveria ler ({what}).", t.id)

    async def verify(self, t: Task, cycle: int) -> tuple[bool, str]:
        """Roda o `[verify] command` na raiz do repo. → (passou?, texto para o prompt). Sem comando: passa calado."""
        cmd = self.task_config(t).verify_command
        if not cmd:
            return True, ""
        await self.checkpoint(t)
        log = t.dir / f"verify-{cycle}.log"
        started, started_iso = time.time(), now_iso()
        self.s.active_start(t.id)
        try:
            rc, timed_out, _ = await run_process(["sh", "-c", "exec 2>&1\n" + cmd], None, self.task_config(t).repo, self.task_env(t),
                                                 self.task_config(t).verify_timeout, log, lambda _: None)
        finally:
            self.s.active_stop(t.id)
        log.with_suffix(".err").unlink(missing_ok=True)  # stderr já vai junto no log
        ok, secs = rc == 0 and not timed_out, int(time.time() - started)
        self.s.event("verify", {"task": t.id, "cycle": cycle, "started": started_iso, "command": cmd, "ok": ok, "exit": rc,
                                "timed_out": timed_out, "duration_s": secs, "log_rel": f"{t.id}/verify-{cycle}.log"})
        status = "passou" if ok else "estourou o timeout" if timed_out else f"falhou (código de saída {rc})"
        tail = log.read_text(errors="replace").splitlines()[-(5 if ok else 80):]  # passou: o revisor só precisa saber o que rodou
        md = (f"Verificação automática `{cmd}`: {status}, em {secs} s. Últimas linhas da saída:\n\n```\n"
              + "\n".join(tail) + "\n```\n")
        (t.dir / f"verify-{cycle}.md").write_text(md)
        return ok, md

    def exec_event(self, t: Task, out: dict, cycle: int, actor: str) -> None:
        self.s.event("exec", {"task": t.id, "cycle": cycle, "actor": actor, **{
            k: out.get(k) for k in ("status", "summary", "commits", "checks", "pending")}})

    async def after_exec(self, t: Task, out: dict, answers_phase: str, nxt: str) -> str:
        status = out.get("status")
        again = "exec" if answers_phase == "exec_answers" else "takeover"
        if status == "blocked":
            raise Problem("blocked", out.get("summary", ""), again)
        if status == "needs_decision":
            rc, answers = await self.resolve_questions(t, "executor", out)
            if rc == 0:
                (t.dir / "answers.last").write_text(answers)
                return answers_phase
            if rc == 2:
                raise Problem("failed", "O conselho não decidiu uma dúvida do executor.", again)
        return nxt

    async def review(self, t: Task, role: str, sid: str | None, resume: bool, report: str, actor: str, cycle: int,
                     sid_key: str | None = None) -> None:
        """A chamada do revisor; o veredito sai de review_outcome, na fase seguinte."""
        before = self.repo_mark(t)
        out, new_sid = await self.call(t, role, f"review-{cycle}-{hms()}", "review", prompt(
            "review", BASE=t.base_prompt, PLAN_FILE=t.plan_file, DECISIONS_FILE=t.decisions_file,
            BASE_SHA=self.s.get(t.id, "base"), ACTOR=actor, CYCLE=cycle, EXEC_REPORT=report,
            VERIFY=_read(t.dir / f"verify-{cycle}.md", "Nenhuma verificação automática configurada.")), sid, resume=resume)
        if out is None:
            raise Problem("failed", f"A revisão (ciclo {cycle}) falhou.", "review" if role == "planner" else "final_review")
        self.warn_if_wrote(t, "O revisor", before)
        if sid_key:
            self.s.set(t.id, sid_key, new_sid)
        if self.cfg.get("test", "force_changes") and role == "planner":
            out["verdict"] = "changes"
            out.setdefault("issues", []).append({"severity": "media", "where": "(teste)",
                                                 "what": "reprovação forçada por test.force_changes", "fix": "nada"})
        self.save_out(t, f"review-{cycle}.out.json", out)
        who = f"planejador, {self.cfg.roles['planner'].label()}" if role == "planner" \
            else f"revisor em sessão nova, {self.cfg.roles['reviewer'].label()}"
        self.s.event("review", {"task": t.id, "cycle": cycle, "reviewer": who, **{
            k: out.get(k) for k in ("verdict", "summary", "highlights", "issues", "validation")}})

    async def review_outcome(self, t: Task, role: str, cycle: int) -> tuple[str, str]:
        """Lê o parecer salvo, resolve as dúvidas do revisor. → (veredito, texto para o próximo prompt)."""
        out = json.loads(_read(t.dir / f"review-{cycle}.out.json", "{}"))
        rc, answers = await self.resolve_questions(t, "revisor", out)
        if rc == 2:
            raise Problem("failed", "O conselho não decidiu uma dúvida do revisor.",
                          "review" if role == "planner" else "final_review")
        md = f"Resumo: {out.get('summary', '')}\n\nProblemas:\n" + "\n".join(
            f"- [{i['severity']}] {i['where']}: {i['what']} → {i['fix']}" for i in out.get("issues") or [])
        if rc == 0:
            md += "\n\nDecisões do conselho sobre as dúvidas do revisor:\n" + answers
        verdict = out.get("verdict", "changes")
        if verdict == "approved" and any(i.get("severity") in ("alta", "media") for i in out.get("issues") or []):
            self.s.log(f"revisão {cycle}: 'approved' com problema alto ou médio aberto; vale como reprovação", t.id)
            verdict = "changes"
        return verdict, md

    def save_out(self, t: Task, name: str, out: dict) -> None:
        """Saída de uma chamada, lida pela fase de perguntas seguinte. Saída nova: as respostas parciais caducam."""
        (t.dir / name).write_text(json.dumps(out, ensure_ascii=False))
        self.s.set(t.id, "partial_answers", None)

    def last_decision(self, qid: str) -> dict:
        return next(e for e in reversed(self.s.events()) if e["type"] == "decision" and e.get("qid") == qid)

    async def resolve_questions(self, t: Task, source: str, out: dict) -> tuple[int, str]:
        """0 = havia perguntas e todas decididas · 1 = nenhuma pergunta · 2 = falha."""
        qs = out.get("questions") or []
        if not qs:
            return 1, ""
        done = self.s.get(t.id, "partial_answers")  # None: rodada nova · dict: `resume` no meio desta rodada
        rounds = self.s.get(t.id, "decision_rounds", 0) + (done is None)
        done = done or {}
        self.s.update_task(t.id, {"decision_rounds": rounds, "partial_answers": done})
        if rounds > self.cfg.max_decision_rounds:
            self.s.notice("error", f"Passou de {self.cfg.max_decision_rounds} rodadas de conselho: laço de dúvidas.", t.id)
            return 2, ""
        answers = ""
        for q in qs:
            if q["id"] in done:  # decidida antes da parada: não volta ao conselho
                answers += done[q["id"]] + "\n"
                continue
            open_ = self.s.top("open_ask") or {}
            if open_.get("kind") == "council" and open_.get("qid") == q["id"] and open_.get("task") == t.id:
                a = await intervene.council(self, t, self.last_decision(q["id"]), ask=open_)  # resume: sem novo conselho
            else:
                a = await council.decide(self, t, source, q)
                if a is None:
                    return 2, ""
                dec = self.last_decision(q["id"])
                if self.cfg.intervene and dec.get("points") is not None and dec["points"] < 3:
                    a = await intervene.council(self, t, dec)
            done[q["id"]] = a
            self.s.set(t.id, "partial_answers", done)
            answers += a + "\n"
        return 0, answers


def hms() -> str:
    return datetime.now().strftime("%H%M%S")


def _read(p: Path, default: str) -> str:
    return p.read_text() if p.exists() else default
