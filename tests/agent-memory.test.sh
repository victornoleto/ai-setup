#!/bin/sh
# Self-check do bin/agent-memory contra um setup descartável. Rode: sh tests/agent-memory.test.sh
set -eu

BIN=$(cd "$(dirname "$0")/../bin" && pwd -P)/agent-memory
SANDBOX=$(mktemp -d)
WS=$(mktemp -d)
trap 'rm -rf "$SANDBOX" "$WS"' EXIT
SANDBOX=$(cd "$SANDBOX" && pwd -P)
WS=$(cd "$WS" && pwd -P)
export AI_SETUP_ROOT="$SANDBOX"
MEM="$SANDBOX/sync/memory"

fail=0
assert() { # assert <descrição> <esperado> <obtido>
	if [ "$2" = "$3" ]; then
		echo "ok   $1"
	else
		echo "FAIL $1"; echo "     esperado: [$2]"; echo "     obtido:   [$3]"; fail=1
	fi
}

mkdir -p "$WS/nested" "$MEM/projects/pai" "$MEM/projects/filho" "$SANDBOX/local/markers"
chmod 700 "$MEM/projects/pai" "$MEM/projects/filho"
cat > "$MEM/registry.json" <<JSON
{"version":1,"projects":[
 {"id":"pai","roots":["$WS"],"memoryDirectory":"projects/pai"},
 {"id":"filho","roots":["$WS/nested"],"memoryDirectory":"projects/filho"}
]}
JSON
echo '# Memory Index' > "$MEM/projects/pai/MEMORY.md"
echo '# Memory Index' > "$MEM/projects/filho/MEMORY.md"

assert "raiz exata resolve o pai" "$MEM/projects/pai" "$("$BIN" dir "$WS")"
assert "raiz mais longa vence o pai" "$MEM/projects/filho" "$("$BIN" dir "$WS/nested")"

echo '# um fato' > "$MEM/projects/pai/orfao.md"
assert "check acusa .md fora do índice" "unindexed: pai/orfao.md" \
	"$("$BIN" check pai 2>/dev/null | grep unindexed || true)"
echo '- [Órfão](orfao.md) — agora indexado' >> "$MEM/projects/pai/MEMORY.md"

assert "check acusa adaptador do Claude Code ausente" "claude adapter missing: pai -> $WS" \
	"$("$BIN" check pai || true)"
mkdir -p "$WS/.claude" "$WS/nested/.claude"
printf '{"autoMemoryDirectory":"%s"}\n' "$MEM/projects/pai" > "$WS/.claude/settings.local.json"
printf '{"autoMemoryDirectory":"%s"}\n' "$MEM/projects/filho" > "$WS/nested/.claude/settings.local.json"
assert "check limpo com índice e adaptador em ordem" "" "$("$BIN" check pai)"

chmod 755 "$MEM/projects/filho"
assert "check acusa diretório sem 700" "loose perms: filho" "$("$BIN" check filho || true)"
chmod 700 "$MEM/projects/filho"

touch "$MEM/projects/pai/MEMORY.md.sync-conflict-20260914-120000-ABCDEFG"
assert "check acusa conflito de sincronia" \
	"sync conflict: projects/pai/MEMORY.md.sync-conflict-20260914-120000-ABCDEFG" \
	"$("$BIN" check pai 2>/dev/null | grep 'sync conflict' || true)"
rm -f "$MEM/projects/pai/MEMORY.md.sync-conflict-"*

jq '.projects += [{"id":"sumiu","roots":["/nao/existe"],"memoryDirectory":"projects/sumiu"}]' \
	"$MEM/registry.json" > "$MEM/r.json" && mv "$MEM/r.json" "$MEM/registry.json"
mkdir -p "$MEM/projects/sumiu" && chmod 700 "$MEM/projects/sumiu"
echo '# Memory Index' > "$MEM/projects/sumiu/MEMORY.md"
assert "check acusa raiz que sumiu do disco" "missing root: sumiu -> /nao/existe" \
	"$("$BIN" check sumiu || true)"

jq '.projects[0].roots += ["/media/disco-externo"]' "$MEM/registry.json" > "$MEM/r.json" \
	&& mv "$MEM/r.json" "$MEM/registry.json"
assert "check isenta ponto de montagem do adaptador" "" "$("$BIN" check pai)"

assert "nudge cala sem marcador" "" "$("$BIN" nudge "$WS")"
assert "marcador fica em local/, fora do acervo" "pai" "$(ls "$SANDBOX/local/markers")"
out=$("$BIN" nudge "$WS" | head -1)
assert "nudge fala quando nada foi escrito desde a última sessão" \
	"Nenhuma memória de \`pai\` foi escrita desde a sessão anterior." "$out"
sleep 0.02   # o marcador acabou de ser tocado; sem isso os dois mtimes empatam sob carga
touch "$MEM/projects/pai/orfao.md"
assert "nudge cala depois de a memória ser escrita" "" "$("$BIN" nudge "$WS")"
assert "nudge cala em raiz não registrada" "" "$("$BIN" nudge /tmp)"

touch -d '400 days ago' "$MEM/projects/filho/antiga.md"
assert "stale acusa memória parada" "$MEM/projects/filho/antiga.md" \
	"$(cd "$WS/nested" && "$BIN" stale 180 | cut -f2)"
assert "stale respeita o corte de dias" "" "$(cd "$WS/nested" && "$BIN" stale 3650)"

exit $fail
