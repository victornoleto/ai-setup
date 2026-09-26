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


def clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def ask_payload(cfg: dict, queue: str, ask: dict) -> dict:
    """Pergunta → kwargs de publish: pergunta e rótulos curtos; botões para a recomendada e as duas seguintes."""
    opts = ask["options"]
    lines = [f"{i}) " + ("★ " if o["id"] == ask["recommended"] else "") + clip(o["label"], 60)
             for i, o in enumerate(opts, 1)]
    order = sorted(range(len(opts)), key=lambda i: opts[i]["id"] != ask["recommended"])[:3]
    actions = [{"action": "http", "label": clip(f"{i + 1} · {opts[i]['label']}", 40), "method": "POST",
                "url": f"{cfg['server']}/{cfg['topic']}-r", "body": f"{ask['id']} {i + 1}", "clear": True}
               for i in order]
    return {"title": f"orq {queue} · {ask['task']} precisa de você", "priority": 5, "tags": ["raising_hand"],
            "message": clip(ask["question"], 200) + "\n" + "\n".join(lines), "actions": actions}


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
