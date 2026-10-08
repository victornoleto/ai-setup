"""Painel do orq: à esquerda, tarefas, timeline e chat; à direita, o stream dos harnesses. Lê o run dir e escreve
só na inbox.jsonl: fechar o painel não mexe na execução (`orq attach` reabre)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Markdown, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from .. import control, journal
from ..store import RunStore
from . import model

HELP_LINES = [
    "Comandos: " + control.HELP,
    "/cost [NN] mostra o custo estimado por papel (total e por tarefa). "
    "/edit NN abre a tarefa pendente no $EDITOR. Texto sem barra vai ao operador (LLM), que propõe comandos.",
    "Teclas fora do chat: q desanexa · p pausa/continua · f segue o stream · ctrl+t troca tarefas ⇄ stream (tela estreita) · "
    "enter na timeline abre o detalhe · enter/clique numa tarefa abre o histórico dela · esc sai do chat.",
]


class DetailScreen(ModalScreen[str | None]):
    """Detalhe de um evento. Numa decisão, um botão por opção troca a escolha (/decision)."""

    BINDINGS = [Binding("escape", "dismiss(None)", "fechar")]

    def __init__(self, ev: dict):
        super().__init__()
        self.ev = ev

    def compose(self) -> ComposeResult:
        body = journal._section(self.ev) or f"```\n{self.ev}\n```"
        with Vertical(id="detail"):
            with VerticalScroll():
                yield Markdown(body)
            with Horizontal(id="detail-buttons"):
                if self.ev["type"] == "decision" and self.ev.get("qid"):
                    for o in self.ev.get("options", []):
                        if o["id"] != self.ev.get("choice"):
                            yield Button(f"Trocar para {o['id']}", id=f"opt-{o['id']}")
                yield Button("Fechar", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        self.dismiss(bid[4:] if bid.startswith("opt-") else None)


class TaskScreen(ModalScreen[None]):
    """Histórico de uma tarefa: estado, +/- por arquivo e o fluxo (eventos + stream), ao vivo. Lê o store direto:
    com o modal na frente, o refresh do painel não alcança os widgets dele."""

    BINDINGS = [Binding("escape", "dismiss(None)", "fechar")]

    def __init__(self, store: RunStore, tid: str):
        super().__init__()
        self.store, self.tid = store, tid
        self.shown, self.diff_at, self.diff = 0, 0.0, None

    def compose(self) -> ComposeResult:
        with Vertical(id="detail"):
            with VerticalScroll(id="task-head-box"):
                yield Static(id="task-head")
            yield RichLog(id="task-log", wrap=True)
            with Horizontal(id="detail-buttons"):
                yield Button("Fechar", id="close", variant="primary")

    def on_mount(self) -> None:
        self.refresh_task()
        self.set_interval(1.0, self.refresh_task)

    def refresh_task(self) -> None:
        evs, st = self.store.events(), self.store.state()
        row = next((r for r in model.task_rows(self.store, evs, state=st) if r.id == self.tid), None)
        now = time.time()
        if now - self.diff_at >= 5:  # em curso, o diff é um git ao vivo: no máximo a cada 5 s
            self.diff, self.diff_at = model.task_diff(st, evs, self.tid), now
        self.query_one("#task-head", Static).update(model.task_head(row, self.diff))
        hist = model.task_history(self.store, evs, self.tid)
        log = self.query_one("#task-log", RichLog)
        for when, text in hist[self.shown:]:  # grade: o texto quebra na própria coluna, sem cair sob o horário
            row = Table.grid(padding=(0, 1))
            row.add_column(width=14, style="dim")
            row.add_column(width=1, style="dim")
            row.add_column(ratio=1)
            row.add_row(when, "│", text)
            log.write(row, expand=True)
        self.shown = len(hist)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Comandos propostos pelo operador: só valem com confirmação."""

    BINDINGS = [Binding("y", "dismiss(True)", "aplicar"), Binding("n,escape", "dismiss(False)", "descartar")]

    def __init__(self, reply: str, commands: list[str]):
        super().__init__()
        self.reply, self.commands = reply, commands

    def compose(self) -> ComposeResult:
        with Vertical(id="detail"):
            yield Static(Text(self.reply + "\n\nComandos propostos:\n" + "\n".join(f"  {c}" for c in self.commands)
                              + "\n\ny aplica · n descarta"))
            with Horizontal(id="detail-buttons"):
                yield Button("Aplicar (y)", id="yes", variant="primary")
                yield Button("Descartar (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class OrqApp(App):
    TITLE = "orq"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #header { height: 1; padding: 0 1; text-style: bold; }
    #main { height: 1fr; }
    #left, #right { width: 1fr; }
    #right { border-left: vkey $foreground 30%; }
    .title { height: 1; padding: 0 1; text-style: bold reverse; }
    #tasks-box { height: auto; max-height: 45%; border: none; }
    #timeline { height: 1fr; border: none; }
    #chat { dock: bottom; }
    #ask { height: auto; max-height: 60%; border: heavy $warning; padding: 0 1; display: none; }
    #stream { height: 1fr; }
    Screen.narrow #right { display: none; }
    Screen.narrow.show-right #left { display: none; }
    Screen.narrow.show-right #right { display: block; border-left: none; }
    DetailScreen, ConfirmScreen, TaskScreen { align: center middle; }
    #task-head-box { height: auto; max-height: 40%; }
    #task-log { height: 1fr; }
    #detail { width: 90%; height: 80%; border: thick $foreground 50%; background: $surface; padding: 1; }
    #detail-buttons { height: 3; }
    #detail-buttons Button { margin-right: 1; }
    """
    BINDINGS = [
        Binding("ctrl+q", "detach", "desanexar", priority=True),
        Binding("q", "detach", "desanexar"),
        Binding("p", "toggle_pause", "pausar/continuar"),
        Binding("f", "follow", "seguir stream"),
        Binding("ctrl+t", "toggle_pane", "tarefas ⇄ stream", priority=True),
        Binding("escape", "leave_chat", "sair do chat"),
        Binding("i", "focus_chat", "chat"),
    ]

    def __init__(self, run_dir: Path):
        super().__init__()
        self.store = RunStore(run_dir)
        self.events: list[dict] = []
        self.ev_tail = model.Tail(self.store.events_path)
        self.stream_tail = model.Tail(self.store.stream_path)
        self.pending_ops: set[str] = set()  # ids de /ask aguardando o operador
        self.task_ids: list[str] | None = None
        self.task_texts: list[str] = []
        self.diffs: dict[str, tuple[float, bool, model.Diff | None]] = {}  # tarefa → (quando, final?, diff)

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("TAREFAS  (enter/clique: histórico)", classes="title")
                yield OptionList(id="tasks-box")
                yield Static("TIMELINE  (enter: detalhe)", classes="title")
                yield OptionList(id="timeline")
                yield Static(id="ask")
                yield Input(placeholder="/help · /add · /skip NN · /note · /decision qid opção · texto livre → operador",
                            id="chat")
            with Vertical(id="right"):
                yield Static("STREAM", classes="title", id="stream-title")
                yield RichLog(id="stream", wrap=True, max_lines=5000)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(0.5, self.refresh_data)
        self.query_one("#chat", Input).focus()
        self.on_resize()

    def on_resize(self, event=None) -> None:
        self.screen.set_class(self.size.width < 120, "narrow")

    # --- dados --------------------------------------------------------------------------------------
    def refresh_data(self) -> None:
        try:
            tl = self.query_one("#timeline", OptionList)
        except NoMatches:  # o timer ainda dispara enquanto o app encerra
            return
        at_bottom = tl.highlighted is None or tl.highlighted >= tl.option_count - 1
        added = False
        for line in self.ev_tail.read():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            idx = len(self.events)
            self.events.append(ev)
            self.handle_operator(ev)
            text = model.timeline_line(ev)
            if text:
                if ev["type"] == "task_start" and tl.option_count:
                    tl.add_option(None)  # separador entre tarefas
                tl.add_option(Option(Text(text, style=model.line_style(ev)), id=str(idx)))
                added = True
        if added and at_bottom:
            tl.highlighted = tl.option_count - 1
        state = self.store.state()
        rows = model.task_rows(self.store, self.events, state=state)
        self.add_diffs(rows, state)
        self.show_tasks(rows)
        ask = state.get("open_ask")
        box = self.query_one("#ask", Static)
        box.display = bool(ask)
        if ask:
            box.update(model.ask_text(ask))
        self.query_one("#header", Static).update(Text(model.header(self.store, self.events, rows, state=state)))
        log = self.query_one("#stream", RichLog)
        for line in self.stream_tail.read():
            if re.match(r"\d\d:\d\d:\d\d ", line):  # hora apagada, o texto em destaque
                log.write(Text.assemble((line[:8], "dim"), line[8:]))
            else:
                log.write(Text(line, style="dim" if line.startswith("── ") else ""))

    def add_diffs(self, rows: list[model.TaskRow], state: dict) -> None:
        """+/- de código na linha da tarefa. Terminada: calcula uma vez; em curso (git ao vivo): a cada 5 s."""
        now = time.time()
        for r in rows:
            if r.glyph == "·":
                continue
            final = r.glyph in "✓✗⊘"
            hit = self.diffs.get(r.id)
            if not hit or not (hit[1] if final else now - hit[0] < 5):
                hit = self.diffs[r.id] = (now, final, model.task_diff(state, self.events, r.id))
            if hit[2]:
                r.extra += (" · " if r.extra else "") + hit[2].summary()

    def show_tasks(self, rows: list[model.TaskRow]) -> None:
        """Uma opção por tarefa. Mesma lista: troca só o texto que mudou, sem perder o destaque."""
        tasks = self.query_one("#tasks-box", OptionList)
        width = tasks.content_size.width or 60
        ids, prompts = [r.id for r in rows], [r.styled(width) for r in rows]
        texts = [p.plain for p in prompts]
        if ids != self.task_ids:
            hl = tasks.highlighted
            tasks.set_options([Option(p, id=i) for i, p in zip(ids, prompts)]
                              or [Option(Text("(fila vazia)"), disabled=True)])
            if hl is not None and ids:
                tasks.highlighted = min(hl, len(ids) - 1)
            self.task_ids = ids
        else:
            for i, p, old, new in zip(ids, prompts, self.task_texts, texts):
                if old != new:
                    tasks.replace_option_prompt(i, p)
        self.task_texts = texts

    def local(self, text: str) -> None:
        """Linha só do painel (ajuda, eco do que foi enviado)."""
        try:
            tl = self.query_one("#timeline", OptionList)
        except NoMatches:
            return
        tl.add_option(Option(Text(text)))
        tl.highlighted = tl.option_count - 1

    def handle_operator(self, ev: dict) -> None:
        if ev["type"] != "operator" or ev.get("id") not in self.pending_ops:
            return
        self.pending_ops.discard(ev["id"])
        cmds = ev.get("commands") or []
        if not cmds:
            return

        def done(ok: bool | None) -> None:
            for c in cmds if ok else []:
                self.store.send(c, source="operador (confirmado)")
            self.local("› comandos do operador " + ("enviados" if ok else "descartados"))

        self.push_screen(ConfirmScreen(ev.get("reply", ""), cmds), done)

    # --- chat ---------------------------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text in ("/help", "/?", "/ajuda"):
            for line in HELP_LINES:
                self.local(line)
            return
        if text.split()[0] == "/cost":
            for line in model.cost_lines(self.store, text[5:].strip()):
                self.local(line)
            return
        if text.startswith("/edit"):
            self.edit_task(text[5:].strip())
            return
        ask = self.store.top("open_ask")
        if ask and not text.startswith("/"):  # com pergunta aberta, texto sem barra é a resposta
            self.store.send(f"/answer {ask['id']} {text}")
            self.local(f"› resposta: {text}")
            return
        if not self.store.engine_alive():
            self.local("✗ motor parado: o comando fica na caixa de entrada e vale no próximo orq resume")
        if text.startswith("/"):
            self.store.send(text)
            self.local(f"› {text}")
            return
        cmd = self.store.send(f"/ask {text}")
        self.pending_ops.add(cmd["id"])
        self.local(f"› operador: {text}")

    def edit_task(self, ref: str) -> None:
        files = sorted(Path(self.store.top("queue")).glob("[0-9]*.md"))
        f = control.find_task(files, ref)
        if not f:
            self.local(f"✗ /edit: tarefa '{ref}' não existe")
            return
        if self.store.state()["tasks"].get(f.stem, {}).get("phase"):
            self.local(f"✗ /edit: {f.stem} já começou; só tarefa pendente é editada")
            return
        with self.suspend():
            subprocess.call([os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano", str(f)])
        self.local(f"› {f.stem} editada")

    # --- timeline -----------------------------------------------------------------------------------
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        if event.option_list.id == "tasks-box":
            self.push_screen(TaskScreen(self.store, event.option.id))
            return
        ev = self.events[int(event.option.id)]

        def done(choice: str | None) -> None:
            if choice:
                cmd = f"/decision {ev['qid']} {choice}"
                self.store.send(cmd)
                self.local(f"› {cmd}")

        self.push_screen(DetailScreen(ev), done)

    # --- ações --------------------------------------------------------------------------------------
    def action_detach(self) -> None:
        self.exit()

    def action_toggle_pause(self) -> None:
        cmd = "/resume" if model.paused(self.events) else "/pause"
        self.store.send(cmd)
        self.local(f"› {cmd}")

    def action_follow(self) -> None:
        log = self.query_one("#stream", RichLog)
        log.auto_scroll = not log.auto_scroll
        if log.auto_scroll:
            log.scroll_end(animate=False)
        self.query_one("#stream-title", Static).update("STREAM" + ("" if log.auto_scroll else "  (parado: f segue)"))

    def action_toggle_pane(self) -> None:
        self.screen.toggle_class("show-right")

    def action_leave_chat(self) -> None:
        self.query_one("#timeline", OptionList).focus()

    def action_focus_chat(self) -> None:
        self.query_one("#chat", Input).focus()


def run_tui(run_dir: Path) -> None:
    OrqApp(run_dir).run()
