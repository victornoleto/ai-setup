#!/bin/sh
# Confere se o setup está inteiro. Só leitura: não conserta nada, diz o que fazer.
set -u

SETUP=$(cd "$(dirname "$0")" && pwd -P)
rc=0
ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FALHA %s\n' "$*"; rc=1; }
note() { printf 'nota  %s\n' "$*"; }

command -v jq >/dev/null && ok "jq instalado" || bad "jq ausente — o resolvedor depende dele"

case ":${PATH}:" in
	*":$SETUP/bin:"*) ok "bin no PATH" ;;
	*) note "bin fora do PATH: export PATH=\"\$HOME/.ai-setup/bin:\$PATH\" no rc do shell" ;;
esac

# --- adaptadores ---
while IFS='	' read -r mode src dst; do
	case "${mode:-}" in ''|\#*) continue ;; esac
	from="$SETUP/adapters/$src"; to="$HOME/$dst"
	case "$mode" in
	link)
		if [ -L "$to" ] && [ "$(readlink -f "$to")" = "$from" ]; then ok "link  $dst"
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

# --- acervo ---
if out=$("$SETUP/bin/agent-memory" check 2>&1); then ok "acervo íntegro (agent-memory check)"
else bad "agent-memory check:"; printf '%s\n' "$out" | sed 's/^/      /'; fi

if sh "$SETUP/tests/agent-memory.test.sh" >/dev/null 2>&1; then ok "suíte do resolvedor passa"
else bad "suíte do resolvedor falha — rode: sh $SETUP/tests/agent-memory.test.sh"; fi

# --- pendências que só o usuário resolve ---
grep -qE "^# copy	codex/config.toml" "$SETUP/adapters/MANIFEST" \
	&& note "config.toml fora do repositório: tem um GitHub PAT em texto puro. Veja o README."
note "o versionamento da pasta sync/ no Syncthing não dá para verificar daqui — confira no minipc."

exit $rc
