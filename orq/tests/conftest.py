import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ORQ_") and k != "ORQ_HOME":
            monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def _registro_de_runs_isolado(tmp_path, monkeypatch):
    """Nenhum teste escreve no ~/.local/state/orq/runs.jsonl de verdade."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _sem_ntfy_real(tmp_path, monkeypatch):
    """Nenhum teste lê o ~/.config/orq/notify.toml de verdade (nem manda notificação)."""
    from orq import notify
    monkeypatch.setattr(notify, "CONFIG", tmp_path / "sem-notify.toml")
    monkeypatch.setattr(notify, "desktop", lambda msg: None)
