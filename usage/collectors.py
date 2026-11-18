#!/usr/bin/env python3
"""Mostra os limites de uso (sessão de 5h e semana) de cada harness.

Uso: ai-usage [conta ...] [--json]
Contas: claude, claude2 (~/.claude*), codex, agy, openrouter.
Fontes: Claude = endpoint do /usage; Codex = `codex app-server`; Antigravity = `agy -p /quota`;
OpenRouter = API de créditos + custo por modelo registrado pelo opencode.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_LABELS = {
    "five_hour": "Sessão (5h)",
    "seven_day": "Semana",
    "seven_day_opus": "Semana Opus",
    "seven_day_sonnet": "Semana Sonnet",
    "seven_day_oauth_apps": "Semana apps",
}
WINDOW_LABELS = {300: "Sessão (5h)", 10080: "Semana"}


def row(label, used, resets_at):
    return {"label": label, "used": float(used), "resets_at": resets_at.isoformat() if resets_at else None}


# --- Claude Code ---------------------------------------------------------------

def claude(cred_path):
    oauth = json.loads(cred_path.read_text())["claudeAiOauth"]
    if oauth.get("expiresAt", 0) / 1000 < time.time():
        # Atalho: não renovamos o token aqui para não disputar o arquivo com o Claude Code.
        raise RuntimeError("token expirado: abra essa conta no Claude Code uma vez para renovar")
    req = urllib.request.Request(CLAUDE_USAGE_URL, headers={
        "Authorization": f"Bearer {oauth['accessToken']}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/ai-usage",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}") from e
    rows = [
        row(CLAUDE_LABELS.get(k, k), w["utilization"] or 0,
            datetime.fromisoformat(w["resets_at"].replace("Z", "+00:00")) if w.get("resets_at") else None)
        for k, w in data.items() if isinstance(w, dict) and "utilization" in w
    ]
    return {"plan": oauth.get("subscriptionType", "?"), "rows": rows, "notes": []}


# --- Codex -------------------------------------------------------------------------

def codex():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "ai-usage", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"},
    ]
    p = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    try:
        p.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        p.stdin.flush()
        for line in p.stdout:  # stdin fica aberto: o app-server sai se ele fechar antes da resposta
            msg = json.loads(line)
            if msg.get("id") == 2:
                break
        else:
            raise RuntimeError("codex app-server encerrou sem responder")
    finally:
        p.kill()
    if "error" in msg:
        raise RuntimeError(msg["error"].get("message", msg["error"]))
    res = msg["result"]
    rl = res["rateLimits"]
    rows = []
    for w in (rl.get("primary"), rl.get("secondary")):
        if w:
            mins = w["windowDurationMins"]
            rows.append(row(WINDOW_LABELS.get(mins, f"Janela {mins}min"), w["usedPercent"],
                            datetime.fromtimestamp(w["resetsAt"], timezone.utc) if w.get("resetsAt") else None))
    notes = []
    resets = (res.get("rateLimitResetCredits") or {}).get("availableCount", 0)
    if resets:
        notes.append(f"{resets} reset grátis de limite disponível")
    return {"plan": rl.get("planType", "?"), "rows": rows, "notes": notes}


# --- Antigravity ---------------------------------------------------------------

def agy():
    out = subprocess.run(["agy", "-p", "/quota"], capture_output=True, text=True, timeout=90, check=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        group, window, remaining, reset = parts
        window = window.replace(" Limit Remaining", "")
        label = f"{group.replace(' models', '').replace(' Models', '')} · " + \
            {"Five Hour": "Sessão (5h)", "Weekly": "Semana"}.get(window, window)
        # O agy informa o que RESTA; convertemos para usado, como nos outros.
        rows.append(row(label, 100 - float(remaining.rstrip("%")),
                        datetime.fromisoformat(reset.replace("Z", "+00:00"))))
    if not rows:
        raise RuntimeError(f"saída inesperada do agy: {out[:200]!r}")
    return {"plan": "google", "rows": rows, "notes": []}


# --- OpenRouter (via opencode) ------------------------------------------------

OPENCODE_DIR = Path.home() / ".local/share/opencode"


def openrouter_get(path, key):
    req = urllib.request.Request(f"https://openrouter.ai/api/v1/{path}", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["data"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: HTTP {e.code}") from e


def openrouter():
    key = os.environ.get("OPENROUTER_API_KEY") or \
        json.loads((OPENCODE_DIR / "auth.json").read_text())["openrouter"]["key"]
    notes = []
    credits = {}
    try:
        c = openrouter_get("credits", key)
        credits = {"comprado": c["total_credits"], "gasto": c["total_usage"],
                   "saldo": c["total_credits"] - c["total_usage"]}
    except RuntimeError as e:
        notes.append(f"saldo indisponível ({e})")
    try:
        k = openrouter_get("key", key)
        credits |= {"gasto hoje": k.get("usage_daily"), "gasto semana": k.get("usage_weekly"),
                    "gasto mês": k.get("usage_monthly")}
    except RuntimeError as e:
        notes.append(f"uso da chave indisponível ({e})")

    # Custo por modelo: o opencode grava o custo de cada resposta; é o que foi gasto por ele.
    now_ms = time.time() * 1000
    day = 86_400_000
    db = sqlite3.connect(f"file:{OPENCODE_DIR / 'opencode.db'}?mode=ro", uri=True)
    q = """select ltrim(json_extract(data,'$.modelID'),'~') m, count(*),
             sum(case when time_created >= ? then json_extract(data,'$.cost') else 0 end),
             sum(case when time_created >= ? then json_extract(data,'$.cost') else 0 end),
             sum(json_extract(data,'$.cost')), max(time_created)
           from message
           where json_extract(data,'$.providerID')='openrouter' and json_extract(data,'$.role')='assistant'
           group by m order by 5 desc"""
    models = [{"modelo": m, "respostas": n, "7d": c7 or 0, "30d": c30 or 0, "total": tot or 0,
               "último uso": datetime.fromtimestamp(last / 1000).astimezone().isoformat()}
              for m, n, c7, c30, tot, last in db.execute(q, (now_ms - 7 * day, now_ms - 30 * day))]
    db.close()
    return {"plan": "créditos", "rows": [], "credits": credits, "models": models, "notes": notes}


# --- saída ---------------------------------------------------------------------------

# Tipos que o ai-usage-monitor aceita no config: tipo -> função(opções da conta) -> dados.
# Harness novo (Kiro, ...) = uma função de coleta acima + uma entrada aqui.
TYPES = {
    "claude": lambda o: claude(Path(o["config_dir"]).expanduser() / ".credentials.json"),
    "codex": lambda o: codex(),
    "agy": lambda o: agy(),
    "openrouter": lambda o: openrouter(),
}


def collect(accounts):
    """accounts: {nome: {"type": ..., ...}} -> {nome: dados ou {"error": ...}}, em paralelo."""
    names = list(accounts)
    fns = [lambda o=accounts[n]: TYPES[o["type"]](o) for n in names]
    with ThreadPoolExecutor() as pool:
        return dict(zip(names, pool.map(run, fns)))


def sources():
    for d in sorted(Path.home().glob(".claude*")):
        cred = d / ".credentials.json"
        if d.is_dir() and cred.is_file():
            yield d.name.lstrip("."), (lambda c=cred: claude(c))
    yield "codex", codex
    yield "agy", agy
    yield "openrouter", openrouter


def until(iso):
    if not iso:
        return "-"
    at = datetime.fromisoformat(iso).astimezone()
    mins = max(0, int((at - datetime.now().astimezone()).total_seconds() // 60))
    d, rem = divmod(mins, 1440)
    h, m = divmod(rem, 60)
    rel = f"{d}d {h}h" if d else f"{h}h{m:02d}m"
    return f"reseta {at:%a %d/%m %H:%M} (em {rel})"


def bar(pct, width=20):
    filled = round(min(pct, 100) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def show(name, data):
    if "error" in data:
        print(f"\n{name}\n  ERRO: {data['error']}")
        return
    print(f"\n{name}  [{data['plan']}]")
    width = max(len(r["label"]) for r in data["rows"]) if data["rows"] else 0
    for r in data["rows"]:
        alert = "  << ALTO" if r["used"] >= 80 else ""
        print(f"  {r['label']:<{width}}  {bar(r['used'])} {r['used']:5.1f}% usado  {until(r['resets_at'])}{alert}")
    if data.get("credits"):
        print("  " + "   ".join(f"{k}: ${v:,.2f}" for k, v in data["credits"].items() if v is not None))
    if data.get("models"):
        w = max(len(m["modelo"]) for m in data["models"])
        print(f"\n  {'modelo (opencode)':<{w}}  {'resp.':>6}  {'7 dias':>8}  {'30 dias':>8}  {'total':>8}  último uso")
        for m in data["models"]:
            print(f"  {m['modelo']:<{w}}  {m['respostas']:>6}  ${m['7d']:>7.2f}  ${m['30d']:>7.2f}  ${m['total']:>7.2f}"
                  f"  {datetime.fromisoformat(m['último uso']):%d/%m/%Y}")
    for n in data["notes"]:
        print(f"  * {n}")


def run(fn):
    try:
        return fn()
    except FileNotFoundError as e:
        return {"error": f"não instalado: {e.filename}"}
    except Exception as e:  # uma fonte quebrada não derruba as outras
        return {"error": f"{type(e).__name__}: {e}"}


def main():
    args = sys.argv[1:]
    wanted = {a for a in args if not a.startswith("-")}
    chosen = [(n, fn) for n, fn in sources() if not wanted or n in wanted]
    with ThreadPoolExecutor() as pool:
        results = dict(zip([n for n, _ in chosen], pool.map(run, [fn for _, fn in chosen])))
    if "--json" in args:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for name, data in results.items():
            show(name, data)
    return 1 if any("error" in d for d in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
