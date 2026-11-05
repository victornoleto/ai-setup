# Instruções: como cada agente sabe quem você é

O núcleo deste repositório: um lugar só para as instruções que valem em toda sessão, e a fiação que as leva às
cinco ferramentas (Claude Code, Codex, OpenCode, Antigravity CLI `agy` e Kiro CLI).

## Instrução contra memória

- **Instrução** vale todo turno, sem ninguém consultar. Mora num arquivo que a própria ferramenta carrega:
  `GLOBAL.md` e `machine.md`.
- **Memória** é recuperada sob demanda, por busca, e o agente a trata como evidência histórica não-confiável,
  nunca como ordem. Mora no [ai-memory](ai-memory.md).

Regra posta no acervo de memória é ignorada por desenho. Fato posto no arquivo de instrução ocupa contexto em
toda sessão de todo projeto. Por isso o `GLOBAL.md` fica curto. Na dúvida:

- Vale todo turno, em qualquer projeto → `GLOBAL.md`.
- Vale todo turno, só nesta máquina → `machine.md`.
- Vale só neste projeto → `AGENTS.md`/`CLAUDE.md` do projeto.
- Aconteceu e pode ser útil lembrar → ai-memory.

## As três gavetas

| Gaveta | O que é | Como viaja |
|---|---|---|
| `sync/` | o que é seu: `GLOBAL.md`, um `machine/<host>.md` por máquina, skills e arquivos pessoais, docs de trabalho | repositório git **privado** seu, clonado em `sync/` (este repositório o ignora) |
| `adapters/`, `*.sh`, `skills/` | a fiação e o comportamento, sem nada pessoal | este repositório |
| `local/` | estado desta máquina | não viaja |

O teste da gaveta: se copiar para outra máquina e virar **mentira lá**, é `local/`. É o que impede a máquina do
trabalho de afirmar que tem a GPU da máquina de casa: os dois `machine/<host>.md` ficam no `sync/`, mas **qual
vale** é decidido por `local/machine.md`, um symlink que o `install.sh` cria pelo hostname.

## Como cada ferramenta recebe as instruções

Nenhuma depende de o modelo lembrar de ler algo: cada uma usa o mecanismo nativo que tem.

| | Mecanismo | Por quê este |
|---|---|---|
| Claude Code | `@import` no `CLAUDE.md` (com `~`) | nativo |
| Codex | hook `SessionStart` (em `~/.codex/hooks.json`) que imprime os dois arquivos | não tem `@import` nem lista de instruções |
| OpenCode | lista `instructions` no `opencode.jsonc` | nativo |
| agy | `~/.gemini/GEMINI.md` → `GLOBAL.md`, `~/.gemini/AGENTS.md` → `machine.md` | lê exatamente esses dois arquivos globais (medido; `context.fileName` com lista maior não surte efeito) |
| Kiro CLI | `~/.kiro/steering/{global,machine,ai-memory}.md` por link | lê todo `.md` do steering global, symlink inclusive (medido em 2026-11-05, 3.0.0) |

A ligação com o ai-memory (hooks, MCP, bloco `<!-- ai-memory:start -->`) é gravada pelo próprio
`ai-memory install-*`, não por este repositório: ver [ai-memory.md](ai-memory.md#9-quem-é-dono-de-quê).

## O que escrever no GLOBAL.md

Ele carrega em **todo turno de toda sessão de toda ferramenta**, então cada linha paga aluguel (o `doctor.sh`
avisa acima de 4 KB). Uma divisão que funciona:

1. **Como trabalhar com você.** Necessidades de leitura e de formato de resposta. Exemplo: verificação que
   nunca depende de cor, regras de saída para TDAH (versão compacta do
   [i-have-adhd](https://github.com/ayghri/i-have-adhd)).
2. **Código.** A "escada do mínimo" do [ponytail](https://github.com/DietrichGebert/ponytail): precisa
   existir? a stdlib faz? a plataforma já tem? uma dependência já instalada resolve? Só então escreva.
3. **Skills.** Linhas de roteamento: feature → `brainstorming`, bug → `systematic-debugging`, vários passos →
   `writing-plans`, implementação → `test-driven-development` (ver [skills.md](skills.md)).
4. **Ferramentas.** Decisões que valem em qualquer projeto: browser pelo `playwright-cli`, GitHub pelo `gh`,
   limite de subagents em paralelo.
5. O resto é do `machine.md`: como o root funciona nesta máquina, onde mora a documentação dela.

## MANIFEST: como cada arquivo chega ao lugar

O [`adapters/MANIFEST`](../adapters/MANIFEST) tem uma linha por arquivo: modo, origem (relativa a `adapters/`)
e destino (relativo a `$HOME`).

```
link	claude/CLAUDE.md	.claude/CLAUDE.md
copy	claude/settings.json	.claude/settings.json
```

- **`link`** quando só você edita o arquivo: o destino é symlink para o repositório.
- **`copy`** quando a ferramenta reescreve sozinha (`/config`, aprovação de hook, instalação de plugin): um
  symlink sumiria na primeira reescrita. A cópia no repositório vira referência, e o `doctor.sh` acusa a
  diferença para você decidir qual lado vale.
- **`@HOME@`**: a referência nunca guarda caminho de usuário. O `install.sh` troca `@HOME@` pelo `$HOME` de
  quem instala, e o comando de aceitar que o `doctor.sh` imprime faz o inverso.

**O que é seu vai no `sync/MANIFEST`**, mesmo formato, origem relativa a `sync/`. Ele é lido antes do público,
e um destino repetido fica com a entrada pessoal. É assim que uma skill sua, uma unit do systemd ou um
`settings.json` diferente entram sem tocar neste repositório:

```
link	skills/slides	.claude/skills/slides
link	systemd/claude.slice	.config/systemd/user/claude.slice
```

Como criar o repositório privado, levar para outra máquina e trocar um arquivo público pelo seu:
[sync.md](sync.md).

## Os scripts

**`install.sh`** lê os dois MANIFESTs e põe cada arquivo no lugar. Idempotente. Arquivo real no caminho de um
link vira `<nome>.pre-ai-setup`. Também monta a conta 2 do Claude, se `~/.claude2` existir
([claude-code.md](claude-code.md)), e lembra das linhas que faltam no rc do shell.

**`doctor.sh`** só verifica, nunca conserta, e diz o comando que resolve:

- **Fiação:** cada link aponta para o repositório; cada `copy` bate com a referência; `machine.md` resolve;
  conta 2 com os links inteiros.
- **ai-memory:** container healthy; hooks, MCP e instrução presentes nas cinco ferramentas (o Kiro, só se `kiro-cli` estiver instalado); memória nativa do
  Claude e do Codex desligada.
- **Núcleo:** nenhuma skill duplicada; plugins substituídos continuam desligados; hooks do Codex aprovados;
  tamanho do `GLOBAL.md`; idade das skills copiadas.
- **Segurança:** nenhum token em texto puro nos configs; `gh` autenticado; sandbox do Codex funcionando
  ([seguranca.md](seguranca.md)).

Rode depois de qualquer `ai-memory install-*` e de qualquer mudança aqui. **`tests/test_install.sh`** roda o
`install.sh` numa cópia com `HOME` falso: rode antes de mexer no `install.sh` ou no `doctor.sh`.
