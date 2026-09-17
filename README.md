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
│   ├── opencode/          opencode.jsonc, AGENTS.md, package.json
│   └── antigravity/       skills.json (aponta o agy para ~/.agents/skills)
├── skills/                skills nossas, um link por harness (UPSTREAM.md: as copiadas)
├── bin/                   entrega-verifica (usado pela skill entrega)
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
| Codex | hook `SessionStart` (em `~/.codex/hooks.json`) que imprime os dois arquivos | não tem `@import` nem lista de instruções: o hook é a única via |
| OpenCode | lista `instructions` no `opencode.jsonc` | nativo |
| Antigravity | `~/.gemini/GEMINI.md` → `GLOBAL.md`, `~/.gemini/AGENTS.md` → `machine.md` | lê exatamente esses dois arquivos globais, medido; `context.fileName` com lista maior não surte efeito |

A ligação com o ai-memory (hooks de captura, MCP, bloco `<!-- ai-memory:start -->` nos
`AGENTS.md`/`CLAUDE.md`) é instalada pelo próprio `ai-memory install-*`, não por este
repositório. Ao atualizar o ai-memory, `ai-memory install-instructions` refaz o bloco.

## Comportamento: uma fonte só

Desde 2026-09-17, comportamento mora no `GLOBAL.md` e em `skills/`, não em plugin. Plugin só
existe no Claude e no Codex, e injeta texto em toda sessão; o `GLOBAL.md` e as skills chegam às
quatro ferramentas.

- **Regras de saída para TDAH** ([i-have-adhd](https://github.com/ayghri/i-have-adhd)) e a
  **escada do mínimo** ([ponytail](https://github.com/DietrichGebert/ponytail)): versões compactas
  no `GLOBAL.md`. Os plugins saíram.
- **brainstorming, systematic-debugging, writing-plans, test-driven-development**: copiadas do
  [superpowers](https://github.com/obra/superpowers) para `skills/`. A seção "Skills" do
  `GLOBAL.md` diz quando carregar cada uma. **Revisar a cada 90 dias** conforme
  `skills/UPSTREAM.md`; o `doctor.sh` avisa.
- **Plugins que ficam no Claude:** `security-guidance` (revisão de segurança) e `commit-commands`.

Onde cada ferramenta acha as skills: Claude em `~/.claude/skills`, Codex e OpenCode em
`~/.agents/skills`, agy pelo `~/.gemini/config/skills.json`. Skill de terceiro instalada por
fora (archify) tem a cópia real em `~/.agents/skills` e um link em `~/.claude/skills`.

## Quem é dono de quê

Os dois sistemas mexem nos mesmos arquivos de config, então a fronteira é por **trecho**, não por
arquivo. Regra: quem grava é o dono, e o outro só confere.

| Trecho | Dono | Como muda |
|---|---|---|
| Entradas de hook com `ai-memory/hooks/` | ai-memory | `ai-memory install-hooks --apply` |
| Servidor MCP `ai-memory` nos quatro configs | ai-memory | `ai-memory install-mcp --apply` |
| Bloco `<!-- ai-memory:start/end -->` nos adaptadores | ai-memory | `ai-memory install-instructions` (arquivo real) |
| Skills `ai-memory-*` e plugin `opencode/plugins/ai-memory.ts` | ai-memory | `install-instructions`/`install-hooks` |
| Todo o resto: `GLOBAL.md`, `machine.md`, `skills/`, permissões, plugins, modelo | ai-setup | editar em `~/.ai-setup` e `install.sh` |

Na prática:

1. **Depois de qualquer `ai-memory install-*`**: `sh doctor.sh`. O `settings.json` do Claude vai
   acusar diferença, porque o instalador grava no vivo. Aceite com `cp ~/.claude/settings.json
   adapters/claude/settings.json`, revise o diff e faça o commit. No Codex, aprove os hooks em
   `/hooks`.
2. **Regra de comportamento nunca vai para o ai-memory.** Memória chega ao agente como evidência
   não-confiável: regra posta lá é ignorada por desenho. Regra global vai no `GLOBAL.md`, regra
   de projeto no `AGENTS.md`/`CLAUDE.md` do projeto.
3. **Fato de projeto nunca vai para o `GLOBAL.md`.** Ele carrega em todo turno de todo projeto.
   Decisão, pegadinha e histórico vão para o ai-memory (a skill `ai-memory-durable-pages`, quando
   o Victor pedir para lembrar).
4. **O `doctor.sh` confere as três pontas do ai-memory em cada ferramenta**: hooks (captura), MCP
   (consulta) e instrução de uso. O agy não recebe o bloco: as instruções do servidor MCP fazem
   esse papel.

## Os scripts

**`install.sh`** lê o `adapters/MANIFEST` e põe cada arquivo onde a ferramenta procura. Modo
`link` cria symlink. Modo `copy` copia, porque a ferramenta reescreve o arquivo sozinha e um
symlink sumiria na primeira reescrita. Arquivo real no caminho vira `<nome>.pre-ai-setup`.

**`doctor.sh`** só verifica: symlinks, cópias iguais à referência, `machine.md` resolvendo,
container do ai-memory healthy, memória nativa do Claude Code e do Codex **desligada**, skills sem
cópia duplicada, plugins substituídos desligados, Codex sem confiança em `/home`, nenhum hook do
Orca, tamanho do `GLOBAL.md` e idade das skills copiadas.

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
- **Codex** pede confiança de novo sempre que um hook muda de hash **ou de posição**: tirar
  uma entrada do `hooks.json` renumera as seguintes e todas perdem a confiança. Aprovar em
  `codex` → `/hooks`. Hook desaprovado não roda em `codex exec` e aparece como `Failed`.
- **agy** não aceita `~` no `skills.json`, apesar da documentação: o caminho tem que ser absoluto
  (o erro só aparece em `~/.gemini/antigravity-cli/log/`).
- **`agy -p` (modo print) não manda `cwd` no hook**: a sessão cai no projeto `scratch` do
  ai-memory. Para testar o agy, use o modo interativo, ou apague depois com `ai-memory purge-session`.
- **O pacote `orca` do Ubuntu é o leitor de tela do GNOME.** O Orca IDE é o `orca-ide`.

## GitHub

Agentes acessam o GitHub pelo `gh`, não por MCP. O token fica no keyring do sistema
(`gh auth login`), um login serve a todas as ferramentas, e nenhum segredo fica em arquivo de
config — o MCP do GitHub exigia um PAT no header, e cada instalador que tocava o config gravava
uma cópia dele num `.bak`. Removido em 2026-09-16 do Claude Code e do Codex (incluindo o plugin
`github@openai-curated`, que embute o mesmo MCP); o PAT foi revogado.

O controle do que o agente pode fazer é a permissão de shell de cada ferramenta: leitura
(`gh pr view`, `gh issue list`, `gh run view`) liberada; `gh pr merge` e `gh repo delete` pedem
aprovação.

| | Onde | `gh api` |
|---|---|---|
| Claude | `permissions` no `adapters/claude/settings.json` | pede aprovação com `-X`, `--method`, `-f`, `-F` |
| Codex | `~/.codex/rules/default.rules` | pede sempre (regra por prefixo não enxerga flag no meio) |
| OpenCode | `permission.bash` no `opencode.jsonc` | pede sempre |

Arquivos de credencial (`~/.claude/.credentials.json`, `~/.codex/auth.json`,
`~/.gemini/oauth_creds.json`, `~/.config/ai-memory/server.env`) têm leitura negada no Claude e no
OpenCode. A regra vale para a ferramenta de leitura, não para `cat` no shell.
