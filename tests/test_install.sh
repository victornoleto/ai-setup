#!/bin/sh
# Roda o install.sh numa cópia do repositório com HOME falso. Uso: sh tests/test_install.sh
set -u
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
falhas=0
ok()  { printf 'ok    %s\n' "$*"; }
bad() { printf 'FALHA %s\n' "$*"; falhas=1; }

# Cópia sem .git, sync/ e local/ (pessoais), com o mínimo de sync/ que o install exige.
novo() {
	t=$(mktemp -d)
	mkdir -p "$t/repo" "$t/home"
	tar -C "$REPO" --exclude=./.git --exclude=./sync --exclude=./local -cf - . | tar -C "$t/repo" -xf -
	mkdir -p "$t/repo/sync/memory/machine" "$t/repo/local"
	echo '# global' > "$t/repo/sync/memory/GLOBAL.md"
	echo "$t"
}
instala() { HOME="$1/home" sh "$1/repo/install.sh" >/dev/null 2>&1; }

# 1. Sem sync/MANIFEST: comportamento de sempre.
t=$(novo)
instala "$t" && ok "sem sync/MANIFEST: sai 0" || bad "sem sync/MANIFEST: saiu com erro"
[ "$(readlink -f "$t/home/.claude/skills/brainstorming")" = "$t/repo/skills/brainstorming" ] \
	&& ok "sem sync/MANIFEST: skill pública linkada" || bad "sem sync/MANIFEST: link errado"
rm -rf "$t"

# 2. sync/MANIFEST com o mesmo destino: vale o pessoal.
t=$(novo)
mkdir -p "$t/repo/sync/skills/x"
printf 'link\tskills/x\t.claude/skills/brainstorming\n' > "$t/repo/sync/MANIFEST"
instala "$t" && ok "com sync/MANIFEST: sai 0" || bad "com sync/MANIFEST: saiu com erro"
[ "$(readlink -f "$t/home/.claude/skills/brainstorming")" = "$t/repo/sync/skills/x" ] \
	&& ok "com sync/MANIFEST: o pessoal vence" || bad "com sync/MANIFEST: o público venceu"
rm -rf "$t"

exit $falhas
