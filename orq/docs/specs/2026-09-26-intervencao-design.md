# Intervenção do Victor: pausa com pergunta, ntfy e painel com estilos

Data: 2026-09-26 · Status: aprovado em conversa, aguardando revisão desta spec.

## Objetivo

Quando a fila precisa do Victor, ela **pausa**, **avisa no celular** (ntfy) e **mostra no painel** uma pergunta com
3 ou 4 opções, uma recomendada. O Victor responde por número (painel ou botão no celular) ou por texto livre (painel).
Texto livre passa pelo operador, que decide se basta para destravar a execução automática ou se precisa de mais uma
pergunta. Resolvida a pergunta, a fila continua sozinha.

Fora do escopo: responder texto livre pelo celular; servidor ntfy próprio (a URL é configurável, mas nada é feito
para autenticação); rodar tarefas seguintes enquanto uma pergunta está aberta.

## 1. Motor

### Gatilhos

| Gatilho | Hoje | Com intervenção | Sem resposta |
|---|---|---|---|
| Decisão do conselho com 2 ou 2,5 pts | segue com a escolha | pergunta; opções = as do conselho; recomendada = a escolha | depois de `decision_timeout` (1 h) segue com a escolha; aviso `[DECISÃO SEM VICTOR]` |
| Tarefa `blocked` (árvore suja no começo, arrumação que não resolveu, executor com `status = blocked`) | `end(blocked)` | pergunta montada pelo operador | espera; lembrete a cada `reminder` (2 h) |
| Tarefa `failed` (chamada falhou, revisão final reprovou, verificação falhou depois do takeover, laço de dúvidas, conselho sem voto válido) | `end(failed)` | pergunta montada pelo operador | espera; lembrete a cada 2 h |

`[intervene] enabled = false` mantém o comportamento de hoje (e é o padrão nos testes antigos).

### Ações

Toda opção de pergunta de bloqueio/falha mapeia para uma ação que o motor sabe executar:

| Ação | Efeito |
|---|---|
| `retry` | refaz a fase que falhou, com `note` no próximo prompt (mesmo mecanismo do `/note`). Revisão final reprovada ou verificação final falhada refazem o `takeover`; árvore suja refaz o `clean`; `blocked` do executor refaz o `exec` (resume da sessão). Nos demais casos (chamada que falhou, laço de dúvidas, conselho sem voto válido), refaz a fase em que a falha aconteceu, guardada em `open_ask.phase`. |
| `replan` | volta à fase `plan` com a nota; `cycle = 1`; sessões do executor descartadas. |
| `accept` | encerra a tarefa com o resultado novo `ok_victor` ("aceita pelo Victor"), que conta como ok. |
| `skip` | encerra a tarefa como `skipped`. |
| `stop` | `StopRun`: a execução para; `orq resume` continua da pergunta. |

Pergunta de decisão do conselho: a resposta é o id da opção (ou texto livre avaliado pelo operador); vira decisão com
`source = victor` pelo mesmo caminho do `/decision` (evento `decision`, `decisions.md`).

### Estado e eventos

- `state.json` → `open_ask`: `{id, task, kind, phase, question, diagnosis, options, recommended, deadline, rounds}`.
  Uma pergunta aberta por vez; a fila inteira espera.
- Eventos: `ask` (abriu), `ask_answer` (resposta, com ação e nota), `ask_timeout` (seguiu sozinha). O journal
  registra perguntas e respostas no "Leia primeiro" (`[DECISÃO DO VICTOR]`, `[INTERVENÇÃO]`, `[DECISÃO SEM VICTOR]`);
  o `report.md` da tarefa, o diálogo inteiro.
- A espera é um `asyncio.Event` que o `Control` dispara ao receber `/answer <id> <texto>` (painel, `orq send` ou
  ntfy). Resposta com id diferente do `open_ask.id` é ignorada, com `control_ack` explicando.
- `orq resume` com `open_ask` no estado volta a esperar a mesma pergunta (sem nova chamada ao operador).

## 2. ntfy

- Configuração **fora do repositório**: `~/.config/orq/notify.toml` com `server` (padrão `https://ntfy.sh`) e `topic`.
  Sem arquivo, nada é enviado (o `notify-send` local continua).
- `orq notify setup`: gera um tópico aleatório (32 caracteres), grava o arquivo, manda uma notificação de teste e
  mostra o nome para assinar no app. `orq notify test` só manda o teste.
- Envio: `POST <server>/<topic>` com `urllib` (stdlib), cabeçalhos `Title`, `Priority`, `Tags`, `Actions`.
- Botões: ação `http` que publica em `<server>/<topic>-r` o corpo `"<ask id> <opção>"`, com `clear=true`. O ntfy
  aceita no máximo **3** botões: a recomendada e as duas seguintes; a quarta opção só no painel.
- Respostas: enquanto há `open_ask`, uma tarefa do motor lê `GET <server>/<topic>-r/json?poll=1&since=<último>` a
  cada 15 s e entrega cada mensagem ao `Control` como `/answer`.
- Notifica: pergunta aberta (prioridade alta, com botões); lembrete (2 h); decisão que seguiu sozinha; espera por
  limite de uso acima de 30 min; fim da fila.
- Conteúdo: fila, tarefa, pergunta (até 200 caracteres) e rótulos (até 60). Nunca código, caminho, diff ou saída de
  teste. O prompt do operador pede rótulos curtos e sem detalhe do cliente.
- Falha de rede: `orq.log` e segue; nunca derruba a execução.

## 3. Painel

- **Bloco da pergunta**, acima do chat, enquanto há `open_ask`: moldura grossa; título em vídeo inverso
  `[PRECISA DE VOCÊ] <tarefa> · <tipo>`; pergunta; diagnóstico (até 3 linhas); opções numeradas, a recomendada em
  negrito com `★ RECOMENDADA`; rodapé com "responda 1–N ou escreva" e, se houver, "segue sozinha com N às HH:MM".
  Cor dourada como segundo canal.
- Com pergunta aberta, texto sem barra no chat vira `/answer <id> <texto>`; comandos com barra seguem como hoje.
- Cabeçalho: `⏸ esperando você · HH:MM:SS`.
- **Lista de tarefas** (`TaskRow` passa a render `rich.Text`): concluída apagada (dim); em curso negrito + dourado
  com `▶`; esperando você vídeo inverso com `⏸`; falhou/bloqueada negrito com `✗`; pendente normal.
- **Timeline**: início/fim de tarefa em negrito, com uma linha separadora antes de cada `task_start`; cada tipo
  mantém o prefixo e ganha estilo próprio (plano, execução, verificação, revisão, decisão, operador em itálico,
  avisos em negrito, pergunta em vídeo inverso). Nada depende só da cor.

## 4. Operador

- `prompts/intervene.md` + `schemas/ask.json`: recebe tarefa, gatilho, motivo, ações permitidas e caminhos de
  `report.md` e `orq.log`; devolve `{question, diagnosis, options[3–4]: {id, label, detail, action, note},
  recommended}`. Chamada do papel `operator` (só leitura; custo "operador").
- `prompts/resolve.md` + `schemas/resolve.json`: recebe a pergunta aberta, o histórico da conversa e o texto do
  Victor; devolve `{sufficient, reply, action, note}` ou `{sufficient: false, reply, follow_up: <ask>}`.
- Resposta por número não passa por LLM (a opção já traz ação e nota).
- Limite: depois de 3 rodadas de `follow_up`, o bloco pede "responda com o número de uma opção".
- `intervene` falhou: opções fixas `1) retry ★ · 2) skip · 3) stop`, com o motivo como pergunta.
  `resolve` falhou: "não entendi — responda com o número" no bloco; a pergunta continua aberta.

## Configuração

```toml
[intervene]
enabled = true
decision_timeout = "1h"   # decisão sem unanimidade: segue com a escolha do conselho depois disso
reminder = "2h"           # lembrete no ntfy enquanto a pergunta estiver aberta
```

## Testes (harness fake, sem rede)

1. Conselho 2 pts → pergunta → `/answer <id> 2` → decisão `source = victor`, fila segue.
2. Conselho 2 pts sem resposta, `decision_timeout = "1s"` → segue com a escolha; aviso `[DECISÃO SEM VICTOR]`.
3. Tarefa bloqueada → pergunta do operador → `retry` com nota → a nota está no prompt da nova execução; resultado ok.
4. Texto livre → `resolve` insuficiente → `follow_up` → resposta por número → `skip`.
5. `orq resume` com `open_ask` → espera de novo sem chamar o operador.
6. `intervene` falhou → opções fixas.
7. ntfy com `urlopen` simulado: corpo, cabeçalhos, 3 botões no máximo; resposta com id velho ignorada.
8. Painel: bloco aparece; digitar `1` envia `/answer`; estilos da lista (dim, negrito, inverso) e da timeline.
9. `make_queue` gera `[intervene] enabled = false`; testes novos ligam explicitamente.
