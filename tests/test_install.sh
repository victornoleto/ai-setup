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
	mkdir -p "$t/repo/sync/memory/machine"
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

# 3. copy com @HOME@: destino que era symlink vira arquivo renderizado; a origem não muda.
t=$(novo)
mkdir -p "$t/repo/sync/cfg" "$t/home/.cfg"
echo '@HOME@/x' > "$t/repo/sync/cfg/f.txt"
printf 'copy\tcfg/f.txt\t.cfg/f.txt\n' > "$t/repo/sync/MANIFEST"
ln -s "$t/repo/sync/cfg/f.txt" "$t/home/.cfg/f.txt"
instala "$t"
[ ! -L "$t/home/.cfg/f.txt" ] && [ "$(cat "$t/home/.cfg/f.txt")" = "$t/home/x" ] \
	&& ok "copy: renderiza @HOME@ e troca o link por arquivo" || bad "copy: destino não renderizado"
[ "$(cat "$t/repo/sync/cfg/f.txt")" = '@HOME@/x' ] && ok "copy: origem intacta" || bad "copy: escreveu na origem"

# 4. O "aceitar" do doctor devolve @HOME@ à origem.
echo "$t/home/y" > "$t/home/.cfg/f.txt"
touch -d '+1 min' "$t/home/.cfg/f.txt"
aceitar=$(HOME="$t/home" sh "$t/repo/doctor.sh" 2>/dev/null | grep -A1 'Para aceitar' | tail -1 | sed 's/^nota *//')
[ -n "$aceitar" ] && HOME="$t/home" sh -c "$aceitar"
[ "$(cat "$t/repo/sync/cfg/f.txt")" = '@HOME@/y' ] \
	&& ok "doctor: aceitar grava @HOME@" || bad "doctor: aceitar deixou caminho real ($(cat "$t/repo/sync/cfg/f.txt"))"
rm -rf "$t"

# 5. Kiro: steering e skills por link; diretório real pré-existente vira .pre-ai-setup.
t=$(novo)
mkdir -p "$t/home/.kiro/skills/brainstorming"
instala "$t"
for f in global machine ai-memory; do
	[ -e "$t/home/.kiro/steering/$f.md" ] && ok "kiro: steering $f.md resolve" || bad "kiro: steering $f.md ausente"
done
[ "$(readlink -f "$t/home/.kiro/skills/brainstorming")" = "$t/repo/skills/brainstorming" ] \
	&& ok "kiro: skill linkada" || bad "kiro: skill não linkada"
[ -d "$t/home/.kiro/skills/brainstorming.pre-ai-setup" ] && ok "kiro: diretório real guardado" || bad "kiro: diretório real perdido"
rm -rf "$t"

exit $falhas
