#!/bin/sh
# Confere se o setup está inteiro. Só leitura: não conserta nada, diz o que fazer.
set -u

SETUP=$(cd "$(dirname "$0")" && pwd -P)
rc=0
ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FALHA %s\n' "$*"; rc=1; }
note() { printf 'nota  %s\n' "$*"; }


# Entradas do MANIFEST, uma por linha: modo<TAB>origem absoluta<TAB>destino. Primeiro o
# sync/MANIFEST (pessoal, origem relativa a sync/), depois o adapters/MANIFEST (relativa a
# adapters/); destino repetido fica com a primeira, então o pessoal sobrepõe o público.
manifest_lines() {
	for base in "$SETUP/sync" "$SETUP/adapters"; do
		[ -f "$base/MANIFEST" ] || continue
		while IFS='	' read -r mode src dst; do
			case "${mode:-}" in
			''|\#*) continue ;;
			skill)   # uma linha, três links: Claude, ~/.agents (Codex, OpenCode, agy) e Kiro
				for h in .claude .agents .kiro; do
					printf 'link\t%s\t%s\n' "$base/$src" "$h/skills/$(basename "$src")"
				done ;;
			*) printf '%s\t%s\t%s\n' "$mode" "$base/$src" "$dst" ;;
			esac
		done < "$base/MANIFEST"
	done | awk -F'\t' '!seen[$3]++'
}

# --- adaptadores ---
governadas='{permissions, hooks, env, autoMemoryEnabled, statusLine, enabledPlugins}'
while IFS='	' read -r mode src dst; do
	from="$src"; to="$HOME/$dst"; rel=${src#"$SETUP"/}
	case "$mode" in
	link)
		if [ -L "$to" ] && [ "$(readlink -f "$to")" = "$(readlink -f "$from")" ]; then ok "link  $dst"
		elif [ ! -e "$to" ]; then bad "link  $dst ausente — rode install.sh"
		else bad "link  $dst não aponta para $rel — rode install.sh"; fi ;;
	copy)
		if [ ! -e "$to" ]; then bad "copy  $dst ausente — rode install.sh"
		elif sed "s|@HOME@|$HOME|g" "$from" | cmp -s - "$to"; then ok "copy  $dst igual à referência"
		# O Claude reescreve o settings.json a cada /model e /config: só as chaves que este
		# repositório governa contam; o resto (model, tema, effort) é escolha de cada sessão.
		elif [ "$dst" = .claude/settings.json ] && [ "$(sed "s|@HOME@|$HOME|g" "$from" | jq -S "$governadas" 2>/dev/null)" = "$(jq -S "$governadas" "$to" 2>/dev/null)" ]; then
			ok "copy  $dst igual à referência nas chaves governadas"
		else
			bad "copy  $dst difere de $rel"
			if [ "$to" -nt "$from" ]; then
				note "      o vivo é mais novo (a ferramenta reescreveu). Para aceitar:"
				note "      sed \"s|\$HOME|@HOME@|g\" \"$to\" > \"$from\""
			else
				note "      a referência é mais nova. Para aplicar:  sed \"s|@HOME@|\$HOME|g\" \"$from\" > \"$to\""
			fi
		fi ;;
	esac
done <<EOF
$(manifest_lines)
EOF

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
else bad "ai-memory ausente — veja docs/ai-memory.md"; fi

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
# 2.x grava `hooks/<agente>/*.sh`; 3.x grava o runner nativo com `--agent <agente>`.
conta() { grep -cE "ai-memory/hooks/$1/|hook --event [a-z-]+ --agent $1 " "$2" 2>/dev/null; }
[ "$(conta claude-code "$HOME/.claude/settings.json")" -ge 9 ] && ok "claude: hooks do ai-memory" || bad "claude: hooks do ai-memory incompletos — install-hooks --agent claude-code"
[ "$(conta codex "$HOME/.codex/hooks.json")" -ge 7 ] && ok "codex: hooks do ai-memory" || bad "codex: hooks do ai-memory incompletos — install-hooks --agent codex"
grep -q '"ai-memory"' "$HOME/.gemini/config/hooks.json" 2>/dev/null && ok "agy: hooks do ai-memory" || bad "agy: hooks do ai-memory ausentes — install-hooks --agent antigravity-cli"
[ -f "$HOME/.config/opencode/plugins/ai-memory.ts" ] && ok "opencode: plugin do ai-memory" || bad "opencode: plugin ausente — install-hooks --agent open-code"

jq -e '.mcpServers["ai-memory"]' "$HOME/.claude.json" >/dev/null 2>&1 && ok "claude: MCP ai-memory" || bad "claude: MCP ai-memory ausente"
# Conta 2 (~/.claude2, opcional): compartilha tudo por symlink, menos .claude.json, onde mora o MCP.
if [ -d "$HOME/.claude2" ]; then
	quebra=""
	for e in CLAUDE.md settings.json plugins skills projects commands agents; do
		[ "$(readlink "$HOME/.claude2/$e")" = "$HOME/.claude/$e" ] && [ -e "$HOME/.claude2/$e" ] || quebra="$quebra $e"
	done
	[ -z "$quebra" ] && ok "claude2: compartilha config com ~/.claude" || bad "claude2: link ausente ou quebrado:$quebra — rode install.sh"
	jq -e '.mcpServers["ai-memory"]' "$HOME/.claude2/.claude.json" >/dev/null 2>&1 && ok "claude2: MCP ai-memory" \
		|| bad "claude2: MCP ai-memory ausente — install-mcp --client claude-code --apply --config-file ~/.claude2/.claude.json"
fi
grep -qs '^\[mcp_servers\.ai-memory\]' "$HOME/.codex/config.toml" && ok "codex: MCP ai-memory" || bad "codex: MCP ai-memory ausente"
jq -e '.mcp["ai-memory"]' "$HOME/.config/opencode/opencode.jsonc" >/dev/null 2>&1 && ok "opencode: MCP ai-memory" || bad "opencode: MCP ai-memory ausente"
jq -e '.mcpServers["ai-memory"]' "$HOME/.gemini/config/mcp_config.json" >/dev/null 2>&1 && ok "agy: MCP ai-memory" || bad "agy: MCP ai-memory ausente"
# Kiro CLI (opcional): só confere onde ele está instalado.
if command -v kiro-cli >/dev/null 2>&1; then
	# Os hooks são da engine v3; o padrão do kiro-cli 3.x ainda é a v2, que não os dispara.
	[ "$(jq -r '."chat.agentEngine" // empty' "$HOME/.kiro/settings/cli.json" 2>/dev/null)" = v3 ] && ok "kiro: engine v3" \
		|| bad "kiro: engine padrão não é v3 (hooks do ai-memory não disparam) — kiro-cli settings chat.agentEngine v3"
	grep -q '"ai-memory' "$HOME/.kiro/hooks/ai-memory.json" 2>/dev/null && ok "kiro: hooks do ai-memory" \
		|| bad "kiro: hooks do ai-memory ausentes — install-hooks --agent kiro-cli-v3 --project-strategy repo-root --apply"
	jq -e '.mcpServers["ai-memory"]' "$HOME/.kiro/settings/mcp.json" >/dev/null 2>&1 && ok "kiro: MCP ai-memory" \
		|| bad "kiro: MCP ai-memory ausente — install-mcp --client kiro-cli --apply"
else
	note "kiro-cli ausente: Kiro não conferido"
fi

for t in claude/CLAUDE.md codex/AGENTS.md opencode/AGENTS.md kiro/ai-memory.md; do
	grep -q '<!-- ai-memory:start -->' "$SETUP/adapters/$t" && ok "bloco ai-memory em $t" \
		|| bad "bloco ai-memory ausente em $t — install-instructions --target (arquivo real)"
done

# O Codex só roda hook aprovado, e a aprovação vale por posição no hooks.json: mexer no
# arquivo desaprova tudo em silêncio (em `codex exec` aparece como "Failed").
hooks_codex=$(jq '[.hooks[][].hooks[]] | length' "$HOME/.codex/hooks.json" 2>/dev/null || echo 0)
hook_estado="^\\[hooks\\.state\\.\"$(printf %s "$HOME" | sed 's/\./\\./g')/\\.codex/hooks\\.json:"
aprovados=$(grep -c "$hook_estado" "$HOME/.codex/config.toml" 2>/dev/null || echo 0)
[ "$aprovados" -ge "$hooks_codex" ] && ok "codex: $aprovados/$hooks_codex hooks aprovados" \
	|| bad "codex: só $aprovados/$hooks_codex hooks aprovados — abra codex e aprove em /hooks (sem isso, nem GLOBAL.md nem captura)"
grep -A2 "$hook_estado" "$HOME/.codex/config.toml" 2>/dev/null | grep -q '^enabled = false' \
	&& bad "codex: hook desligado (enabled = false) em hooks.state" || true

# O sandbox do Codex usa bubblewrap, que precisa de user namespace. O Ubuntu 24.04 bloqueia isso
# por AppArmor; o perfil em adapters/codex/apparmor/ libera só os dois bwrap.
if bwrap --ro-bind / / --unshare-user true 2>/dev/null; then ok "bwrap cria user namespace (sandbox do Codex)"
else bad "bwrap sem user namespace — o Codex roda sem sandbox: sudo install -m 644 $SETUP/adapters/codex/apparmor/codex-bwrap /etc/apparmor.d/codex-bwrap && sudo apparmor_parser -r /etc/apparmor.d/codex-bwrap"; fi
if [ -f /etc/apparmor.d/codex-bwrap ] && ! cmp -s /etc/apparmor.d/codex-bwrap "$SETUP/adapters/codex/apparmor/codex-bwrap"; then
	note "/etc/apparmor.d/codex-bwrap difere da referência do repositório"
fi

# --- pendências que só o usuário resolve ---
# Token em texto puro em config de harness vaza para todo backup que um instalador grava ao
# lado. GitHub vai pelo `gh` (token no keyring), não por MCP com header.
for f in "$HOME/.claude.json" "$HOME/.claude2/.claude.json" "$HOME/.codex/config.toml" "$HOME/.config/opencode/opencode.jsonc" "$HOME/.gemini/config/mcp_config.json" "$HOME/.kiro/settings/mcp.json"; do
	[ -f "$f" ] || continue
	if grep -qE 'github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-|sk-or-v1-' "$f"; then bad "token em texto puro em ${f#"$HOME"/}"
	else ok "sem token em texto puro: ${f#"$HOME"/}"; fi
done
grep -qs 'adapters/shell/aliases.sh' "$HOME/.bashrc" "$HOME/.zshrc" && ok "rc do shell carrega adapters/shell/aliases.sh" \
	|| note "rc do shell não carrega adapters/shell/aliases.sh (claude2, xclaude..., bin/ no PATH): veja docs/claude-code.md"
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

# A skill handoff copia para a área de transferência por uma destas ferramentas.
if command -v xclip >/dev/null || command -v wl-copy >/dev/null || command -v pbcopy >/dev/null
then ok "clipboard: ferramenta para /handoff presente"
else bad "sem xclip/wl-copy/pbcopy — a skill handoff não consegue copiar"; fi

command -v ccstatusline >/dev/null && ok "ccstatusline no PATH (status line do Claude)" \
	|| bad "ccstatusline ausente — a status line do Claude fica vazia: npm install -g ccstatusline"

# A skill do playwright-cli é cópia da que vem na CLI; atualizar a CLI sem rodar o install a deixa velha.
if command -v playwright-cli >/dev/null; then
	# O `--help` só mostra o caminho da skill com CLAUDECODE setada; aqui ele sai do próprio binário.
	pw="$(dirname "$(realpath "$(command -v playwright-cli)")")/node_modules/playwright-core/lib/tools/skills/playwright-cli"
	if diff -rq "$pw" "$HOME/.agents/skills/playwright-cli" >/dev/null 2>&1 \
		&& [ -e "$HOME/.claude/skills/playwright-cli" ] && [ -e "$HOME/.kiro/skills/playwright-cli" ]
	then ok "playwright-cli: skill global igual à da CLI"
	else bad "playwright-cli: skill global ausente ou de outra versão da CLI — rode install.sh"; fi
else bad "playwright-cli ausente — npm install -g @playwright/cli"; fi

jq -e '.entries[]?.path | select(startswith("/"))' "$HOME/.gemini/config/skills.json" >/dev/null 2>&1 \
	&& ok "agy lê ~/.agents/skills" \
	|| bad "~/.gemini/config/skills.json ausente ou com caminho relativo (o agy não aceita ~)"

if jq -e '.enabledPlugins | to_entries[] | select(.key|test("^(playwright|superpowers|ponytail|frontend-design|code-review|code-simplifier|claude-md-management|security-guidance)@")) | select(.value)' "$HOME/.claude/settings.json" >/dev/null 2>&1
then bad "plugin substituído voltou a ligar no Claude (veja a regex acima)"
else ok "sem MCP do Playwright nem plugins substituídos no Claude"; fi

grep -Eqs "^\\[projects\\.\"(/home|$HOME)\"\\]" "$HOME/.codex/config.toml" \
	&& bad "Codex confia em /home ou no \$HOME inteiro" || ok "confiança do Codex sem /home"
# Confiança larga: pasta temporária, ou pasta que contém outro projeto já confiado (a mãe cobre tudo abaixo).
largas=$(sed -n 's/^\[projects\."\(.*\)"\]$/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | awk '
	{ p[NR] = $0 }
	END { for (i in p) { larga = (p[i] ~ /^\/tmp\//)
		for (j in p) if (i != j && index(p[j], p[i] "/") == 1) larga = 1
		if (larga) printf "%s ", p[i] } }')
[ -z "$largas" ] && ok "confiança do Codex só por projeto" \
	|| note "AVISO Codex confia em pasta temporária ou pasta-mãe: $largas— remova de ~/.codex/config.toml"
# O push fica com o usuário: regra que o libera no Codex anula isso.
grep -qs '"git", "push".*decision="allow"' "$HOME/.codex/rules/default.rules" \
	&& bad "Codex com git push liberado em ~/.codex/rules/default.rules — apague a regra" || ok "Codex sem git push liberado"

grep -rqs '\.orca' "$HOME/.claude/settings.json" "$HOME/.codex/hooks.json" "$HOME/.gemini/config/hooks.json" \
	&& bad "hook do Orca voltou" || ok "sem hooks do Orca"

g=$(wc -c < "$SETUP/sync/memory/GLOBAL.md")
[ "$g" -le 4000 ] && ok "GLOBAL.md com $g bytes" || note "GLOBAL.md com $g bytes (> 4000): carrega em todo turno, enxugue"

# Tamanho das respostas finais do Claude nos últimos 14 dias (meta: mediana <= 80 palavras).
v=$("$SETUP/bin/verbosidade" 2>/dev/null) && note "verbosidade: $v"

# Sem esta checagem o docs/catalogo.md envelhece na primeira skill nova.
falta=$(for s in "$SETUP/skills"/*/; do n=$(basename "$s"); grep -qF "\`$n\`" "$SETUP/docs/catalogo.md" || printf '%s ' "$n"; done)
[ -z "$falta" ] && ok "toda skill de skills/ está no docs/catalogo.md" \
	|| note "AVISO skills fora do docs/catalogo.md: $falta"

copiado=$(sed -n 's/^copiado-em: //p' "$SETUP/skills/UPSTREAM.md")
idade=$(( ( $(date +%s) - $(date -d "$copiado" +%s) ) / 86400 ))
[ "$idade" -le 90 ] && ok "skills copiadas revisadas há $idade dias" \
	|| note "AVISO skills copiadas do superpowers sem revisão há $idade dias — veja skills/UPSTREAM.md"

exit $rc
