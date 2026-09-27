# Confiabilidade do orq — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task, in order, verifying each step before the next. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir as falhas de retomada, controles, notificações e relatórios descritas na revisão aprovada.

**Architecture:** Preservar o motor por fases e o run dir. Persistir configuração e chamadas em curso; confirmar comandos individualmente, com operações reaplicáveis; derivar relatórios da tentativa atual. Usar locks exclusivos no motor e testes locais com harness falso.

**Tech Stack:** Python 3.12+, asyncio, JSON/JSONL, flock, pytest, Textual; sem dependências novas.

**Spec:** [Relatório aprovado](../../astra-suggestions.md).

## Global Constraints

- Preservar execuções antigas e alterações existentes; não operar a fila gt-v3.
- Nenhuma chamada paga ou notificação real nos testes; executar em isolamento local.
- Somente leitura continua somente leitura nas tentativas e retomadas.
- Funcionalidades novas ficam condicionadas à resposta de escopo; este plano cobre correções e otimizações.
- Sem commit automático; entregar alterações e evidências de validação.

## 1. Permissões, processos e política do conselho

**Files:** `src/orq/harness/{base,codex}.py`, `src/orq/council.py`, `tests/test_reliability.py`.

**Interfaces:** manter `CallRequest.read_only`; acrescentar callback opcional `on_session: Callable[[str], None]`. `run_process` continua retornando `(exit_code, timed_out, stderr_tail)`.

- [x] Testar retomada Codex só leitura, processo que ignora TERM e votação 2–1–1–1.
- [x] Observar falha: `bash tests/run-isolated.sh tests/test_reliability.py -q`.
- [x] Preservar sandbox no argv; aguardar TERM por prazo limitado e escalar a KILL; exigir `top > n / 2`.
- [x] Verificar testes novos e os testes de harness/conselho existentes.

## 2. Configuração, sessões e exclusividade

**Files:** `src/orq/{config,cli,engine,store}.py`, adaptadores, `tests/test_reliability.py`.

**Interfaces:** `config.from_raw(raw, queue_dir)` valida snapshot; `RunStore.engine_lock(repo)` retém locks do run e worktree; estado `config` e `active_calls` registra configuração efetiva e sessões em voo.

- [x] Testar configuração congelada com fila externa, recuperação de sessão interrompida e colisão de motores.
- [x] Observar os testes falharem antes de implementar.
- [x] Usar snapshot no processo desanexado/resume; legado recupera repo do evento inicial; persistir ID pelo callback durante stream; lock antes de retry e execução.
- [x] Testar compatibilidade com run antigo e execução sequencial após liberação dos locks.

## 3. Comandos, intervenção e espera

**Files:** `src/orq/{store,control,intervene,engine}.py`, `tests/test_reliability.py`.

**Interfaces:** `take_inbox()` somente lê pendências; `ack_inbox(cmd)` avança após efeito persistido; IDs de comando tornam operações reaplicáveis; respostas e pausa/parada ficam no estado.

- [x] Testar leitura sem perda, reaplicação de add/note sem duplicação, stop da intervenção preservando a pergunta e interrupção da espera por quota.
- [x] Observar falhas antes das mudanças.
- [x] Confirmar um comando por vez; persistir preparação de criação de arquivos e ações; preservar pergunta no stop; esperar com pontos de controle.
- [x] Verificar testes de controle e intervenção existentes.

## 4. Privacidade, custos e tentativas

**Files:** `src/orq/{notify,intervene,engine,journal,store}.py`, `src/orq/tui/model.py`, testes correspondentes.

**Interfaces:** conteúdo externo fixo e opções numeradas; `CallResult.cost: float | None`; eventos de nova tentativa delimitam estado atual sem apagar histórico.

- [x] Testar que nenhum texto livre chega ao payload externo, falhas com custo são somadas e retry invalida encerramentos anteriores.
- [x] Observar falhas antes das mudanças.
- [x] Usar notificações genéricas, contabilizar tentativas conhecidas e sinalizar custos desconhecidos; projetar eventos da tentativa atual para journal e painel.
- [x] Verificar relatórios anteriores e recentes, inclusive enquanto retry ainda está em andamento.

## 5. I/O, documentação e regressão

**Files:** `src/orq/{store,context}.py`, `src/orq/tui/{app,model}.py`, `README.md`, relatório.

**Interfaces:** cache invalidado por metadados, retornando dados isolados; snapshot de estado por atualização de painel; relatórios permanecem derivados e recuperáveis.

- [x] Testar invalidação após escrita de outra instância e linha JSONL incompleta.
- [x] Medir leituras repetidas antes/depois com fixtures locais; aplicar somente otimizações verificáveis.
- [x] Atualizar documentação de retomada, privacidade, custos e controles.
- [x] Rodar suíte isolada (limite de 110 s por comando), diff check e revisar regressões do conjunto.

## Resultado

Suíte completa: **111 testes passaram em 19,85 s**, em isolamento local. Inclui 24 casos de regressão em
`tests/test_reliability.py` e um fluxo real de CLI com harness falso, fila externa e `resume --retry`.
Não houve chamadas pagas, publicação, commit ou operação na execução gt-v3.

O cache reduziu de dez para uma as leituras do conteúdo de estado em dez consultas sem alteração, mantendo
invalidação entre instâncias. A geração dos relatórios continua imediata; agrupamento foi adiado para não
alterar essa garantia sem medição. As cinco funcionalidades novas permanecem propostas separadas.
