# orq — utilitários: log, eventos, estado, prompts.
# shellcheck shell=bash

orq_die() { printf 'orq: %s\n' "$*" >&2; exit 1; }

orq_log() {
	local line
	line="$(date '+%F %T') $*"
	printf '%s\n' "$line" >&2
	[ -n "${RUN_DIR:-}" ] && [ -d "$RUN_DIR" ] && printf '%s\n' "$line" >> "$RUN_DIR/orq.log"
	return 0
}

# Conta → diretório de configuração do Claude Code (o que os aliases xclaude/xclaude2 fazem).
orq_account_dir() {
	case "$1" in
		1) printf '%s' "$ORQ_ACCOUNT_DIR_1" ;;
		2) printf '%s' "$ORQ_ACCOUNT_DIR_2" ;;
		*) orq_die "conta inválida: '$1' (use 1 ou 2)" ;;
	esac
}

# render TEMPLATE_FILE KEY=VALUE... → stdout. Troca {{KEY}} pelo valor, literal (sem glob nem &).
orq_render() {
	local tpl kv key val
	tpl=$(cat "$1"); shift
	for kv in "$@"; do
		key=${kv%%=*}; val=${kv#*=}
		tpl=${tpl//"{{$key}}"/"$val"}
	done
	printf '%s\n' "$tpl"
}

# event TYPE JSON_OBJECT — acrescenta ao events.jsonl e regenera o journal.
orq_event() {
	local line
	line=$(jq -cn --arg type "$1" --arg ts "$(date -Iseconds)" --argjson data "$2" '$data + {type: $type, ts: $ts}')
	# votantes em paralelo também geram eventos: uma escrita por vez.
	(
		flock 8
		printf '%s\n' "$line" >> "$RUN_DIR/events.jsonl"
		orq_journal_render
	) 8> "$RUN_DIR/events.lock"
}

# Estado por tarefa em state.json: state_get TASK KEY [PADRÃO] · state_set TASK KEY JSON
orq_state_get() {
	local v
	v=$(jq -r --arg t "$1" --arg k "$2" '.tasks[$t][$k] // empty' "$RUN_DIR/state.json")
	printf '%s' "${v:-${3:-}}"
}

orq_state_set() {
	local tmp="$RUN_DIR/state.json.tmp"
	jq --arg t "$1" --arg k "$2" --argjson v "$3" '.tasks[$t][$k] = $v' "$RUN_DIR/state.json" > "$tmp"
	mv "$tmp" "$RUN_DIR/state.json"
}

orq_state_set_str() { orq_state_set "$1" "$2" "$(jq -cn --arg v "$3" '$v')"; }

# Bloqueia `git push` nos processos filhos: pushurl inválido para cada remote do repositório, por
# GIT_CONFIG_COUNT/KEY_n/VALUE_n (sem tocar em hook nem em arquivo do repo).
orq_block_push() {
	local repo=$1 i r
	i=${GIT_CONFIG_COUNT:-0}
	for r in $(git -C "$repo" remote 2>/dev/null); do
		export "GIT_CONFIG_KEY_$i=remote.$r.pushurl" "GIT_CONFIG_VALUE_$i=blocked://orq-sem-push"
		i=$((i + 1))
	done
	export GIT_CONFIG_COUNT=$i
}

orq_notify() {
	[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v notify-send >/dev/null 2>&1 \
		&& notify-send "orq" "$1" 2>/dev/null
	return 0
}
