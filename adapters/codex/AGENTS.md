# Codex Adapter

The SessionStart hook loads the canonical `GLOBAL.md`, `PROTOCOL.md`, and the
resolved project's `MEMORY.md` from `/home/victor/.ai-setup/sync/memory/`.
Follow that injected context. Read a linked topical memory only when it applies.

If the hook reports no registry entry, ask before creating one. If it reports a
workspace `.ai/README.md`, read it before working; its project-specific
instructions override generic guidance.
