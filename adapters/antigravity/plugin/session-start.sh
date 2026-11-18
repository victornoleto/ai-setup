#!/bin/sh
# SessionStart do agy: injeta o .ai/README.md do projeto, que o agy não descobre sozinho
# (lê AGENTS.md na raiz, não .ai/). Procura na raiz do git do cwd, no cwd e nos workspacePaths.
in=$(cat)
cwd=$(printf '%s' "$in" | jq -r '.cwd // empty' 2>/dev/null)
{
	[ -n "$cwd" ] && git -C "$cwd" rev-parse --show-toplevel 2>/dev/null
	[ -n "$cwd" ] && printf '%s\n' "$cwd"
	printf '%s' "$in" | jq -r '.workspacePaths[]? // empty' 2>/dev/null
} | while IFS= read -r d; do
	f="$d/.ai/README.md"
	[ -f "$f" ] || continue
	jq -n --rawfile t "$f" --arg p "$f" \
		'{injectSteps: [{systemMessage: {systemMessage: ("Regras do projeto, de " + $p + " (vencem orientação genérica):\n\n" + $t)}}]}'
	exit 0
done | grep . || echo '{}'
