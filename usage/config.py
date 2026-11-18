"""Lê e valida o config TOML do ai-usage-monitor."""
import tomllib
from pathlib import Path

from collectors import TYPES

DEFAULT_PATH = Path.home() / ".config/ai-usage/config.toml"
MIN_INTERVAL = 30


def load(path=DEFAULT_PATH):
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    interval = int(raw.get("interval_seconds", 300))
    if interval < MIN_INTERVAL:
        raise ValueError(f"interval_seconds deve ser >= {MIN_INTERVAL} (está {interval})")
    accounts = raw.get("accounts") or {}
    if not accounts:
        raise ValueError("nenhuma conta em [accounts.<nome>]")
    for name, opts in accounts.items():
        kind = opts.get("type")
        if kind not in TYPES:
            raise ValueError(f"conta {name}: type {kind!r} desconhecido (use {', '.join(TYPES)})")
        if kind == "claude" and not opts.get("config_dir"):
            raise ValueError(f"conta {name}: type claude precisa de config_dir")
    return {
        "interval_seconds": interval,
        "db": Path(raw.get("db", "~/.local/share/ai-usage/usage.db")).expanduser(),
        "port": int(raw.get("port", 49381)),
        "accounts": accounts,
    }
