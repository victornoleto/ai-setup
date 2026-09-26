# orq — events.jsonl (lido com -s) → journal.md. Etiquetas em texto e negrito: nada depende de cor.

def esc: tostring | gsub("\\|"; "\\|") | gsub("\n+"; " ");
def pts: if . == 3 then "3" elif . == 2.5 then "2,5" else tostring end;
def anchor: "t-" + (ascii_downcase | gsub("[^a-z0-9]+"; "-"));
def link: "[\(.)](#\(anchor))";
def dur: if . == null then "—" elif . < 60 then "\(.) s" else "\((. / 60) | floor) min" end;
def result_label: if . == null then "em andamento" else
	{ok: "ok", ok_takeover: "**ok (assumida pelo planejador)**", failed: "**FALHOU**", blocked: "**BLOQUEADA**",
	 skipped: "pulada"}[.] // . end;
def verdict_label: {approved: "aprovada", changes: "**reprovada**"}[.] // .;
def status_label: {done: "concluída", needs_decision: "parou com dúvida", blocked: "**bloqueada**"}[.] // .;
def notice_label:
	{limit_wait: "LIMITE DE USO", limit_giveup: "LIMITE DE USO", account_switch: "TROCA DE CONTA",
	 timeout: "TIMEOUT", error: "ERRO", interrupted: "INTERROMPIDO", resumed: "RETOMADA",
	 retry: "REFEITA"}[.] // "AVISO";

. as $ev
| ([$ev[] | select(.type == "run_start")][0]) as $rs
| ([$ev[] | select(.type == "run_end")][0]) as $re
| [$ev[] | select(.type == "task_start")] as $ts
| [$ev[] | select(.type == "task_end")] as $te
| ([$ev[] | select(.type == "exec")] | group_by(.task) | map(last)) as $last_exec
| ([$ev[] | select(.type == "review")] | group_by(.task) | map(last)) as $last_review
| (
	[$te[] | select(.result == "failed") | "- **[FALHOU]** \(.task | link) — \(.reason // "" | esc)"]
	+ [$te[] | select(.result == "blocked") | "- **[BLOQUEIO]** \(.task | link) — \(.reason // "" | esc)"]
	+ [$te[] | select(.result == "ok_takeover") | "- **[ASSUMIDA PELO PLANEJADOR]** \(.task | link) — o executor não passou na revisão em \($rs.max_cycles) ciclos"]
	+ [$ev[] | select(.type == "decision" and .points < 3)
		| "- **[DECISÃO \(.points | pts) pts]** \(.task | link) — \(.question | esc) → `\(.choice)` \(.label | esc)"]
	+ [$last_exec[] | .task as $t | .pending[]? | "- **[PENDENTE]** \($t | link) — \(. | esc)"]
	+ [$last_review[] | .task as $t | .highlights[]? | "- **[DESTAQUE]** \($t | link) — \(. | esc)"]
	+ [$ev[] | select(.type == "notice") | "- **[\(.kind | notice_label)]** \(if (.task // "") != "" then (.task | link) + " — " else "" end)\(.text | esc)"]
  ) as $attn
| [
	"# orq — \($rs.queue) — \($rs.ts[0:16] | sub("T"; " "))",
	"",
	"Repositório `\($rs.repo)` · conta \($rs.account) · planejador/revisor \($rs.planner) · executor \($rs.executor) · conselho \($rs.voters)× \($rs.voter), desempate \($rs.tiebreak) · até \($rs.max_cycles) ciclos",
	"",
	(if $re then "**Fim:** \($re.ts[0:16] | sub("T"; " ")) — \($re.result | esc). Custo estimado: US$ \($re.cost)." else "**Em andamento.** Última atualização: \($ev[-1].ts[0:16] | sub("T"; " "))." end),
	"",
	"## Leia primeiro",
	"",
	(if ($attn | length) == 0 then "Nada exige atenção." else $attn[] end),
	"",
	"## Resumo",
	"",
	"| # | Tarefa | Resultado | Ciclos | Decisões (3 / 2,5 / 2 pts) | Commits | Duração |",
	"|---|---|---|---|---|---|---|",
	($ts | to_entries[] | .key as $i | .value.task as $t
		| ([$te[] | select(.task == $t)][0]) as $end
		| ([$ev[] | select(.type == "exec" and .task == $t) | .cycle] | max // 0) as $cyc
		| ([$ev[] | select(.type == "decision" and .task == $t) | .points]) as $d
		| ([$ev[] | select(.type == "exec" and .task == $t) | .commits[]?.hash] | unique | length) as $nc
		| "| \($i + 1) | \($t | link) | \($end.result // null | result_label) | \($cyc) | \([$d[] | select(. == 3)] | length) / \([$d[] | select(. == 2.5)] | length) / \([$d[] | select(. == 2)] | length) | \($nc) | \($end.duration_s // null | dur) |"),
	"",
	($ts | to_entries[] | .key as $i | .value as $start | $start.task as $t
		| "<a id=\"\($t | anchor)\"></a>",
		  "",
		  "## Run \($i + 1) — \($t)",
		  "",
		  "Início \($start.ts[11:16]) · base `\($start.base[0:9])` · tarefa: `\($start.task_file)`",
		  "",
		  ($ev[] | select(.task == $t and .type != "task_start")
			| if .type == "plan" then
				"### Plano\n\n\(.summary)\n\nArquivo: [\(.plan_rel)](\(.plan_rel))\n"
			  elif .type == "decision" then
				"### Decisão — \(.question | esc) (**\(.points | pts) pontos**)\n\nPerguntado por: \(.source). \(.context | esc)\n\n| Opção | Votos |\n|---|---|\n"
				+ ([.options[] as $o | "| `\($o.id)` — \($o.label | esc)\(if $o.id == .choice then " **← escolhida**" else "" end) | \([.votes[] | select(.option_id == $o.id) | .voter | tostring] | join(", ") | if . == "" then "—" else . end) |"] | join("\n"))
				+ "\n\n"
				+ ([.votes[] | "- Conselheiro \(.voter) (`\(.option_id)`): \(.rationale | esc)"] | join("\n"))
				+ (if .tiebreak != "" then "\n- **Desempate** (`\(.choice)`): \(.tiebreak | esc)" else "" end)
				+ "\n"
			  elif .type == "exec" then
				"### Ciclo \(.cycle) — execução (\(.actor)): \(.status | status_label)\n\n\(.summary)\n"
				+ (if (.commits | length) > 0 then "\nCommits: " + ([.commits[] | "`\(.hash[0:9])` \(.message | esc)"] | join(" · ")) + "\n" else "" end)
				+ (if (.checks | length) > 0 then "\nVerificações:\n" + ([.checks[] | "- `\(.command | esc)` → \(.result | esc)"] | join("\n")) + "\n" else "" end)
				+ (if (.pending | length) > 0 then "\n**Pendente:**\n" + ([.pending[] | "- \(. | esc)"] | join("\n")) + "\n" else "" end)
			  elif .type == "review" then
				"### Ciclo \(.cycle) — revisão (\(.reviewer)): \(.verdict | verdict_label)\n\n\(.summary)\n"
				+ (if (.issues | length) > 0 then "\n| Sev. | Onde | O quê | Correção |\n|---|---|---|---|\n" + ([.issues[] | "| \(.severity) | \(.where | esc) | \(.what | esc) | \(.fix | esc) |"] | join("\n")) + "\n" else "" end)
				+ (if (.highlights | length) > 0 then "\n**Destaques:**\n" + ([.highlights[] | "- \(. | esc)"] | join("\n")) + "\n" else "" end)
			  elif .type == "notice" then
				"> **[\(.kind | notice_label)]** \(.text | esc)\n"
			  elif .type == "task_end" then
				"### Resultado: \(.result | result_label)\n\n\(.reason // "" )\n"
			  else empty end),
		  "")
  ]
| join("\n")
