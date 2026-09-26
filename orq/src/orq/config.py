"""Configuração em camadas, da mais fraca para a mais forte:
orq.toml global (ORQ_HOME) → <fila>/orq.toml (ou queue.conf legado) → variáveis ORQ_* → flags."""
from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ORQ_HOME = Path(os.environ.get("ORQ_HOME") or Path(__file__).resolve().parents[2])

ROLES = ("planner", "executor", "reviewer", "voter", "tiebreak", "operator", "wizard")
HARNESSES = ("claude", "codex", "opencode", "fake")

# Nome legado (queue.conf / ambiente) → caminho no TOML.
_LEGACY = {
    "ORQ_ACCOUNT": ("accounts", "claude", "default"),
    "ORQ_FALLBACK_ACCOUNT": ("accounts", "claude", "fallback"),
    "ORQ_ACCOUNT_DIR_1": ("accounts", "claude", "dirs", "1"),
    "ORQ_ACCOUNT_DIR_2": ("accounts", "claude", "dirs", "2"),
    "ORQ_VOTERS": ("roles", "voter", "count"),
    "ORQ_MAX_CYCLES": ("loop", "max_cycles"),
    "ORQ_MAX_DECISION_ROUNDS": ("loop", "max_decision_rounds"),
    "ORQ_ON_FAIL": ("loop", "on_fail"),
    "ORQ_CALL_TIMEOUT": ("time", "call_timeout"),
    "ORQ_LIMIT_MAX_WAIT": ("time", "limit_max_wait"),
    "ORQ_LIMIT_POLL": ("time", "limit_poll"),
    "ORQ_REPO": ("run", "repo"),
    "ORQ_RULES_FILE": ("run", "rules_file"),
    "ORQ_STREAM": ("ui", "stream"),
    "ORQ_STREAM_THINKING": ("ui", "thinking"),
    "ORQ_TEST_FORCE_CHANGES": ("test", "force_changes"),
}
for _r in ROLES:
    for _k in ("model", "effort", "account", "harness"):
        _LEGACY[f"ORQ_{_r.upper()}_{_k.upper()}"] = ("roles", _r, _k)


class ConfigError(Exception):
    pass


@dataclass
class Role:
    name: str
    harness: str
    model: str
    effort: str
    account: str = ""  # só o claude usa (CLAUDE_CONFIG_DIR)
    count: int = 1

    def label(self) -> str:
        return f"{self.harness}:{self.model} {self.effort}"


@dataclass
class Config:
    raw: dict
    queue_dir: Path
    roles: dict[str, Role] = field(default_factory=dict)

    # atalhos
    def get(self, *path, default=None):
        node = self.raw
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node

    @property
    def repo(self) -> Path:
        return Path(self.get("run", "repo") or ".").resolve()

    @property
    def max_cycles(self) -> int:
        return int(self.get("loop", "max_cycles", default=3))

    @property
    def max_decision_rounds(self) -> int:
        return int(self.get("loop", "max_decision_rounds", default=5))

    @property
    def on_fail(self) -> str:
        return str(self.get("loop", "on_fail", default="stop"))

    @property
    def voters(self) -> int:
        return self.roles["voter"].count

    def seconds(self, key: str) -> int:
        return parse_duration(self.get("time", key))

    def account_dir(self, account: str) -> str:
        dirs = self.get("accounts", "claude", "dirs", default={})
        if str(account) not in dirs:
            raise ConfigError(f"conta inválida: '{account}' (contas: {', '.join(dirs)})")
        return os.path.expanduser(dirs[str(account)])

    @property
    def fallback_account(self) -> str:
        return str(self.get("accounts", "claude", "fallback", default="") or "")

    def rules_text(self) -> str:
        f = self.get("run", "rules_file")
        if not f:
            return "(nenhuma)"
        p = Path(f) if os.path.isabs(f) else self.queue_dir / f
        if not p.is_file():
            raise ConfigError(f"arquivo de regras não existe: {p}")
        return p.read_text()


def parse_duration(v) -> int:
    """'4h' '30m' '90s' '120' → segundos."""
    s = str(v).strip()
    m = re.fullmatch(r"(\d+)([hms]?)", s)
    if not m:
        raise ConfigError(f"duração inválida: {v!r}")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"h": 3600, "m": 60, "s": 1, "": 1}[unit]


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _set_path(d: dict, path: tuple, value) -> None:
    for p in path[:-1]:
        d = d.setdefault(p, {})
    d[path[-1]] = value


def _coerce(path: tuple, value: str):
    if path[-1] in ("count", "max_cycles", "max_decision_rounds"):
        return int(value)
    if path[-1] in ("thinking", "force_changes"):
        return value not in ("", "0", "false")
    return value


def legacy_to_toml(pairs: dict[str, str]) -> dict:
    out: dict = {}
    for k, v in pairs.items():
        if k in _LEGACY:
            _set_path(out, _LEGACY[k], _coerce(_LEGACY[k], v))
    return out


def parse_queue_conf(text: str) -> dict[str, str]:
    """queue.conf legado: só `ORQ_X=valor` simples (aspas opcionais, comentários ignorados)."""
    pairs = {}
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?(ORQ_[A-Z0-9_]+)=(.*)$", line)
        if not m:
            continue
        val = m.group(2).split(" #")[0].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        pairs[m.group(1)] = val
    return pairs


def resolve_queue_dir(path: str | Path) -> Path:
    """Aceita a pasta da atividade (com orq/ dentro) ou a própria pasta da fila."""
    p = Path(path).resolve()
    if (p / "orq").is_dir() and not any(p.glob("[0-9]*.md")):
        return p / "orq"
    return p


def git_toplevel(path: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def load(queue_dir: Path | None, flags: dict | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    raw = tomllib.loads((ORQ_HOME / "orq.toml").read_text())
    qd = Path(queue_dir).resolve() if queue_dir else Path.cwd()
    if queue_dir:
        if (qd / "orq.toml").is_file():
            raw = deep_merge(raw, tomllib.loads((qd / "orq.toml").read_text()))
        elif (qd / "queue.conf").is_file():
            raw = deep_merge(raw, legacy_to_toml(parse_queue_conf((qd / "queue.conf").read_text())))
    raw = deep_merge(raw, legacy_to_toml({k: v for k, v in env.items() if k.startswith("ORQ_")}))
    flags = flags or {}
    if flags.get("account"):
        # --account vale para todo papel que não fixa a conta no TOML da fila.
        raw = deep_merge(raw, {"accounts": {"claude": {"default": str(flags["account"])}}})
    if flags.get("repo"):
        raw = deep_merge(raw, {"run": {"repo": flags["repo"]}})

    repo = raw.get("run", {}).get("repo") or ""
    if repo:
        rp = Path(os.path.expanduser(repo))
        repo_path = (rp if rp.is_absolute() else qd / rp).resolve()
    else:
        repo_path = git_toplevel(qd) or Path.cwd()
    raw.setdefault("run", {})["repo"] = str(repo_path)

    cfg = Config(raw=raw, queue_dir=qd)
    default_account = str(cfg.get("accounts", "claude", "default", default="1"))
    for name in ROLES:
        r = raw.get("roles", {}).get(name, {})
        missing = [k for k in ("harness", "model", "effort") if not r.get(k)]
        if missing:
            raise ConfigError(f"papel {name}: falta {', '.join(missing)} no orq.toml")
        if r["harness"] not in HARNESSES:
            raise ConfigError(f"papel {name}: harness '{r['harness']}' desconhecido ({', '.join(HARNESSES)})")
        cfg.roles[name] = Role(name=name, harness=r["harness"], model=str(r["model"]), effort=str(r["effort"]),
                               account=str(r.get("account") or default_account), count=int(r.get("count", 1)))
        if r["harness"] == "claude":
            cfg.account_dir(cfg.roles[name].account)
    for key in ("call_timeout", "limit_max_wait", "limit_poll"):
        cfg.seconds(key)
    if cfg.on_fail not in ("stop", "continue"):
        raise ConfigError(f"loop.on_fail inválido: {cfg.on_fail}")
    return cfg

