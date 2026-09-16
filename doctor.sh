#!/bin/sh
# Confere se o setup está inteiro. Só leitura: não conserta nada, diz o que fazer.
set -u

SETUP=$(cd "$(dirname "$0")" && pwd -P)
rc=0
ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FALHA %s\n' "$*"; rc=1; }
note() { printf 'nota  %s\n' "$*"; }


# --- adaptadores ---
while IFS='	' read -r mode src dst; do
	case "${mode:-}" in ''|\#*) continue ;; esac
	from="$SETUP/adapters/$src"; to="$HOME/$dst"
	case "$mode" in
	link)
		if [ -L "$to" ] && [ "$(readlink -f "$to")" = "$(readlink -f "$from")" ]; then ok "link  $dst"
		elif [ ! -e "$to" ]; then bad "link  $dst ausente — rode install.sh"
		else bad "link  $dst não aponta para adapters/$src — rode install.sh"; fi ;;
	copy)
		if [ ! -e "$to" ]; then bad "copy  $dst ausente — rode install.sh"
		elif cmp -s "$from" "$to"; then ok "copy  $dst igual à referência"
		else
			bad "copy  $dst difere de adapters/$src"
			if [ "$to" -nt "$from" ]; then
				note "      o vivo é mais novo (a ferramenta reescreveu). Para aceitar:"
				note "      cp \"$to\" \"$from\""
			else
				note "      a referência é mais nova. Para aplicar:  cp \"$from\" \"$to\""
			fi
		fi ;;
	esac
done < "$SETUP/adapters/MANIFEST"

# --- máquina ---
if [ -L "$SETUP/local/machine.md" ] && [ -f "$SETUP/local/machine.md" ]; then
	ok "machine.md -> $(basename "$(readlink -f "$SETUP/local/machine.md")")"
	grep -q '(preencher' "$SETUP/local/machine.md" && note "      ainda tem seção por preencher"
else
	bad "local/machine.md não resolve — rode install.sh"
fi

# --- memória: ai-memory ---
# A memória de longo prazo saiu deste repositório em 2026-09-16. O que se confere
# aqui é só se o servidor está de pé e se nenhum harness voltou a escrever num
# acervo paralelo.
if command -v ai-memory >/dev/null; then ok "ai-memory no PATH"
else bad "ai-memory ausente — veja ~/Documents/notas/ia/migrar-ai-setup-para-ai-memory.md"; fi

estado=$(docker inspect -f '{{.State.Health.Status}}' ai-memory 2>/dev/null || echo ausente)
[ "$estado" = healthy ] && ok "container ai-memory healthy" \
	|| bad "container ai-memory: $estado — docker start ai-memory"

# AI_MEMORY_SERVER_URL setada faz o CLI responder "local spool" em vez de erro.
[ -z "${AI_MEMORY_SERVER_URL:-}" ] || bad "AI_MEMORY_SERVER_URL setada — quebra o wrapper em silêncio; unset"

if jq -e '.autoMemoryEnabled == false' "$HOME/.claude/settings.json" >/dev/null 2>&1; then
	ok "memória nativa do Claude Code desligada"
else bad "autoMemoryEnabled não é false em ~/.claude/settings.json — dois acervos vivos"; fi

grep -Eq '^\s*memories\s*=\s*false' "$HOME/.codex/config.toml" 2>/dev/null \
	&& ok "memória nativa do Codex desligada" \
	|| bad "[features] memories = false ausente em ~/.codex/config.toml"

# --- pendências que só o usuário resolve ---
grep -qE "^# copy	codex/config.toml" "$SETUP/adapters/MANIFEST" \
	&& note "config.toml fora do repositório: tem um GitHub PAT em texto puro. Veja o README."

exit $rc
