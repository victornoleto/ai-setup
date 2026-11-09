# Skills: comportamento numa fonte só

Comportamento mora no `GLOBAL.md` e em [`skills/`](../skills/), não em plugin. Plugin só existe em parte das
ferramentas e injeta texto em toda sessão; skill vale nas cinco e só entra no contexto quando o modelo decide
carregar (a descrição dela fica no contexto; o corpo, só quando usada).

Onde cada ferramenta acha as skills: Claude em `~/.claude/skills`, Codex e OpenCode em `~/.agents/skills`,
agy pelo `~/.gemini/config/skills.json`, Kiro em `~/.kiro/skills` (ele não lê `~/.agents/skills`). Uma fonte em `skills/`, um link por diretório, criados pelo
`install.sh` a partir do `adapters/MANIFEST`.

## As skills deste repositório

**Nossas:**

| Skill | Para quê |
|---|---|
| `orq-setup` | monta a fila do [orq](orq.md) para uma atividade; é a sessão que o `orq new` abre |
| `entrega` | relatório de leitura fácil do que uma branch, um commit ou um intervalo entregou, conferido contra o código (`bin/entrega-verifica`) |
| `handoff` | `/handoff`: o handoff mais detalhado da sessão, impresso, copiado para o clipboard e salvo em `local/handoffs/`, para colar numa sessão nova quando o contexto passar de ~50% |
| `spec-review` | `/spec-review <ponto>`: confere o diff contra a issue, o plano ou o card que o pediu (o que falta, sobra ou está errado); complementa o `/code-review`, que caça bug |

**Copiadas de fora** (origem, versão e edições locais em [`skills/UPSTREAM.md`](../skills/UPSTREAM.md)):

| Skill | Origem | Observação |
|---|---|---|
| brainstorming, systematic-debugging, writing-plans, test-driven-development, verification-before-completion, receiving-code-review | [superpowers](https://github.com/obra/superpowers) | a seção "Skills" do `GLOBAL.md` diz quando carregar cada uma |
| security-audit | [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) | *guidance mode* por padrão; auditoria completa só quando pedida |
| impeccable | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | uma variante por harness: `impeccable` (agents) e `impeccable-claude` |
| writing-for-agents, wizard, retro, grill-me | [mattpocock/skills](https://github.com/mattpocock/skills) | `retro` e `grill-me` só por comando; `/grill-me` entrevista em rodadas até fechar um plano, sem escrever arquivo |
| diagram-design | [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | |

**Pessoais** ficam no seu `sync/skills/`, com uma linha no `sync/MANIFEST` (ver
[instrucoes.md](instrucoes.md#manifest-como-cada-arquivo-chega-ao-lugar)). Assim uma skill da empresa ou de um
projeto seu não vai para este repositório público.

## Trocar plugin por skill

O que foi feito aqui, e dá para repetir:

1. **Meça o uso antes de decidir.** No Claude, as skills invocadas nos últimos 45 dias:

   ```sh
   find ~/.claude/projects -name '*.jsonl' -mtime -45 | xargs grep -ohE '"skill":"[^"]+"' \
     | sort | uniq -c | sort -rn | head -20
   ```

2. **Copie as skills que você realmente usa** (respeitando a licença) para `skills/` e desinstale o plugin.
3. **Compense o que a injeção do plugin fazia** com linhas de roteamento no `GLOBAL.md`: ~300 B em vez de
   3 KB. Teste: peça "quero adicionar o recurso X" e confira no transcript que a primeira chamada de
   ferramenta foi a skill.
4. **Anote a dívida.** `skills/UPSTREAM.md` guarda origem, versão, data e as edições locais (referências
   cruzadas a skills que você não copiou viram texto). O `doctor.sh` avisa quando a cópia passa de 90 dias.

Resultado aqui: o contexto fixo por sessão do Claude caiu de ~18 KB para ~9 KB.

**Plugins que ficam no Claude:** só `commit-commands`. Saíram, por repetirem o que já existe: `superpowers`
(skills copiadas), `frontend-design` (`impeccable`), `code-review` e `code-simplifier` (`/code-review` e
`/simplify` nativos), `claude-md-management` (regra mora no `GLOBAL.md`, fato no ai-memory) e
`security-guidance` (`security-audit` cobre nas cinco ferramentas). O `doctor.sh` acusa se algum voltar a
ligar.

## Pegadinhas

- **agy não aceita `~` no `skills.json`**, apesar da documentação: o caminho tem que ser absoluto (o erro só
  aparece em `~/.gemini/antigravity-cli/log/`). Aqui ele é `copy` com `@HOME@`.
- **Skill de terceiro instalada por fora** (um `npx skills add`, por exemplo) costuma cair como cópia em
  `~/.claude/skills`. O `doctor.sh` acusa (`skill copiada`): mova a cópia real para `~/.agents/skills` e
  deixe um link em `~/.claude/skills`.
