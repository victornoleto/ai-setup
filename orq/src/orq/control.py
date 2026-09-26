"""Ajustes ao vivo: o painel (ou `orq send`) grava um comando por linha em inbox.jsonl; o motor lê a cada segundo,
aplica e responde com o evento control_ack. Mudança na fila, nota e decisão valem já; pausa e parada, no próximo
ponto seguro (entre duas chamadas de harness)."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import Engine

HELP = ("/add <texto> [--after NN] · /skip NN · /unskip NN · /note <texto> [--task NN] · "
        "/decision <qid> <opção ou texto> · /pause · /resume · /stop · /ask <texto> (operador)")


class StopRun(Exception):
    """/stop: a execução para no ponto seguro; `orq resume` continua dali."""


def slug(text: str, n: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower().translate(str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")))
    return "-".join(words[:n]) or "tarefa"


def parse(text: str) -> tuple[str, dict, str]:
    """'/add texto --after 02' → ('add', {'after': '02'}, 'texto')."""
    text = text.strip()
    m = re.match(r"/(\w+)\s*(.*)$", text, re.S)
    if not m:
        return "", {}, text
    cmd, rest = m.group(1).lower(), m.group(2)
    opts = {}
    for key in ("after", "task"):
        mm = re.search(rf"(?:^|\s)--{key}[ =](\S+)", rest)
        if mm:
            opts[key] = mm.group(1)
            rest = (rest[: mm.start()] + rest[mm.end():])
    return cmd, opts, rest.strip()


def find_task(files: list[Path], ref: str) -> Path | None:
    """'2', '02' ou '02-nome' → o arquivo da tarefa."""
    ref = ref.strip()
    for f in files:
        if f.stem == ref or f.stem.split("-")[0] == ref or f.stem.split("-")[0] == ref.zfill(2):
            return f
    return None


def new_task_name(files: list[Path], text: str, after: Path | None) -> str:
    if after is None:
        nums = [int(m.group(1)) for f in files if (m := re.match(r"(\d+)", f.stem))]
        width = max([len(re.match(r"\d+", f.stem).group(0)) for f in files] or [2])
        return f"{(max(nums) + 1 if nums else 1):0{width}d}-{slug(text)}.md"
    prefix = re.match(r"\d+[a-z]*", after.stem).group(0)
    for letter in "abcdefghijklmnopqrstuvwxyz":
        cand = f"{prefix}{letter}"
        if not any(f.stem.startswith(cand + "-") for f in files):
            return f"{cand}-{slug(text)}.md"
    raise ValueError("letras esgotadas depois de " + after.stem)


class Control:
    poll_interval = 1.0

    def __init__(self, eng: "Engine"):
        self.eng = eng
        self.paused = False
        self.stop = False
        self.resumed = asyncio.Event()
        self.background: set[asyncio.Task] = set()

    @property
    def s(self):
        return self.eng.s

    async def loop(self) -> None:
        while True:
            self.drain()
            await asyncio.sleep(self.poll_interval)

    def drain(self) -> None:
        for cmd in self.s.take_inbox():
            try:
                ok, result = self.apply(cmd["text"], cmd["id"])
            except Exception as exc:  # comando ruim nunca derruba o motor
                ok, result = False, f"erro: {exc}"
            self.s.event("control_ack", {"id": cmd["id"], "command": cmd["text"], "ok": ok, "result": result,
                                         "source": cmd.get("source", "")})

    async def checkpoint(self) -> None:
        self.drain()
        if self.stop:
            raise StopRun
        if self.paused:
            self.s.notice("paused", "Execução pausada no ponto seguro. /resume continua.")
            while self.paused and not self.stop:
                self.resumed.clear()
                try:
                    await asyncio.wait_for(self.resumed.wait(), self.poll_interval)
                except asyncio.TimeoutError:
                    self.drain()
            if self.stop:
                raise StopRun
            self.s.notice("resumed", "Execução retomada pelo painel.")

    # --- comandos ---------------------------------------------------------------------------------
    def apply(self, text: str, cmd_id: str = "") -> tuple[bool, str]:
        cmd, opts, rest = parse(text)
        files = self.eng.task_files()
        if cmd == "ask":
            if not rest:
                return False, "uso: /ask <mensagem>"
            job = asyncio.get_running_loop().create_task(self.ask(cmd_id, rest))
            self.background.add(job)
            job.add_done_callback(self.background.discard)
            return True, "operador consultado; a resposta aparece aqui"
        if cmd == "add":
            if not rest:
                return False, "uso: /add <texto da tarefa> [--after NN]"
            after = find_task(files, opts["after"]) if opts.get("after") else None
            if opts.get("after") and not after:
                return False, f"tarefa {opts['after']} não existe"
            name = new_task_name(files, rest, after)
            (self.eng.cfg.queue_dir / name).write_text(rest.rstrip() + "\n")
            return True, f"tarefa {Path(name).stem} criada na fila"
        if cmd in ("skip", "unskip"):
            f = find_task(files, rest)
            if not f:
                return False, f"tarefa '{rest}' não existe"
            st = self.s.state()["tasks"].get(f.stem, {})
            if cmd == "skip":
                if st.get("phase"):
                    return False, f"{f.stem} já começou ({st.get('result') or st.get('phase')}); só tarefa pendente é pulada"
                self.s.set(f.stem, "phase", "done")
                self.s.set(f.stem, "result", "skipped")
                return True, f"{f.stem} será pulada"
            if st.get("result") != "skipped":
                return False, f"{f.stem} não está pulada"
            self.s.drop_task(f.stem)
            self.eng.handled.discard(f.stem)
            return True, f"{f.stem} volta para a fila"
        if cmd == "note":
            if not rest:
                return False, "uso: /note <texto> [--task NN]"
            task = ""
            if opts.get("task"):
                f = find_task(files, opts["task"])
                if not f:
                    return False, f"tarefa {opts['task']} não existe"
                task = f.stem
            self.s.event("note", {"text": rest, "for_task": task})
            return True, f"nota para {task or 'todas as tarefas'}: entra no próximo prompt"
        if cmd == "decision":
            return self.decision(rest)
        if cmd == "pause":
            self.paused = True
            return True, "pausa no próximo ponto seguro (fim da chamada atual)"
        if cmd == "resume":
            self.paused = False
            self.resumed.set()
            return True, "execução continua"
        if cmd == "stop":
            self.stop = True
            self.resumed.set()
            return True, "para no próximo ponto seguro; continue com orq resume"
        if cmd == "edit":
            return False, "/edit só no painel (abre o $EDITOR)"
        return False, f"comando desconhecido. {HELP}"

    def decision(self, rest: str) -> tuple[bool, str]:
        m = re.match(r"(\S+)\s+(.+)$", rest, re.S)
        if not m:
            return False, "uso: /decision <qid> <id da opção ou texto livre>"
        qid, answer = m.group(1), m.group(2).strip()
        orig = next((e for e in reversed(self.s.events())
                     if e["type"] == "decision" and e.get("qid") == qid and e.get("source") != "victor"), None)
        if not orig:
            return False, f"decisão '{qid}' não encontrada"
        opt = next((o for o in orig["options"] if o["id"] == answer), None)
        choice, label = (opt["id"], opt["label"]) if opt else ("victor", answer)
        task = orig["task"]
        self.s.event("decision", {
            "task": task, "source": "victor", "qid": qid, "question": orig["question"], "context": orig.get("context", ""),
            "options": orig["options"], "votes": [], "choice": choice, "label": label, "points": None, "tiebreak": "",
            "why": f"trocada pelo Victor (o conselho tinha escolhido `{orig['choice']}` — {orig['label']})",
            "override": True})
        d = self.s.dir / task / "decisions.md"
        d.parent.mkdir(parents=True, exist_ok=True)
        with open(d, "a") as fh:
            fh.write(f"## {orig['question']} (decisão do Victor)\n\nEscolha: `{choice}` — {label}. Substitui a do "
                     f"conselho (`{orig['choice']}` — {orig['label']}).\n\n")
        if self.s.get(task, "phase") != "done":
            return True, f"{task} recebe a decisão no próximo prompt"
        files = self.eng.task_files()
        after = find_task(files, task)
        text = (f"Ajuste pedido pelo Victor na tarefa `{task}`: a decisão **{orig['question']}** foi trocada de "
                f"`{orig['choice']}` ({orig['label']}) para `{choice}` ({label}).\n\n"
                f"Leia o que a `{task}` fez (`git log`, o plano e o journal da execução em {self.s.dir}) e ajuste o "
                "código, os testes e a documentação para a decisão nova. Commits no padrão do repositório.\n")
        name = new_task_name(files, f"ajuste decisao {qid}", after)
        (self.eng.cfg.queue_dir / name).write_text(text)
        return True, f"{task} já terminou: criada a tarefa {Path(name).stem} para aplicar a decisão"

    async def ask(self, cmd_id: str, message: str) -> None:
        """Texto livre → papel operator (só leitura, sessão nova) → resposta + comandos propostos. O painel só
        aplica os comandos com a confirmação do Victor."""
        from .engine import prompt
        from .tui.model import task_rows, timeline_line

        events = self.s.events()
        tasks = "\n".join(f"- {r.glyph} `{r.id}` {r.status}{' · ' + r.extra if r.extra else ''} — {r.title}"
                           for r in task_rows(self.s, events))
        decisions = "\n".join(
            f"- qid `{e['qid']}` ({e['task']}): {e['question']} → `{e['choice']}` {e['label']}; opções: "
            + ", ".join(f"`{o['id']}` {o['label']}" for o in e.get("options", []))
            for e in events if e["type"] == "decision") or "(nenhuma)"
        timeline = "\n".join(line for e in events[-40:] if (line := timeline_line(e)))
        out, _ = await self.eng.call(None, "operator", f"operator-{cmd_id}", "operator", prompt(
            "operator", REPO=self.eng.cfg.repo, RUN_DIR=self.s.dir, TASKS=tasks, DECISIONS=decisions,
            TIMELINE=timeline, RULES=self.eng.rules.rstrip("\n"), MESSAGE=message), gate=False)
        if out is None:
            out = {"reply": "O operador não respondeu (ver orq.log).", "commands": []}
        cmds = [c.strip() for c in out.get("commands") or [] if c.strip().startswith("/") and not c.startswith("/ask")]
        self.s.event("operator", {"id": cmd_id, "text": message, "reply": out.get("reply", ""), "commands": cmds})
