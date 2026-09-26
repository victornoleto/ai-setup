# orq — a única porta para o `claude -p`.
# shellcheck shell=bash

# orq_call ROLE NAME SCHEMA PROMPT_FILE MODE SESSION_ID OUT_FILE
#   ROLE        PLANNER | EXECUTOR | REVIEWER | VOTER | TIEBREAK (lê ORQ_<ROLE>_MODEL/_EFFORT/_ACCOUNT)
#   NAME        nome da chamada (arquivo do JSON cru em $TASK_DIR/calls/NAME.json)
#   SCHEMA      nome do schema em schemas/ (plan, execute, review, vote)
#   MODE        new | resume
#   OUT_FILE    recebe o structured_output
# Retorna 0 com o JSON no OUT_FILE; 1 em erro que não é limite de uso (o motivo vai no log).
orq_call() {
	local role=$1 name=$2 schema=$3 prompt=$4 mode=$5 sid=$6 out=$7
	local model effort account var raw err rc waited=0 limit_s resume_flag perm tries=0
	var="ORQ_${role}_MODEL";   model=${!var}
	var="ORQ_${role}_EFFORT";  effort=${!var}
	var="ORQ_${role}_ACCOUNT"; account=${!var:-$ORQ_ACCOUNT}
	[ "$role" = VOTER ] || [ "$role" = TIEBREAK ] && perm=(--permission-mode plan) \
		|| perm=(--dangerously-skip-permissions)
	[ "$mode" = resume ] && resume_flag=(--resume "$sid") || resume_flag=(--session-id "$sid")
	raw="$TASK_DIR/calls/$name.json"; err="$TASK_DIR/calls/$name.err"
	limit_s=$(orq_seconds "$ORQ_LIMIT_MAX_WAIT")
	mkdir -p "$TASK_DIR/calls"

	if [ "${ORQ_DRY_RUN:-0}" = 1 ]; then
		orq_log "[dry-run] $name: conta $account · $model · effort $effort · $mode $sid · schema $schema"
		return 0
	fi

	while :; do
		tries=$((tries + 1))
		orq_log "$name: conta $account · $model · effort $effort · $mode ${sid:0:8}"
		rc=0
		# stream-json: cada passo sai ao vivo (orq_stream_print) e fica em .stream.jsonl; a última linha,
		# type=result, tem o mesmo formato do --output-format json e vira o $raw.
		( cd "${ORQ_REPO:-.}" && CLAUDE_CONFIG_DIR=$(orq_account_dir "$account") \
			timeout -k 60s "$ORQ_CALL_TIMEOUT" claude -p "${perm[@]}" "${resume_flag[@]}" \
			--model "$model" --effort "$effort" -n "orq:$name" \
			--output-format stream-json --verbose --json-schema "$(cat "$ORQ_HOME/schemas/$schema.json")" \
			< "$prompt" 2> "$err" | tee "$raw.stream.jsonl" | orq_stream_print "$role" "$name"
			exit "${PIPESTATUS[0]}" ) || rc=$?
		jq -c 'select(.type == "result")' "$raw.stream.jsonl" 2>/dev/null | tail -1 > "$raw" || true

		if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
			orq_notice timeout "$name passou de $ORQ_CALL_TIMEOUT e foi encerrada."
			return 1
		fi

		if [ "$rc" = 0 ] && jq -e '.is_error == false and .structured_output != null' "$raw" >/dev/null 2>&1; then
			jq '.structured_output' "$raw" > "$out"
			orq_cost_add "$(jq -r '.total_cost_usd // 0' "$raw")"
			return 0
		fi

		local text
		text="$(jq -r '.result // empty' "$raw" 2>/dev/null) $(tail -c 2000 "$err")"
		# retomada depois de uma queda: a sessão "nova" já existe.
		if [ "$mode" = new ] && printf '%s' "$text" | grep -qiE 'already (in use|exists)'; then
			mode=resume; resume_flag=(--resume "$sid"); continue
		fi
		if printf '%s' "$text" | grep -qiE 'usage limit|limit reached|hit your .*limit|rate.?limit|resets? (at )?[0-9]'; then
			if [ -n "$ORQ_FALLBACK_ACCOUNT" ] && [ "$ORQ_FALLBACK_ACCOUNT" != "$account" ]; then
				orq_notice account_switch "Limite de uso na conta $account em $name; trocando para a conta $ORQ_FALLBACK_ACCOUNT."
				account=$ORQ_FALLBACK_ACCOUNT
				# resume de sessão funciona entre contas: projects/ é compartilhado (notas/ia/claude-code-duas-contas.md).
				continue
			fi
			local wait_s
			wait_s=$(orq_reset_wait "$text")
			if [ $((waited + wait_s)) -gt "$limit_s" ]; then
				orq_notice limit_giveup "Limite de uso em $name; a espera passaria de $ORQ_LIMIT_MAX_WAIT. Chamada abandonada."
				return 1
			fi
			orq_notice limit_wait "Limite de uso na conta $account em $name; esperando $((wait_s / 60)) min."
			sleep "$wait_s"; waited=$((waited + wait_s))
			# a sessão nova já pode ter sido criada antes do erro: dali em diante, retomar.
			[ "$mode" = new ] && [ -f "$raw" ] && jq -e '.session_id' "$raw" >/dev/null 2>&1 \
				&& { mode=resume; resume_flag=(--resume "$sid"); }
			continue
		fi

		if printf '%s' "$text" | grep -qiE 'overloaded|529|5[0-9][0-9] |timed? ?out|ECONNRESET|network' && [ "$tries" -lt 5 ]; then
			orq_log "$name: erro transitório (tentativa $tries), nova tentativa em 2 min"
			sleep 120
			[ "$mode" = new ] && jq -e '.session_id' "$raw" >/dev/null 2>&1 \
				&& { mode=resume; resume_flag=(--resume "$sid"); }
			continue
		fi

		if [ "$tries" -lt 2 ] && [ "$rc" = 0 ] && jq -e '.structured_output == null' "$raw" >/dev/null 2>&1; then
			orq_log "$name: resposta sem structured_output; retomando a sessão uma vez"
			mode=resume; resume_flag=(--resume "$sid")
			printf 'Responda de novo, preenchendo a saída estruturada do schema pedido.\n' > "$prompt.retry"
			prompt="$prompt.retry"
			continue
		fi

		orq_notice error "$name falhou (saída $rc): $(printf '%s' "$text" | tr '\n' ' ' | cut -c1-300)"
		return 1
	done
}

# "4h" "30m" "90s" "120" → segundos
orq_seconds() {
	local v=$1
	case "$v" in
		*h) echo $(( ${v%h} * 3600 )) ;;
		*m) echo $(( ${v%m} * 60 )) ;;
		*s) echo "${v%s}" ;;
		*)  echo "$v" ;;
	esac
}

# Segundos até o reset citado na mensagem ("resets 3am", "resets at 3:30 PM"); sem horário, ORQ_LIMIT_POLL.
orq_reset_wait() {
	local when target now
	when=$(printf '%s' "$1" | grep -oiE 'resets? (at )?[0-9]{1,2}(:[0-9]{2})? ?(am|pm)?' | head -1 \
		| sed -E 's/^[Rr]esets? (at )?//' || true)
	if [ -n "$when" ] && target=$(date -d "$when" +%s 2>/dev/null); then
		now=$(date +%s)
		[ "$target" -le "$now" ] && target=$((target + 86400))
		echo $((target - now + 120))
	else
		orq_seconds "$ORQ_LIMIT_POLL"
	fi
}

orq_cost_add() {
	# os votantes rodam em paralelo: trava o arquivo.
	(
		flock 9
		local f="$RUN_DIR/cost"
		[ -f "$f" ] || echo 0 > "$f"
		awk -v a="$(cat "$f")" -v b="${1:-0}" 'BEGIN { printf "%.4f\n", a + b }' > "$f.tmp" && mv "$f.tmp" "$f"
	) 9> "$RUN_DIR/cost.lock"
}

orq_notice() {
	orq_log "[$1] $2"
	orq_event notice "$(jq -cn --arg task "${TASK_ID:-}" --arg kind "$1" --arg text "$2" '{task: $task, kind: $kind, text: $text}')"
}

# Mostra o stream do claude no terminal (stderr) e no orq.log: texto do modelo e cada ferramenta chamada.
# ORQ_STREAM: main (padrão: planejador, executor e revisor; votantes em silêncio) | all | none.
# ORQ_STREAM_THINKING=1 mostra também o raciocínio.
orq_stream_print() {
	local role=$1 name=$2
	if [ "$ORQ_STREAM" = none ] || { [ "$ORQ_STREAM" = main ] && { [ "$role" = VOTER ] || [ "$role" = TIEBREAK ]; }; }; then
		cat > /dev/null; return 0
	fi
	jq --unbuffered -rR --arg p "  [$name]" --arg think "$ORQ_STREAM_THINKING" \
		--arg repo "${ORQ_REPO:-$PWD}/" --arg run "${RUN_DIR:-/nenhum}/" '
		def short: tostring | split($run) | join("run/") | split($repo) | join("");
		def clip($n): short | gsub("\\s+"; " ") | if length > $n then .[0:$n] + "…" else . end;
		def tool:
			if .name == "Bash" then "$ " + (.input.command // "" | clip(220))
			elif (.name | test("^(Read|Write|Edit|NotebookEdit)$")) then "\(.name) \(.input.file_path // .input.notebook_path // "" | short)"
			elif (.name | test("^(Grep|Glob)$")) then "\(.name) \(.input.pattern // "")\(if .input.path then " em " + .input.path else "" end)"
			elif .name == "Agent" or .name == "Task" then "subagente: \(.input.description // "")"
			elif .name == "Skill" then "skill \(.input.skill // "")"
			elif .name == "TodoWrite" or .name == "StructuredOutput" then empty
			else "\(.name) \(.input | tostring | clip(120))" end;
		(try fromjson catch null) as $e
		| if $e == null then empty
		  elif $e.type == "assistant" then
			$e.message.content[]?
			| if .type == "text" then (.text | split("\n")[] | select(test("\\S")) | "\($p) \(.)")
			  elif .type == "tool_use" then (tool | "\($p) › \(.)")
			  elif .type == "thinking" and $think == "1" then "\($p) (pensando) \(.thinking | clip(300))"
			  else empty end
		  elif $e.type == "user" then
			$e.message.content[]? | select(type == "object" and .type == "tool_result" and .is_error == true)
			| "\($p) ✗ \(.content | if type == "array" then map(.text? // "") | join(" ") else . end | clip(200))"
		  else empty end' \
		| while IFS= read -r line; do
			printf '%s\n' "$line" >&2
			[ -n "${RUN_DIR:-}" ] && printf '%s\n' "$line" >> "$RUN_DIR/orq.log"
		done
	return 0
}
