# orq — fila de tarefas para agentes de código

Roda uma fila de tarefas sem supervisão, com papéis separados e **uma sessão nova por tarefa**:

1. O **planejador** lê a tarefa e o repositório e escreve o plano.
2. O **executor** executa e commita.
3. Se a execução deixou arquivo sem commit, quem executou tem uma chance de arrumar (sem gastar ciclo); senão, a
   tarefa fica **bloqueada**. Se houver `[verify] command`, o orq o roda: falhou, a entrega volta ao executor sem revisão (gasta um ciclo).
   Passou, o planejador **revisa**, com a saída do comando à mão. Se reprovar, o executor corrige, até `max_cycles` (3) execuções revisadas.
4. Reprovado no último ciclo, o planejador **assume**; a verificação roda de novo e um **revisor** em sessão
   nova confere.
5. Toda **dúvida** vai a um **conselho**: N votantes em paralelo, só leitura. Unânime = **3 pontos**; maioria absoluta (mais da metade dos N votantes configurados) =
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
orq notify setup | test
orq selftest
```

`orq run` aceita a pasta da atividade (com `orq/` dentro) ou a própria fila. A árvore precisa estar limpa no
começo de cada tarefa; se não estiver, a tarefa fica **bloqueada**. Com `on_fail = "stop"` (padrão), a fila para
na primeira tarefa que falha.

Cada execução nova salva a configuração efetiva (incluindo o `--repo`) em `state.json`. O `resume` usa esse
snapshot, mesmo que o TOML ou o ambiente tenham mudado; `--account` continua sendo uma substituição explícita.
Execuções antigas recuperam o repositório do evento inicial e carregam as demais opções da configuração atual.
O motor mantém locks exclusivos da execução e da árvore de trabalho: duas filas não executam simultaneamente
no mesmo worktree. `--retry` exige o nome exato da tarefa e arquiva seus relatórios antes de recomeçar.

## Painel

```
orq · public-links · 1/3 tarefas · motor rodando · 00:27:41 · termina ~12:05 · US$ 3.10 estimado
TAREFAS                                  │ STREAM
✓ 01-seeder  ok · 00:12:08 · US$ 1.20    │   [plan] › $ git branch --show-current
▶ 02-command  executando c2 · 00:04:11   │   [plan] › Read api/app/Core/Support/UrlHelper.php
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
| `/answer <id> <nº ou texto>` | responde a pergunta aberta (no painel, basta digitar sem barra) |
| `/decision <qid> <opção ou texto>` | troca uma decisão do conselho; se a tarefa já terminou, cria a tarefa de ajuste |
| `/cost [NN]` | custo estimado por papel (planejador, executor, revisor final, conselho, operador), total e por tarefa |
| `/pause` · `/resume` · `/stop` | pausa ou para no próximo ponto seguro (entre duas chamadas); `orq resume` continua |
| texto sem barra | vai ao **operador** (LLM, só leitura), que responde e propõe comandos; `y` aplica, `n` descarta |

Os mesmos comandos funcionam sem painel: `orq send <run-dir> "/skip 03"`.

Comandos são confirmados individualmente depois de aplicados. A criação de tarefas, notas e trocas de decisão
usam o ID do comando para evitar duplicação na reentrega; respostas à intervenção são persistidas. `/stop`
também interrompe a espera entre tentativas por quota ou erro transitório, antes da próxima chamada.

## Quando a fila precisa de você

Com `[intervene] enabled = true` (padrão), a fila **pausa e pergunta** em vez de falhar ou bloquear:

| Gatilho | Opções | Sem resposta |
|---|---|---|
| Decisão do conselho com 2 ou 2,5 pts | as do conselho; recomendada = a escolhida | depois de `decision_timeout` (1 h), segue com a escolha: **[DECISÃO SEM VICTOR]** |
| Tarefa bloqueada (árvore suja, executor travado) ou que falhou (chamada, revisão final, verificação depois do takeover, laço de dúvidas) | 3 ou 4, montadas pelo operador (só leitura), uma recomendada | espera; lembrete no ntfy a cada `reminder` (2 h) |

Cada opção de bloqueio/falha é uma ação: `retry` (refaz a fase com uma nota), `replan` (volta ao plano), `accept`
(fecha como **ok, aceita pelo Victor**), `skip` (pula) ou `stop` (para; `orq resume` volta à mesma pergunta).

A pergunta aparece num bloco destacado acima do chat (`[PRECISA DE VOCÊ]`, a recomendada com `★ RECOMENDADA`); o
celular (ntfy) recebe só a fila e a tarefa. Consulte os detalhes no painel antes de responder com o **número** da
opção (no painel ou no botão da notificação) ou com **texto livre** no
painel: o operador avalia se basta; se não, faz a próxima pergunta. Depois de 3 rodadas, só número.

### ntfy no celular

1. Instale o app **ntfy** (Play Store ou F-Droid no Android; App Store no iPhone). No PC não há nada para instalar.
2. Rode `orq notify setup`: gera um tópico aleatório em `~/.config/orq/notify.toml` (fora do repositório: o nome do
   tópico funciona como senha), mostra o nome e manda uma notificação de teste.
3. No app: **+ Subscribe to topic**, cole o tópico, servidor `ntfy.sh`. No Android, ligue **Instant delivery** nessa
   assinatura.
4. `orq notify test` manda outra notificação quando quiser conferir.

Os botões de resposta funcionam no Android e no web app (`https://ntfy.sh/app`); no iPhone, o ntfy não mostra
botões — a notificação avisa e você responde pelo painel (ou pelo web app no navegador do celular). O ntfy mostra
no máximo 3 botões: a recomendada e as duas seguintes, identificadas por número. O título leva só a fila e o id da
tarefa; pergunta, rótulos, caminhos e saídas nunca vão ao ntfy: a mensagem é fixa, com o ID da pergunta e os
números das opções. O diagnóstico completo permanece no painel e no aviso local. Sem `notify.toml`, fica só o `notify-send`.

Também notificam: lembrete de pergunta aberta, decisão que seguiu sem você, espera por limite de uso acima de 30 min
e o fim da fila.

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

[report]
llm_summary = true               # no fim, o planejador (só leitura) escreve "O que foi entregue" no journal

[intervene]
enabled = true                   # false: falha/bloqueio encerram a tarefa, como antes
decision_timeout = "1h"
reminder = "2h"

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
| `journal.md` | o resumo da execução, regenerado a cada evento: **"Leia primeiro"**, "O que foi entregue" (escrito
pelo planejador no fim, só leitura) e uma linha por tarefa com link para o report |
| `NN-tarefa/report.md` | o relatório da tarefa: plano, execuções, verificações, revisões, decisões, custo e a entrega
(commits e arquivos alterados) |
| `events.jsonl` | a fonte do journal e da timeline |
| `state.json` | fase, ciclo e sessões de cada tarefa (o que o `resume` lê) |
| `stream.log` / `orq.log` | o stream dos harnesses / o log corrido |
| `inbox.jsonl` | os comandos do painel e do `orq send` |
| `NN-tarefa/plan.md`, `decisions.md` | o plano e as decisões |
| `NN-tarefa/verify-<ciclo>.log` | a saída completa da verificação automática |
| `NN-tarefa/calls/*` | prompt, stream cru e resposta de cada chamada |

O journal e o painel mostram a tentativa atual; `events.jsonl` mantém o histórico completo. Depois de `--retry`,
o journal aponta também para o relatório arquivado. Custos incluem tentativas com erro quando o harness informa
o consumo. Sem informação de custo (por exemplo, no adaptador Codex), o total aparece como **parcial**; zero
informado e custo desconhecido são situações distintas. O detalhamento está em `/cost` e nos relatórios finais.

Etiquetas do journal e da timeline: **[PRECISA DE VOCÊ]**, **[INTERVENÇÃO]**, **[DECISÃO SEM VICTOR]**, **[VERIFICAÇÃO cN]** (só timeline), **[FALHOU]**, **[BLOQUEIO]**, **[ASSUMIDA PELO PLANEJADOR]**,
**[DECISÃO 2 pts]**/**[DECISÃO 2,5 pts]** (sem unanimidade: vale conferir), **[DECISÃO DO VICTOR]**, **[PENDÊNCIAS]**
(só a contagem: o texto de cada pendência e destaque fica na seção da tarefa), **[LIMITE DE USO]**, **[TROCA DE CONTA]**, **[TIMEOUT]**, **[ERRO]**, **[INTERROMPIDO]**, **[PAUSA]**,
**[AJUSTE]**, **[OPERADOR]**, **[ÁRVORE SUJA]**, **[SEM COMMIT]** (terminou ok sem commit: confira).

## Proteções

- **`git push` bloqueado**: cada remote ganha um `pushurl` inválido via `GIT_CONFIG_*` no ambiente das sessões,
  sem alterar o repositório.
- Conselho e operador rodam só leitura. Planejador, executor e revisor rodam com as permissões liberadas; o que
  eles podem fazer é o que a tarefa e as regras dizem.
- Timeout por chamada (`call_timeout`, 4 h). Erro transitório tem nova tentativa. No limite de uso, espera o reset
  (até `limit_max_wait`, 8 h) ou troca de conta.
- `Ctrl-C`/`kill` no motor registram "interrompido"; `orq resume` continua da fase em curso. IDs de sessão são
  persistidos assim que conhecidos (antes da chamada quando o harness permite escolher o ID). A retomada do
  Codex preserva o acesso somente leitura. O encerramento aguarda até 1 s após TERM e usa KILL no grupo restante.

Retomada de sessão não garante execução exatamente uma vez de ferramentas externas: uma queda entre uma ação
do agente e seu registro ainda exige conferir o estado do repositório. Nenhuma limpeza ou rollback automático
é aplicado aos commits existentes.

## Desenvolvimento

Projeto uv em Python ([`src/orq/`](src/orq/)); o painel usa Textual. `orq selftest` (ou
`uv run --project ~/.ai-setup/orq pytest`) roda a suíte com o harness **fake**
([`harness/fake.py`](src/orq/harness/fake.py)): respostas de um JSON por schema, sem gastar quota. O mesmo fake
serve para ver o painel com uma fila de mentira (`harness = "fake"`, `model = "script.json"`).

Para rodar a suíte local isolada, sem rede nem acesso às credenciais:

```sh
bash tests/run-isolated.sh -q
```

Esse lançador requer Linux com Bubblewrap e `prlimit`, além da `.venv` já instalada. O checkout fica somente
leitura; arquivos temporários ficam em tmpfs limitado a 256 MiB. A execução tem limites de 110 s de parede,
90 s de CPU, 2 GiB de memória virtual, 128 processos, 32 MiB por arquivo e 256 descritores. Não instala dependências.
