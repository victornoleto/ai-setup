# orq — conselho: N votantes independentes, contagem e desempate.
# Pontos: unânime = 3 · maioria = 2 · sem maioria, decidida pelo desempatador = 2,5.
# shellcheck shell=bash

# orq_council SOURCE QUESTION_JSON → imprime a linha de resposta; grava evento e decisions.md.
orq_council() {
	local source=$1 q=$2 qid dir options_md question qctx i pids=() votes ids tally choice points
	local tiebreak_rationale=""
	qid=$(jq -r '.id' <<< "$q")
	question=$(jq -r '.question' <<< "$q")
	qctx=$(jq -r '.context' <<< "$q")
	options_md=$(jq -r '.options[] | "- `\(.id)` — \(.label): \(.detail)"' <<< "$q")
	ids=$(jq -c '[.options[].id]' <<< "$q")
	dir="$TASK_DIR/council/$(date +%H%M%S)-$qid"
	mkdir -p "$dir"

	orq_render "$ORQ_HOME/prompts/vote.md" \
		"VOTERS=$ORQ_VOTERS" "REPO=${ORQ_REPO:-$PWD}" "TASK_ID=$TASK_ID" "PLAN_FILE=$PLAN_FILE" \
		"SOURCE=$source" "TASK=$TASK_TEXT" "RULES=$RULES_TEXT" "QUESTION=$question" "QCONTEXT=$qctx" \
		"OPTIONS=$options_md" > "$dir/vote.md"

	orq_log "conselho: $qid ($ORQ_VOTERS votantes)"
	for i in $(seq 1 "$ORQ_VOTERS"); do
		orq_call VOTER "vote-$qid-$i" vote "$dir/vote.md" new "$(uuidgen)" "$dir/vote-$i.json" &
		pids+=("$!")
	done
	for i in "${pids[@]}"; do wait "$i" || true; done
	[ "${ORQ_DRY_RUN:-0}" = 1 ] && { echo "- $question → (dry-run)"; return 0; }

	# voto com id fora das opções: o votante é chamado de novo, uma vez; persistindo, o voto não conta.
	for i in $(seq 1 "$ORQ_VOTERS"); do
		if ! orq_vote_valid "$dir/vote-$i.json" "$ids"; then
			orq_log "conselho: voto $i inválido, nova chamada"
			orq_call VOTER "vote-$qid-$i-b" vote "$dir/vote.md" new "$(uuidgen)" "$dir/vote-$i.json" || true
			orq_vote_valid "$dir/vote-$i.json" "$ids" || rm -f "$dir/vote-$i.json"
		fi
	done

	votes=$(for i in $(seq 1 "$ORQ_VOTERS"); do
		if [ -f "$dir/vote-$i.json" ]; then jq -c --argjson n "$i" '{voter: $n, option_id, rationale}' "$dir/vote-$i.json"; fi
	done | jq -sc '.')
	[ "$(jq 'length' <<< "$votes")" -gt 0 ] || { orq_notice error "Conselho sem nenhum voto válido para '$qid'."; return 1; }

	tally=$(orq_tally "$votes" "$ORQ_VOTERS")
	if [ "$tally" != tie ]; then
		choice=${tally% *}; points=${tally#* }
	else
		orq_log "conselho: sem maioria em $qid, desempate"
		orq_render "$ORQ_HOME/prompts/tiebreak.md" \
			"VOTERS=$ORQ_VOTERS" "REPO=${ORQ_REPO:-$PWD}" "TASK_ID=$TASK_ID" "PLAN_FILE=$PLAN_FILE" \
			"SOURCE=$source" "TASK=$TASK_TEXT" "RULES=$RULES_TEXT" "QUESTION=$question" "QCONTEXT=$qctx" \
			"OPTIONS=$options_md" \
			"VOTES=$(jq -r '.[] | "- Conselheiro \(.voter): `\(.option_id)` — \(.rationale)"' <<< "$votes")" \
			> "$dir/tiebreak.md"
		orq_call TIEBREAK "tiebreak-$qid" vote "$dir/tiebreak.md" new "$(uuidgen)" "$dir/tiebreak.json" || true
		if ! orq_vote_valid "$dir/tiebreak.json" "$ids"; then
			orq_call TIEBREAK "tiebreak-$qid-b" vote "$dir/tiebreak.md" new "$(uuidgen)" "$dir/tiebreak.json" || true
			orq_vote_valid "$dir/tiebreak.json" "$ids" \
				|| { orq_notice error "Desempate sem resposta válida para '$qid'."; return 1; }
		fi
		choice=$(jq -r '.option_id' "$dir/tiebreak.json"); points=2.5
		tiebreak_rationale=$(jq -r '.rationale' "$dir/tiebreak.json")
	fi

	orq_decision_record "$source" "$q" "$votes" "$choice" "$points" "$tiebreak_rationale"
}

# orq_tally VOTES_JSON N → "opção 3" (unânime) | "opção 2" (maioria única) | "tie"
orq_tally() {
	jq -r --argjson n "$2" '
		(group_by(.option_id) | map({id: .[0].option_id, c: length}) | sort_by(-.c)) as $t
		| ($t[0].c) as $top
		| if $top == $n then "\($t[0].id) 3"
		  elif $top >= 2 and ([$t[] | select(.c == $top)] | length) == 1 then "\($t[0].id) 2"
		  else "tie" end' <<< "$1"
}

orq_vote_valid() {
	[ -s "$1" ] && jq -e --argjson ids "$2" '.option_id as $o | $ids | index($o) != null' "$1" >/dev/null 2>&1
}

orq_points_label() { [ "$1" = 2.5 ] && echo "2,5" || echo "$1"; }

orq_decision_record() {
	local source=$1 q=$2 votes=$3 choice=$4 points=$5 tb=$6 label why pts
	label=$(jq -r --arg c "$choice" '.options[] | select(.id == $c) | .label' <<< "$q")
	if [ -n "$tb" ]; then why=$tb
	else why=$(jq -r --arg c "$choice" '[.[] | select(.option_id == $c)][0].rationale' <<< "$votes"); fi
	pts=$(orq_points_label "$points")

	orq_event decision "$(jq -cn --arg task "$TASK_ID" --arg source "$source" --argjson q "$q" --argjson votes "$votes" \
		--arg choice "$choice" --arg label "$label" --argjson points "$points" --arg tiebreak "$tb" --arg why "$why" \
		'{task: $task, source: $source, qid: $q.id, question: $q.question, context: $q.context, options: $q.options,
		  votes: $votes, choice: $choice, label: $label, points: $points, tiebreak: $tiebreak, why: $why}')"

	{
		printf '## %s (%s pontos)\n\n' "$(jq -r '.question' <<< "$q")" "$pts"
		printf 'Perguntado por: %s. Escolha: `%s` — %s.\n\n' "$source" "$choice" "$label"
		printf 'Por quê: %s\n\n' "$why"
	} >> "$DECISIONS_FILE"

	printf -- '- **%s** → `%s` — %s (conselho, %s pontos). Por quê: %s\n' \
		"$(jq -r '.question' <<< "$q")" "$choice" "$label" "$pts" "$why"
}

# orq_resolve_questions SOURCE OUT_JSON → ORQ_ANSWERS com as respostas; 0 = havia perguntas e todas decididas,
# 1 = nenhuma pergunta, 2 = falha (conselho sem resposta ou limite de rodadas).
orq_resolve_questions() {
	local source=$1 out=$2 n rounds q answer
	ORQ_ANSWERS=""
	[ "${ORQ_DRY_RUN:-0}" = 1 ] && return 1
	n=$(jq '.questions | length' "$out")
	[ "$n" -gt 0 ] || return 1
	rounds=$(( $(orq_state_get "$TASK_ID" decision_rounds 0) + 1 ))
	orq_state_set "$TASK_ID" decision_rounds "$rounds"
	if [ "$rounds" -gt "$ORQ_MAX_DECISION_ROUNDS" ]; then
		orq_notice error "Passou de $ORQ_MAX_DECISION_ROUNDS rodadas de conselho: laço de dúvidas."
		return 2
	fi
	while IFS= read -r q; do
		answer=$(orq_council "$source" "$q") || return 2
		ORQ_ANSWERS+="$answer"$'\n'
	done < <(jq -c '.questions[]' "$out")
	return 0
}
