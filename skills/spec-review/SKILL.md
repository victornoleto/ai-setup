---
name: spec-review
description: Confere se o diff desde um ponto fixo entrega o que a spec pediu (o que falta, o que sobra, o que está errado). Complementa o /code-review, que caça bug.
disable-model-invocation: true
---

# spec-review

Revisa um diff contra a **spec** que o originou: issue, plano ou card. Responde uma pergunta só: o
código faz o que foi pedido? Bug de correção é do `/code-review`; reuso e simplificação, do
`/simplify`.

Eixo Spec do `code-review` do [mattpocock/skills](https://github.com/mattpocock/skills), adaptado
às fontes de spec daqui.

## Entrada

`$ARGUMENTS`: o ponto fixo (SHA, branch, tag, `HEAD~5`) e, opcional, o caminho da spec. Sem ponto
fixo, use a branch principal (`git symbolic-ref --short refs/remotes/origin/HEAD`, ou `main`/`master`);
se você já está nela, pergunte.

## 1. Fixar o diff

```sh
git rev-parse --verify <ponto>
git diff --stat <ponto>...HEAD
git log --oneline <ponto>..HEAD
```

Três pontos no diff: a comparação é contra o merge-base. Mudança fora de commit não entra; se
`git status --short` mostrar alguma, avise no relatório.

**Pronto quando:** a referência resolve e o diff não está vazio. Ref inválida ou diff vazio: pare
aqui com o erro.

## 2. Achar a spec

Pare na primeira fonte que existir:

1. O caminho passado em `$ARGUMENTS`.
2. Issue citada nos commits (`#123`, `Closes #45`): `gh issue view <n> --comments`.
3. Spec ou plano versionado: arquivo sob algum `docs/` (`specs/`, `plans/`, `superpowers/`) cujo
   nome bate com a branch ou com o escopo dos commits (`feat(memory-ui)` → `*memory-ui*`).
4. Pasta de atividade do orq: `plan.md`, `notion.md` e as tarefas em `orq/`.
5. Nada disso: pergunte ao Victor onde está. Sem spec, este eixo não tem o que revisar: diga isso e
   pare.

Duas fontes candidatas no mesmo degrau: pergunte qual vale.

**Pronto quando:** você tem o texto da spec e sabe qual fonte usou.

## 3. Revisar

Rode a revisão num subagent quando o harness tiver: contexto limpo, sem a memória de quem escreveu
o código. Sem subagent, rode nesta sessão. O prompt leva os comandos do passo 1, o caminho (ou o
texto) da spec, e este pedido:

> Enumere os requisitos da spec, numerados. Cada um termina **atendido**, **faltando** (ausente ou
> pela metade) ou **errado** (implementado de um jeito que contradiz a spec). Depois liste o que
> está **sobrando**: comportamento no diff que nenhum requisito pede. Teste, migração e ajuste que
> um requisito exige contam como parte dele. Leia o código além do diff quando o diff não bastar
> para decidir. Cada achado leva `arquivo:linha`, a linha da spec citada e o porquê, em uma frase.
> Requisito atendido entra só na contagem. Até 400 palavras.

**Pronto quando:** todo requisito da spec tem veredito.

## 4. Relatar

```
Spec: <fonte>
Diff: <ponto>...HEAD, <n> commits
Cobertura: <N> requisitos: <a> atendidos, <f> faltando, <e> errados; <s> sobrando

### Faltando
### Errado
### Sobrando
```

Seção vazia sai. Termine com o achado mais grave e a próxima ação. A skill acaba no relatório;
corrigir é outro pedido do Victor.
