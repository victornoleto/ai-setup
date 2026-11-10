# Catálogo: o que o ai-setup tem e o que não tem

Uma página para responder "o ai-setup tem X?". Como as skills chegam a cada ferramenta está em
[skills.md](skills.md); versão e edições locais das copiadas, em [`skills/UPSTREAM.md`](../skills/UPSTREAM.md).
Skills pessoais ou de empresa ficam no `sync/` de cada um e não aparecem aqui.

**Como uma skill entra no contexto** (coluna "Entra"):

- **roteada:** uma linha da seção "Skills" do `GLOBAL.md` manda carregar (ver [instrucoes.md](instrucoes.md));
- **por descrição:** o modelo carrega quando o pedido bate com a descrição da skill;
- **só por comando:** tem `disable-model-invocation`, então só entra com `/nome`.

## O que tem

### Skills

| Skill | Origem | Para quê | Entra |
|---|---|---|---|
| `orq-setup` | nossa | monta a fila do [orq](orq.md) para uma atividade; é a sessão que o `orq new` abre | por descrição |
| `entrega` | nossa | relatório de leitura fácil do que uma branch, um commit ou um intervalo entregou, conferido contra o código (`bin/entrega-verifica`) | por descrição |
| `handoff` | nossa | o handoff mais detalhado da sessão, impresso, copiado para o clipboard e salvo em `local/handoffs/`, para colar numa sessão nova quando o contexto passar de ~50% | só por comando |
| `spec-review` | nossa | `/spec-review <ponto>`: confere o diff contra a issue, o plano ou o card que o pediu; complementa o `/code-review`, que caça bug | só por comando |
| `brainstorming` | [superpowers](https://github.com/obra/superpowers) | desenho aprovado antes de feature ou mudança não trivial | roteada |
| `systematic-debugging` | superpowers | causa raiz antes de corrigir bug ou teste falhando | roteada |
| `writing-plans` | superpowers | plano em passos, depois do desenho aprovado | roteada |
| `test-driven-development` | superpowers | teste falhando antes da implementação | roteada |
| `verification-before-completion` | superpowers | prova rodada antes de dizer "pronto" ou "passando" | roteada |
| `receiving-code-review` | superpowers | avaliar o review antes de aplicar, sem concordar por reflexo | roteada |
| `security-audit` | [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) | *guidance mode* por padrão; auditoria completa só quando pedida | roteada |
| `impeccable`, `impeccable-claude` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | desenho, revisão e polimento de frontend; uma variante por harness (`impeccable` nos agents, `impeccable-claude` no Claude) | por descrição |
| `writing-for-agents` | [mattpocock/skills](https://github.com/mattpocock/skills) | escrever skill, `AGENTS.md` e `CLAUDE.md` | por descrição |
| `wizard` | mattpocock/skills | gera um wizard em bash para os passos que só o humano faz (credencial, painel de terceiro, migração) | por descrição |
| `retro` | mattpocock/skills | retrospectiva da sessão | só por comando |
| `grill-me` | mattpocock/skills | `/grill-me` entrevista em rodadas até fechar um plano, sem escrever arquivo (traz o corpo do `grilling`) | só por comando |
| `diagram-design` | [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | diagramas de arquitetura, fluxo, sequência, ER e gráficos em HTML/SVG/PNG | por descrição |
| `playwright-cli` | vem dentro da CLI do Playwright | automação de browser pelo shell; acompanha a versão da CLI (ver [skills.md](skills.md)) | por descrição |

### Regras absorvidas no `GLOBAL.md`

Não são skills: viraram linhas do `GLOBAL.md`, que carrega em todo turno. O seu fica no `sync/`;
[instrucoes.md](instrucoes.md) mostra a divisão.

| De | Virou |
|---|---|
| [ponytail](https://github.com/DietrichGebert/ponytail) | a "escada do mínimo" da seção Código: precisa existir? a stdlib faz? a plataforma já tem? uma dependência instalada resolve? Só então escreva |
| [i-have-adhd](https://github.com/ayghri/i-have-adhd) | as regras de resposta para TDAH, em versão compacta |

## O que não tem

### Plugins do Claude que saíram

O único plugin ligado no Claude é o `commit-commands`. O `doctor.sh` acusa se algum destes voltar a ligar.

| Plugin | No lugar |
|---|---|
| superpowers | as seis skills copiadas, roteadas pelo `GLOBAL.md` em ~300 B (o plugin injetava ~3 KB em toda sessão) |
| frontend-design | `impeccable` |
| code-review | `/code-review`, nativo do Claude Code |
| code-simplifier | `/simplify`, nativo do Claude Code |
| claude-md-management | regra no `GLOBAL.md`, fato no ai-memory |
| security-guidance | `security-audit`, que vale nas cinco ferramentas (o plugin só existia no Claude) |
| playwright (MCP) | `playwright-cli` pelo shell: o MCP despeja cada snapshot no contexto |
| ponytail | a escada do mínimo, no `GLOBAL.md` |

### Skills que ficaram no pacote de origem

Copiamos só o que usamos, com o uso medido antes ([skills.md](skills.md#trocar-plugin-por-skill)).

**superpowers** (6.4.2: 15 skills, 6 copiadas)

| Skill | Por que não |
|---|---|
| using-superpowers | é a injeção do plugin em toda sessão; a seção "Skills" do `GLOBAL.md` faz o papel dela |
| diagnosing-superpowers | diagnostica o próprio plugin; sem plugin, não tem o que diagnosticar |
| writing-skills | `writing-for-agents` cobre |
| requesting-code-review | `/code-review` (nativo) caça bug; `spec-review` confere contra a spec |
| executing-plans, subagent-driven-development, dispatching-parallel-agents | o orq executa plano com revisão e conselho; fora dele, o `GLOBAL.md` limita a 2 subagents em paralelo |
| using-git-worktrees, finishing-a-development-branch | branch, merge e push ficam com você; commit pelo plugin `commit-commands` |

**mattpocock/skills** (40 skills, 4 copiadas). As que se sobrepõem a algo daqui:

| Skill | No lugar |
|---|---|
| handoff, claude-handoff | `handoff` e os handoffs do ai-memory |
| code-review | `/code-review` (nativo) e `spec-review` |
| tdd | `test-driven-development` |
| diagnosing-bugs | `systematic-debugging` |
| grilling | o corpo dela entrou no `grill-me` |

O resto é fluxo que não usamos aqui: [lista no repositório](https://github.com/mattpocock/skills/tree/main/skills).

**impeccable, cloudflare/security-audit-skill e diagram-design** têm uma skill cada, e ela está aqui. Do
impeccable ficou de fora o plugin, que põe hook em toda edição e só existe no Claude; o detector liga por projeto
com `/impeccable hooks on`.

## Manter atualizado

Skill nova em `skills/` ganha uma linha em "O que tem"; plugin removido, uma em "Plugins do Claude que saíram". O
`doctor.sh` avisa quando uma pasta de `skills/` não aparece nesta página.
