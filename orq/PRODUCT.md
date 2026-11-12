# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Svelte 5 + Vite + TypeScript em `orq/web/`, com `dist/` commitado. Servidor em Python puro
(`orq/src/orq/web/server.py`), só em `127.0.0.1`. Markdown por `marked` + `DOMPurify`, empacotados (sem CDN).

## Users

Desenvolvedores que clonam o ai-setup e rodam filas do orq nos próprios projetos, cada um na própria máquina.
Não escrevem o código: validam o que os agentes escreveram. Passam a maior parte da execução longe da tela.

## Product Purpose

O orq orquestra uma execução longa, dividida em tarefas, rodada por agentes (planejador, executor, revisor,
conselho). A interface web existe para o dono se atualizar em 1 a 3 minutos quando volta: o que foi feito, o
que falta, o que espera decisão dele; e para mudar o rumo do que foi feito ou do que ainda não foi.

Sucesso: ao voltar, o dono sabe em uma tela se precisa agir, e age sem ir ao terminal.

## Positioning

Fila sem supervisão com revisão e conselho entre agentes, que só chama o humano quando precisa. A tela é para
quem valida, não para quem acompanha cada passo.

## Operating Context

- Duas cenas, com o mesmo peso: voltar de tempos em tempos para se atualizar e decidir; e a aba aberta num
  segundo monitor, lida de relance.
- Execuções de horas, muitas vezes à noite; a fila para quando precisa de decisão humana.
- Convive com o painel do terminal (`orq attach`), que lê os mesmos arquivos do run dir.
- Conteúdo é markdown escrito por modelos: plano, decisões, report, journal.

## Capabilities and Constraints

- Entrega 1: leitura (fila, plano, report, linha do tempo ao vivo, "desde a última visita").
- Entrega 2: ação (responder decisão, instrução por tarefa ou para a fila via operador, com confirmação).
- Entrega 3: rascunho encadeado de planos com revalidação e aprovação com prazo.
- Sem login, sem acesso de fora da máquina. Sem dependência de rede em tempo de uso.
- Vocabulário do orq, em pt-BR: tarefa, fila, ciclo, plano, conselho, execução, verificação, revisão,
  takeover, harness.

## Evidence on Hand

Execuções reais em `~/.local/state/orq/runs.jsonl`; fila de exemplo com o harness `fake` em
`orq/tests/test_engine.py`; eventos de exemplo em `orq/tests/fixtures/events.jsonl`.

## Product Principles

1. O que pede ação do dono vem primeiro; operação fica em segundo plano.
2. A tela nunca afirma mais que os arquivos do run dir.
3. Toda mudança de rumo é proposta e confirmada antes de valer.
4. O que serve ao terminal continua servindo: a web não vira fonte de verdade.

## Accessibility & Inclusion

O dono é daltônico (vermelho-verde): estado nunca é comunicado só por cor, e vermelho contra verde nunca separa
dois estados. Ícone, forma e palavra sempre. Tem TDAH: informação mais importante primeiro, pouco texto por
bloco. Respeitar `prefers-reduced-motion`.
