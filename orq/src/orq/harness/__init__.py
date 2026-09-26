from __future__ import annotations

from pathlib import Path

from .base import Harness


def make(name: str, base_dir: Path | None = None) -> Harness:
    if name == "claude":
        from .claude import ClaudeHarness
        return ClaudeHarness()
    if name == "codex":
        from .codex import CodexHarness
        return CodexHarness()
    if name == "opencode":
        from .opencode import OpencodeHarness
        return OpencodeHarness()
    if name == "fake":
        from .fake import FakeHarness
        return FakeHarness(base_dir)
    raise ValueError(f"harness desconhecido: {name}")
