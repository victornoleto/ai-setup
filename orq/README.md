# orq — fila de tarefas para o Claude Code

Roda uma fila de tarefas sem supervisão, com papéis separados:

1. O **planejador** (Opus 5.5, high) lê a tarefa e o repositório e escreve o plano.
2. O **executor** (Sonnet 5, high) executa e commita.
3. O planejador **revisa**. Se reprovar, o executor corrige, até `ORQ_MAX_CYCLES` (3) execuções revisadas.
4. Reprovado no 3º ciclo, o planejador **assume** e corrige ele mesmo; um Opus em **sessão nova** revisa.
5. Toda **dúvida** (do planejador, do executor ou do revisor) vai a um **conselho**: 3 Opus high votam em
   paralelo, só leitura. 3 votos iguais = **3 pontos**; maioria de 2 = **2 pontos**; três votos diferentes →
   um Opus `max` desempata = **2,5 pontos**.
6. Tudo vira um `journal.md` por execução, com **"Leia primeiro"** no topo.

## Uso

```sh
orq run <fila> [--account 1|2] [--repo DIR] [--run-dir DIR] [--dry-run]
orq resume <run-dir> [--account 1|2] [--retry NN-tarefa]
orq status <run-dir>
orq decide "Pergunta?" --option a="Rótulo: detalhe" --option b="…" [--context "…"]
orq selftest
```

Deixe rodando num `tmux` (`tmux new -s orq`), com o notebook na tomada e sem suspender.

## Conta: xclaude ou xclaude2

`--account 1` usa `~/.claude` (o `xclaude`); `--account 2` usa `~/.claude2` (o `xclaude2`). O padrão é
`ORQ_ACCOUNT=2` no `orq.conf`. Alias não vale em script, então o `orq` faz o que eles fazem: `CLAUDE_CONFIG_DIR`
+ `--dangerously-skip-permissions`. Uma conta por papel: `ORQ_EXECUTOR_ACCOUNT=1`, `ORQ_VOTER_ACCOUNT=1`…

No limite de uso, com `ORQ_FALLBACK_ACCOUNT` preenchido, o `orq` troca de conta; vazio, espera o reset. A sessão
retomada funciona nas duas contas, porque o `projects/` é compartilhado
(`~/Documents/notas/ia/claude-code-duas-contas.md`).

## Fila

Um diretório:

```
minha-fila/
  queue.conf        # opcional: ORQ_REPO, ORQ_RULES_FILE e qualquer ORQ_* (vence o ambiente)
  regras.md         # opcional: anexado a todo prompt (branch, o que não fazer, onde registrar)
  01-algo.md        # uma tarefa por arquivo, em ordem de nome; texto livre, como um prompt de sessão
  02-outra.md
  runs/             # criado pelo orq: uma pasta por execução
```

A tarefa roda em `ORQ_REPO` (ou no diretório atual). A árvore precisa estar limpa no começo de cada tarefa; se não
estiver, a tarefa fica **bloqueada**. Com `ORQ_ON_FAIL=stop` (padrão), a fila para na primeira tarefa que falha ou
bloqueia, porque as seguintes costumam depender dela.

## O que fica no run dir

| Arquivo | O quê |
|---|---|
| `journal.md` | o relatório; regenerado a cada evento |
| `events.jsonl` | a fonte do journal (um evento por linha) |
| `state.json` | fase, ciclo e sessões de cada tarefa (é o que o `resume` lê) |
| `orq.log` | o log corrido |
| `NN-tarefa/plan.md` | o plano; `decisions.md`, as decisões do conselho |
| `NN-tarefa/calls/*.json` | a resposta crua de cada chamada ao `claude` |

## Lendo o journal

Comece pelo **"Leia primeiro"**. As etiquetas são texto, e nenhuma depende de cor:

| Etiqueta | O que significa |
|---|---|
| **[FALHOU]** / **[BLOQUEIO]** | a tarefa não terminou; o motivo vem ao lado |
| **[ASSUMIDA PELO PLANEJADOR]** | o executor não passou nos ciclos; o Opus assumiu |
| **[DECISÃO 2 pts]** / **[DECISÃO 2,5 pts]** | decisão sem unanimidade: vale conferir |
| **[PENDENTE]** | o que o executor declarou não ter feito ou verificado |
| **[DESTAQUE]** | o que o revisor pediu para você ler |
| **[LIMITE DE USO]** / **[TROCA DE CONTA]** / **[TIMEOUT]** / **[ERRO]** / **[INTERROMPIDO]** | eventos da execução |

## Proteções

- **`git push` bloqueado.** Cada remote do repositório ganha um `pushurl` inválido via `GIT_CONFIG_*` no ambiente
  das sessões. O repositório não é alterado; fora do `orq`, o push volta a funcionar.
- O conselho roda com `--permission-mode plan` (só leitura). Planejador, executor e revisor rodam com
  `--dangerously-skip-permissions`; o que eles podem fazer é o que a tarefa e as regras dizem.
- `timeout` por chamada (`ORQ_CALL_TIMEOUT`, 4 h), nova tentativa em erro transitório, espera no limite de uso
  (até `ORQ_LIMIT_MAX_WAIT`, 8 h).
- `Ctrl-C` ou `kill` registram "interrompido"; `orq resume` continua da fase em curso, retomando as sessões.

## Configuração

Tudo em [`orq.conf`](orq.conf): modelos, effort e conta por papel, número de votantes, ciclos, timeouts.
`ORQ_TEST_FORCE_CHANGES=1` força a revisão a reprovar, o que serve para testar o takeover.
