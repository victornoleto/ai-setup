---
version: 1
slug: "web"
primary_target: "web"
related_targets: []
---

# Surface: orq web (painel de execução)

Modo: Operate. Público: dev que valida o trabalho de agentes; volta de tempos em tempos e também deixa a aba num
segundo monitor. Tarefa: saber em uma tela se precisa agir, ler plano e entrega, decidir.

## Direction contract

Direção fixada pelo usuário em rodadas de mockup (2026-11-12); o sorteio (seed 5141c46a) foi superado por ela.

THESIS: uma tela inteira sem rolagem de página, em cartões verticais que rolam por dentro; recusa o dashboard de
métricas e o log corrido.

OWN-WORLD: identidade do shadcn/ui (tokens neutros oklch, raio 0.375rem, borda fina, sombra mínima, abas em
pílula sobre fundo `muted`, botões primary e outline), temas claro e escuro alternáveis, IBM Plex Sans e Mono.
Só dois estados têm cor: azul para a tarefa em execução, âmbar para "espera você". Nunca vermelho contra verde.

STORY: o dono vê o que mudou desde a última visita, o que espera decisão dele e onde a fila está; lê o plano e
como validar a entrega.

FIRST VIEWPORT: barra com fila, contagem, relógio, previsão e custo; trilho linear das cinco etapas da tarefa em
curso com harness e modelo; colunas Fila (288px) · Tarefa em abas (e Entrega ao lado em ultrawide) · à direita o
cartão âmbar da decisão pendente e propostas do operador sobre o cartão Atividade. Barra de instrução sob a
coluna do meio.

FORM: aplicação de três a quatro colunas de altura total; direção fixada pelo usuário, seed 5141c46a.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Fechado

Fila sem ícone de estado: estado pelo fundo e pela palavra na segunda linha. Seleção por fundo cinza, sem borda e
sem mudar o peso do texto. Sistema visual documentado em `orq/DESIGN.md`.
