---
name: entrega
description: Gera um relatório de leitura fácil sobre o que uma branch, um commit ou um intervalo de commits entregou — prosa curta mais os trechos de código que importam, conferidos contra o código real
---

## Entrega

Escreve um documento que explica o que foi feito em um pedaço de histórico do
Git. O documento serve para duas coisas, nesta ordem:

1. Entender a mudança sem abrir o diff.
2. Apresentar a mudança a outra pessoa, lendo o arquivo em voz alta durante uma
   gravação de tela.

O texto não é o resumo do diff. O diff diz o que mudou; o documento diz o que o
sistema passou a fazer e por quê. Trecho de código entra quando é a explicação
mais curta — nunca como enfeite.

### Entrada

`$ARGUMENTS` aceita um alvo e duas opções.

| Forma | Alvo |
|---|---|
| (vazio) | branch atual contra a base |
| `feature/xyz` | branch inteira contra a base |
| `f18f86d4` | um commit |
| `-3` | os três últimos commits do `HEAD` |
| `a1b2c3..f4e5d6` | intervalo |

| Opção | Efeito |
|---|---|
| `--base=develop` | troca a base do cálculo |
| `--context=<caminho>` | arquivo ou pasta com a especificação da tarefa |

Base padrão: `develop`, se o repositório tiver. Senão `master`. Senão `main`.

---

## Passo 1 — Resolver o alvo

```bash
git rev-parse --abbrev-ref HEAD
git merge-base HEAD <base>
git log --oneline <base>..<head>
git diff --stat <base>..<head>
```

Confirme o alvo em uma linha antes de seguir: quantos commits, quantos arquivos,
quantas linhas. Se o intervalo vier vazio ou passar de 60 arquivos, pare e
pergunte se o alvo está certo.

## Passo 2 — Ler a especificação, quando houver

Sem `--context`, procure sozinho: `docs/.local/specs/**/*<slug-da-branch>*`. Achou
uma pasta só, use. Achou mais de uma, pergunte qual. Não achou, siga sem.

Numa pasta de tarefa, leia nesta ordem e pare quando tiver o suficiente:

| Arquivo | Serve para |
|---|---|
| `plan.md` | o que foi combinado, premissas, o que ficou fora de escopo |
| `notion.md` | o pedido original, na linguagem de quem pediu |
| `journal.md` | decisões tomadas durante a execução e o que surpreendeu |
| `questions.md` | o que continua sem resposta |
| `delivery.md` | resumo já escrito para quem assiste; não copie, complete |

**A especificação é evidência de intenção. O código é a verdade.** Nunca escreva
que algo foi entregue porque o plano listava a tarefa. Confira no diff. Item
planejado que não aparece no diff vira linha na seção *Pedido e entrega*.

## Passo 3 — Ler a mudança

```bash
git diff <base>..<head> -- <caminho>
git show <sha>:<caminho>
```

Leia o arquivo inteiro quando o diff não bastar para entender a peça. Separe o
que mudou em três baldes:

- **Comportamento novo** — o usuário vê diferença. É o corpo do documento.
- **Estrutura** — migration, enum, contrato, job, permissão. Vai para *Impacto*.
- **Ruído** — lint, import, espaço, renomear variável. Fica de fora.

## Passo 4 — Escolher os trechos

Um trecho por decisão que não é óbvia pelo nome do método. Entre 5 e 25 linhas.
Se a peça inteira importa e passa de 40 linhas, não cole: entre na tabela
*Arquivos grandes* com uma frase de função.

Máximo de 8 trechos no documento. Passou disso, o recorte está grosso demais.

## Passo 5 — Escrever

Destino: `docs/.local/entregas/YYYY-MM-DD-<slug>.md`, em pt-BR.

A data é a de hoje. O slug sai do nome da branch sem o prefixo (`feature/`,
`fix/`), ou da pasta de `--context`, ou do tema dos commits. Sempre minúsculo,
com hífen.

Crie a pasta se faltar. Depois confira que ela está fora do versionamento:

```bash
git check-ignore -q docs/.local/entregas && echo ignorado
```

Sem saída, avise o usuário em uma linha e siga.

## Passo 6 — Conferir os trechos

```bash
~/.ai-setup/bin/entrega-verifica docs/.local/entregas/<arquivo>.md
```

Saiu diferente de zero, corrija o documento e rode de novo. Não entregue com
divergência aberta.

## Passo 7 — Fechar

Diga o caminho do arquivo, quantos trechos conferiram e quanto tempo de leitura
em voz alta o documento tem, contando 130 palavras por minuto.

---

## Blocos de código

Todo bloco de código do documento abre com a âncora:

~~~
```php title="app/Actions/Analysis/GetMostUsed.php:23-41 @f18f86d"
~~~

O caminho é relativo à raiz do repositório. O intervalo são as linhas no arquivo
daquele commit. O `@` é o commit de onde o trecho saiu — em geral o `head` do
alvo.

Regras duras:

1. O conteúdo sai de `git show <sha>:<caminho> | sed -n '23,41p'`. Nunca da
   memória, nunca reescrito à mão.
2. Não reformate, não reindente, não renomeie nada dentro do bloco.
3. Não junte pedaços distantes do arquivo em um bloco só. Dois trechos são dois
   blocos.
4. Não corte o meio com `...`. Se o meio não importa, o recorte está errado.
5. Bloco sem âncora só para comando de terminal e saída de log.

## Estrutura do documento

~~~markdown
# <título curto do que foi entregue>

Branch `feature/xyz` · 7 commits · `a1b2c3..f4e5d6` · 2026-09-16

## O que mudou

Três a seis itens. Um por entrega que alguém percebe usando o sistema.
Cada item em uma frase. É o roteiro da gravação.

## Por quê

Um parágrafo por problema resolvido. O que doía antes, o que passa a
acontecer agora. Linguagem de negócio, sem nome de classe.

## Como funciona

Uma seção por peça. Cada uma abre com duas ou três frases de prosa, depois o
trecho de código que sustenta a explicação, depois uma frase sobre o que o
trecho decide. Título de seção diz a função da peça, não o nome do arquivo.

## Arquivos grandes

| Arquivo | O que faz |
|---|---|
| `app/Jobs/X.php` | uma frase |

Só os arquivos que importam inteiros e não cabem em trecho.

## Pedido e entrega

Só quando há `--context`. Três listas curtas: entregue como combinado,
mudou de rumo e por quê, ficou de fora e por quê. Premissa aberta e pergunta
sem resposta entram aqui.

## Impacto

Migration, variável de ambiente, fila nova, permissão nova, contrato que
mudou. O que o deploy precisa. Não há nada? Escreva "Nada. O deploy é o
padrão."

## Como verificar

Passos na tela, na ordem de gravar: entre nesta tela, clique nisto, repare
naquilo. Cada passo diz o que deve acontecer.
~~~

Seção sem conteúdo é escrita como vazia, com uma frase dizendo isso. Seção
ausente não prova que a checagem rodou.

## Como escrever

O leitor não implementou nada e vai ouvir o texto, não estudá-lo.

1. Frase de até 20 palavras. Parágrafo de até 6 frases, um assunto só.
2. Voz ativa e tempo simples. "O sistema sugere", não "passou a ser sugerido".
3. Sem pessoas. "A tela passa a mostrar", nunca "eu fiz" nem "foi pedido pelo
   Diego".
4. Termo técnico ganha definição de até 10 palavras na primeira vez. Não defina
   nome de produto nem sigla que o leitor usa todo dia.
5. Sem ponto e vírgula e sem travessão. Duas frases resolvem.
6. Sem palavra que não carrega fato: robusto, poderoso, simplesmente, de forma
   transparente, vale notar, é importante ressaltar.
7. Uma palavra, um sentido, no documento inteiro. Escolha entre detecção e
   ocorrência, e repita a escolhida.
8. Sem emoji, sem negrito de ênfase. Negrito só em rótulo de tabela.
9. Nada de "como citado acima" nem "conforme a seção anterior". Quem lê em voz
   alta não volta.
10. Cor nunca é o único sinal. "O marcador fica cheio", não "o marcador fica
    vermelho".

Antes de entregar, releia em voz alta a seção *O que mudou*. Tropeçou, corte a
frase em duas.

## O que nunca entra

- Nome de teste, saída de suíte, contagem de asserção.
- Diff colado, lista de arquivos alterados, estatística de linhas.
- Elogio ao próprio trabalho.
- Detalhe de implementação que não muda o que o sistema faz.

$ARGUMENTS
