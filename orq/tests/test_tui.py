import re
import time

from textual.widgets import Input, OptionList, RichLog, Static

from orq.tui import model
from orq.tui.app import DetailScreen, OrqApp, TaskScreen

from .test_engine import APPROVED, EXEC_OK, PLAN, Q, engine, make_queue, vote


async def finished_run(tmp_path):
    script = {"plan": [{"summary": "s", "questions": [Q]}, PLAN], "execute": [EXEC_OK], "review": [APPROVED],
              "voter:vote": [vote("a"), vote("a"), vote("b")]}
    e = engine(tmp_path, make_queue(tmp_path, script, tasks=("01-a", "02-b", "03-c")))
    e.s.send("/skip 03")
    await e.run()
    return e


async def test_modelo_das_tarefas(tmp_path):
    e = await finished_run(tmp_path)
    rows = model.task_rows(e.s, e.s.events())
    assert [(r.glyph, r.status) for r in rows] == [("✓", "ok"), ("✓", "ok"), ("⊘", "pulada")]
    assert rows[0].title == "Tarefa 01-a"
    e.s.set("03-c", "result", None); e.s.set("03-c", "phase", "exec"); e.s.set("03-c", "cycle", 2)
    assert model.task_rows(e.s, e.s.events())[2].status == "executando c2"
    assert "2/3 tarefas" in model.header(e.s, e.s.events(), model.task_rows(e.s, e.s.events()))


async def test_painel(tmp_path):
    e = await finished_run(tmp_path)
    (e.s.dir / "stream.log").write_text("  [plan] › $ ls\n")
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        tasks = app.query_one("#tasks-box", OptionList)
        assert "✓ 01-a  ok · " in str(tasks.get_option_at_index(0).prompt)
        assert re.search(r"\+\d+ −\d+ · 1 arq", str(tasks.get_option_at_index(0).prompt))
        tl = app.query_one("#timeline", OptionList)
        texts = [str(tl.get_option_at_index(i).prompt) for i in range(tl.option_count)]
        assert any("[DECISÃO 2 pts]" in t for t in texts)
        assert app.query_one("#stream", RichLog).lines
        chat = app.query_one("#chat", Input)
        chat.value = "/note teste do painel"
        await pilot.press("enter")
        assert e.s.inbox_path.read_text().count("/note teste do painel") == 1
        # enter na decisão abre o detalhe; o botão troca a escolha
        idx = next(i for i, t in enumerate(texts) if "[DECISÃO" in t)
        tl.focus()
        tl.highlighted = idx
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.click("#opt-b")
        await pilot.pause()
        assert "/decision nome b" in e.s.inbox_path.read_text()
        await pilot.press("q")


async def test_tela_estreita(tmp_path):
    e = await finished_run(tmp_path)
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.has_class("narrow")
        assert not app.query_one("#right").display
        await pilot.press("ctrl+t")
        assert app.query_one("#right").display and not app.query_one("#left").display


async def test_confirmacao_do_operador(tmp_path):
    from orq.tui.app import ConfirmScreen
    e = await finished_run(tmp_path)
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        app.pending_ops.add("op1")
        e.s.event("operator", {"id": "op1", "text": "x", "reply": "Faço assim.", "commands": ["/note y"]})
        await pilot.pause(0.8)
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        assert '"/note y"' in e.s.inbox_path.read_text()


def test_hms():
    assert model.fmt_hms(0) == "00:00:00"
    assert model.fmt_hms(3725) == "01:02:05"
    assert model.fmt_hms(None) == ""


async def test_relogio_custo_e_previsao(tmp_path):
    e = await finished_run(tmp_path)
    ev = [x for x in e.s.events() if x["type"] != "run_end"]  # como se ainda rodasse
    e.s.set("03-c", "result", None)
    e.s.set("03-c", "phase", None)
    rows = model.task_rows(e.s, ev)
    assert rows[0].extra.count(":") == 2 and "US$ 0.0" in rows[0].extra  # HH:MM:SS · US$
    h = model.header(e.s, ev, rows, now=time.time())
    assert "estimado" in h and "termina ~" in h
    assert re.search(r"\b\d\d:\d\d:\d\d\b", h)


async def test_comando_cost_no_painel(tmp_path):
    e = await finished_run(tmp_path)
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        chat = app.query_one("#chat", Input)
        chat.value = "/cost"
        await pilot.press("enter")
        tl = app.query_one("#timeline", OptionList)
        texts = [str(tl.get_option_at_index(i).prompt) for i in range(tl.option_count)]
        assert any("planejador" in t and "US$" in t for t in texts)
        assert "/cost" not in e.s.inbox_path.read_text() if e.s.inbox_path.exists() else True


async def test_estilos_da_lista_e_timeline(tmp_path):
    e = await finished_run(tmp_path)
    e.s.set("03-c", "result", None)
    e.s.set("03-c", "phase", "exec")
    rows = model.task_rows(e.s, e.s.events())
    styles = [str(r.styled(60).style) for r in rows]
    assert "dim" in styles[0] and "bold" in styles[2]
    assert model.line_style({"type": "task_start"}).startswith("bold")
    assert "reverse" in model.line_style({"type": "ask"})
    assert "italic" in model.line_style({"type": "operator"})


async def test_bloco_da_pergunta_e_resposta(tmp_path):
    from orq import intervene
    e = await finished_run(tmp_path)
    ask = intervene.new_ask("03-c", "blocked", "exec", "E agora?", "diag",
                            [{"id": "1", "label": "Tentar", "detail": "", "action": "retry", "note": ""},
                             {"id": "2", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                             {"id": "3", "label": "Parar", "detail": "", "action": "stop", "note": ""}], "1")
    e.s.set_top("open_ask", ask)
    txt = model.ask_text(ask).plain
    assert "★ RECOMENDADA" in txt and "[PRECISA DE VOCÊ]" in txt and "responda 1–3" in txt
    ev = [x for x in e.s.events() if x["type"] != "run_end"]
    assert "esperando você" in model.header(e.s, ev, model.task_rows(e.s, ev))
    assert model.task_rows(e.s, ev)[2].status == "esperando você"
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause(0.6)
        assert app.query_one("#ask").display
        chat = app.query_one("#chat", Input)
        chat.value = "1"
        await pilot.press("enter")
        assert f'"/answer {ask["id"]} 1"' in e.s.inbox_path.read_text()
        e.s.set_top("open_ask", None)
        await pilot.pause(0.6)
        assert not app.query_one("#ask").display


async def test_tempo_ativo_na_lista_e_na_previsao(tmp_path):
    e = await finished_run(tmp_path)
    ev = [x for x in e.s.events() if x["type"] != "run_end" and not (x["type"] == "task_end" and x["task"] == "03-c")]
    now = time.time()
    e.s.update_task("03-c", {"result": None, "phase": "exec", "started": now - 3600, "active_s": 10,
                             "active_since": now - 5})
    rows = model.task_rows(e.s, ev, now=now)
    assert rows[2].extra.startswith("00:00:15")  # ativo (15 s), não a hora de parede
    with_wait = model.eta(ev, rows, now, e.s.state()["tasks"])
    e.s.update_task("03-c", {"active_s": 0, "active_since": None})
    without = model.eta(ev, rows, now, e.s.state()["tasks"])
    assert with_wait is not None and without is not None and with_wait <= without


async def test_tarefas_rolam_e_cabecalho_fica(tmp_path):
    e = await finished_run(tmp_path)
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 10)) as pilot:
        await pilot.pause()
        assert app.query_one("#tasks-box").max_scroll_y > 0
        assert "tarefas" in str(app.query_one("#header", Static).render())
        await pilot.press("q")


def test_diff_por_numstat_e_por_stat_antigo():
    d = model.Diff.from_numstat("10\t2\tsrc/a.py\n-\t-\timg.png\n0\t5\tb.md\n")
    assert (d.add, d.rem, d.nfiles) == (10, 7, 3) and d.files[1] == (0, 0, "img.png")
    assert d.summary() == "+10 −7 · 3 arq"
    old = model.Diff.from_stat(" a.py | 3 ++-\n b.py | 1 -\n 2 files changed, 2 insertions(+), 2 deletions(-)")
    assert (old.add, old.rem, old.nfiles, old.files) == (2, 2, 2, [])
    assert model.Diff.from_stat(" 1 file changed, 4 insertions(+)").rem == 0
    assert model.Diff.from_stat("") is None


async def test_diff_e_historico_da_tarefa(tmp_path):
    e = await finished_run(tmp_path)
    st, evs = e.s.state(), e.s.events()
    d = model.task_diff(st, evs, "01-a")
    assert d.add >= 1 and d.files and d.files[0][2].endswith(".txt")
    assert model.task_diff(st, evs, "03-c") is None  # pulada: sem entrega
    start = next(x for x in evs if x["type"] == "task_start" and x["task"] == "01-a")
    n_start = evs.index(start) + 1  # a linha foi gravada logo depois do task_start, no mesmo segundo do plano
    (e.s.dir / "01-a" / "activity.log").write_text(f"{start['ts']}\t{n_start}\t  [exec-1] › $ ls\n")
    hist = [(when, str(t)) for when, t in model.task_history(e.s, evs, "01-a")]
    assert re.fullmatch(r"\d\d/\d\d \d\d:\d\d:\d\d", hist[0][0]) and hist[0][1] == "▶ 01-a começou"
    assert hist[1][1] == "[exec-1] › $ ls" and "[PLANO]" in hist[2][1]  # entre os eventos, pela contagem
    assert any(when == "" for when, _ in hist)  # o detalhe do evento continua sem horário
    assert not any("02-b" in t for _, t in hist)


async def test_modal_da_tarefa(tmp_path):
    e = await finished_run(tmp_path)
    e.s.stream("  [exec-1] › $ ls", task="01-a")
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert re.match(r"\d\d:\d\d:\d\d   \[exec-1\]", str(app.query_one("#stream", RichLog).lines[-1].text))
        await pilot.click("#tasks-box", offset=(3, 0))  # clique na 1ª tarefa
        await pilot.pause()
        assert isinstance(app.screen, TaskScreen)
        head = str(app.screen.query_one("#task-head", Static).render())
        assert "01-a" in head and re.search(r"\+\d+ +−\d+ +\S+\.txt", head)
        lines = [str(x.text) for x in app.screen.query_one("#task-log", RichLog).lines]
        assert any("│ ▶ 01-a começou" in x for x in lines) and any("[exec-1] › $ ls" in x for x in lines)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TaskScreen)
        await pilot.press("q")
