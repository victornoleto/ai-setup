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
else bad "ai-memory ausente — veja "Ligar o ai-memory" no README"; fi

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

# Cada harness precisa das três pontas do ai-memory: hooks (captura), MCP (consulta) e a
# instrução de uso (bloco markered ou, no agy, as instruções do próprio servidor MCP).
# Quem grava essas pontas é o `ai-memory install-*`; aqui só se confere que estão lá.
conta() { grep -c "ai-memory/hooks/$1/" "$2" 2>/dev/null || echo 0; }
[ "$(conta claude-code "$HOME/.claude/settings.json")" -ge 9 ] && ok "claude: hooks do ai-memory" || bad "claude: hooks do ai-memory incompletos — install-hooks --agent claude-code"
[ "$(conta codex "$HOME/.codex/hooks.json")" -ge 7 ] && ok "codex: hooks do ai-memory" || bad "codex: hooks do ai-memory incompletos — install-hooks --agent codex"
grep -q '"ai-memory"' "$HOME/.gemini/config/hooks.json" 2>/dev/null && ok "agy: hooks do ai-memory" || bad "agy: hooks do ai-memory ausentes — install-hooks --agent antigravity-cli"
[ -f "$HOME/.config/opencode/plugins/ai-memory.ts" ] && ok "opencode: plugin do ai-memory" || bad "opencode: plugin ausente — install-hooks --agent open-code"

jq -e '.mcpServers["ai-memory"]' "$HOME/.claude.json" >/dev/null 2>&1 && ok "claude: MCP ai-memory" || bad "claude: MCP ai-memory ausente"
grep -q '^\[mcp_servers\.ai-memory\]' "$HOME/.codex/config.toml" && ok "codex: MCP ai-memory" || bad "codex: MCP ai-memory ausente"
jq -e '.mcp["ai-memory"]' "$SETUP/adapters/opencode/opencode.jsonc" >/dev/null 2>&1 && ok "opencode: MCP ai-memory" || bad "opencode: MCP ai-memory ausente"
jq -e '.mcpServers["ai-memory"]' "$HOME/.gemini/config/mcp_config.json" >/dev/null 2>&1 && ok "agy: MCP ai-memory" || bad "agy: MCP ai-memory ausente"

for t in claude/CLAUDE.md codex/AGENTS.md opencode/AGENTS.md; do
	grep -q '<!-- ai-memory:start -->' "$SETUP/adapters/$t" && ok "bloco ai-memory em $t" \
		|| bad "bloco ai-memory ausente em $t — install-instructions --target (arquivo real)"
done

# O Codex só roda hook aprovado, e a aprovação vale por posição no hooks.json: mexer no
# arquivo desaprova tudo em silêncio (em `codex exec` aparece como "Failed").
hooks_codex=$(jq '[.hooks[][].hooks[]] | length' "$HOME/.codex/hooks.json" 2>/dev/null || echo 0)
aprovados=$(grep -c '^\[hooks\.state\."/home/victor/\.codex/hooks\.json:' "$HOME/.codex/config.toml")
[ "$aprovados" -ge "$hooks_codex" ] && ok "codex: $aprovados/$hooks_codex hooks aprovados" \
	|| bad "codex: só $aprovados/$hooks_codex hooks aprovados — abra codex e aprove em /hooks (sem isso, nem GLOBAL.md nem captura)"
grep -A2 '^\[hooks\.state\."/home/victor/\.codex/hooks\.json:' "$HOME/.codex/config.toml" | grep -q '^enabled = false' \
	&& bad "codex: hook desligado (enabled = false) em hooks.state" || true

# --- pendências que só o usuário resolve ---
# Token em texto puro em config de harness vaza para todo backup que um instalador grava ao
# lado. GitHub vai pelo `gh` (token no keyring), não por MCP com header.
for f in "$HOME/.claude.json" "$HOME/.codex/config.toml" "$HOME/.config/opencode/opencode.jsonc" "$HOME/.gemini/config/mcp_config.json"; do
	[ -f "$f" ] || continue
	if grep -qE 'github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-|sk-or-v1-' "$f"; then bad "token em texto puro em ${f#"$HOME"/}"
	else ok "sem token em texto puro: ${f#"$HOME"/}"; fi
done
gh auth status >/dev/null 2>&1 && ok "gh autenticado" || note "gh sem login: gh auth login"

# --- núcleo: skills, plugins, confiança ---
# ~/.agents/skills guarda a única cópia real; em ~/.claude/skills tudo é link para lá ou para skills/.
dup=0
for s in "$HOME/.claude/skills"/*/; do
	n=$(basename "$s")
	case "$n" in ai-memory-*|synced) continue ;; esac
	[ -L "${s%/}" ] || { bad "skill copiada em .claude/skills/$n — troque por link"; dup=1; }
done
[ $dup = 0 ] && ok "skills sem cópia duplicada"

jq -e '.entries[]?.path | select(startswith("/"))' "$HOME/.gemini/config/skills.json" >/dev/null 2>&1 \
	&& ok "agy lê ~/.agents/skills" \
	|| bad "~/.gemini/config/skills.json ausente ou com caminho relativo (o agy não aceita ~)"

if jq -e '.enabledPlugins | to_entries[] | select(.key|test("^(playwright|superpowers|ponytail)@")) | select(.value)' "$HOME/.claude/settings.json" >/dev/null 2>&1
then bad "plugin substituído voltou a ligar no Claude (playwright/superpowers/ponytail)"
else ok "sem MCP do Playwright nem plugins substituídos no Claude"; fi

grep -Eq '^\[projects\."/home(/victor)?"\]' "$HOME/.codex/config.toml" \
	&& bad "Codex confia em /home ou /home/victor inteiro" || ok "confiança do Codex sem /home"

grep -rqs '\.orca' "$HOME/.claude/settings.json" "$HOME/.codex/hooks.json" "$HOME/.gemini/config/hooks.json" \
	&& bad "hook do Orca voltou" || ok "sem hooks do Orca"

g=$(wc -c < "$SETUP/sync/memory/GLOBAL.md")
[ "$g" -le 4000 ] && ok "GLOBAL.md com $g bytes" || note "GLOBAL.md com $g bytes (> 4000): carrega em todo turno, enxugue"

copiado=$(sed -n 's/^copiado-em: //p' "$SETUP/skills/UPSTREAM.md")
idade=$(( ( $(date +%s) - $(date -d "$copiado" +%s) ) / 86400 ))
[ "$idade" -le 90 ] && ok "skills copiadas revisadas há $idade dias" \
	|| note "AVISO skills copiadas do superpowers sem revisão há $idade dias — veja skills/UPSTREAM.md"

exit $rc
