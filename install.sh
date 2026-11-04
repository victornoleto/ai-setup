#!/bin/sh
# Põe cada arquivo de configuração no lugar onde a ferramenta procura, conforme
# adapters/MANIFEST (e sync/MANIFEST, se existir). Idempotente: rodar de novo não estraga nada.
set -eu

SETUP=$(cd "$(dirname "$0")" && pwd -P)
host=$(hostname)
rc=0

say() { printf '%s\n' "$*"; }

# --- machine.md: qual arquivo desta máquina o adaptador carrega ---
if [ ! -e "$SETUP/local/machine.md" ]; then
	target="$SETUP/sync/memory/machine/$host.md"
	if [ ! -f "$target" ]; then
		cat > "$target" <<TPL
# Machine: $host

Fatos verdadeiros só desta máquina. O \`GLOBAL.md\` carrega o que vale em qualquer uma.

## This Machine

(preencher: como root funciona aqui, o que só o usuário consegue fazer no terminal)

## Conventions Tied To This Machine

(preencher: onde mora a documentação desta máquina, exceções de diretório)
TPL
		say "criado $target — preencha antes de confiar nele"
	fi
	ln -sfn "../sync/memory/machine/$host.md" "$SETUP/local/machine.md"
	say "local/machine.md -> machine/$host.md"
fi

# Entradas do MANIFEST, uma por linha: modo<TAB>origem absoluta<TAB>destino. Primeiro o
# sync/MANIFEST (pessoal, origem relativa a sync/), depois o adapters/MANIFEST (relativa a
# adapters/); destino repetido fica com a primeira, então o pessoal sobrepõe o público.
manifest_lines() {
	for base in "$SETUP/sync" "$SETUP/adapters"; do
		[ -f "$base/MANIFEST" ] || continue
		while IFS='	' read -r mode src dst; do
			case "${mode:-}" in ''|\#*) continue ;; esac
			printf '%s\t%s\t%s\n' "$mode" "$base/$src" "$dst"
		done < "$base/MANIFEST"
	done | awk -F'\t' '!seen[$3]++'
}

# --- adaptadores ---
while IFS='	' read -r mode src dst; do
	from=$(realpath -m "$src")
	to="$HOME/$dst"
	[ -e "$from" ] || { say "FALTA no repositório: ${src#"$SETUP"/}"; rc=1; continue; }
	mkdir -p "$(dirname "$to")"
	case "$mode" in
	link)
		if [ -L "$to" ] && [ "$(readlink -f "$to")" = "$from" ]; then
			continue
		fi
		if [ -e "$to" ] && [ ! -L "$to" ]; then
			mv "$to" "$to.pre-ai-setup"
			say "guardado $dst.pre-ai-setup (era arquivo real)"
		fi
		ln -sfn "$from" "$to"
		say "link  $dst"
		;;
	copy)
		# A referência guarda @HOME@ no lugar do caminho do usuário; aqui vira o $HOME real.
		# Destino que ainda é symlink (modo link antigo) vira arquivo, sem escrever na origem.
		[ -L "$to" ] && rm "$to"
		if [ ! -e "$to" ]; then
			sed "s|@HOME@|$HOME|g" "$from" > "$to"
			say "copy  $dst (criado)"
		elif ! sed "s|@HOME@|$HOME|g" "$from" | cmp -s - "$to"; then
			say "difere $dst — a ferramenta reescreveu; resolva com doctor.sh"
		fi
		;;
	*) say "modo desconhecido no MANIFEST: $mode"; rc=1 ;;
	esac
done <<EOF
$(manifest_lines)
EOF

# --- segunda conta do Claude Code (opcional: só se ~/.claude2 existir) ---
# CLAUDE_CONFIG_DIR=~/.claude2 isola credencial e .claude.json; o resto é symlink para ~/.claude,
# então instrução, settings, skills, plugins e histórico são os mesmos nas duas contas.
if [ -d "$HOME/.claude2" ]; then
	mkdir -p "$HOME/.claude/commands" "$HOME/.claude/agents"
	for e in CLAUDE.md settings.json plugins skills projects commands agents; do
		to="$HOME/.claude2/$e"
		[ -L "$to" ] && [ "$(readlink "$to")" = "$HOME/.claude/$e" ] && continue
		if [ -e "$to" ] && [ ! -L "$to" ]; then
			mv "$to" "$to.pre-ai-setup"
			say "guardado .claude2/$e.pre-ai-setup (era arquivo real)"
		fi
		ln -sfn "$HOME/.claude/$e" "$to"
		say "link  .claude2/$e -> .claude/$e"
	done
	grep -qs "alias claude2=" "$HOME/.bashrc" "$HOME/.zshrc" || {
		say ""; say "Falta o alias da conta 2. Acrescente ao rc do shell:"
		say "  alias claude2='CLAUDE_CONFIG_DIR=\$HOME/.claude2 claude'"
	}
fi

case ":${PATH}:" in
	*":$SETUP/bin:"*) ;;
	*) say ""; say "Falta o bin no PATH. Acrescente ao rc do shell:"
	   say "  export PATH=\"\$HOME/.ai-setup/bin:\$PATH\"" ;;
esac

exit $rc
