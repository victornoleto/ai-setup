# TODO

Pendências anotadas durante a primeira execução real do orq v2 (gt-v3, 2026-09-26-antes-da-revisao, 13 tarefas).

## Painel (TUI)

- [ ] **Lista de tarefas com estado visual.** Tarefa concluída fica apagada (dim/cinza); tarefa em
  execução ganha cor de destaque (amarelo/dourado) e negrito; pendente fica no estilo normal.
  - Onde: `TaskRow.text()` em `src/orq/tui/model.py` devolve `str`; passar a devolver `rich.Text`
    com estilo por estado, e `refresh_data()` em `src/orq/tui/app.py` junta os `Text`.
  - Cor não pode ser o único canal: manter o glifo (`▶`, `·`, glifo do resultado) e usar
    intensidade (dim × bold) além da cor.

- [ ] **Timeline (lado esquerdo) com cor por tipo de mensagem.** Estilos distintos para: plano,
  execução, revisão, início/fim de tarefa, avisos (pausa, retomada, erro) e mensagens do operador.
  - Onde: `timeline_line()` / `event_line()` em `src/orq/tui/model.py`; hoje vira `Text(text)`
    sem estilo em `refresh_data()`.
  - Cor não pode ser o único canal: cada tipo também leva um marcador próprio (prefixo curto ou
    glifo), e início/fim de tarefa em negrito para separar os blocos.

## Motor

- [x] **Verificação determinística antes da revisão.** Chave `verify = "make test"` (ou similar) no
  `orq.toml`, global ou da fila. O motor roda o comando depois de cada execução e antes da revisão.
  - Falhou: volta para o executor como correção, com a saída do comando, sem gastar chamada de revisão.
  - Passou: a saída vai no prompt da revisão (`prompts/review.md`) como evidência.
  - Onde: `_run_task()` em `src/orq/engine.py`, entre `exec` e `review`; `review()` hoje só recebe o
    relatório do executor.
  - Registrar no journal/timeline (evento próprio, ex. `[VERIFICAÇÃO]`), com tempo e código de saída.

- [x] **Árvore limpa conferida no fim da tarefa, não só no começo da próxima.** Hoje o check fica no
  `phase == "start"` (`src/orq/engine.py`): um arquivo esquecido sem commit bloqueia a tarefa seguinte e,
  com `on_fail = "stop"`, para a fila.
  - Ao terminar a execução: se `git status --porcelain` não estiver vazio, retomar a sessão do executor
    e pedir o commit (ou a limpeza) antes da revisão.
  - Conferir também `HEAD != base`: tarefa "ok" sem nenhum commit é suspeita; sinalizar no journal.

## Intervenção do Victor

- [ ] **Notificação por ntfy.** Tópico e servidor no `orq.toml` (ex. `[notify] ntfy = "https://ntfy.sh/<tópico>"`).
  Hoje só existe `notify-send` no fim da fila (`notify()` em `src/orq/engine.py`).
  - Disparar em: intervenção necessária (abaixo), fim da fila, limite de uso/espera longa.
  - Mensagem curta: fila, tarefa, o que aconteceu, e a pergunta quando houver.

- [ ] **Pausa com pergunta quando a execução precisar do Victor.** Em vez de só falhar/bloquear, o
  motor pausa, notifica e espera a resposta no input do painel (ou `orq send`).
  - Quando: tarefa bloqueada, falha sem saída automática, laço de dúvidas do conselho, verificação
    falhando depois do último ciclo, e decisão do conselho sem unanimidade (2 e 2,5 pts). Nesse
    último caso, as opções são as do conselho e a recomendada é a que ele escolheu, com os votos à mostra.
  - Na tela: bloco destacado com a pergunta, o contexto mínimo e **no mínimo 3 opções** numeradas,
    com a recomendação marcada. Destaque não só por cor: moldura/negrito + rótulo `RECOMENDADA`
    e um prefixo próprio (ex. `[PRECISA DE VOCÊ]`), no mesmo esquema de estilos da timeline.
  - Resposta: número da opção ou texto livre.
  - Depois da resposta, o operador (LLM) avalia se ela basta para destravar a execução automática.
    Se basta, retoma sozinho; se não, faz a próxima pergunta no mesmo formato.
  - Registrar pergunta, opções e resposta no journal (`[DECISÃO DO VICTOR]`) e no `decisions.md` da tarefa.

## Custo e tempo

- [x] **Custo total e por parte.** Hoje `add_cost()` em `src/orq/store.py` só soma um total.
  - Guardar por papel (planejador, executor, revisor, conselho, desempate, operador, verificação) e
    por tarefa; `call()` em `src/orq/engine.py` já sabe o papel e a tarefa.
  - Painel: total no cabeçalho; custo de cada tarefa na lista; detalhamento por papel no journal e
    num detalhe (enter ou comando `/cost`).
  - Deixar claro que é estimativa (via CLI o custo não é o real faturado).
  - Opcional: `max_cost` que pausa a fila (e notifica) ao passar do teto.

- [x] **Relógio `HH:MM:SS` ao vivo.** Tempo total da execução no cabeçalho e tempo da tarefa em curso
  na lista, atualizando a cada segundo. O painel já faz `set_interval(0.5, refresh_data)` em
  `src/orq/tui/app.py`; só baixar para 5–10 s se pesar.
  - Duração final de cada tarefa concluída também em `HH:MM:SS` (hoje `fmt_dur()` arredonda para min).
  - Previsão de término: tempo médio por tarefa concluída × tarefas restantes.

## Relatórios

- [x] **Relatório por tarefa.** Um `NN-tarefa/report.md` ao terminar cada tarefa: resultado, resumo do
  que foi feito, commits (`base..HEAD`), arquivos alterados (`--stat`), verificação, decisões, custo por
  papel e duração.

- [x] **Resumo da execução inteira.** No `run_end`, um `summary.md` no run dir: resultado geral, tempo
  e custo totais (com detalhamento), tabela de tarefas com link para cada `report.md`, pontos que pedem
  atenção (decisões sem unanimidade, takeovers, intervenções). Avaliar reaproveitar a skill `entrega`
  sobre o intervalo de commits da fila.
