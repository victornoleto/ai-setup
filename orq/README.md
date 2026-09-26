# orq — fila de tarefas para agentes de código

Roda uma fila de tarefas sem supervisão, com papéis separados e **uma sessão nova por tarefa**:

1. O **planejador** lê a tarefa e o repositório e escreve o plano.
2. O **executor** executa e commita.
3. Se houver `[verify] command`, o orq o roda: falhou, a entrega volta ao executor sem revisão (gasta um ciclo).
   Passou, o planejador **revisa**, com a saída do comando à mão. Se reprovar, o executor corrige, até `max_cycles` (3) execuções revisadas.
4. Reprovado no último ciclo, o planejador **assume**; a verificação roda de novo e um **revisor** em sessão
   nova confere.
5. Toda **dúvida** vai a um **conselho**: N votantes em paralelo, só leitura. Unânime = **3 pontos**; maioria =
   **2 pontos**; sem maioria, o desempatador decide = **2,5 pontos**.
6. Cada sessão recebe o **progresso** da fila: o que já foi feito (resumo e commits), a tarefa atual e o que falta.

Cada papel escolhe harness e modelo: **claude**, **codex** ou **opencode** (e, por ele, OpenRouter).

## Fluxo

```sh
orq new docs/.local/specs/fire-hotspot/2026-09-30-painel   # wizard: monta <pasta>/orq/ com você
orq check docs/.local/specs/fire-hotspot/2026-09-30-painel # confere antes de rodar
orq run docs/.local/specs/fire-hotspot/2026-09-30-painel   # motor em segundo plano + painel
```

A `<pasta>` pode ter qualquer origem (card do Notion, spec, anotações). O `orq new` cria `<pasta>/orq/` e abre o
harness do papel `wizard` em sessão **interativa**, com a skill [`orq-setup`](../skills/orq-setup/SKILL.md). Ela
lê a pasta e o repositório, pergunta uma coisa por vez e divide o trabalho em tarefas pequenas.

```
<pasta>/
  notion.md, plan.md, …   # o contexto da atividade
  orq/
    orq.toml              # só o que difere do global
    regras.md             # anexado a todo prompt: branch, proibições, verificação, onde registrar
    01-algo.md            # uma tarefa por arquivo, em ordem de nome, como um prompt de sessão
    02-outra.md
    runs/<data-hora>/     # uma pasta por execução
```

Dividir para conquistar: cada tarefa é uma sessão de 20 a 90 min de agente, autossuficiente ("pronto quando" e
verificação próprios). O `orq check` avisa quando uma tarefa passa de 6.000 caracteres.

## Comandos

```sh
orq new <pasta> [--repo DIR]
orq check <pasta>
orq run <pasta> [--repo DIR] [--account N] [--run-dir DIR] [--headless]
orq attach <run-dir>
orq resume <run-dir> [--account N] [--retry NN-tarefa]... [--headless]
orq send <run-dir> "/comando …"
orq status <run-dir>
orq decide "Pergunta?" --option a="Rótulo: detalhe" --option b="…" [--context "…"]
orq selftest
```

`orq run` aceita a pasta da atividade (com `orq/` dentro) ou a própria fila. A árvore precisa estar limpa no
começo de cada tarefa; se não estiver, a tarefa fica **bloqueada**. Com `on_fail = "stop"` (padrão), a fila para
na primeira tarefa que falha.

## Painel

```
orq · public-links · 1/3 tarefas · motor rodando · US$ 3,10
TAREFAS                                  │ STREAM
✓ 01-seeder  ok · 12 min                 │   [plan] › $ git branch --show-current
▶ 02-command  executando c2 · 4 min      │   [plan] › Read api/app/Core/Support/UrlHelper.php
· 03-coordenadas  pendente               │   [exec-2-1131] › Edit api/app/…
TIMELINE  (enter: detalhe)               │   [exec-2-1131] ✗ Exit code 1 …
11:18 ▶ 01-seeder começou                │
11:31 [DECISÃO 2 pts] 01-seeder: …       │
11:40 ✓ 01-seeder terminou: ok (12 min)  │
> /note use o formato em cache           │
```

- O motor roda desanexado: **`q`** (ou `ctrl+q`) fecha o painel e a execução continua; `orq attach` reabre.
- Estado por glifo e texto, sem depender de cor: `✓` ok, `▶` rodando, `⏸` pausada, `·` pendente, `✗` falhou,
  `⊘` pulada.
- **enter** num item da timeline abre o detalhe. Numa decisão, mostra os votos e as justificativas, com um botão
  para trocar a escolha.
- Abaixo de 120 colunas, as metades alternam com **`ctrl+t`**. **`esc`** sai do chat, **`i`** volta a ele;
  fora do chat, `p` pausa ou continua e `f` liga ou desliga o seguimento do stream.

### Chat: ajustes ao vivo

| Comando | Efeito |
|---|---|
| `/add <texto> [--after NN]` | cria a tarefa na fila (no fim, ou `NNa-…` logo depois da NN) |
| `/skip NN` · `/unskip NN` | pula ou devolve uma tarefa pendente |
| `/edit NN` | abre a tarefa pendente no `$EDITOR` |
| `/note <texto> [--task NN]` | instrução para o próximo prompt da tarefa em curso (ou da NN) e das seguintes |
| `/decision <qid> <opção ou texto>` | troca uma decisão do conselho; se a tarefa já terminou, cria a tarefa de ajuste |
| `/pause` · `/resume` · `/stop` | pausa ou para no próximo ponto seguro (entre duas chamadas); `orq resume` continua |
| texto sem barra | vai ao **operador** (LLM, só leitura), que responde e propõe comandos; `y` aplica, `n` descarta |

Os mesmos comandos funcionam sem painel: `orq send <run-dir> "/skip 03"`.

## Configuração

O global fica em [`orq.toml`](orq.toml). A fila repete só o que muda, em `<pasta>/orq/orq.toml` (modelo em
[`defaults/`](defaults/)). Precedência: global → fila → variáveis `ORQ_*` → flags.

```toml
[roles.executor]                 # planner, executor, reviewer, voter (count), tiebreak, operator, wizard
harness = "codex"                # claude | codex | opencode
model = "gpt-5.6-sol"            # opencode: "provedor/modelo", ex. "openrouter/~deepseek/deepseek-v4-flash-latest"
effort = "high"                  # claude: low…max · codex: minimal…high · opencode: --variant

[verify]
command = "make test"            # vazio = desligado; roda via sh -c na raiz do repo, sem push
timeout = "30m"

[accounts.claude]
default = "2"                    # 1 = ~/.claude (xclaude) · 2 = ~/.claude2 (xclaude2); por papel: account = "1"
fallback = ""                    # "1": no limite de uso troca de conta em vez de esperar
```

O `queue.conf` das filas antigas continua sendo lido: `ORQ_ACCOUNT`, `ORQ_RULES_FILE`, `ORQ_<PAPEL>_MODEL` e outras.

| Harness | Chamada | Saída estruturada | Só leitura / tudo liberado |
|---|---|---|---|
| claude | `claude -p --output-format stream-json` | `--json-schema` | `--permission-mode plan` / `--dangerously-skip-permissions` |
| codex | `codex exec --json` | `--output-schema` | `-s read-only` / `--dangerously-bypass-approvals-and-sandbox` |
| opencode | `opencode run --format json` | schema no prompt + validação | `--agent plan` / `--auto` |

## Run dir

| Arquivo | O quê |
|---|---|
| `journal.md` | o relatório, regenerado a cada evento; comece pelo **"Leia primeiro"** |
| `events.jsonl` | a fonte do journal e da timeline |
| `state.json` | fase, ciclo e sessões de cada tarefa (o que o `resume` lê) |
| `stream.log` / `orq.log` | o stream dos harnesses / o log corrido |
| `inbox.jsonl` | os comandos do painel e do `orq send` |
| `NN-tarefa/plan.md`, `decisions.md` | o plano e as decisões |
| `NN-tarefa/verify-<ciclo>.log` | a saída completa da verificação automática |
| `NN-tarefa/calls/*` | prompt, stream cru e resposta de cada chamada |

Etiquetas do journal e da timeline: **[VERIFICAÇÃO cN]** (só timeline), **[FALHOU]**, **[BLOQUEIO]**, **[ASSUMIDA PELO PLANEJADOR]**,
**[DECISÃO 2 pts]**/**[DECISÃO 2,5 pts]** (sem unanimidade: vale conferir), **[DECISÃO DO VICTOR]**, **[PENDENTE]**,
**[DESTAQUE]**, **[LIMITE DE USO]**, **[TROCA DE CONTA]**, **[TIMEOUT]**, **[ERRO]**, **[INTERROMPIDO]**, **[PAUSA]**,
**[AJUSTE]**, **[OPERADOR]**.

## Proteções

- **`git push` bloqueado**: cada remote ganha um `pushurl` inválido via `GIT_CONFIG_*` no ambiente das sessões,
  sem alterar o repositório.
- Conselho e operador rodam só leitura. Planejador, executor e revisor rodam com as permissões liberadas; o que
  eles podem fazer é o que a tarefa e as regras dizem.
- Timeout por chamada (`call_timeout`, 4 h). Erro transitório tem nova tentativa. No limite de uso, espera o reset
  (até `limit_max_wait`, 8 h) ou troca de conta.
- `Ctrl-C`/`kill` no motor registram "interrompido"; `orq resume` continua da fase em curso, retomando as sessões.

## Desenvolvimento

Projeto uv em Python ([`src/orq/`](src/orq/)); o painel usa Textual. `orq selftest` (ou
`uv run --project ~/.ai-setup/orq pytest`) roda a suíte com o harness **fake**
([`harness/fake.py`](src/orq/harness/fake.py)): respostas de um JSON por schema, sem gastar quota. O mesmo fake
serve para ver o painel com uma fila de mentira (`harness = "fake"`, `model = "script.json"`).
