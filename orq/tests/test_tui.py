import re
import time

from textual.widgets import Input, OptionList, RichLog, Static

from orq.tui import model
from orq.tui.app import DetailScreen, OrqApp

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
        assert "✓ 01-a  ok" in str(app.query_one("#tasks", Static).render())
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
