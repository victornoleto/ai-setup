# orq — journal.md regenerado de events.jsonl a cada evento (o jsonl é a fonte; o .md nunca é editado à mão).
# shellcheck shell=bash

orq_journal_render() {
	jq -rs -f "$ORQ_HOME/lib/journal.jq" "$RUN_DIR/events.jsonl" > "$RUN_DIR/journal.md.tmp" \
		&& mv "$RUN_DIR/journal.md.tmp" "$RUN_DIR/journal.md" \
		|| orq_log "aviso: falha ao renderizar o journal (events.jsonl intacto)"
}
