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
