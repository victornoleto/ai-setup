#!/usr/bin/env bash
# Tempo até o reset de um limite, no formato do antigo metricc: "(~3h)", "(~166h)" ou "(~42m)".
# Uso: reset-left.sh five_hour|seven_day  (lê o JSON da status line no stdin)
# Sem rate_limits no JSON (início de sessão), não imprime nada.
reset=$(jq -r --arg k "$1" '.rate_limits[$k].resets_at // empty' 2>/dev/null)
[ -z "$reset" ] && exit 0

left=$(( ${reset%.*} - $(date +%s) ))
(( left < 0 )) && left=0
if (( left >= 3600 )); then echo "(~$(( left / 3600 ))h)"
else echo "(~$(( left / 60 ))m)"
fi
