"""SQLite do ai-usage-monitor: uma linha por janela de uso por coleta."""
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
  ts INTEGER NOT NULL,   -- epoch da coleta
  account TEXT NOT NULL, -- nome da conta no config
  plan TEXT,
  window TEXT,           -- "Sessão (5h)", "Semana", ...; nulo em linha de erro
  used REAL,             -- % usado
  resets_at TEXT,        -- ISO 8601
  error TEXT
);
CREATE INDEX IF NOT EXISTS samples_account_ts ON samples(account, ts);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def insert_snapshot(db, ts, results):
    rows = []
    for account, data in results.items():
        if "error" in data:
            rows.append((ts, account, None, None, None, None, data["error"]))
            continue
        for r in data["rows"]:
            rows.append((ts, account, data.get("plan"), r["label"], r["used"], r["resets_at"], None))
    with db:
        db.executemany("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _epoch(day, end=False):
    """YYYY-MM-DD no fuso local -> epoch do início (ou fim, se end) do dia."""
    d = datetime.strptime(day, "%Y-%m-%d").astimezone()
    return int(d.timestamp()) + (86400 if end else 0)


def query(db, accounts=(), window=None, start=None, end=None):
    sql, args = "SELECT * FROM samples WHERE 1=1", []
    if accounts:
        sql += f" AND account IN ({','.join('?' * len(accounts))})"
        args += list(accounts)
    if window:
        sql += " AND (window = ? OR window IS NULL)"
        args.append(window)
    if start:
        sql += " AND ts >= ?"
        args.append(_epoch(start))
    if end:
        sql += " AND ts < ?"
        args.append(_epoch(end, end=True))
    return [dict(r) for r in db.execute(sql + " ORDER BY ts", args)]


def meta(db):
    accounts = [r[0] for r in db.execute("SELECT DISTINCT account FROM samples ORDER BY account")]
    windows = [r[0] for r in db.execute(
        "SELECT DISTINCT window FROM samples WHERE window IS NOT NULL ORDER BY window")]
    return {"accounts": accounts, "windows": windows}
