#!/usr/bin/env bash
# Tempo até o reset de um limite, em no máximo duas unidades: "6d 3h", "3h 19m" ou "42m".
# Uso: reset-left.sh five_hour|seven_day  (lê o JSON da status line no stdin)
# Sem rate_limits no JSON (início de sessão), não imprime nada.
reset=$(jq -r --arg k "$1" '.rate_limits[$k].resets_at // empty' 2>/dev/null)
[ -z "$reset" ] && exit 0

left=$(( ${reset%.*} - $(date +%s) ))
(( left < 0 )) && left=0
d=$(( left / 86400 )) h=$(( left % 86400 / 3600 )) m=$(( left % 3600 / 60 ))

if (( d > 0 )); then echo "${d}d ${h}h"
elif (( h > 0 )); then echo "${h}h ${m}m"
else echo "${m}m"
fi
