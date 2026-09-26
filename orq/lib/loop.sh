# orq — o laço de uma tarefa: plano → (conselho) → execução → revisão → correção … → takeover → revisão final.
# Cada fase é gravada em state.json antes de rodar; `orq resume` recomeça da fase em curso, retomando as sessões.
# shellcheck shell=bash

# Variáveis de tarefa usadas pelos outros arquivos: TASK_ID TASK_DIR TASK_TEXT PLAN_FILE DECISIONS_FILE.
orq_task_setup() {
	TASK_FILE=$1
	TASK_ID=$(basename "$TASK_FILE" .md)
	TASK_DIR="$RUN_DIR/$TASK_ID"
	TASK_TEXT=$(cat "$TASK_FILE")
	PLAN_FILE="$TASK_DIR/plan.md"
	DECISIONS_FILE="$TASK_DIR/decisions.md"
	mkdir -p "$TASK_DIR/calls"
	BASE_PROMPT=$(orq_render "$ORQ_HOME/prompts/_base.md" \
		"REPO=${ORQ_REPO:-$PWD}" "TASK_ID=$TASK_ID" "TASK=$TASK_TEXT" "RULES=$RULES_TEXT")
}

# O resultado final fica em state.json (result: ok | ok_takeover | failed | blocked).
orq_run_task() {
	orq_task_setup "$1"
	local phase cycle psid esid rsid out rc next_prompt started report
	phase=$(orq_state_get "$TASK_ID" phase start)
	[ "$phase" = done ] && return 0

	while :; do
		orq_state_set_str "$TASK_ID" phase "$phase"
		cycle=$(orq_state_get "$TASK_ID" cycle 1)
		psid=$(orq_state_get "$TASK_ID" planner_sid)
		esid=$(orq_state_get "$TASK_ID" exec_sid)

		case "$phase" in
		start)
			if [ -n "$(git -C "${ORQ_REPO:-.}" status --porcelain 2>/dev/null)" ] && [ "${ORQ_DRY_RUN:-0}" != 1 ]; then
				orq_task_end blocked "Árvore de trabalho suja antes de começar: $(git -C "${ORQ_REPO:-.}" status --porcelain | head -5 | tr '\n' ' ')"
				return 0
			fi
			orq_state_set_str "$TASK_ID" base "$(git -C "${ORQ_REPO:-.}" rev-parse HEAD 2>/dev/null || echo none)"
			orq_state_set_str "$TASK_ID" planner_sid "$(uuidgen)"
			orq_state_set_str "$TASK_ID" started "$(date +%s)"
			orq_state_set "$TASK_ID" cycle 1
			orq_event task_start "$(jq -cn --arg task "$TASK_ID" --arg base "$(orq_state_get "$TASK_ID" base)" \
				--arg f "$TASK_FILE" '{task: $task, base: $base, task_file: $f}')"
			phase=plan ;;

		plan)
			orq_render "$ORQ_HOME/prompts/plan.md" "BASE=$BASE_PROMPT" "PLAN_FILE=$PLAN_FILE" > "$TASK_DIR/plan.prompt.md"
			out="$TASK_DIR/plan.out.json"
			orq_call PLANNER plan plan "$TASK_DIR/plan.prompt.md" new "$psid" "$out" \
				|| { orq_task_end failed "O planejamento falhou (ver orq.log)."; return 0; }
			orq_state_set_str "$TASK_ID" planner_mode resume
			[ "${ORQ_DRY_RUN:-0}" = 1 ] && { phase=exec; continue; }
			orq_event plan "$(jq -c --arg task "$TASK_ID" --arg rel "$TASK_ID/plan.md" \
				'{task: $task, summary, plan_rel: $rel}' "$out")"
			phase=plan_questions ;;

		plan_questions)
			rc=0; orq_resolve_questions planejador "$TASK_DIR/plan.out.json" || rc=$?
			case $rc in
				0)  orq_render "$ORQ_HOME/prompts/plan_update.md" "ANSWERS=$ORQ_ANSWERS" "PLAN_FILE=$PLAN_FILE" \
						> "$TASK_DIR/plan_update.prompt.md"
					orq_call PLANNER "plan-update-$(date +%H%M%S)" plan "$TASK_DIR/plan_update.prompt.md" resume "$psid" "$TASK_DIR/plan.out.json" \
						|| { orq_task_end failed "A atualização do plano falhou."; return 0; } ;;   # volta a conferir perguntas
				1)  phase=exec ;;
				*)  orq_task_end failed "O conselho não decidiu uma dúvida do plano."; return 0 ;;
			esac ;;

		exec)
			if [ -z "$esid" ]; then
				esid=$(uuidgen); orq_state_set_str "$TASK_ID" exec_sid "$esid"
				orq_render "$ORQ_HOME/prompts/execute.md" "BASE=$BASE_PROMPT" "PLAN_FILE=$PLAN_FILE" \
					"DECISIONS_FILE=$DECISIONS_FILE" > "$TASK_DIR/exec.prompt.md"
				orq_state_set_str "$TASK_ID" next_exec_prompt "$TASK_DIR/exec.prompt.md"
				orq_state_set_str "$TASK_ID" exec_mode new
			fi
			next_prompt=$(orq_state_get "$TASK_ID" next_exec_prompt)
			out="$TASK_DIR/exec-$cycle.out.json"
			orq_call EXECUTOR "exec-$cycle-$(date +%H%M%S)" execute "$next_prompt" \
				"$(orq_state_get "$TASK_ID" exec_mode new)" "$esid" "$out" \
				|| { orq_task_end failed "A execução (ciclo $cycle) falhou."; return 0; }
			orq_state_set_str "$TASK_ID" exec_mode resume
			[ "${ORQ_DRY_RUN:-0}" = 1 ] && { phase=review; continue; }
			orq_exec_event "$out" "$cycle" "executor, $ORQ_EXECUTOR_MODEL"
			phase=$(orq_after_exec "$out" exec_answers review) || return 0 ;;

		exec_answers)
			orq_render "$ORQ_HOME/prompts/exec_answers.md" "ANSWERS=$(cat "$TASK_DIR/answers.last")" "DECISIONS_FILE=$DECISIONS_FILE" \
				> "$TASK_DIR/exec_answers-$(date +%H%M%S).prompt.md"
			orq_state_set_str "$TASK_ID" next_exec_prompt "$(ls -t "$TASK_DIR"/exec_answers-*.prompt.md | head -1)"
			phase=exec ;;

		review)
			report=$(cat "$TASK_DIR/exec-$cycle.out.json" 2>/dev/null || echo '{}')
			orq_review PLANNER "$psid" resume "$report" "executor" || return 0
			case "$ORQ_VERDICT" in
				approved) orq_task_end ok "Aprovada pelo revisor no ciclo $cycle."; return 0 ;;
				changes)
					if [ "$cycle" -lt "$ORQ_MAX_CYCLES" ]; then
						cycle=$((cycle + 1)); orq_state_set "$TASK_ID" cycle "$cycle"
						orq_render "$ORQ_HOME/prompts/fix.md" "CYCLE=$((cycle - 1))" "MAX_CYCLES=$ORQ_MAX_CYCLES" \
							"REVIEW=$ORQ_REVIEW_MD" > "$TASK_DIR/fix-$cycle.prompt.md"
						orq_state_set_str "$TASK_ID" next_exec_prompt "$TASK_DIR/fix-$cycle.prompt.md"
						phase=exec
					else
						orq_render "$ORQ_HOME/prompts/takeover.md" "MAX_CYCLES=$ORQ_MAX_CYCLES" \
							"REVIEW=$ORQ_REVIEW_MD" > "$TASK_DIR/takeover.prompt.md"
						phase=takeover
					fi ;;
			esac ;;

		takeover)
			out="$TASK_DIR/takeover.out.json"
			orq_call PLANNER "takeover-$(date +%H%M%S)" execute "$TASK_DIR/takeover.prompt.md" resume "$psid" "$out" \
				|| { orq_task_end failed "O takeover do planejador falhou."; return 0; }
			[ "${ORQ_DRY_RUN:-0}" = 1 ] && { phase=final_review; continue; }
			orq_exec_event "$out" "$((cycle + 1))" "planejador assumiu, $ORQ_PLANNER_MODEL"
			phase=$(orq_after_exec "$out" takeover_answers final_review) || return 0 ;;

		takeover_answers)
			orq_render "$ORQ_HOME/prompts/exec_answers.md" "ANSWERS=$(cat "$TASK_DIR/answers.last")" "DECISIONS_FILE=$DECISIONS_FILE" \
				> "$TASK_DIR/takeover.prompt.md"
			phase=takeover ;;

		final_review)
			rsid=$(orq_state_get "$TASK_ID" final_review_sid)
			[ -n "$rsid" ] || { rsid=$(uuidgen); orq_state_set_str "$TASK_ID" final_review_sid "$rsid"; }
			report=$(cat "$TASK_DIR/takeover.out.json" 2>/dev/null || echo '{}')
			cycle=$((cycle + 1))
			orq_review REVIEWER "$rsid" new "$report" "planejador, depois de assumir" "$cycle" || return 0
			if [ "$ORQ_VERDICT" = approved ]; then
				orq_task_end ok_takeover "O executor não passou em $ORQ_MAX_CYCLES ciclos; o planejador assumiu e um revisor novo aprovou."
			else
				orq_task_end failed "Nem o takeover do planejador passou na revisão independente."
			fi
			return 0 ;;
		esac
	done
}

orq_exec_event() {
	jq -c --arg task "$TASK_ID" --argjson cycle "$2" --arg actor "$3" \
		'{task: $task, cycle: $cycle, actor: $actor, status, summary, commits, checks, pending}' "$1" \
		| { read -r ev; orq_event exec "$ev"; }
}

# Depois de uma execução: imprime a próxima fase. Com dúvida, decide no conselho e aponta para ANSWERS_PHASE.
orq_after_exec() {
	local out=$1 answers_phase=$2 next=$3 status rc
	status=$(jq -r '.status' "$out")
	case "$status" in
		blocked) orq_task_end blocked "$(jq -r '.summary' "$out")"; return 1 ;;
		needs_decision)
			rc=0; orq_resolve_questions executor "$out" || rc=$?
			if [ "$rc" = 0 ]; then
				# ORQ_ANSWERS não sobrevive ao $( ): vai por arquivo.
				printf '%s' "$ORQ_ANSWERS" > "$TASK_DIR/answers.last"
				echo "$answers_phase"
			elif [ "$rc" = 1 ]; then
				echo "$next"   # disse needs_decision sem perguntas: segue para a revisão
			else
				orq_task_end failed "O conselho não decidiu uma dúvida do executor."; return 1
			fi ;;
		*) echo "$next" ;;
	esac
}

# orq_review ROLE SID MODE REPORT_JSON ACTOR [CYCLE] → ORQ_VERDICT e ORQ_REVIEW_MD. Retorna 1 se a tarefa terminou.
orq_review() {
	local role=$1 sid=$2 mode=$3 report=$4 actor=$5 cyc=${6:-$(orq_state_get "$TASK_ID" cycle 1)} out rc prompt
	out="$TASK_DIR/review-$cyc.out.json"
	prompt="$TASK_DIR/review-$cyc.prompt.md"
	orq_render "$ORQ_HOME/prompts/review.md" "BASE=$BASE_PROMPT" "PLAN_FILE=$PLAN_FILE" \
		"DECISIONS_FILE=$DECISIONS_FILE" "BASE_SHA=$(orq_state_get "$TASK_ID" base)" "ACTOR=$actor" \
		"CYCLE=$cyc" "EXEC_REPORT=$report" > "$prompt"
	orq_call "$role" "review-$cyc-$(date +%H%M%S)" review "$prompt" "$mode" "$sid" "$out" \
		|| { orq_task_end failed "A revisão (ciclo $cyc) falhou."; return 1; }
	[ "${ORQ_DRY_RUN:-0}" = 1 ] && { ORQ_VERDICT=approved; ORQ_REVIEW_MD=""; return 0; }

	if [ "$ORQ_TEST_FORCE_CHANGES" = 1 ] && [ "$role" = PLANNER ]; then
		jq '.verdict = "changes" | .issues += [{severity: "media", where: "(teste)", what: "reprovação forçada por ORQ_TEST_FORCE_CHANGES", fix: "nada"}]' \
			"$out" > "$out.tmp" && mv "$out.tmp" "$out"
	fi

	jq -c --arg task "$TASK_ID" --argjson cycle "$cyc" --arg reviewer "$([ "$role" = PLANNER ] && echo "planejador, $ORQ_PLANNER_MODEL" || echo "revisor em sessão nova, $ORQ_REVIEWER_MODEL")" \
		'{task: $task, cycle: $cycle, reviewer: $reviewer, verdict, summary, highlights, issues}' "$out" \
		| { read -r ev; orq_event review "$ev"; }

	# Dúvida do revisor: o conselho decide, e a resposta segue junto com a lista de correções.
	rc=0; orq_resolve_questions revisor "$out" || rc=$?
	[ "$rc" -ge 2 ] && { orq_task_end failed "O conselho não decidiu uma dúvida do revisor."; return 1; }

	ORQ_VERDICT=$(jq -r '.verdict' "$out")
	ORQ_REVIEW_MD=$(jq -r '"Resumo: \(.summary)\n\nProblemas:\n" + ([.issues[] | "- [\(.severity)] \(.where): \(.what) → \(.fix)"] | join("\n"))' "$out")
	[ "$rc" = 0 ] && ORQ_REVIEW_MD+=$'\n\nDecisões do conselho sobre as dúvidas do revisor:\n'"$ORQ_ANSWERS"
	return 0
}

orq_task_end() {
	local result=$1 reason=$2 started now cycles
	started=$(orq_state_get "$TASK_ID" started "$(date +%s)"); now=$(date +%s)
	cycles=$(orq_state_get "$TASK_ID" cycle 1)
	orq_state_set_str "$TASK_ID" phase done
	orq_state_set_str "$TASK_ID" result "$result"
	orq_event task_end "$(jq -cn --arg task "$TASK_ID" --arg result "$result" --arg reason "$reason" \
		--argjson d "$((now - started))" --argjson c "$cycles" \
		'{task: $task, result: $result, reason: $reason, duration_s: $d, cycles: $c}')"
	orq_log "$TASK_ID: $result — $reason"
}
