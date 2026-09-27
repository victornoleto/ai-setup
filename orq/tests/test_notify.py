import io
import json
import stat

from orq import notify


class Fake:
    def __init__(self, body=b""):
        self.reqs, self.body = [], body

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        return io.BytesIO(self.body)


CFG = {"server": "https://ntfy.sh", "topic": "orq-abc"}
ASK = {"id": "q1", "task": "04-x", "question": "Qual driver?", "recommended": "b",
       "options": [{"id": "a", "label": "A" * 80}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"},
                   {"id": "d", "label": "D"}]}


def test_publish_json(monkeypatch):
    f = Fake()
    monkeypatch.setattr(notify.urllib.request, "urlopen", f)
    assert notify.publish(CFG, "t", "m", priority=5, tags=["warning"], actions=[{"a": i} for i in range(5)])
    body = json.loads(f.reqs[0].data)
    assert f.reqs[0].full_url == "https://ntfy.sh" and body["topic"] == "orq-abc"
    assert body["priority"] == 5 and len(body["actions"]) == 3


def test_publish_sem_rede_nao_quebra(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.publish(CFG, "t", "m") is False


def test_ask_payload_botoes_e_limites():
    p = notify.ask_payload(CFG, "gt-v3", ASK)
    labels = [a["label"] for a in p["actions"]]
    assert len(labels) == 3 and labels[0].startswith("2")  # recomendada primeiro (é a 2ª opção)
    assert p["actions"][0]["body"] == "q1 2" and p["actions"][0]["url"] == "https://ntfy.sh/orq-abc-r"
    assert "★" in p["message"] and "A" * 61 not in p["message"]  # rótulo cortado em 60
    assert p["priority"] == 5 and p["title"] == "orq gt-v3 · 04-x precisa de você"


def test_poll(monkeypatch):
    lines = [{"id": "m1", "event": "open"}, {"id": "m2", "event": "message", "message": "q1 2"}]
    f = Fake("\n".join(json.dumps(x) for x in lines).encode())
    monkeypatch.setattr(notify.urllib.request, "urlopen", f)
    msgs, since = notify.poll(CFG, "123")
    assert msgs == ["q1 2"] and since == "m2"
    assert f.reqs[0] == "https://ntfy.sh/orq-abc-r/json?poll=1&since=123"


def test_setup_e_load(tmp_path, monkeypatch):
    monkeypatch.setattr(notify.urllib.request, "urlopen", Fake())
    p = tmp_path / "notify.toml"
    assert notify.load(p) is None
    cfg = notify.setup(p)
    assert cfg["topic"].startswith("orq-") and len(cfg["topic"]) == 36
    assert notify.load(p) == cfg and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert notify.setup(p) == cfg  # não troca o tópico existente


async def test_motor_avisa_no_fim(tmp_path, monkeypatch):
    from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue
    sent = []
    monkeypatch.setattr(notify, "publish", lambda cfg, title, message, *a, **k: sent.append((title, message)) or True)
    e = engine(tmp_path, make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]}))
    e.notifier = CFG
    assert await e.run()
    assert sent and "terminou" in sent[-1][0] and "painel" in sent[-1][1]


def test_cli_notify_test_sem_config(capsys):
    import pytest
    from orq import cli
    with pytest.raises(SystemExit):
        cli.main(["notify", "test"])
    assert "orq notify setup" in capsys.readouterr().err
