---
name: handoff
description: Gera o handoff mais detalhado possível da sessão atual (feito, pendente, decisões, estado), imprime na tela e copia para a área de transferência, para colar numa sessão nova e limpa sem perder contexto. Só quando o usuário chama /handoff.
disable-model-invocation: true
---

## Handoff

Escreve o documento que uma sessão **nova e sem contexto** lê para continuar este trabalho sem
ficar pior do que esta sessão. Depois imprime na tela e copia para o clipboard.

`$ARGUMENTS` (opcional): foco extra do usuário, por exemplo "ênfase no bug do webhook". Dê
mais espaço a isso; não corte o resto.

**Princípio.** Só vale preservar o que existe na conversa e **não** se reobtém com um comando
barato. Fato recuperável (diff, status, log) entra como *comando + resultado de agora*. O que
só existe na sessão — intenção, correções do usuário, decisões e seus porquês, becos sem
saída, hipóteses — entra por extenso. Densidade acima de brevidade: cada linha carrega um
fato; sem "etc.", sem "conforme discutido".

**As regras de saída do GLOBAL.md (TDAH: sem recapitulação, listas ≤ 5, só o diff) não valem
para o documento.** Valem só para a linha que fecha o turno.

---

## Passo 1 — Coletar o estado ao vivo

Rode, não lembre. Em paralelo:

```bash
pwd
git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD
git status --short
git diff --stat
git log --oneline -15
```

- Fora de repositório git, pule os comandos de git e diga isso no documento.
- Separe **o que esta sessão mudou** do que **já estava sujo** antes (o `gitStatus` do início
  da sessão é a referência). Na dúvida sobre um arquivo, marque `[inferido]`.
- Liste o que vive fora do repo: tarefas em background, servidor rodando, migração ou seed
  aplicado, variável de ambiente exportada, worktree, PR ou artefato publicado.
- Arquivo de plano desta sessão (`~/.claude/plans/*`), se houver: cite o caminho.
- Transcript desta sessão, para o agente novo consultar quando faltar detalhe (Claude Code):

```bash
ls -t ~/.claude/projects/"$(pwd | tr / -)"/*.jsonl | head -1
```

  O mais recente é o desta sessão. Em outra ferramenta, omita a linha.
- Para cada caminho que você vai citar: `test -e <caminho>`. Não cite o que não existe.

## Passo 2 — Reler a conversa inteira

Procure só o que é da conversa: pedidos literais do usuário, correções ("não faça X"),
mudanças de escopo, decisões com alternativas descartadas, erros e como foram resolvidos,
hipóteses testadas e refutadas, coisas que o usuário disse estar esperando ou ter aprovado.

## Passo 3 — Escrever no gabarito

Em pt-BR, Markdown, exatamente estas seções, na ordem. Seção sem conteúdo diz "nada" — não
some, para o agente novo saber que foi checada.

```
# Handoff — <projeto> — <AAAA-MM-DD HH:MM>

## 0. Cabeçalho
cwd, branch, HEAD, id/caminho do transcript, plano, tamanho aproximado da sessão

## 1. Como usar este handoff
(instruções ao agente novo — texto fixo abaixo)

## 2. Objetivo e pedidos
Meta em uma frase. Depois os pedidos do usuário LITERAIS, em ordem, com mudanças de escopo
marcadas ("→ depois o usuário mudou para …").

## 3. Instruções e preferências desta sessão
Correções, restrições e gostos do usuário que não estão em nenhum arquivo.

## 4. Decisões
Cada uma: o que, por quê, alternativas descartadas e por quê.

## 5. Feito
Por unidade de trabalho: o quê, `arquivo:linha`, como foi verificado (comando + resultado).

## 6. Estado do repositório
Saída dos comandos do passo 1. Mudanças desta sessão × pré-existentes. Commits feitos.
O que NÃO está commitado.

## 7. Pendente
Lista ordenada; cada item com critério de pronto.
**Próxima ação:** o primeiro passo, executável sozinho, que cabe em menos de 2 minutos.

## 8. Problemas abertos
Sintoma, o que foi tentado e descartado, hipótese atual, erro literal quando curto.

## 9. Descobertas e armadilhas
Fatos do código/ambiente que custaram caro; comandos que funcionam; onde as coisas moram.

## 10. Contexto a recarregar
Arquivos-chave a ler e por quê (mais barato que colar o conteúdo), skills a carregar,
consultas úteis ao ai-memory.

## 11. Fora do repositório
Processos em background, servidores, migrações/seeds aplicados, env vars, worktrees,
PRs/artefatos publicados.

## 12. Não fazer sem perguntar
Ações destrutivas, itens que aguardam aprovação do usuário.
```

**Texto fixo da § 1** (copie, ajustando só os números de seção se mudar algo):

> Você continua o trabalho de uma sessão anterior que acabou por falta de contexto, não por
> falta de progresso. Leia o documento inteiro antes de agir.
> 1. Rode os comandos da § 6 e confie neles acima do texto se divergirem — o texto é uma
>    fotografia de quando o handoff foi escrito.
> 2. Não refaça o que está na § 5. Não reabra o que está na § 4 sem um motivo novo.
> 3. Carregue as instruções do projeto (`.ai/README.md`, `CLAUDE.md`) e as skills da § 10.
> 4. Comece pela **Próxima ação** da § 7.
> 5. Se faltar um detalhe, faça `grep` no transcript do cabeçalho antes de perguntar ao
>    usuário.
> 6. Marcas: `[verificado]` foi checado por comando ou leitura; `[inferido]` é palpite
>    razoável — cheque antes de agir sobre ele.

Regras de escrita:

- Pedidos do usuário e mensagens de erro importantes: **verbatim**, entre aspas ou bloco.
- Caminhos relativos ao cwd; `arquivo:linha` quando aponta código.
- Separe `[verificado]` de `[inferido]` onde a diferença muda o que o agente novo faz.
- **Nenhum segredo**: token, senha, chave, cookie, conteúdo de `.env`. Redija (`<redigido>`).
- Não recapitule o que um comando da § 6 devolve; aponte o comando.

## Passo 4 — Autoverificação

Antes de emitir, confira e corrija:

1. Os pedidos do usuário estão literais e completos, incluindo as mudanças de escopo?
2. Toda decisão tem o porquê?
3. Todo pendente tem critério de pronto?
4. A **Próxima ação** é executável sozinha e cabe em menos de 2 minutos?
5. Todo caminho citado existe (passo 1)?
6. Há segredo no texto?
7. Uma sessão sem esta conversa entenderia cada frase? Troque "isso", "aquele arquivo",
   "o problema de antes" pelo nome.

## Passo 5 — Emitir

Numa única resposta:

1. **Imprima o handoff inteiro** na tela (o usuário lê e confere).
2. **Copie**, na mesma ação, pelo script, com o mesmo texto num heredoc de delimitador citado
   (o `'EOF'` impede que o shell expanda `$` e crases):

```bash
~/.ai-setup/bin/handoff-copia <<'EOF'
<o handoff, byte a byte igual ao impresso>
EOF
```

   Se o texto contiver uma linha `EOF`, troque o delimitador (`HANDOFF_FIM`).
3. **Feche com uma linha**: o resultado do script ("copiado: N linhas … arquivo: …") e
   "Cole na sessão nova (Ctrl+V)". Se o script falhar, diga o código de saída e o caminho do
   arquivo salvo; o texto já está na tela.

Não chame `memory_handoff_begin`: ele entregaria o baton a qualquer sessão futura do projeto,
relacionada ou não. O canal aqui é o clipboard.
