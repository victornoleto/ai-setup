# ~/.ai-setup

As instruções que valem em toda sessão de agente, e a fiação que as leva a cada ferramenta.
Quatro ferramentas usam isto: **Claude Code**, **Codex**, **OpenCode** e **Antigravity CLI** (`agy`).

**A memória de longo prazo não mora mais aqui.** Desde 2026-09-16 ela é do
[ai-memory](https://github.com/akitaonrails/ai-memory), servidor em Docker nesta máquina. O
acervo antigo (136 memórias) foi importado nele; o estado anterior está na tag `pre-ai-memory`
e em `~/backups-ai-setup/`.

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
4. Subir o ai-memory e ligar cada ferramenta (ver abaixo).
5. `sh doctor.sh` até sair sem FALHA.

### Ligar o ai-memory

Wrapper do CLI: seguir o *Quick start → Docker* do README do ai-memory (baixa
`~/.local/bin/ai-memory` conferindo o sha256). Depois:

```sh
# Servidor. As chaves ficam em ~/.config/ai-memory/server.env (chmod 600, fora de qualquer repo):
#   AI_MEMORY_LLM_PROVIDER=openai-compat
#   AI_MEMORY_LLM_BASE_URL=https://openrouter.ai/api/v1
#   AI_MEMORY_LLM_MODEL=z-ai/glm-5.3-flash
#   AI_MEMORY_LLM_REASONING_EFFORT=low
#   AI_MEMORY_EMBEDDING_PROVIDER=local
#   AI_MEMORY_RERANKER=llm
#   LLM_API_KEY=<chave da OpenRouter>
docker run -d --name ai-memory --restart unless-stopped \
  -p 127.0.0.1:49374:49374 -v ai-memory-data:/data \
  --env-file ~/.config/ai-memory/server.env docker.io/akitaonrails/ai-memory:latest

# Hooks e MCP, por ferramenta. Rodar a partir de ~, nunca de dentro de um repositório.
for a in claude-code codex open-code antigravity-cli; do
  ai-memory install-hooks --agent $a --project-strategy repo-root --apply
done
ai-memory install-mcp --client claude-code --apply
ai-memory install-mcp --client codex --apply
ai-memory install-mcp --client open-code --apply --config-file ~/.ai-setup/adapters/opencode/opencode.jsonc
ai-memory install-mcp --client antigravity-cli --apply

# Bloco de instruções, sempre no arquivo real (nunca no symlink):
ai-memory install-instructions --compact --skills-scope global --skills-agent claude-code \
  --target ~/.ai-setup/adapters/claude/CLAUDE.md
for t in codex opencode; do
  ai-memory install-instructions --compact --skills-scope global --skills-agent agents \
    --target ~/.ai-setup/adapters/$t/AGENTS.md
done
```

Projeto cujo nome não é o basename da raiz, ou raiz que não é repositório git, precisa de
`.ai-memory.toml` com `workspace = "default"` e `project = "<nome>"`. Em repositório de time,
excluir localmente: `echo .ai-memory.toml >> .git/info/exclude`.

`REASONING_EFFORT` tem que ser `low`, nunca `none`: o `glm-5.3-flash` exige raciocínio e a
OpenRouter recusa a chamada com 400. O `llm-test` não pega isso, porque não manda o parâmetro — a
falha só aparece no log do servidor, e o servidor degrada em silêncio (reranker mantém a ordem,
consolidação cai para o resumo por regra).

O reranker custa uma chamada ao LLM por `memory_query` (mediana 2,4 s). Medido em 30 perguntas
parafraseadas sobre o acervo: a memória certa em 1º lugar passou de 15 para 26, sem piorar
nenhuma. Sem ele, o multiplicador de autoridade por `kind` (fixo no código: `rule` +0,15,
`fact` 0) derruba notas `fact` que casam melhor.

Nunca exporte `AI_MEMORY_SERVER_URL` no shell: o wrapper roda em container com `--network host`,
e a variável faz o CLI responder `local spool` em vez de erro.

Validar: `ai-memory audit-contamination` limpo e, depois de qualquer `memory_query`,
`docker logs ai-memory 2>&1 | grep -iE 'provider error|reranker failed'` vazio. O `llm-test` sozinho
não serve de prova — ele passou com a configuração quebrada.

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

## GitHub

Agentes acessam o GitHub pelo `gh`, não por MCP. O token fica no keyring do sistema
(`gh auth login`), um login serve a todas as ferramentas, e nenhum segredo fica em arquivo de
config — o MCP do GitHub exigia um PAT no header, e cada instalador que tocava o config gravava
uma cópia dele num `.bak`. Removido em 2026-09-16 do Claude Code e do Codex (incluindo o plugin
`github@openai-curated`, que embute o mesmo MCP); o PAT foi revogado.

O controle do que o agente pode fazer passa a ser a permissão de Bash de cada ferramenta: leitura
(`gh pr view`, `gh issue list`, `gh run view`) liberada; `gh pr merge`, `gh repo delete` e
`gh api -X POST/PATCH/DELETE` pedindo aprovação.
