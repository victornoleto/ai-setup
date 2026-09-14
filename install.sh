#!/bin/sh
# Põe cada arquivo de configuração no lugar onde a ferramenta procura, conforme
# adapters/MANIFEST. Idempotente: rodar de novo não estraga nada.
set -eu

SETUP=$(cd "$(dirname "$0")" && pwd -P)
MANIFEST="$SETUP/adapters/MANIFEST"
host=$(hostname)
rc=0

say() { printf '%s\n' "$*"; }

mkdir -p "$SETUP/local/markers" "$SETUP/local/notices"

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

# --- adaptadores ---
while IFS='	' read -r mode src dst; do
	case "${mode:-}" in ''|\#*) continue ;; esac
	from="$SETUP/adapters/$src"
	to="$HOME/$dst"
	[ -e "$from" ] || { say "FALTA no repositório: adapters/$src"; rc=1; continue; }
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
		if [ ! -e "$to" ]; then
			cp "$from" "$to"
			say "copy  $dst (criado)"
		elif ! cmp -s "$from" "$to"; then
			say "difere $dst — a ferramenta reescreveu; resolva com doctor.sh"
		fi
		;;
	*) say "modo desconhecido no MANIFEST: $mode"; rc=1 ;;
	esac
done < "$MANIFEST"

case ":${PATH}:" in
	*":$SETUP/bin:"*) ;;
	*) say ""; say "Falta o bin no PATH. Acrescente ao rc do shell:"
	   say "  export PATH=\"\$HOME/.ai-setup/bin:\$PATH\"" ;;
esac

exit $rc
