---
name: orq web
description: A tela de quem valida uma fila de agentes — neutra, calma, direta.
colors:
  ink: "oklch(0.145 0 0)"
  paper: "oklch(1 0 0)"
  page: "oklch(0.985 0 0)"
  mist: "oklch(0.97 0 0)"
  selected: "oklch(0.935 0 0)"
  hairline: "oklch(0.922 0 0)"
  quiet-text: "oklch(0.556 0 0)"
  ring: "oklch(0.708 0 0)"
  primary: "oklch(0.205 0 0)"
  on-primary: "oklch(0.985 0 0)"
  running-bg: "oklch(0.95 0.035 255)"
  running-text: "oklch(0.33 0.11 262)"
  running-border: "oklch(0.82 0.07 255)"
  waiting-bg: "oklch(0.965 0.06 88)"
  waiting-text: "oklch(0.34 0.07 70)"
  waiting-border: "oklch(0.8 0.14 82)"
typography:
  headline:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1.45rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.88rem"
    fontWeight: 500
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.9rem"
    lineHeight: 1.55
rounded:
  control: "4px"
  base: "6px"
  card: "8px"
spacing:
  queue-gap: "4px"
  inline: "8px"
  gutter: "16px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 14px"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 14px"
  button-outline-hover:
    backgroundColor: "{colors.mist}"
  button-small:
    rounded: "{rounded.control}"
    height: "28px"
    padding: "0 10px"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.card}"
  badge:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "26px"
    padding: "0 10px"
  queue-item:
    rounded: "{rounded.control}"
    padding: "8px 10px"
  queue-item-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.ink}"
  queue-item-running:
    backgroundColor: "{colors.running-bg}"
    textColor: "{colors.running-text}"
  queue-item-waiting:
    backgroundColor: "{colors.waiting-bg}"
    textColor: "{colors.waiting-text}"
  tab-selected:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "28px"
    padding: "0 12px"
  instruction-bar:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.card}"
    padding: "9px"
---

# Design System: orq web

Fonte normativa dos valores: `orq/web/src/app.css` (tema claro acima; o tema escuro redefine os mesmos tokens em
`[data-theme=dark]`).

## Overview

**Creative North Star: "A mesa de quem valida"**

A tela é a bancada de quem confere o trabalho dos agentes. O dono chega, olha, e em uma tela sabe se precisa
agir. O que pede decisão dele vem à frente; o que é operação fica quieto ao redor. Nada na tela existe para
impressionar: ela existe para ser lida em um a três minutos e largada de novo.

O tom é neutro, calmo e direto. A base é a identidade do shadcn/ui em cinzas sem matiz, com borda fina e quase
nenhuma sombra. Pouco texto por bloco, a informação mais importante primeiro. A cor é rara de propósito: só dois
estados a recebem, e por isso eles saltam.

Os componentes são contidos e precisos: raio pequeno, contorno de um pixel, sem efeito. Um estado é sempre dito
por fundo mais claro ou mais escuro e por uma palavra, nunca só por cor: o dono é daltônico.

**Key Characteristics:**
- Uma tela inteira, sem rolagem de página: cartões de altura total que rolam por dentro.
- Neutro por padrão; azul só para "em execução", âmbar só para "espera você".
- Estado em palavra e em fundo, nunca só em cor; vermelho contra verde não existe.
- Tema claro e escuro com os mesmos papéis.
- Toda mudança de rumo é proposta e confirmada antes de valer.

## Colors

Cinzas sem matiz do shadcn/ui, mais dois estados com cor.

### Primary
- **Tinta** (`oklch(0.205 0 0)`): botão principal, etapa ativa do trilho, seleção de texto. No tema escuro vira
  quase branco (`oklch(0.922 0 0)`).

### Secondary
- **Azul de execução** (fundo `oklch(0.95 0.035 255)`, texto `oklch(0.33 0.11 262)`): a tarefa que está rodando,
  na fila e na etiqueta de estado. Em nenhum outro lugar.
- **Âmbar de espera** (fundo `oklch(0.965 0.06 88)`, texto `oklch(0.34 0.07 70)`): a pergunta que espera o dono,
  a tarefa parada por ela e a etiqueta "esperando você".

### Neutral
- **Papel** (`oklch(1 0 0)`): fundo dos cartões, da barra e dos botões de contorno.
- **Página** (`oklch(0.985 0 0)`): fundo atrás dos cartões.
- **Névoa** (`oklch(0.97 0 0)`): hover, trilho das abas, blocos de código.
- **Selecionado** (`oklch(0.935 0 0)`): item da fila selecionado, etiqueta de estado, opção escolhida.
- **Fio** (`oklch(0.922 0 0)`): bordas e divisórias.
- **Texto quieto** (`oklch(0.556 0 0)`): segunda linha, horários, tarefa concluída.
- **Tinta de texto** (`oklch(0.145 0 0)`): texto principal.

### Named Rules
**A Regra das Duas Cores.** Só "em execução" e "espera você" têm matiz. Qualquer outro estado é cinza mais
palavra. Um terceiro estado colorido precisa tirar um desses dois.

**A Regra da Palavra.** Todo estado aparece escrito. Fundo e cor reforçam; nunca são o único canal. Vermelho e
verde nunca separam dois estados.

## Typography

**Body Font:** IBM Plex Sans (com system-ui, sans-serif)
**Label/Mono Font:** IBM Plex Mono (com ui-monospace, monospace)

**Character:** Uma família só, técnica sem ser fria. A mono entra apenas onde o conteúdo é literal: código,
caminhos de arquivo, comandos propostos, log ao vivo.

A base é `14px` no `html`; os tamanhos abaixo são relativos a ela.

### Hierarchy
- **Headline** (600, 1.45rem, 1.2): título da tarefa selecionada. Um por tela.
- **Title** (600, 1rem): cabeçalho de cartão e títulos dentro do markdown.
- **Body** (400, 1rem, 1.65): plano, relatório, linha do tempo. Largura máxima de 70ch no markdown.
- **Label** (500, 0.86 a 0.93rem): etiquetas, abas, botões pequenos, segunda linha da fila.
- **Mono** (400, 0.86 a 0.9rem, 1.55): código, arquivos, comandos, atividade ao vivo.

### Named Rules
**A Regra do Peso Parado.** Selecionar, passar o mouse ou mudar de estado nunca muda peso nem tamanho de texto:
o texto não pode se mexer. Números usam `tabular-nums`.

## Layout

Aplicação de altura total: barra (52px), trilho das etapas (44px) e a área de colunas, sem rolagem de página.
Três colunas: Fila (272px) · Tarefa (flexível) · Atividade (352px). A partir de 1700px de largura, a coluna do
meio se divide em duas e o cartão "Entrega e como validar" fica ao lado das abas; Fila e Atividade passam a 288px
e 368px. Espaço de 16px entre cartões e nas margens; 4px entre itens da fila; 8px entre controles vizinhos.

Cada cartão rola por dentro. A barra de instrução fica sob a coluna do meio e cresce com o texto. Na coluna da
direita, pergunta aberta e propostas do operador empilham sobre a Atividade, cada uma com no máximo 40% da altura.

## Elevation & Depth

Plano. A profundidade vem de camadas de cinza (página, papel, névoa) e da borda de um pixel. A única sombra é
ambiente e quase invisível.

### Shadow Vocabulary
- **Fio de sombra** (`box-shadow: 0 1px 2px 0 oklch(0 0 0 / .05)`): cartões, botões de contorno, aba ativa.
- **Anel de foco** (`box-shadow: 0 0 0 3px` de `ring` a 50%): foco pelo teclado, em qualquer controle.

### Named Rules
**A Regra do Plano.** Nada flutua. Não há sombra de elevação, brilho nem desfoque; hover troca o fundo.

## Shapes

Raio pequeno em três degraus: 4px nos controles (botão, aba, item da fila, etiqueta), 6px na base, 8px nos
cartões e na barra de instrução. Borda de 1px em `fio`. Círculo só nos marcadores do trilho de etapas. Borda
tracejada marca exclusivamente tarefa com problema.

## Components

### Buttons
- **Shape:** raio de 4px, altura de 36px (28px na variante pequena), peso 500.
- **Primary:** fundo tinta, texto claro. É a ação recomendada ou a confirmação.
- **Outline:** fundo papel, borda de 1px, fio de sombra. Hover troca o fundo para névoa.
- **Hover / Focus:** hover muda só o fundo; foco usa o anel de 3px.
- **Em lista de opções:** altura automática e quebra de linha; a recomendada é a primary e diz "(recomendada)".

### Chips
- **Etiqueta de estado:** 26px de altura, 10px de cada lado, fundo `selecionado`, sem borda, texto escuro. Em
  execução e esperando você trocam o fundo pelo azul e pelo âmbar claros.
- **Abas:** pílulas de 28px sobre trilho névoa; a ativa tem fundo papel e fio de sombra.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** papel sobre página.
- **Shadow Strategy:** fio de sombra.
- **Border:** 1px em fio.
- **Internal Padding:** 16px; cabeçalho 14px 16px 10px.
- **Cartão de pergunta:** fundo, texto e borda âmbar; opções como botões empilhados.

### Inputs / Fields
- **Barra de instrução:** cartão de 8px com botão de alvo (Tarefa NN ⇄ Fila inteira), área de texto sem borda que
  cresce até 140px e botão de envio quadrado de 32px. A resposta do motor aparece numa linha acima, com ícone e
  a palavra "ok" ou "recusado".
- **Editor de tarefa e de plano:** área de texto em mono, borda de 1px, raio de 4px.
- **Focus:** a barra inteira recebe o anel.

### Navigation
- **Barra do topo:** marca, fila, contagem, relógio, previsão, custo, etiqueta de estado; controles da execução e
  o alternador de tema à direita.
- **Trilho de etapas:** cinco marcadores circulares de 22px ligados por linha de 1px; concluída com ícone de
  visto, ativa em tinta e pulsando (parado com `prefers-reduced-motion`).

### Item da fila (componente de assinatura)
Duas linhas: número e título; embaixo, a palavra do estado. Sem ícone. Concluída em texto quieto; em execução
com fundo azul claro; esperando você com fundo âmbar claro; selecionada com fundo `selecionado`, sem borda e sem
mudar o peso do texto; com problema, borda tracejada e estado em maiúsculas.

## Do's and Don'ts

### Do:
- **Do** escrever o estado em palavra em todo lugar onde ele aparece.
- **Do** marcar seleção por fundo (`oklch(0.935 0 0)` no claro), sem borda.
- **Do** manter todos os cartões terminando na mesma linha de base; a página nunca rola.
- **Do** pedir confirmação na própria linha antes de trocar decisão ou parar a execução.
- **Do** usar o mesmo raio dos controles (4px) em etiquetas e botões.

### Don't:
- **Don't** separar dois estados por vermelho contra verde, nem por cor sozinha.
- **Don't** usar contorno escuro ou anel para marcar o item selecionado.
- **Don't** mudar peso ou tamanho de texto em seleção ou hover.
- **Don't** dar matiz a um terceiro estado: azul e âmbar já estão ocupados.
- **Don't** usar etiqueta em pílula totalmente arredondada com borda.
