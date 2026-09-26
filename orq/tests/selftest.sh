#!/usr/bin/env bash
# orq selftest — sem chamar API: contagem do conselho, render do journal, bloqueio de push, render de prompt.
set -uo pipefail
ORQ_HOME=${ORQ_HOME:-$(cd "$(dirname "$0")/.." && pwd -P)}
for f in common claude council journal loop; do . "$ORQ_HOME/lib/$f.sh"; done
. "$ORQ_HOME/orq.conf"
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FALHA $1: esperado '$3', veio '$2'"; fail=1; fi; }
v() { jq -cn --args '[$ARGS.positional[] | {option_id: .}]' "$@"; }

check "unânime = 3 pontos"          "$(orq_tally "$(v a a a)" 3)" "a 3"
check "maioria = 2 pontos"          "$(orq_tally "$(v b a b)" 3)" "b 2"
check "três diferentes = desempate" "$(orq_tally "$(v a b c)" 3)" "tie"
check "voto inválido + 2 iguais"    "$(orq_tally "$(v a a)" 3)"   "a 2"
check "voto inválido + divergência" "$(orq_tally "$(v a b)" 3)"   "tie"

md=$(jq -rs -f "$ORQ_HOME/lib/journal.jq" "$ORQ_HOME/tests/fixtures/events.jsonl")
check "journal: falha no topo"      "$(grep -c '^- \*\*\[FALHOU\]\*\* \[02-dificil\]' <<< "$md")" 1
check "journal: decisão 2,5 pts"    "$(grep -c 'DECISÃO 2,5 pts' <<< "$md")" 1
check "journal: pendente"           "$(grep -c '^- \*\*\[PENDENTE\]\*\*' <<< "$md")" 1
check "journal: uma seção por run"  "$(grep -c '^## Run ' <<< "$md")" 2
check "journal: pipe escapado"      "$(grep -c 'md \\| é melhor' <<< "$md")" 1

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git init -q --bare "$tmp/remoto.git"
git init -q "$tmp/repo" && git -C "$tmp/repo" remote add origin "$tmp/remoto.git"
git -C "$tmp/repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m x
( orq_block_push "$tmp/repo"; git -C "$tmp/repo" push -q origin HEAD:main >/dev/null 2>&1 ); r=$?
check "git push bloqueado"          "$([ "$r" != 0 ] && echo sim || echo não)" sim
git -C "$tmp/repo" push -q origin HEAD:main >/dev/null 2>&1; r=$?
check "push volta fora do orq"      "$([ "$r" = 0 ] && echo sim || echo não)" sim

printf 'a {{X}} b {{Y}}' > "$tmp/t.md"
check "render literal (& e *)"      "$(orq_render "$tmp/t.md" 'X=1 & *' 'Y=$HOME')" 'a 1 & * b $HOME'
check "reset 3am vira espera"       "$([ "$(orq_reset_wait 'limit reached, resets 3am')" -gt 0 ] && echo sim)" sim
check "segundos"                    "$(orq_seconds 4h)" 14400

# Conselho de ponta a ponta com o orq_call trocado por um dublê: votos a, b, c → desempate escolhe b (2,5 pts).
RUN_DIR="$tmp/run"; mkdir -p "$RUN_DIR"; jq -n '{tasks: {}}' > "$RUN_DIR/state.json"
cp "$ORQ_HOME/tests/fixtures/events.jsonl" "$RUN_DIR/events.jsonl"
TASK_ID=t; TASK_DIR="$RUN_DIR/t"; TASK_TEXT=x; RULES_TEXT=x; PLAN_FILE=x; DECISIONS_FILE="$TASK_DIR/decisions.md"
mkdir -p "$TASK_DIR"
orq_call() {  # ROLE NAME SCHEMA PROMPT MODE SID OUT
	case "$2" in
		*-1) echo '{"option_id":"a","rationale":"r1"}' > "$7" ;;
		*-2) echo '{"option_id":"b","rationale":"r2"}' > "$7" ;;
		*-3) echo '{"option_id":"c","rationale":"r3"}' > "$7" ;;
		tiebreak-*) echo '{"option_id":"b","rationale":"b vence"}' > "$7" ;;
	esac
}
q='{"id":"q1","question":"Qual?","context":"c","options":[{"id":"a","label":"A","detail":""},{"id":"b","label":"B","detail":""},{"id":"c","label":"C","detail":""}]}'
ans=$(ORQ_VOTERS=3 orq_council teste "$q")
check "desempate grava 2,5 pts"     "$(tail -1 "$RUN_DIR/events.jsonl" | jq -r '"\(.choice) \(.points)"')" "b 2.5"
check "resposta cita o desempate"   "$(grep -c 'conselho, 2,5 pontos' <<< "$ans")" 1
check "decisions.md escrito"        "$(grep -c '^## Qual? (2,5 pontos)' "$DECISIONS_FILE")" 1

[ "$fail" = 0 ] && echo "selftest: tudo ok" || { echo "selftest: FALHOU"; exit 1; }
