# ~/.ai-setup

As instruções que valem em toda sessão de agente, e a fiação que as leva a cada ferramenta.
Quatro ferramentas usam isto: **Claude Code**, **Codex**, **OpenCode** e **Antigravity CLI** (`agy`).

**A memória de longo prazo não mora mais aqui.** Desde 2026-09-16 ela é do
[ai-memory](https://github.com/akitaonrails/ai-memory), servidor em Docker nesta máquina. O
procedimento e as decisões da migração estão em
`~/Documents/notas/ia/migrar-ai-setup-para-ai-memory.md`.

## Instrução contra memória

A regra que separa o que fica aqui do que foi para o ai-memory:

- **Instrução** vale todo turno, sem ninguém consultar. Mora num arquivo carregado pela própria
  ferramenta: `GLOBAL.md` e `machine.md`.
- **Memória** é recuperada sob demanda, por busca, e o agente a trata como evidência histórica
  não-confiável — nunca como ordem. Mora no ai-memory.

Regra posta no acervo de memória é ignorada por desenho. Fato posto no arquivo de instrução
ocupa contexto em toda sessão de todo projeto. Por isso `GLOBAL.md` fica curto.

## As três gavetas

| Gaveta | O que é | Como viaja |
|---|---|---|
| `sync/` | `GLOBAL.md` e um `machine/<host>.md` por máquina | fora do git; sincronização entre máquinas a definir |
| `adapters/`, `*.sh` | a fiação: como cada ferramenta acha as instruções | git |
| `local/` | estado desta máquina | não viaja |

O teste para saber a gaveta: se copiar para outra máquina e virar **mentira lá**, é `local/`.
É o que impede a máquina do trabalho de afirmar que tem uma GPU Acer Predator: `machine/pc.md`
fica em `sync/`, mas **qual deles vale** é decidido por `local/machine.md`, um symlink.

## Mapa

```
~/.ai-setup/
├── install.sh             põe cada arquivo no lugar (idempotente)
├── doctor.sh              confere tudo, não conserta nada
├── adapters/
│   ├── MANIFEST           o que é symlink, o que é cópia, e para onde
│   ├── claude/            CLAUDE.md, settings.json
│   ├── codex/             AGENTS.md, hooks/load-portable-memory.sh
│   └── opencode/          opencode.jsonc, AGENTS.md, package.json
├── sync/memory/
│   ├── GLOBAL.md          quem é o Victor, em qualquer máquina
│   └── machine/pc.md      o que só vale nesta máquina
└── local/
    └── machine.md         symlink para machine/<esta máquina>.md
```

## Como cada ferramenta recebe as instruções

Nenhuma depende de o modelo lembrar de ler nada: cada uma usa o mecanismo nativo que tem.

| | Mecanismo | Por quê este |
|---|---|---|
| Claude Code | `@import` no `CLAUDE.md` | nativo |
| Codex | hook `SessionStart` que imprime os dois arquivos | não tem `@import` nem lista de instruções: o hook é a única via |
| OpenCode | lista `instructions` no `opencode.jsonc` | nativo |
| Antigravity | `~/.gemini/GEMINI.md` → `GLOBAL.md`, `~/.gemini/AGENTS.md` → `machine.md` | lê exatamente esses dois arquivos globais, medido; `context.fileName` com lista maior não surte efeito |

A ligação com o ai-memory (hooks de captura, MCP, bloco `<!-- ai-memory:start -->` nos
`AGENTS.md`/`CLAUDE.md`) é instalada pelo próprio `ai-memory install-*`, não por este
repositório. Ao atualizar o ai-memory, `ai-memory install-instructions` refaz o bloco.

## Os scripts

**`install.sh`** lê o `adapters/MANIFEST` e põe cada arquivo onde a ferramenta procura. Modo
`link` cria symlink. Modo `copy` copia, porque a ferramenta reescreve o arquivo sozinha e um
symlink sumiria na primeira reescrita. Arquivo real no caminho vira `<nome>.pre-ai-setup`.

**`doctor.sh`** só verifica: symlinks, cópias iguais à referência, `machine.md` resolvendo,
container do ai-memory healthy, e que a memória nativa do Claude Code e do Codex continua
**desligada** — se uma religar, voltam a existir dois acervos.

## Máquina nova

1. Clonar este repositório em `~/.ai-setup` e trazer o `sync/`.
2. `sh install.sh` — cria os symlinks e o `machine/<hostname>.md` em branco.
3. Preencher o `machine/<hostname>.md`.
4. Subir o ai-memory e ligar cada ferramenta — passos em
   `~/Documents/notas/ia/migrar-ai-setup-para-ai-memory.md`.
5. `sh doctor.sh` até sair sem FALHA.

## Pegadinhas

- **Nunca rode `ai-memory install-instructions` apontando para um symlink.** Ele grava com
  arquivo temporário + rename, e o rename troca o link por arquivo comum. O alvo é sempre o
  arquivo real em `adapters/`.
- **Rode `install-instructions` com `--skills-scope global`.** Sem isso, as Agent Skills caem
  em `$PWD/.claude/skills` — dentro do repositório onde você estiver.
- **`install-mcp --client open-code` recusa JSONC com comentário.** Mantenha o
  `opencode.jsonc` sem `//`.
- **OpenCode** carrega plugins quando a sessão é criada, não quando o servidor sobe.
- **Codex** pede confiança de novo sempre que um hook muda de hash.

## Pendências

- **`~/.codex/config.toml` está fora do repositório.** Tem um GitHub PAT em texto puro em
  `[mcp_servers.github.http_headers]`. Revogar o token em `github.com/settings/tokens`, trocar o
  bloco por `bearer_token_env_var = "GITHUB_MCP_TOKEN"` e então descomentar a linha
  `copy codex/config.toml` no `MANIFEST`.
