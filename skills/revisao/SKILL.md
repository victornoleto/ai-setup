---
name: revisao
description: Roteiro de validação de um diff (branch, commit ou intervalo) em uma tela — por onde começar a ler, o que mudou de comportamento e o que ficou sem teste. Use quando pedirem para revisar, validar ou conferir o que a IA escreveu
---

## Revisão

O leitor não escreveu o código: ele valida. A saída é um **roteiro de validação** que cabe em uma tela
e responde, nesta ordem: está certo confiar? por onde começo a ler? o que testo à mão?

A `entrega` apresenta a mudança a outra pessoa; esta skill aponta onde ela pode estar errada.

### Entrada

`$ARGUMENTS`: vazio (branch atual contra a base), uma branch, um commit, `-N` (os N últimos commits) ou
`a..b`. Base: `develop`, senão `master`, senão `main`; `--base=<ref>` troca.

## Passo 1 — Medir

```bash
git log --oneline <base>..<head>
git diff --numstat <base>..<head>
```

Feito quando você tem commits, arquivos e linhas. Intervalo vazio ou acima de 60 arquivos: pergunte se
o alvo está certo e pare.

## Passo 2 — Classificar cada arquivo por risco

Leia o diff de todo arquivo alterado e dê a cada um uma classe:

| Classe | Entra aqui |
|---|---|
| **alto** | autenticação, permissão, dinheiro, migration, apagar ou sobrescrever dado, concorrência, entrada externa sem validação, contrato público (rota, schema, evento) |
| **médio** | regra de negócio, consulta, tratamento de erro, configuração de ambiente |
| **baixo** | texto, estilo, renomeação, teste, documentação, arquivo gerado |

Feito quando todo arquivo do `--numstat` tem classe.

## Passo 3 — Procurar o que quebra

Em cada arquivo **alto** e **médio**, procure e anote com `arquivo:linha`:

- comportamento que mudou para quem usa o sistema;
- caminho de erro ou borda sem tratamento (vazio, nulo, duplicado, sem permissão);
- código alterado sem teste que o exercite: confira com `git diff --stat <base>..<head> -- '*test*' '*spec*'`
  e lendo o teste, pelo que ele afirma;
- mudança fora do que os commits dizem fazer.

Rode a suíte do projeto quando ela leva menos de 2 minutos; acima disso, diga o comando e pergunte.

Feito quando cada arquivo alto e médio tem um veredito: nada a apontar, ou os achados.

## Passo 4 — Escrever o roteiro

Na resposta, neste formato, com no máximo 25 linhas:

~~~markdown
**Veredito:** <pode aprovar | aprovar depois de N conferências | não aprovar: motivo> · N commits, N arquivos, +A −R

**Leia nesta ordem** (máx. 5)
1. `caminho:linha` — por que este primeiro, em uma frase

**Mudou de comportamento** (máx. 5)
- o que o usuário passa a ver ou deixa de ver

**Sem teste** (máx. 3)
- `caminho:linha` — o que ficou descoberto

**Teste à mão** (máx. 3)
1. o que fazer e o que deve acontecer

Baixo risco, só passar o olho: N arquivos (<tipos>).
~~~

Seção sem item sai com "nada". Suíte: uma linha, só se falhou ou não rodou. Cor nunca é o sinal: use
a palavra (alto, médio, baixo).

O que passar das 25 linhas vai para `docs/.local/revisoes/YYYY-MM-DD-<slug>.md`, e a resposta fecha com
o caminho.

$ARGUMENTS
