---
name: orq-setup
description: Monta a fila do orq para uma atividade — lê a pasta de contexto (card do Notion, spec, plano), tira as dúvidas com o Victor e escreve <pasta>/orq/ com tarefas pequenas, regras e config. Use quando o `orq new` abrir a sessão, ou quando pedirem para criar, revisar ou dividir uma fila do orq.
---

# orq-setup — montar a fila do orq

O `orq` roda uma fila de tarefas sem supervisão: para cada tarefa, uma **sessão nova** planeja, outra executa e
commita, o planejador revisa, e dúvidas vão a um conselho de agentes. Nenhuma sessão vê esta conversa. Tudo o que
elas sabem é o arquivo da tarefa, as regras da fila e o bloco de progresso (o que já foi feito e o que falta).

Você recebe:

- `<atividade>`: a pasta com o contexto;
- `<fila>` = `<atividade>/orq/`: o destino, já com `orq.toml` e `regras.md` copiados dos modelos do ai-setup.

## 1. Ler

1. Tudo em `<atividade>` fora de `orq/`: `notion.md`, `video-transcript.md`, `plan.md`, `questions.md`, specs e
   anotações. Se houver `plan.md` (o fluxo de card do Notion gera um), as tarefas saem dele.
2. As instruções do repositório: `.ai/README.md`, `CLAUDE.md`/`AGENTS.md` e o que eles mandam ler.
3. O estado: `git branch --show-current`, `git status`, `git log --oneline -15`, e se o repositório tem TODO,
   journal ou doc que as tarefas precisam atualizar.

## 2. Perguntar

Só o que a pasta e o repositório não respondem e que muda o resultado. **Uma pergunta por vez**, com opções
numeradas e a sua recomendação primeiro. Nesta ordem, e só o que faltar:

1. **Escopo**: o que entra e o que fica de fora desta fila.
2. **Branch** e se a fila pode criar branch, fazer squash ou merge.
3. **Proibições** além do `git push` (já bloqueado): banco compartilhado, comando destrutivo, serviço externo.
4. **Verificação**: quais testes, lint e build valem, e se suítes longas estão liberadas.
5. **Registro**: onde cada tarefa anota o que fez (TODO, journal, doc).
6. **Harness e modelos**: pergunte só se o Victor quer mudar o padrão (mostre o padrão do `orq.toml` global).

## 3. Dividir para conquistar

Regra da fila: **muitas tarefas pequenas, não uma grande**. Cada uma:

- é **uma sessão**: de 20 a 90 min de trabalho de agente, com um entregável e poucos commits;
- é **autossuficiente**: o texto diz o que fazer, onde está o detalhe (arquivo e seção; aponte, não copie) e o
  critério de **"Pronto quando"**. Nunca "continue de onde parou";
- **não depende de decisão** que só sai no meio de outra; se depender, a anterior registra a decisão num arquivo
  e esta manda ler esse arquivo;
- tem **verificação própria**: os comandos que provam que ficou pronta.

Ordene por dependência. A primeira tarefa costuma ser a fundação (modelo, migração, contrato). A última, se fizer
sentido, é o fecho (documentação, revisão geral, squash, se o Victor liberou).

Quando a spec já tem seções com "Pronto quando", a tarefa pode ser uma linha: "Execute a seção 4 de
`docs/x.md`, e só ela, até o 'Pronto quando' dela." Mais que ~6.000 caracteres numa tarefa é sinal de que ela
devia ser duas.

## 4. Escrever

Em `<fila>`:

- `NN-slug.md`, uma por tarefa (`01-`, `02-`…, na ordem de execução), em pt-BR, como um prompt de sessão;
- `regras.md`: preencha o modelo (troque os `<…>`, apague o que não se aplica) com o que vale para **toda**
  tarefa: branch, proibições, verificação, registro;
- `orq.toml`: só o que difere do global (harness e modelo por papel, conta, `on_fail`).

Mostre ao Victor a lista final (número, título, "pronto quando" em uma linha) e ajuste até ele aprovar.

## 5. Conferir

Rode `orq check <atividade>` e corrija o que ele apontar. Termine dizendo o comando para rodar:
`orq run <atividade>` (painel), ou `orq run <atividade> --headless`.
