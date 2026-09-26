# Intervenção do Victor — plano de implementação

> **For agentic workers:** Implement this plan task-by-task, in order, verifying each step before the next. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a fila pausa quando precisa do Victor, avisa no celular (ntfy) e no painel com uma pergunta de 3–4 opções
(uma recomendada), e continua sozinha depois da resposta.

**Architecture:** dois módulos novos — `notify.py` (ntfy + notify-send, só stdlib) e `intervene.py` (pergunta aberta
em `state.json`, espera, casamento de resposta, chamadas ao operador). O motor troca os `end(failed/blocked)` por uma
exceção `Problem`, que vira pergunta quando `[intervene] enabled`. O `Control` ganha `/answer`. O painel ganha o
bloco da pergunta e estilos (dim/negrito/inverso) na lista e na timeline.

**Tech Stack:** Python 3.12 (uv), Textual/Rich, pytest + pytest-asyncio, harness fake. Sem dependência nova.

**Spec:** `orq/docs/specs/2026-09-26-intervencao-design.md`

## Global Constraints

- Trabalhar só na worktree `/var/www/victor/ai-setup-orq-todo` (branch `orq-todo`); a gt-v3 roda de `~/.ai-setup/orq`.
- Testes: `uv run --project /var/www/victor/ai-setup-orq-todo/orq pytest -q` (rodar a partir de `orq/`).
- Nada depende só de cor: todo estado tem glifo, rótulo ou intensidade (dim/negrito/inverso).
- ntfy: no máximo **3** botões; pergunta até 200 caracteres, rótulos até 60; nunca código, caminho, diff ou saída de teste.
- Configuração do ntfy fora do repositório: `~/.config/orq/notify.toml` (`ORQ_NOTIFY_CONFIG` sobrescreve, para testes).
- Ações de falha: `retry`, `replan`, `accept`, `skip`, `stop`. Resultado novo: `ok_victor` (conta como ok).
- `[intervene]`: `enabled = true`, `decision_timeout = "1h"`, `reminder = "2h"`. Leitura de respostas no ntfy a cada 15 s.
- Rede nunca derruba a execução: erro de ntfy vai para o `orq.log`.
- Commits em pt-BR no padrão `feat(orq): …`, autor `Victor Noleto <victornoleto95@gmail.com>` (já configurado).

---

### Task 1: configuração, resultado `ok_victor` e helper de teste

**Files:**
- Modify: `src/orq/config.py` (propriedades), `src/orq/engine.py` (`OK_RESULTS`, aviso sem commit),
  `src/orq/journal.py` (`RESULT_LABEL`, glifo), `src/orq/tui/model.py` (`RESULT`), `orq.toml`
- Test: `tests/test_base.py`, `tests/test_engine.py` (`make_queue`)

**Interfaces:**
- Produces: `Config.intervene -> bool`; `Config.intervene_seconds(key: "decision_timeout" | "reminder") -> int`;
  `make_queue(tmp_path, script, tasks=..., extra_toml="", intervene="enabled = false")`.

- [ ] **Step 1: teste que falha**

```python
# tests/test_base.py
def test_intervencao_padrao(tmp_path):
    (tmp_path / "orq.toml").write_text("")
    c = config.load(tmp_path)
    assert c.intervene is True
    assert c.intervene_seconds("decision_timeout") == 3600 and c.intervene_seconds("reminder") == 7200
    (tmp_path / "orq.toml").write_text('[intervene]\nenabled = false\ndecision_timeout = "5s"\n')
    c = config.load(tmp_path)
    assert c.intervene is False and c.intervene_seconds("decision_timeout") == 5
    assert journal.RESULT_LABEL["ok_victor"] == "**ok (aceita pelo Victor)**"
```

- [ ] **Step 2:** `pytest tests/test_base.py::test_intervencao_padrao` → FAIL (`intervene` não existe).

- [ ] **Step 3: implementação**

```python
# src/orq/config.py, em Config
    @property
    def intervene(self) -> bool:
        return bool(self.get("intervene", "enabled", default=True))

    def intervene_seconds(self, key: str) -> int:
        return parse_duration(self.get("intervene", key, default={"decision_timeout": "1h", "reminder": "2h"}[key]))
# em load(), depois de cfg.verify_timeout:
    cfg.intervene_seconds("decision_timeout"), cfg.intervene_seconds("reminder")  # valida já no load
```

```python
# engine.py
OK_RESULTS = ("ok", "ok_takeover", "ok_victor", "skipped")
# em end(): if result in ("ok", "ok_takeover", "ok_victor") and git(...) == base:
# journal.py
RESULT_LABEL[...] += "ok_victor": "**ok (aceita pelo Victor)**"
# event_line task_end: glyph = {"ok": "✓", "ok_takeover": "✓", "ok_victor": "✓", "skipped": "⊘"}
# tui/model.py
RESULT[...] += "ok_victor": ("✓", "ok, aceita pelo Victor")
```

`orq.toml` global, antes de `[time]`:

```toml
[intervene]
enabled = true             # a fila pausa e pergunta ao Victor (painel + ntfy) em vez de falhar/bloquear
decision_timeout = "1h"    # decisão sem unanimidade: segue com a escolha do conselho depois disso
reminder = "2h"            # lembrete no ntfy enquanto a pergunta estiver aberta
```

`tests/test_engine.py`: `make_queue` ganha `intervene: str = "enabled = false"` e escreve
`f'{ROLES_FAKE}\n[run]\nrepo = "{repo}"\n[intervene]\n{intervene}\n{extra_toml}'`.

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): configuração [intervene] e resultado ok_victor`.

---

### Task 2: `notify.py` — ntfy e notify-send

**Files:**
- Create: `src/orq/notify.py`
- Modify: `src/orq/engine.py` (tirar `notify()`; `Engine.notify()`; aviso de limite ≥ 30 min), `src/orq/cli.py`
  (`orq notify setup|test`)
- Test: `tests/test_notify.py`

**Interfaces:**
- Produces: `notify.load(path=None) -> dict | None` (`{"server", "topic"}`); `notify.publish(cfg, title, message,
  priority=3, tags=(), actions=()) -> bool`; `notify.ask_payload(cfg, queue, ask) -> dict` (kwargs de `publish`);
  `notify.poll(cfg, since: str) -> tuple[list[str], str]`; `notify.setup(path=None) -> dict`;
  `notify.desktop(msg)`; `Engine.notifier`; `Engine.notify(title, message, priority=3, actions=())`.

- [ ] **Step 1: testes que falham**

```python
# tests/test_notify.py
import io, json, stat
import pytest
from orq import notify

class Fake:
    def __init__(self, body=b""): self.reqs, self.body = [], body
    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        return io.BytesIO(self.body)

CFG = {"server": "https://ntfy.sh", "topic": "orq-abc"}
ASK = {"id": "q1", "task": "04-x", "question": "Qual driver?", "recommended": "b",
       "options": [{"id": "a", "label": "A" * 80}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}, {"id": "d", "label": "D"}]}

def test_publish_json(monkeypatch):
    f = Fake(); monkeypatch.setattr(notify.urllib.request, "urlopen", f)
    assert notify.publish(CFG, "t", "m", priority=5, tags=["warning"], actions=[{"a": i} for i in range(5)])
    body = json.loads(f.reqs[0].data)
    assert f.reqs[0].full_url == "https://ntfy.sh" and body["topic"] == "orq-abc"
    assert body["priority"] == 5 and len(body["actions"]) == 3

def test_publish_sem_rede_nao_quebra(monkeypatch):
    def boom(*a, **k): raise OSError("offline")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.publish(CFG, "t", "m") is False

def test_ask_payload_botoes_e_limites():
    p = notify.ask_payload(CFG, "gt-v3", ASK)
    labels = [a["label"] for a in p["actions"]]
    assert len(labels) == 3 and labels[0].startswith("2")          # recomendada primeiro (é a 2ª opção)
    assert p["actions"][0]["body"] == "q1 2" and p["actions"][0]["url"] == "https://ntfy.sh/orq-abc-r"
    assert "★" in p["message"] and "A" * 61 not in p["message"]      # rótulo cortado em 60
    assert p["priority"] == 5 and "04-x" in p["title"]

def test_poll(monkeypatch):
    lines = [{"id": "m1", "event": "open"}, {"id": "m2", "event": "message", "message": "q1 2"}]
    f = Fake("\n".join(json.dumps(l) for l in lines).encode()); monkeypatch.setattr(notify.urllib.request, "urlopen", f)
    msgs, since = notify.poll(CFG, "123")
    assert msgs == ["q1 2"] and since == "m2"
    assert f.reqs[0].full_url == "https://ntfy.sh/orq-abc-r/json?poll=1&since=123"

def test_setup_e_load(tmp_path, monkeypatch):
    monkeypatch.setattr(notify.urllib.request, "urlopen", Fake())
    p = tmp_path / "notify.toml"
    assert notify.load(p) is None
    cfg = notify.setup(p)
    assert cfg["topic"].startswith("orq-") and len(cfg["topic"]) == 36
    assert notify.load(p) == cfg and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert notify.setup(p) == cfg                                    # não troca o tópico existente
```

- [ ] **Step 2:** `pytest tests/test_notify.py` → FAIL (módulo não existe).

- [ ] **Step 3: implementação**

```python
# src/orq/notify.py
"""Avisos: ntfy (celular; https://ntfy.sh) e notify-send (desktop). A configuração fica fora do repositório, em
~/.config/orq/notify.toml, porque o nome do tópico funciona como senha. Rede nunca derruba a execução."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import tomllib
import urllib.request
from pathlib import Path

CONFIG = Path(os.environ.get("ORQ_NOTIFY_CONFIG") or Path.home() / ".config" / "orq" / "notify.toml")
TIMEOUT = 10


def load(path: Path | None = None) -> dict | None:
    try:
        raw = tomllib.loads((path or CONFIG).read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return None
    if not raw.get("topic"):
        return None
    return {"server": str(raw.get("server") or "https://ntfy.sh").rstrip("/"), "topic": str(raw["topic"])}


def setup(path: Path | None = None) -> dict:
    """Cria o arquivo com um tópico aleatório (se ainda não existe) e manda uma notificação de teste."""
    p = path or CONFIG
    cfg = load(p)
    if not cfg:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'server = "https://ntfy.sh"\ntopic = "orq-{secrets.token_hex(16)}"\n')
        p.chmod(0o600)
        cfg = load(p)
    publish(cfg, "orq · teste", "Notificações do orq chegando neste aparelho.")
    return cfg


def publish(cfg: dict, title: str, message: str, priority: int = 3, tags=(), actions=()) -> bool:
    body = {"topic": cfg["topic"], "title": title, "message": message, "priority": priority, "tags": list(tags)}
    if actions:
        body["actions"] = list(actions)[:3]  # limite do ntfy
    req = urllib.request.Request(cfg["server"], data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            return True
    except OSError:
        return False


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def ask_payload(cfg: dict, queue: str, ask: dict) -> dict:
    """Pergunta → kwargs de publish: pergunta e rótulos curtos; botões para a recomendada e as duas seguintes."""
    opts = ask["options"]
    lines = [f"{i}) " + ("★ " if o["id"] == ask["recommended"] else "") + _clip(o["label"], 60)
             for i, o in enumerate(opts, 1)]
    order = sorted(range(len(opts)), key=lambda i: opts[i]["id"] != ask["recommended"])[:3]
    actions = [{"action": "http", "label": _clip(f"{i + 1} · {opts[i]['label']}", 40), "method": "POST",
                "url": f"{cfg['server']}/{cfg['topic']}-r", "body": f"{ask['id']} {i + 1}", "clear": True}
               for i in order]
    return {"title": f"orq {queue} · {ask['task']} precisa de você", "priority": 5, "tags": ["raising_hand"],
            "message": _clip(ask["question"], 200) + "\n" + "\n".join(lines), "actions": actions}


def poll(cfg: dict, since: str) -> tuple[list[str], str]:
    """Respostas publicadas no tópico <topic>-r desde `since` (id de mensagem ou unix time)."""
    url = f"{cfg['server']}/{cfg['topic']}-r/json?poll=1&since={since}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            raw = r.read().decode(errors="replace")
    except OSError:
        return [], since
    msgs = []
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "message":
            msgs.append(str(ev.get("message", "")))
            since = str(ev.get("id") or since)
    return msgs, since


def desktop(msg: str) -> None:
    if subprocess.run(["sh", "-c", "command -v notify-send"], capture_output=True).returncode == 0:
        subprocess.run(["notify-send", "orq", msg], capture_output=True)
```

Motor: apagar a função `notify()` do fim de `engine.py`; em `Engine.__init__`: `self.notifier = notify.load()`;
novo método:

```python
    def notify(self, title: str, message: str, priority: int = 3, actions=()) -> None:
        notify.desktop(f"{title}: {message}")
        if self.notifier and not notify.publish(self.notifier, title, message, priority, actions=actions):
            self.s.log("aviso: ntfy não respondeu (a execução segue)")
```

`_run_queue`: `notify(f"Fila terminou: {summary}")` → `self.notify(f"orq {self.queue_name()} terminou", summary)`
(extrair `queue_name()` de `start_event`). Em `call()`, depois do `notice("limit_wait", …)`:
`if wait_s >= 1800: self.notify(f"orq · limite de uso", f"{name}: esperando {wait_s // 60} min")`.
O import `from . import notify` fica no topo; o método chama `notify.publish` (módulo) — sem conflito de nome
porque o método é `self.notify`.

CLI (`cli.py`): subcomando `notify` com `action` em `setup|test`:

```python
def cmd_notify(args) -> int:
    from . import notify
    if args.action == "setup":
        cfg = notify.setup()
        print(f"tópico: {cfg['topic']} (servidor {cfg['server']})\nNo app ntfy: + Subscribe to topic → cole o tópico."
              f"\nConfiguração em {notify.CONFIG}. Uma notificação de teste foi enviada.")
        return 0
    cfg = notify.load()
    if not cfg:
        die(f"sem {notify.CONFIG}: rode `orq notify setup`")
    ok = notify.publish(cfg, "orq · teste", "Notificação de teste do orq.")
    print("enviada" if ok else "falhou (ver rede)")
    return 0 if ok else 1
```

`nt = sub.add_parser("notify"); nt.add_argument("action", choices=["setup", "test"])`; linha no `USAGE`.

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): notify.py — ntfy (publicar, botões, ler respostas) e orq notify setup|test`.

---

### Task 3: pergunta aberta, `/answer` e espera

**Files:**
- Create: `src/orq/intervene.py`
- Modify: `src/orq/control.py` (`answers`, `/answer`, `HELP`)
- Test: `tests/test_intervene.py`

**Interfaces:**
- Consumes: `Engine.notifier`, `Engine.notify`, `notify.ask_payload`, `notify.poll`, `Config.intervene_seconds`.
- Produces: `intervene.new_ask(task, kind, phase, question, diagnosis, options, recommended, deadline=None) -> dict`
  (campos `id, task, kind, phase, question, diagnosis, options, recommended, deadline, rounds, opened, reply`);
  `await intervene.wait(eng, ask) -> str | None`; `intervene.close(eng, ask, **answer)`;
  `intervene.match_option(ask, text) -> dict | None`; `Control.answers: dict[str, str]`; `POLL_S = 15`.

- [ ] **Step 1: testes que falham**

```python
# tests/test_intervene.py
import asyncio, time
import pytest
from orq import intervene
from .test_engine import APPROVED, EXEC_OK, PLAN, engine, make_queue

OPTS = [{"id": "a", "label": "A", "detail": "", "action": "retry", "note": "n-a"},
        {"id": "b", "label": "B", "detail": "", "action": "skip", "note": ""}]

async def until(cond, n=300):
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condição não veio")

def eng(tmp_path):
    return engine(tmp_path, make_queue(tmp_path, {"plan": [PLAN], "execute": [EXEC_OK], "review": [APPROVED]},
                                       intervene="enabled = true"))

async def test_resposta_pelo_answer(tmp_path):
    e = eng(tmp_path)
    ask = intervene.new_ask("01-a", "failed", "exec", "E agora?", "d", OPTS, "a")
    job = asyncio.create_task(intervene.wait(e, ask))
    await until(lambda: (e.s.top("open_ask") or {}).get("id") == ask["id"])
    e.s.send(f"/answer velho 1"); e.s.send(f"/answer {ask['id']} 2")
    assert await job == "2"
    acks = [x for x in e.s.events() if x["type"] == "control_ack"]
    assert [a["ok"] for a in acks] == [False, True]
    assert intervene.match_option(ask, "2")["id"] == "b" and intervene.match_option(ask, "a")["id"] == "a"
    assert intervene.match_option(ask, "talvez") is None
    intervene.close(e, ask, action="skip")
    assert e.s.top("open_ask") is None and [x["type"] for x in e.s.events()][-1] == "ask_answer"

async def test_prazo_vencido(tmp_path):
    e = eng(tmp_path)
    ask = intervene.new_ask("01-a", "council", "plan_questions", "Q?", "d", OPTS, "a", deadline=time.time() + 0.2)
    assert await intervene.wait(e, ask) is None

async def test_resposta_pelo_ntfy(tmp_path, monkeypatch):
    e = eng(tmp_path)
    e.notifier = {"server": "https://ntfy.sh", "topic": "t"}
    monkeypatch.setattr(intervene.notify, "publish", lambda *a, **k: True)
    ask = intervene.new_ask("01-a", "failed", "exec", "E agora?", "d", OPTS, "a")
    monkeypatch.setattr(intervene.notify, "poll", lambda cfg, since: ([f"{ask['id']} 1"], "m9"))
    assert await asyncio.wait_for(intervene.wait(e, ask), 5) == "1"
    assert any(x.get("source") == "ntfy" for x in e.s.events() if x["type"] == "control_ack")
```

- [ ] **Step 2:** `pytest tests/test_intervene.py` → FAIL (módulo não existe).

- [ ] **Step 3: implementação**

```python
# src/orq/control.py
HELP += " · /answer <id> <nº ou texto> (responde a pergunta aberta)"
# __init__: self.answers: dict[str, str] = {}
# apply(), antes de "decision":
        if cmd == "answer":
            m = re.match(r"(\S+)\s+(.+)$", rest, re.S)
            if not m:
                return False, "uso: /answer <id da pergunta> <nº da opção ou texto>"
            open_ = self.s.top("open_ask") or {}
            if open_.get("id") != m.group(1):
                return False, f"a pergunta {m.group(1)} não está aberta"
            self.answers[m.group(1)] = m.group(2).strip()
            self.resumed.set()
            return True, "resposta recebida"
```

```python
# src/orq/intervene.py
"""Intervenção do Victor: a fila pausa, avisa (painel e ntfy) e espera a resposta a uma pergunta com opções. A
pergunta aberta mora em state.json (open_ask): sobrevive a um `orq resume`."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from . import notify
from .control import StopRun

if TYPE_CHECKING:
    from .engine import Engine

POLL_S = 15
ACTIONS = ("retry", "replan", "accept", "skip", "stop")


def new_ask(task: str, kind: str, phase: str, question: str, diagnosis: str, options: list[dict],
            recommended: str, deadline: float | None = None) -> dict:
    return {"id": f"{time.time_ns():x}"[-8:], "task": task, "kind": kind, "phase": phase, "question": question,
            "diagnosis": diagnosis, "options": options, "recommended": recommended, "deadline": deadline,
            "rounds": 0, "opened": time.time(), "reply": ""}


def match_option(ask: dict, text: str) -> dict | None:
    t = text.strip()
    if t.isdigit() and 1 <= int(t) <= len(ask["options"]):
        return ask["options"][int(t) - 1]
    return next((o for o in ask["options"] if o["id"] == t), None)


def open_(eng: "Engine", ask: dict) -> None:
    """Grava a pergunta, registra o evento e avisa. Reabrir a mesma (resume) não repete o aviso."""
    if (eng.s.top("open_ask") or {}).get("id") == ask["id"]:
        return
    eng.s.set_top("open_ask", ask)
    eng.s.event("ask", {k: ask[k] for k in ("id", "task", "kind", "question", "diagnosis", "options", "recommended")})
    if eng.notifier:
        p = notify.ask_payload(eng.notifier, eng.queue_name(), ask)
        eng.notify(p["title"], p["message"], p["priority"], p["actions"])
    else:
        notify.desktop(f"{ask['task']} precisa de você: {ask['question']}")


async def wait(eng: "Engine", ask: dict) -> str | None:
    """Espera a resposta (painel, `orq send` ou ntfy). → o texto, ou None se o prazo venceu."""
    open_(eng, ask)
    ctl = eng.control
    since, next_poll, last_remind = str(int(ask["opened"])), 0.0, time.time()
    while True:
        ctl.drain()
        if ctl.stop:
            raise StopRun
        if ask["id"] in ctl.answers:
            return ctl.answers.pop(ask["id"])
        now = time.time()
        if ask.get("deadline") and now >= ask["deadline"]:
            return None
        if eng.notifier and now >= next_poll:
            msgs, since = await asyncio.to_thread(notify.poll, eng.notifier, since)
            for m in msgs:
                eng.s.send(f"/answer {m}", source="ntfy")
            next_poll = now + POLL_S
        if not ask.get("deadline") and now - last_remind >= eng.cfg.intervene_seconds("reminder"):
            eng.notify(f"orq · lembrete: {ask['task']} ainda precisa de você", notify._clip(ask["question"], 200), 4)
            last_remind = now
        ctl.resumed.clear()
        try:
            await asyncio.wait_for(ctl.resumed.wait(), ctl.poll_interval)
        except asyncio.TimeoutError:
            pass


def close(eng: "Engine", ask: dict, **answer) -> None:
    eng.s.set_top("open_ask", None)
    eng.s.event("ask_answer", {"id": ask["id"], "task": ask["task"], "kind": ask["kind"],
                               "question": ask["question"], **answer})
```

`Engine.queue_name()` (extraído de `start_event`): `self.cfg.queue_dir.parent.name if self.cfg.queue_dir.name ==
"orq" else self.cfg.queue_dir.name`.

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): pergunta aberta (open_ask), /answer e espera com leitura do ntfy`.

---

### Task 4: decisão do conselho sem unanimidade vira pergunta

**Files:**
- Modify: `src/orq/intervene.py` (`council()`), `src/orq/council.py` (`record_victor()`), `src/orq/control.py`
  (`decision()` usa `record_victor`), `src/orq/engine.py` (`resolve_questions`), `src/orq/journal.py`
  (`NOTICE_LABEL["decision_no_victor"]`)
- Test: `tests/test_intervene.py`

**Interfaces:**
- Consumes: `new_ask`, `wait`, `close`, `match_option` (Task 3).
- Produces: `await intervene.council(eng, t, dec: dict, ask: dict | None = None) -> str` (linha de resposta para o
  prompt); `council.record_victor(store, task, orig: dict, choice, label, why) -> str`.

- [ ] **Step 1: testes que falham**

```python
# tests/test_intervene.py
from .test_engine import Q, vote, types

async def test_conselho_2_pts_pergunta_e_victor_escolhe(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [{"summary": "s", "questions": [Q]}, PLAN], "execute": [EXEC_OK],
                                "review": [APPROVED], "voter:vote": [vote("a"), vote("a"), vote("b")]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    ask = e.s.top("open_ask")
    assert ask["kind"] == "council" and ask["recommended"] == "a" and len(ask["options"]) == 3
    e.s.send(f"/answer {ask['id']} 2")
    assert await job
    decs = [x for x in e.s.events() if x["type"] == "decision"]
    assert (decs[-1]["source"], decs[-1]["choice"]) == ("victor", "b")
    upd = next((e.s.dir / "01-a" / "calls").glob("plan-update-*.prompt.md")).read_text()
    assert "decisão do Victor" in upd

async def test_conselho_sem_resposta_segue_com_a_escolha(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [{"summary": "s", "questions": [Q]}, PLAN], "execute": [EXEC_OK],
                                "review": [APPROVED], "voter:vote": [vote("a"), vote("a"), vote("b")]},
                     intervene='enabled = true\ndecision_timeout = "1s"')
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert [x["kind"] for x in e.s.events() if x["type"] == "notice"] .count("decision_no_victor") == 1
    assert "[DECISÃO SEM VICTOR]" in e.s.journal_path.read_text()
    assert e.s.top("open_ask") is None
```

- [ ] **Step 2:** `pytest tests/test_intervene.py -k conselho` → FAIL (nenhuma pergunta abre).

- [ ] **Step 3: implementação**

```python
# src/orq/council.py
def record_victor(store, task: str, orig: dict, choice: str, label: str, why: str) -> str:
    """Decisão do Victor sobre uma pergunta do conselho: evento + decisions.md. → a linha para o prompt."""
    store.event("decision", {
        "task": task, "source": "victor", "qid": orig["qid"], "question": orig["question"],
        "context": orig.get("context", ""), "options": orig["options"], "votes": [], "choice": choice,
        "label": label, "points": None, "tiebreak": "", "why": why, "override": choice != orig["choice"]})
    d = store.dir / task / "decisions.md"
    d.parent.mkdir(parents=True, exist_ok=True)
    with open(d, "a") as fh:
        fh.write(f"## {orig['question']} (decisão do Victor)\n\nEscolha: `{choice}` — {label}. {why}\n\n")
    return f"- **{orig['question']}** → `{choice}` — {label} (decisão do Victor). {why}"
```

`control.decision()` passa a chamar `council.record_victor(self.s, task, orig, choice, label, why)` com o mesmo
`why` de hoje (e mantém a criação da tarefa de ajuste quando a tarefa já terminou).

```python
# src/orq/intervene.py
from . import council as council_mod
from .council import points_label

async def council(eng, t, dec: dict, ask: dict | None = None) -> str:
    """Decisão com 2 ou 2,5 pts: pergunta ao Victor; sem resposta no prazo, fica a do conselho."""
    votes = ", ".join(f"{v['option_id']}" for v in dec.get("votes") or [])
    ask = ask or new_ask(t.id, "council", eng.s.get(t.id, "phase"), dec["question"],
                         f"Conselho sem unanimidade ({points_label(dec['points'])} pts; votos {votes}). "
                         f"Escolheu `{dec['choice']}` — {dec['label']}: {dec.get('why', '')}",
                         [{**o, "action": "", "note": ""} for o in dec["options"]], dec["choice"],
                         deadline=time.time() + eng.cfg.intervene_seconds("decision_timeout"))
    ask["qid"] = dec["qid"]
    while True:
        text = await wait(eng, ask)
        if text is None:
            close(eng, ask, timeout=True, choice=dec["choice"])
            eng.s.notice("decision_no_victor", f"Sem resposta: segue com `{dec['choice']}` — {dec['label']}.", t.id)
            eng.notify(f"orq · {t.id}: decisão seguiu sem você", notify._clip(dec["question"], 200))
            return (f"- **{dec['question']}** → `{dec['choice']}` — {dec['label']} (conselho, "
                    f"{points_label(dec['points'])} pontos; o Victor não respondeu no prazo).")
        opt = match_option(ask, text)
        choice, label = (opt["id"], opt["label"]) if opt else ("victor", text)  # Task 6 troca por resolve()
        close(eng, ask, choice=choice, answer=text)
        return council_mod.record_victor(eng.s, t.id, dec, choice, label, "Escolhida pelo Victor no painel.")
```

```python
# src/orq/engine.py, resolve_questions(): o laço vira
        for q in qs:
            open_ = self.s.top("open_ask") or {}
            if open_.get("kind") == "council" and open_.get("qid") == q["id"] and open_.get("task") == t.id:
                dec = next(e for e in reversed(self.s.events()) if e["type"] == "decision" and e.get("qid") == q["id"])
                a = await intervene.council(self, t, dec, ask=open_)   # resume: mesma pergunta, sem novo conselho
            else:
                a = await council.decide(self, t, source, q)
                if a is None:
                    return 2, ""
                dec = next(e for e in reversed(self.s.events()) if e["type"] == "decision" and e.get("qid") == q["id"])
                if self.cfg.intervene and dec.get("points") is not None and dec["points"] < 3:
                    a = await intervene.council(self, t, dec)
            answers += a + "\n"
```

`journal.NOTICE_LABEL["decision_no_victor"] = "DECISÃO SEM VICTOR"`.

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): decisão do conselho sem unanimidade pergunta ao Victor (prazo: segue com a escolha)`.

---

### Task 5: bloqueio e falha viram pergunta (`Problem`, operador, ações)

**Files:**
- Create: `prompts/intervene.md`, `schemas/ask.json`
- Modify: `src/orq/engine.py` (`Problem`, `problem()`, trocas de `end(failed/blocked)`), `src/orq/intervene.py`
  (`failure()`, `build_failure_ask()`, `fallback_ask()`), `src/orq/harness/fake.py` (`SCHEMA_KEYS`)
- Test: `tests/test_intervene.py`

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces: `class Problem(Exception)` com `result, reason, phase`; `await Engine.problem(t, p, ask=None) -> str`
  (próxima fase); `await intervene.failure(eng, t, p, ask=None) -> tuple[str, str]` (ação, nota).

Mapeamento de cada `end` de hoje para `raise Problem(result, reason, phase_para_refazer)`:

| Onde | result | phase |
|---|---|---|
| `start`, árvore suja | blocked | `start` |
| `plan` sem saída | failed | `plan` |
| `plan_questions` rc 2 / atualização falhou | failed | `plan_questions` |
| `exec` sem saída | failed | `exec` |
| `after_exec` status blocked / rc 2 | blocked / failed | `exec` (ou `takeover` se `answers_phase == "takeover_answers"`) |
| `clean` sem saída / continuou suja | failed / blocked | `clean` (ou `final_clean`) |
| `review` sem saída / rc 2 | failed | `review` (ou `final_review` se `role == "reviewer"`) |
| `takeover` sem saída | failed | `takeover` |
| `final_verify` falhou | failed | `takeover` |
| `final_review` reprovou | failed | `takeover` |

- [ ] **Step 1: testes que falham**

```python
# tests/test_intervene.py
ASK_OUT = {"question": "O executor travou. E agora?", "diagnosis": "Faltou a lib X.",
           "options": [{"id": "1", "label": "Tentar de novo usando a lib Y", "detail": "", "action": "retry", "note": "use a lib Y"},
                       {"id": "2", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                       {"id": "3", "label": "Parar a fila", "detail": "", "action": "stop", "note": ""}],
           "recommended": "1"}
BLOCKED = {**EXEC_OK, "_sh": "true", "status": "blocked", "commits": [], "summary": "Sem a lib X."}

async def answer_when_open(e, text):
    await until(lambda: e.s.top("open_ask"))
    e.s.send(f"/answer {e.s.top('open_ask')['id']} {text}")

async def test_bloqueio_retry_com_nota(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED, EXEC_OK], "review": [APPROVED],
                                "ask": [ASK_OUT]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "1")
    assert await job and e.s.get("01-a", "result") == "ok"
    execs = [c for c in e.harness("fake").calls if c.name.startswith("exec-")]
    assert "use a lib Y" in execs[-1].prompt
    assert [x["action"] for x in e.s.events() if x["type"] == "ask_answer"] == ["retry"]

async def test_operador_falhou_usa_opcoes_padrao(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED],
                                "ask": [{"_error": "fatal"}]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    assert [o["action"] for o in e.s.top("open_ask")["options"]] == ["retry", "skip", "stop"]
    await answer_when_open(e, "2")
    assert await job and e.s.get("01-a", "result") == "skipped"

async def test_accept_fecha_como_ok_victor(tmp_path):
    out = {**ASK_OUT, "options": [*ASK_OUT["options"][:2], {"id": "3", "label": "Aceitar", "detail": "",
                                                              "action": "accept", "note": ""}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED], "ask": [out]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "3")
    assert await job and e.s.get("01-a", "result") == "ok_victor"

async def test_resume_com_pergunta_aberta_nao_chama_o_operador(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED, EXEC_OK], "review": [APPROVED],
                                "ask": [ASK_OUT]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await until(lambda: e.s.top("open_ask"))
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    from orq.engine import Engine
    from orq.store import RunStore
    e2 = Engine(cfg, RunStore(e.s.dir))
    job2 = asyncio.create_task(e2.run())
    await answer_when_open(e2, "1")
    assert await job2 and e2.s.get("01-a", "result") == "ok"
    assert not [c for c in e2.harness("fake").calls if c.name.startswith("intervene-")]
```

- [ ] **Step 2:** `pytest tests/test_intervene.py` → FAIL nos 4 novos.

- [ ] **Step 3: implementação**

`schemas/ask.json`:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["diagnosis", "question", "options", "recommended"],
  "properties": {
    "diagnosis": {"type": "string", "description": "o que aconteceu, em até 3 frases, sem código nem caminhos"},
    "question": {"type": "string", "description": "a pergunta ao Victor, até 200 caracteres, sem código nem caminhos"},
    "options": {"type": "array", "minItems": 3, "maxItems": 4, "items": {
      "type": "object", "additionalProperties": false, "required": ["id", "label", "detail", "action", "note"],
      "properties": {
        "id": {"type": "string"},
        "label": {"type": "string", "description": "até 60 caracteres, sem detalhe do cliente"},
        "detail": {"type": "string"},
        "action": {"type": "string", "enum": ["retry", "replan", "accept", "skip", "stop"]},
        "note": {"type": "string", "description": "instrução que entra no próximo prompt (retry/replan); vazio nas outras"}}}},
    "recommended": {"type": "string", "description": "id da opção recomendada"}
  }
}
```

`prompts/intervene.md`:

```markdown
Você é o OPERADOR de uma fila automática de trabalho (orq). A tarefa `{{TASK_ID}}` não consegue seguir sozinha e o
Victor, dono do projeto, precisa decidir. **Só leitura**: não altere nada.

Repositório: {{REPO}} · run dir: {{RUN_DIR}}
Situação: **{{KIND}}** na fase `{{PHASE}}`. Motivo registrado pelo motor: {{REASON}}

Leia `{{RUN_DIR}}/{{TASK_ID}}/report.md` (o que a tarefa já fez), o fim de `{{RUN_DIR}}/orq.log` e, se ajudar, o
`git status` e o `git log` do repositório. Depois monte a pergunta:

- `diagnosis`: o que aconteceu e por quê, em até 3 frases.
- `question`: o que o Victor precisa decidir, até 200 caracteres.
- `options`: 3 ou 4, cada uma com uma `action`:
  - `retry` refaz a fase `{{PHASE}}`; `note` é a instrução concreta que muda o resultado desta vez.
  - `replan` volta ao plano; `note` diz o que o plano novo deve considerar.
  - `accept` aceita a tarefa como está. `skip` pula a tarefa. `stop` para a fila.
- `recommended`: o id da opção que você escolheria, e por quê no `detail` dela.

A pergunta e os rótulos vão para o celular do Victor por um serviço público: **nada de código, caminhos de arquivo,
nomes de cliente, diffs ou saídas de teste** em `question` e `label`. O detalhe vai em `diagnosis` e `detail`.
```

`src/orq/harness/fake.py`: `SCHEMA_KEYS["diagnosis"] = "ask"`.

```python
# src/orq/engine.py
class Problem(Exception):
    """A tarefa não consegue seguir sozinha. Com [intervene], vira pergunta ao Victor; sem, encerra a tarefa."""

    def __init__(self, result: str, reason: str, phase: str):
        super().__init__(reason)
        self.result, self.reason, self.phase = result, reason, phase
```

Em `_run_task`, o corpo do `while True` (do `t.base_prompt = …` até o `else: raise RuntimeError`) fica dentro de
`try: … except Problem as p: phase = await self.problem(t, p)`. Antes do `try`, no topo do laço:

```python
            open_ = s.top("open_ask") or {}
            if open_.get("task") == t.id and open_.get("kind") in ("failed", "blocked"):
                phase = await self.problem(t, Problem(open_["kind"], open_["reason"], open_["phase"]), ask=open_)
```

Cada `self.end(t, "failed"|"blocked", reason)` da tabela acima vira `raise Problem(...)`. Novo método:

```python
    async def problem(self, t: Task, p: Problem, ask: dict | None = None) -> str:
        """Sem intervenção: encerra a tarefa como hoje. Com: pergunta ao Victor e aplica a ação escolhida."""
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
            self.end(t, "ok_victor", f"Aceita pelo Victor. {p.reason}")
        if action == "skip":
            self.end(t, "skipped", f"Pulada pelo Victor. {p.reason}")
        raise StopRun
```

```python
# src/orq/intervene.py
def fallback_ask(t_id: str, p) -> dict:
    what = "bloqueada" if p.result == "blocked" else "falhou"
    return new_ask(t_id, p.result, p.phase, f"{t_id} {what}: {notify._clip(p.reason, 150)} O que fazer?",
                   "O operador não montou a pergunta; estas são as opções padrão.",
                   [{"id": "1", "label": f"Tentar de novo (fase {p.phase})", "detail": "", "action": "retry", "note": ""},
                    {"id": "2", "label": "Pular a tarefa", "detail": "", "action": "skip", "note": ""},
                    {"id": "3", "label": "Parar a fila", "detail": "", "action": "stop", "note": ""}], "1")


async def build_failure_ask(eng, t, p) -> dict:
    from .engine import hms, prompt
    out, _ = await eng.call(t, "operator", f"intervene-{hms()}", "ask", prompt(
        "intervene", REPO=eng.cfg.repo, RUN_DIR=eng.s.dir, TASK_ID=t.id, KIND=p.result, PHASE=p.phase,
        REASON=p.reason), gate=False)
    opts = [o for o in (out or {}).get("options") or [] if o.get("action") in ACTIONS][:4]
    if len(opts) < 2:
        ask = fallback_ask(t.id, p)
    else:
        rec = out["recommended"] if any(o["id"] == out["recommended"] for o in opts) else opts[0]["id"]
        ask = new_ask(t.id, p.result, p.phase, out["question"], out["diagnosis"], opts, rec)
    ask["reason"] = p.reason
    return ask


async def failure(eng, t, p, ask: dict | None = None) -> tuple[str, str]:
    ask = ask or await build_failure_ask(eng, t, p)
    while True:
        text = await wait(eng, ask)
        opt = match_option(ask, text)
        action, note = (opt["action"], opt["note"]) if opt else ("retry", text)  # Task 6 troca por resolve()
        close(eng, ask, action=action, note=note, answer=text)
        return action, note
```

`fallback_ask` também grava `ask["reason"] = p.reason` (via `build_failure_ask`).

- [ ] **Step 4:** suíte inteira verde (os testes antigos seguem com `enabled = false`).
- [ ] **Step 5:** commit `feat(orq): bloqueio e falha perguntam ao Victor (retry/replan/accept/skip/stop)`.

---

### Task 6: resposta em texto livre avaliada pelo operador

**Files:**
- Create: `prompts/resolve.md`, `schemas/resolve.json`
- Modify: `src/orq/intervene.py` (`resolve()`; `council()` e `failure()` usam), `src/orq/harness/fake.py`
- Test: `tests/test_intervene.py`

**Interfaces:**
- Produces: `await intervene.resolve(eng, t, ask, text) -> dict | None` (saída do schema `resolve`);
  `ask["reply"]` (última resposta do operador, mostrada no painel); `MAX_ROUNDS = 3`; evento `ask_reply`.

- [ ] **Step 1: testes que falham**

```python
# tests/test_intervene.py
def res(**kw):
    return {"sufficient": True, "reply": "ok", "option_id": "", "action": "", "note": "", "follow_up": None, **kw}

async def test_texto_livre_insuficiente_vira_nova_pergunta(tmp_path):
    follow = {"question": "Pular ou parar?", "diagnosis": "d", "recommended": "1",
              "options": [{"id": "1", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                          {"id": "2", "label": "Parar", "detail": "", "action": "stop", "note": ""},
                          {"id": "3", "label": "Tentar", "detail": "", "action": "retry", "note": ""}]}
    cfg = make_queue(tmp_path, {"plan": [PLAN], "execute": [BLOCKED], "review": [APPROVED], "ask": [ASK_OUT],
                                "resolve": [res(sufficient=False, reply="Preciso saber mais.", follow_up=follow)]},
                     intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "sei lá, vê aí")
    await until(lambda: (e.s.top("open_ask") or {}).get("question") == "Pular ou parar?")
    assert e.s.top("open_ask")["reply"] == "Preciso saber mais."
    await answer_when_open(e, "1")
    assert await job and e.s.get("01-a", "result") == "skipped"

async def test_texto_livre_suficiente_no_conselho(tmp_path):
    cfg = make_queue(tmp_path, {"plan": [{"summary": "s", "questions": [Q]}, PLAN], "execute": [EXEC_OK],
                                "review": [APPROVED], "voter:vote": [vote("a"), vote("a"), vote("b")],
                                "resolve": [res(option_id="c")]}, intervene="enabled = true")
    e = engine(tmp_path, cfg)
    job = asyncio.create_task(e.run())
    await answer_when_open(e, "vai de C, é mais simples")
    assert await job
    assert [x for x in e.s.events() if x["type"] == "decision"][-1]["choice"] == "c"
```

- [ ] **Step 2:** `pytest tests/test_intervene.py -k texto_livre` → FAIL.

- [ ] **Step 3: implementação**

`schemas/resolve.json` (todas as chaves obrigatórias, como os outros schemas; `follow_up` aceita `null`):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["sufficient", "reply", "option_id", "action", "note", "follow_up"],
  "properties": {
    "sufficient": {"type": "boolean"},
    "reply": {"type": "string", "description": "uma frase ao Victor: o que vai acontecer, ou o que falta saber"},
    "option_id": {"type": "string", "description": "decisão do conselho: id da opção escolhida, ou vazio"},
    "action": {"type": "string", "enum": ["", "retry", "replan", "accept", "skip", "stop"]},
    "note": {"type": "string", "description": "instrução para o próximo prompt (retry/replan) ou decisão livre"},
    "follow_up": {"type": ["object", "null"], "additionalProperties": false,
                  "required": ["diagnosis", "question", "options", "recommended"],
                  "properties": {"diagnosis": {"type": "string"}, "question": {"type": "string"},
                                 "recommended": {"type": "string"},
                                 "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {
                                   "type": "object", "additionalProperties": false,
                                   "required": ["id", "label", "detail", "action", "note"],
                                   "properties": {"id": {"type": "string"}, "label": {"type": "string"},
                                                  "detail": {"type": "string"}, "note": {"type": "string"},
                                                  "action": {"type": "string", "enum": ["retry", "replan", "accept", "skip", "stop"]}}}}}}
  }
}
```

`prompts/resolve.md`:

```markdown
Você é o OPERADOR de uma fila automática (orq). O Victor respondeu em texto livre a uma pergunta aberta; decida se a
resposta basta para a fila seguir sozinha. **Só leitura.**

Repositório: {{REPO}} · run dir: {{RUN_DIR}} · tarefa `{{TASK_ID}}` · tipo: {{KIND}}

Pergunta: {{QUESTION}}
Diagnóstico: {{DIAGNOSIS}}
Opções:
{{OPTIONS}}

Resposta do Victor: {{ANSWER}}

- Basta (`sufficient = true`): numa decisão do conselho (`council`), `option_id` = a opção que ele quis, ou vazio e
  `note` = a decisão dele em uma frase se não for nenhuma das opções. Nos outros tipos, `action` + `note` (a
  instrução concreta para o próximo prompt).
- Não basta (`sufficient = false`): `reply` diz o que falta; em tipos que não são `council`, `follow_up` traz a nova
  pergunta no mesmo formato (3–4 opções, uma recomendada; sem código nem caminhos em `question` e `label`). Em
  `council`, `follow_up = null`.
- `reply` sempre, em uma frase, dizendo o que **vai** acontecer.
```

`src/orq/harness/fake.py`: `SCHEMA_KEYS["sufficient"] = "resolve"` — e em `schema_key`, `"sufficient"` precisa
vir antes de `"reply"` no `required` (já vem, pela ordem do schema).

```python
# src/orq/intervene.py
MAX_ROUNDS = 3

async def resolve(eng, t, ask: dict, text: str) -> dict | None:
    from .engine import hms, prompt
    opts = "\n".join(f"{i}) `{o['id']}` {o['label']}" + (f" — ação {o['action']}" if o.get("action") else "")
                     for i, o in enumerate(ask["options"], 1))
    out, _ = await eng.call(t, "operator", f"resolve-{hms()}", "resolve", prompt(
        "resolve", REPO=eng.cfg.repo, RUN_DIR=eng.s.dir, TASK_ID=t.id, KIND=ask["kind"], QUESTION=ask["question"],
        DIAGNOSIS=ask["diagnosis"], OPTIONS=opts, ANSWER=text), gate=False)
    return out


def reask(eng, ask: dict, reply: str, follow: dict | None = None) -> dict:
    """Mantém a pergunta aberta com a resposta do operador (e, se houver, a pergunta nova no lugar)."""
    new = {**ask, "rounds": ask["rounds"] + 1, "reply": reply}
    if follow and new["rounds"] < MAX_ROUNDS:
        opts = [o for o in follow["options"] if o.get("action") in ACTIONS] or ask["options"]
        new.update(question=follow["question"], diagnosis=follow["diagnosis"], options=opts,
                   recommended=follow["recommended"] if any(o["id"] == follow["recommended"] for o in opts) else opts[0]["id"],
                   id=f"{time.time_ns():x}"[-8:], opened=time.time())
    if new["rounds"] >= MAX_ROUNDS:
        new["reply"] = (reply + " " if reply else "") + "Responda com o número de uma opção."
    eng.s.event("ask_reply", {"id": ask["id"], "task": ask["task"], "text": new["reply"]})
    eng.s.set_top("open_ask", new)
    if new["id"] != ask["id"]:
        eng.s.set_top("open_ask", None)
        open_(eng, new)
    return new
```

Em `council()` e `failure()`, quando `match_option` falha:

```python
        if ask["rounds"] >= MAX_ROUNDS:
            ask = reask(eng, ask, "")
            continue
        out = await resolve(eng, t, ask, text)
        if out is None:
            ask = reask(eng, ask, "Não entendi — responda com o número de uma opção.")
            continue
        if not out["sufficient"]:
            ask = reask(eng, ask, out["reply"], out.get("follow_up") if ask["kind"] != "council" else None)
            continue
        # council: choice = out["option_id"] se for de uma opção; senão ("victor", out["note"] or text)
        # failure: action, note = out["action"] or "retry", out["note"] or text
```

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): resposta em texto livre avaliada pelo operador (basta? senão pergunta de novo)`.

---

### Task 7: journal, report e timeline das perguntas

**Files:**
- Modify: `src/orq/journal.py` (`event_line`, `_section`, "Leia primeiro")
- Test: `tests/test_base.py`

**Interfaces:**
- Consumes: eventos `ask`, `ask_reply`, `ask_answer`, notice `decision_no_victor`.

- [ ] **Step 1: teste que falha**

```python
# tests/test_base.py
def test_linhas_da_intervencao():
    ask = {"type": "ask", "ts": "2026-09-26T10:00:00-03:00", "id": "q1", "task": "04-x", "kind": "blocked",
           "question": "E agora?", "diagnosis": "d", "options": [], "recommended": "1"}
    ans = {"type": "ask_answer", "ts": "2026-09-26T10:05:00-03:00", "id": "q1", "task": "04-x", "kind": "blocked",
           "question": "E agora?", "action": "retry", "note": "use Y", "answer": "1"}
    assert journal.event_line(ask) == "[PRECISA DE VOCÊ] 04-x: E agora?"
    assert journal.event_line(ans) == "[INTERVENÇÃO] 04-x: retry — use Y"
    md = journal.render([{"type": "run_start", "ts": ask["ts"]}, ask, ans])
    assert "- **[INTERVENÇÃO]** [04-x](04-x/report.md) — E agora? → retry: use Y" in md
    assert "### Pergunta ao Victor" in journal.render_task([ask, ans], "04-x")
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: implementação**

```python
# event_line
    if t == "ask":
        return f"[PRECISA DE VOCÊ] {task}: {_clip(e['question'], 200)}"
    if t == "ask_reply":
        return f"[OPERADOR] {task}: {_clip(e.get('text', ''), 300)}"
    if t == "ask_answer":
        if e.get("kind") == "council":
            return None  # o evento decision já conta
        return f"[INTERVENÇÃO] {task}: {e.get('action')}" + (f" — {_clip(e['note'], 200)}" if e.get("note") else "")
# _section
    if t == "ask":
        opts = "\n".join(f"{i}. `{o['id']}` {esc(o['label'])}" + (" **← recomendada**" if o["id"] == e["recommended"] else "")
                         for i, o in enumerate(e.get("options") or [], 1))
        return f"### Pergunta ao Victor ({e['kind']})\n\n{esc(e['question'])}\n\n{esc(e.get('diagnosis', ''))}\n\n{opts}\n"
    if t == "ask_answer" and e.get("kind") != "council":
        return f"**Resposta do Victor:** {esc(e.get('answer', ''))} → `{e.get('action')}`" + (f": {esc(e['note'])}" if e.get("note") else "") + "\n"
# attn (render), junto dos outros:
        + [f"- **[INTERVENÇÃO]** {link(e['task'])} — {esc(e['question'])} → {e.get('action')}" + (f": {esc(e['note'])}" if e.get("note") else "")
           for e in ev if e["type"] == "ask_answer" and e.get("kind") != "council"]
```

- [ ] **Step 4:** suíte inteira verde.
- [ ] **Step 5:** commit `feat(orq): perguntas e respostas do Victor no journal, no report e na timeline`.

---

### Task 8: painel — bloco da pergunta e estilos

**Files:**
- Modify: `src/orq/tui/model.py` (`TaskRow.styled()`, `line_style()`, `ask_text()`, espera no `header`/`task_rows`),
  `src/orq/tui/app.py` (`#ask`, roteamento do chat, `Text` com estilo, separador antes de `task_start`)
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces: `TaskRow.styled(width) -> rich.text.Text`; `model.line_style(e: dict) -> str`;
  `model.ask_text(ask: dict, now: float | None = None) -> Text`.

- [ ] **Step 1: testes que falham**

```python
# tests/test_tui.py
from orq import intervene

async def test_estilos_da_lista_e_timeline(tmp_path):
    e = await finished_run(tmp_path)
    e.s.set("03-c", "result", None); e.s.set("03-c", "phase", "exec")
    rows = model.task_rows(e.s, e.s.events())
    styles = [str(r.styled(60).style) for r in rows]
    assert "dim" in styles[0] and "bold" in styles[2]
    assert model.line_style({"type": "task_start"}).startswith("bold")
    assert "reverse" in model.line_style({"type": "ask"})
    assert "italic" in model.line_style({"type": "operator"})

async def test_bloco_da_pergunta_e_resposta(tmp_path):
    e = await finished_run(tmp_path)
    ask = intervene.new_ask("03-c", "blocked", "exec", "E agora?", "diag",
                            [{"id": "1", "label": "Tentar", "detail": "", "action": "retry", "note": ""},
                             {"id": "2", "label": "Pular", "detail": "", "action": "skip", "note": ""},
                             {"id": "3", "label": "Parar", "detail": "", "action": "stop", "note": ""}], "1")
    e.s.set_top("open_ask", ask)
    assert "★ RECOMENDADA" in model.ask_text(ask).plain and "[PRECISA DE VOCÊ]" in model.ask_text(ask).plain
    app = OrqApp(e.s.dir)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause(0.6)
        assert app.query_one("#ask").display
        assert "esperando você" in str(app.query_one("#header", Static).render())
        chat = app.query_one("#chat", Input)
        chat.value = "1"
        await pilot.press("enter")
        assert f'"/answer {ask["id"]} 1"' in e.s.inbox_path.read_text()
        e.s.set_top("open_ask", None)
        await pilot.pause(0.6)
        assert not app.query_one("#ask").display
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: implementação**

```python
# src/orq/tui/model.py
from rich.text import Text

STYLE_BY_TYPE = {"task_start": "bold", "task_end": "bold", "plan": "cyan", "exec": "", "verify": "blue",
                 "review": "magenta", "decision": "yellow", "operator": "italic green", "ask": "reverse bold yellow",
                 "ask_reply": "italic green", "ask_answer": "bold yellow", "notice": "bold red",
                 "run_start": "bold", "run_end": "bold", "run_summary": "italic"}

def line_style(e: dict) -> str:
    return STYLE_BY_TYPE.get(e.get("type", ""), "")

# TaskRow
    def styled(self, width: int = 60) -> Text:
        style = {"✓": "dim", "⊘": "dim", "▶": "bold yellow", "⏸": "reverse bold", "✗": "bold red"}.get(self.glyph, "")
        return Text(self.text(width), style=style)

# task_rows(): depois de montar glyph/status, se a tarefa é a da pergunta aberta:
    waiting = (store.top("open_ask") or {}).get("task")
    ...
        if f.stem == waiting:
            glyph, status = "⏸", "esperando você"

# header(): motor
    ask = store.top("open_ask")
    if ask and not re_:
        motor = f"⏸ esperando você · {fmt_hms(now - ask['opened'])}"

def ask_text(ask: dict, now: float | None = None) -> Text:
    t = Text()
    kind = {"council": "decisão sem unanimidade", "blocked": "bloqueada", "failed": "falhou"}.get(ask["kind"], ask["kind"])
    t.append(f" [PRECISA DE VOCÊ] {ask['task']} · {kind} \n", style="reverse bold")
    t.append(ask["question"] + "\n", style="bold")
    if ask.get("diagnosis"):
        t.append("Por quê: " + ask["diagnosis"] + "\n")
    for i, o in enumerate(ask["options"], 1):
        rec = o["id"] == ask["recommended"]
        t.append(f" {i}) " + ("★ RECOMENDADA  " if rec else "") + o["label"] + "\n", style="bold yellow" if rec else "")
    if ask.get("reply"):
        t.append("operador: " + ask["reply"] + "\n", style="italic")
    foot = f"responda 1–{len(ask['options'])} ou escreva"
    if ask.get("deadline"):
        foot += f" · segue sozinha com a recomendada às {datetime.fromtimestamp(ask['deadline']):%H:%M}"
    t.append(foot, style="dim")
    return t
```

```python
# src/orq/tui/app.py
# CSS: "#ask { dock: bottom; height: auto; border: heavy $warning; padding: 0 1; display: none; }"
# compose(): antes do Input do chat: yield Static(id="ask")
# refresh_data():
        self.query_one("#tasks", Static).update(Text("\n").join(r.styled(width) for r in rows) if rows else Text("(fila vazia)"))
        ask = self.store.top("open_ask")
        box = self.query_one("#ask", Static)
        box.display = bool(ask)
        if ask:
            box.update(model.ask_text(ask))
# timeline: separador antes de cada task_start e estilo por tipo
            if ev["type"] == "task_start" and tl.option_count:
                tl.add_option(Option(Text("─" * 40, style="dim"), disabled=True))
            tl.add_option(Option(Text(text, style=model.line_style(ev)), id=str(idx)))
# on_input_submitted(), antes do "if text.startswith('/')":
        ask = self.store.top("open_ask")
        if ask and not text.startswith("/"):
            self.store.send(f"/answer {ask['id']} {text}")
            self.local(f"› resposta: {text}")
            return
```

(Se `Option(..., disabled=True)` não existir na versão instalada do Textual, usar `tl.add_option(None)` — separador
nativo do `OptionList`; conferir com `uv run python -c "import textual; print(textual.__version__)"`.)

- [ ] **Step 4:** suíte inteira verde; conferir o painel com a fila fake (`harness = "fake"`) abrindo uma pergunta.
- [ ] **Step 5:** commit `feat(orq): painel — bloco da pergunta, resposta pelo chat e estilos na lista e na timeline`.

---

### Task 9: README, TODO e fechamento

**Files:**
- Modify: `README.md`, `TODO.md`

- [ ] **Step 1:** README — seção nova "Quando a fila precisa de você": gatilhos, ações, `/answer`, `[intervene]`;
  seção "ntfy": instalar o app (Play Store/F-Droid no Android, App Store no iPhone); `orq notify setup`; no app
  `+ Subscribe to topic`, servidor `ntfy.sh`; no Android ligar **Instant delivery** na assinatura; no iPhone não há
  botões (limite do ntfy) — responder pelo painel ou por `https://ntfy.sh/app` no navegador; o que vai na
  notificação (pergunta e rótulos; nunca código). Etiquetas novas: `[PRECISA DE VOCÊ]`, `[INTERVENÇÃO]`,
  `[DECISÃO SEM VICTOR]`. Comando `/answer` na tabela do chat; `orq notify setup|test` em Comandos.
- [ ] **Step 2:** TODO — marcar ntfy, pausa com pergunta, e os dois itens de estilo do painel.
- [ ] **Step 3:** suíte inteira verde; commit `docs(orq): intervenção e ntfy no README; TODO fechado`.
