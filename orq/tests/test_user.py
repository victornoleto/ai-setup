from orq import context, engine, journal


def test_from_user():
    assert journal.from_user({"source": "usuario"})
    assert not journal.from_user({"source": "council"})
    assert not journal.from_user({})


def test_user_messages_le_decisao_do_usuario():
    ev = [{"type": "decision", "source": "usuario", "task": "01-a", "ts": "2026-10-01T12:34:00",
           "question": "Qual banco?", "choice": "b", "label": "Postgres", "why": ""}]
    msgs = context.user_messages(ev, "01-a")
    assert len(msgs) == 1 and "Qual banco?" in msgs[0] and "pelo usuário" in msgs[0]


def test_resultado_aceito_pelo_usuario_conta_como_ok():
    assert journal.OK_USER == "ok_usuario"
    assert "ok_usuario" in engine.OK_RESULTS
    assert journal.RESULT_LABEL["ok_usuario"] == "**ok (aceita pelo usuário)**"
