from orq.config import Config


def cfg(tmp_path):
    return Config(raw={"accounts": {"claude": {"dirs": {"1": "~/.claude", "2": "~/.claude2"}}}}, queue_dir=tmp_path)


def test_conta_no_diretorio_padrao_nao_define_claude_config_dir(tmp_path, monkeypatch):
    # CLAUDE_CONFIG_DIR=~/.claude troca ~/.claude.json por ~/.claude/.claude.json: outra configuração e o onboarding de novo.
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cfg(tmp_path).claude_config_env("1") is None


def test_outra_conta_define_claude_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cfg(tmp_path).claude_config_env("2") == str(tmp_path / ".claude2")
