from orq import context, engine, journal


def test_from_operator():
    assert journal.from_operator({"source": "operador"})
    assert not journal.from_operator({"source": "council"})
    assert not journal.from_operator({})


def test_operator_messages_le_decisao_do_operador():
    ev = [{"type": "decision", "source": "operador", "task": "01-a", "ts": "2026-10-01T12:34:00",
           "question": "Qual banco?", "choice": "b", "label": "Postgres", "why": ""}]
    msgs = context.operator_messages(ev, "01-a")
    assert len(msgs) == 1 and "Qual banco?" in msgs[0] and "operador" in msgs[0]


def test_resultado_aceito_pelo_operador_conta_como_ok():
    assert journal.OK_OPERATOR == "ok_operador"
    assert "ok_operador" in engine.OK_RESULTS
    assert journal.RESULT_LABEL["ok_operador"] == "**ok (aceita pelo operador)**"
