# TODO

Pendências do orq v2. Histórico: os itens da primeira execução real (2026-09-26) e a revisão do Astra
(`docs/astra-suggestions.md`) estão todos aplicados; o `git log -- orq` conta a história.

## Revisão de 2026-10-03 (código + 5 execuções reais)

- [x] **Corrigir**: retry depois da revisão final leva o parecer do revisor; `/skip` aparece no journal e no resumo
  final; `orq run` com erro de configuração não abre o painel sobre motor morto; chamada fora de tarefa grava em
  `<papel>/calls`.
- [x] **Tempo ativo** por tarefa (chamadas e verificação): duração "parede (ativa)", lista do painel e previsão de
  término sem a espera pelo Victor nem o tempo parado.
- [x] **Journal**: "Leia primeiro" só com o que exige ação; pendências e destaques na seção de cada tarefa;
  PROGRESS leva as pendências das tarefas feitas; revisor não repete verificação já feita; `orq check` avisa
  `[verify]` vazio.
- [x] **`orq runs`** e `attach`/`status`/`send`/`resume` sem run dir (registro em `~/.local/state/orq/runs.jsonl`).
- [x] **Orçamento**: `[loop] max_task_time` (3 h ativas) e `max_run_cost` perguntam ao Victor antes de seguir
  gastando; `orq check` avisa branch das regras ≠ atual e tarefa sem "Pronto quando".

## Fica para depois (avaliado e não recomendado agora)

- Bloquear `git push` por `core.hooksPath` com um `pre-push`: fecharia o `git push <url>`, mas derruba os hooks
  do próprio repositório (husky, pre-commit). Hoje só o `pushurl` dos remotes é bloqueado.
- Custo do Codex estimado por tokens (`turn.completed.usage` × tabela de preços): na prática só o claude é usado.
- Worktree dedicada por execução: isola o trabalho manual, mas muda o fluxo das filas (branch, `make dev`).
- `TRANSIENT_RE` pega "network"/"timed out" no texto final do modelo em erro fatal: até 5 tentativas × 2 min
  perdidas. Só classificar como transitório o que vier do stderr ou do campo de erro do harness.
