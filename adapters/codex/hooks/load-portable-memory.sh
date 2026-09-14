#!/bin/sh
# Inject the canonical portable-memory context for every Codex session.
set -eu

SETUP="${AI_SETUP_ROOT:-$HOME/.ai-setup}"
MEMORY_ROOT="$SETUP/sync/memory"
RESOLVER="$SETUP/bin/agent-memory"

# Codex supplies one JSON object on stdin; tolerate missing or malformed input.
payload=$(cat || true)
cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)
[ -n "$cwd" ] || cwd="$PWD"
workspace=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || (cd "$cwd" && pwd -P))

printf '%s\n' '# Canonical portable-memory context'
printf '%s\n\n' 'The following files are authoritative local context injected at session start.'
printf '%s\n' '## GLOBAL.md'
cat "$MEMORY_ROOT/GLOBAL.md"
if [ -f "$SETUP/local/machine.md" ]; then
    printf '\n%s\n' '## machine.md'
    cat "$SETUP/local/machine.md"
fi
printf '\n%s\n' '## PROTOCOL.md'
cat "$MEMORY_ROOT/PROTOCOL.md"

if memory_dir=$($RESOLVER dir "$workspace" 2>/dev/null); then
    printf '\n## Resolved project memory index\n'
    printf 'Workspace: `%s`\nMemory directory: `%s`\n\n' "$workspace" "$memory_dir"
    cat "$memory_dir/MEMORY.md"
    printf '\n\nRead a linked topical memory only when it applies to the task.\n'
else
    printf '\n## Resolved project memory index\n'
    printf 'No registry entry matches `%s`. Do not create or guess a memory entry; ask before creating one.\n' "$workspace"
fi

if [ -f "$workspace/.ai/README.md" ]; then
    printf '\nA `.ai/README.md` exists at the workspace root. Read it before working; its project-specific instructions override generic guidance.\n'
fi

# Reminder when sessions came and went with nothing written down. Silent otherwise.
"$RESOLVER" nudge "$workspace"
