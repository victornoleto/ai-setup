# Memória persistente + harnesses afinados

Como montar, numa máquina nova, o mesmo arranjo que roda aqui: **um acervo de memória que
atravessa ferramentas** (ai-memory) e **uma fonte única de instrução e comportamento** para
Claude Code, Codex, OpenCode e Antigravity CLI (`agy`).

Versão em página, para compartilhar com quem não tem acesso a este repositório:
<https://claude.ai/artifact/QbnTHv9wRfH21xP8n7u9P8> (o fonte dela é `docs/tutorial.html`; ao
editar este arquivo, atualize os dois).

Os dois pedaços são independentes. O ai-memory funciona sem este repositório, e este repositório
funciona sem o ai-memory. Juntos, a conta fecha assim:

| | Responsável | O que é |
|---|---|---|
| **ai-memory** | acervo | o que já aconteceu: decisões, pegadinhas, handoffs. Buscado sob demanda, tratado como **evidência não-confiável** |
| **ai-setup** (este repo) | configuração | o que vale sempre: instrução, skills, permissões, plugins, modelo |

A regra que decide onde cada coisa mora: **regra vai para instrução, história vai para memória.**
Regra escrita no acervo é ignorada por desenho — o agente recebe memória como dado, nunca como
ordem. Fato de projeto escrito na instrução custa contexto em toda sessão de todo projeto.

Tempo: ~40 min para a parte 1, ~30 min para a parte 2.

---

# Parte 1 — ai-memory

Servidor em Docker na própria máquina, um acervo só, quatro ferramentas escrevendo e lendo nele.

## 1.1 Antes de começar

- Docker, `jq` e `git`.
- Pelo menos um harness instalado (Claude Code, Codex, OpenCode ou `agy`).
- Uma chave de LLM. Aqui é OpenRouter com `z-ai/glm-5.3-flash`: o servidor usa o LLM para
  consolidar sessões e para reordenar resultados de busca.

## 1.2 O CLI

Siga o **Quick start → Docker** do [README do ai-memory](https://github.com/akitaonrails/ai-memory):
ele baixa o wrapper para `~/.local/bin/ai-memory` conferindo o sha256. O wrapper fala com o
servidor em container.

> **Nunca exporte `AI_MEMORY_SERVER_URL` no shell.** O wrapper roda o container com
> `--network host`; com a variável setada, o CLI responde `local spool` em vez de erro, e você
> demora a perceber que estava escrevendo num lugar que ninguém lê.

## 1.3 O servidor

As chaves ficam fora de qualquer repositório, em `~/.config/ai-memory/server.env`, com
`chmod 600`:

```sh
AI_MEMORY_LLM_PROVIDER=openai-compat
AI_MEMORY_LLM_BASE_URL=https://openrouter.ai/api/v1
AI_MEMORY_LLM_MODEL=z-ai/glm-5.3-flash
AI_MEMORY_LLM_REASONING_EFFORT=low
AI_MEMORY_EMBEDDING_PROVIDER=local
AI_MEMORY_RERANKER=llm
LLM_API_KEY=<sua chave>
```

```sh
docker run -d --name ai-memory --restart unless-stopped \
  -p 127.0.0.1:49374:49374 -v ai-memory-data:/data \
  --env-file ~/.config/ai-memory/server.env docker.io/akitaonrails/ai-memory:latest
```

Duas escolhas que custaram caro para descobrir:

- **`REASONING_EFFORT=low`, nunca `none`.** O `glm-5.3-flash` exige raciocínio e a OpenRouter
  recusa com 400. Pior: **o servidor degrada em silêncio** — o reranker mantém a ordem original
  e a consolidação cai para um resumo por regra. O `llm-test` passa mesmo assim, porque não manda
  esse parâmetro. A falha só aparece em `docker logs`.
- **`AI_MEMORY_RERANKER=llm` vale a pena.** Medido aqui em 30 perguntas parafraseadas sobre um
  acervo de 136 notas: a memória certa em 1º lugar passou de 15 para 26, sem piorar nenhuma.
  Custa uma chamada por busca (mediana 2,4 s). Sem ele, o multiplicador de autoridade por tipo
  (`rule` +0,15, `fact` 0, fixo no código) enterra notas `fact` que casam melhor com a pergunta.

## 1.4 Ligar cada ferramenta

Três pontas por ferramenta: **hooks** (captura), **MCP** (consulta) e **instrução de uso**.
Rode **a partir de `~`**, nunca de dentro de um repositório:

```sh
for a in claude-code codex open-code antigravity-cli; do
  ai-memory install-hooks --agent $a --project-strategy repo-root --apply
done

ai-memory install-mcp --client claude-code --apply
ai-memory install-mcp --client codex --apply
ai-memory install-mcp --client open-code --apply --config-file ~/.config/opencode/opencode.jsonc
ai-memory install-mcp --client antigravity-cli --apply

ai-memory install-instructions --compact --skills-scope global --skills-agent claude-code \
  --target ~/.claude/CLAUDE.md
ai-memory install-instructions --compact --skills-scope global --skills-agent agents \
  --target ~/.codex/AGENTS.md
ai-memory install-instructions --compact --skills-scope global --skills-agent agents \
  --target ~/.config/opencode/AGENTS.md
```

Quatro pegadinhas dos instaladores:

1. **`--skills-scope global` sempre.** Sem isso, as Agent Skills caem em `$PWD/.claude/skills` —
   dentro do repositório onde você estiver.
2. **`install-instructions` nunca aponta para symlink.** Ele grava com arquivo temporário +
   rename, e o rename troca o link por arquivo comum. Se você versiona os arquivos de instrução
   (parte 2), aponte para o arquivo real.
3. **`install-mcp --client open-code` recusa JSONC com comentário.** Deixe o `opencode.jsonc`
   sem `//`.
4. **O agy não recebe o bloco de instruções.** Ele lê exatamente dois arquivos globais
   (`~/.gemini/GEMINI.md` e `~/.gemini/AGENTS.md`), e as instruções do próprio servidor MCP já
   cobrem escopo e dado não-confiável.

## 1.5 Desligar a memória nativa dos harnesses

Senão você fica com dois acervos, e o que a outra ferramenta não enxerga some do mapa.

- **Claude Code**, em `~/.claude/settings.json`: `"autoMemoryEnabled": false`.
- **Codex**, em `~/.codex/config.toml`: `[features]` com `memories = false`.

## 1.6 Dizer a que projeto cada diretório pertence

O projeto é o nome da raiz do repositório. Quando o nome não serve, ou a raiz não é um
repositório git, ponha um marcador `.ai-memory.toml` na raiz:

```toml
workspace = "default"
project = "nome-do-projeto"
```

A busca do marcador sobe até `$HOME`. Em repositório de time, exclua localmente:
`echo .ai-memory.toml >> .git/info/exclude`.

## 1.7 Validar (não pule)

```sh
ai-memory status                 # container de pé, contagem de páginas e sessões
ai-memory audit-contamination    # nenhuma sessão no projeto errado
docker logs ai-memory 2>&1 | grep -iE 'provider error|reranker failed'   # vazio
```

Depois, o teste que realmente prova o arranjo: **abra uma ferramenta, peça um handoff, abra
outra e veja se ela recebe.** Handoff é consumido uma vez só; encadear A → B → C funciona se cada
sessão escrever o seu.

## 1.8 Pegadinhas que só aparecem com o tempo

- **Codex só roda hook aprovado, e a aprovação é por posição.** Mexer no `hooks.json` renumera as
  entradas e derruba a confiança de todas, em silêncio; em `codex exec` elas viram `Failed`.
  Reaprovar em `codex` → `/hooks`. Aqui isso manteve o Codex sem captura e sem as instruções
  globais por dias.
- **Mantenha os hooks num arquivo só.** O Codex aceita `hooks.json` e `config.toml`, e avisa
  quando você usa os dois.
- **`agy -p` (modo print) não manda o diretório**, e a sessão cai num projeto `scratch`. Para
  testar o agy, use o modo interativo.
- **OpenCode carrega plugin quando a sessão é criada**, não quando o servidor sobe.
- Sessão de teste suja o acervo: `ai-memory purge-session --session-id <uuid> --confirm`.

---

# Parte 2 — ai-setup

O que sobra depois que a memória sai: instrução, skills, permissões, plugins, modelo. A ideia é
que **cada coisa tenha um dono só** e que um script diga quando algo saiu do lugar.

## 2.1 As três gavetas

```
~/.ai-setup/
├── install.sh          põe cada arquivo onde a ferramenta procura (idempotente)
├── doctor.sh           confere tudo, não conserta nada
├── adapters/MANIFEST   o que é symlink, o que é cópia, e para onde
├── adapters/           claude/, codex/, opencode/, antigravity/
├── skills/             skills nossas, uma fonte, um link por harness
├── sync/memory/        GLOBAL.md + machine/<host>.md   (fora do git)
└── local/machine.md    symlink para o machine/<esta máquina>.md
```

O teste da gaveta: se copiar para outra máquina e virar **mentira lá**, é `local/`. É o que
impede a máquina do trabalho de afirmar que tem a GPU da máquina de casa.

## 2.2 Como a instrução chega em cada ferramenta

Nenhuma depende de o modelo lembrar de ler algo: cada uma usa o mecanismo nativo que tem.

| | Mecanismo |
|---|---|
| Claude Code | `@import` no `CLAUDE.md` |
| Codex | hook `SessionStart` que imprime os dois arquivos (não tem import nem lista) |
| OpenCode | lista `instructions` no `opencode.jsonc` |
| agy | `~/.gemini/GEMINI.md` e `~/.gemini/AGENTS.md`, que ele lê sempre |

O `MANIFEST` tem uma linha por arquivo, com o modo:

```
link    claude/CLAUDE.md        .claude/CLAUDE.md
copy    claude/settings.json    .claude/settings.json
```

**`link`** quando só você edita o arquivo. **`copy`** quando a ferramenta reescreve sozinha
(`/config`, aprovação de hook, instalação de plugin): um symlink sumiria na primeira reescrita, e
aí a cópia no repositório vira referência — o `doctor.sh` acusa a diferença e você decide qual
lado vale.

## 2.3 Instalar numa máquina nova

```sh
git clone <seu-fork> ~/.ai-setup
# traga o sync/ (ele fica fora do git: contém o GLOBAL.md e um arquivo por máquina)
sh ~/.ai-setup/install.sh      # cria os links e um machine/<hostname>.md em branco
$EDITOR ~/.ai-setup/sync/memory/machine/$(hostname).md
sh ~/.ai-setup/doctor.sh       # até sair sem FALHA
```

## 2.4 O que escrever no GLOBAL.md

Ele carrega em **todo turno de toda sessão de toda ferramenta**, então cada linha paga aluguel.
Aqui ele tem 3,9 KB e cinco seções:

1. **Como trabalhar com você.** Aqui: daltonismo (verificação nunca depende de cor) e as regras
   de saída para TDAH, na versão compacta do [i-have-adhd](https://github.com/ayghri/i-have-adhd).
2. **Código.** A "escada do mínimo" do [ponytail](https://github.com/DietrichGebert/ponytail) em
   seis linhas: precisa existir? a stdlib faz? a plataforma já tem? uma dependência já instalada
   resolve? Só então escreva.
3. **Skills.** Quatro linhas de roteamento: feature → `brainstorming`, bug →
   `systematic-debugging`, trabalho em vários passos → `writing-plans`, implementação com teste →
   `test-driven-development`.
4. **Ferramentas.** Decisões que valem em qualquer projeto: browser pelo `playwright-cli` e não
   por MCP, GitHub pelo `gh` e não por MCP, limite de subagents em paralelo.
5. O resto é do `machine.md`: como o root funciona nesta máquina, onde mora a documentação dela.

## 2.5 Comportamento: skill em vez de plugin

Plugin bom existe só em parte das ferramentas e injeta texto em toda sessão. Skill vale nas
quatro e só entra no contexto quando o modelo decide carregar.

O que foi feito aqui, e dá para repetir:

1. **Meça o uso antes de decidir.** No Claude, as skills invocadas nos últimos 45 dias:

   ```sh
   find ~/.claude/projects -name '*.jsonl' -mtime -45 | xargs grep -ohE '"skill":"[^"]+"' \
     | sort | uniq -c | sort -rn | head -20
   ```

2. **Copie as skills que você realmente usa** (respeitando a licença) para `skills/` e desinstale
   o plugin. Aqui foram quatro do [superpowers](https://github.com/obra/superpowers), que valiam
   só no Claude e no Codex e passaram a valer nas quatro ferramentas.
3. **Compense o que a injeção do plugin fazia** com as quatro linhas de roteamento do
   `GLOBAL.md`. Custa ~300 B em vez de 3 KB. Teste: peça "quero adicionar o recurso X" e confira
   no transcript que a primeira chamada de ferramenta foi a skill.
4. **Anote a dívida.** `skills/UPSTREAM.md` guarda origem, versão, data e as edições locais
   (referências cruzadas a skills que você não copiou precisam virar texto). O `doctor.sh` avisa
   quando a cópia passa de 90 dias.

Onde cada ferramenta procura skill: Claude em `~/.claude/skills`, Codex e OpenCode em
`~/.agents/skills`, agy pelo `~/.gemini/config/skills.json` — que **não aceita `~`**, apesar da
documentação dizer que sim; use caminho absoluto. Uma fonte, um link por diretório.

## 2.6 Permissões

Depois de tirar o MCP do GitHub (o token ficava em texto puro no header, e cada instalador que
tocava o config gravava uma cópia num `.bak`), o controle virou permissão de shell:

| | Onde | Leitura do `gh` | Escrita do `gh` |
|---|---|---|---|
| Claude | `permissions` no `settings.json` | `allow` | `ask` em `pr merge`, `repo delete`, `api` com `-X`/`--method` |
| Codex | `~/.codex/rules/default.rules` | `prefix_rule … allow` | `prompt` (regra por prefixo não enxerga flag no meio: `gh api` pede sempre) |
| OpenCode | `permission.bash` no `opencode.jsonc` | `allow` | `ask` |

Negue também a leitura dos arquivos de credencial (`~/.claude/.credentials.json`,
`~/.codex/auth.json`, `~/.gemini/oauth_creds.json`, o `server.env` do ai-memory). A regra vale
para a ferramenta de leitura do agente, não para um `cat` no shell — não é sandbox, é rede de
proteção contra o acidente comum.

E revise a confiança do Codex: `trust_level = "trusted"` em `/home` faz todo diretório da máquina
herdar confiança.

## 2.7 O `doctor.sh`

É o que segura o arranjo ao longo do tempo. As 47 verificações de hoje, por tema:

- **Fiação:** cada symlink aponta para o repositório; cada `copy` bate com a referência;
  `machine.md` resolve.
- **ai-memory:** container healthy; as três pontas (hooks, MCP, instrução) presentes nas quatro
  ferramentas; memória nativa do Claude e do Codex desligada; `AI_MEMORY_SERVER_URL` não setada.
- **Núcleo:** nenhuma skill duplicada; plugins substituídos continuam desligados; Codex sem
  confiança em `/home`; quantos hooks do Codex estão aprovados; tamanho do `GLOBAL.md`; idade das
  skills copiadas.
- **Segurança:** nenhum token em texto puro nos configs; `gh` autenticado; `bwrap` conseguindo
  criar user namespace (sem isso o sandbox do Codex fica inerte — no Ubuntu 24.04 é preciso um
  perfil AppArmor, que está em `adapters/codex/apparmor/`).

Rode depois de **qualquer** `ai-memory install-*`: o instalador grava no arquivo vivo e o
`doctor.sh` vai apontar a diferença para você aceitar no repositório com um `cp` e um commit.

## 2.8 A fronteira entre os dois

Os dois sistemas mexem nos mesmos arquivos, então a divisão é por **trecho**, não por arquivo:

| Trecho | Dono |
|---|---|
| Entradas de hook com `ai-memory/hooks/`, servidor MCP `ai-memory`, bloco `<!-- ai-memory:start -->`, skills `ai-memory-*` | ai-memory |
| Todo o resto: instrução, skills próprias, permissões, plugins, modelo | ai-setup |

Na dúvida sobre onde escrever algo:

- Vale todo turno, em qualquer projeto → `GLOBAL.md`.
- Vale todo turno, só nesta máquina → `machine.md`.
- Vale só neste projeto → `AGENTS.md`/`CLAUDE.md` do projeto.
- Aconteceu e pode ser útil lembrar → ai-memory.

---

## Resultado

- Uma memória só, que as quatro ferramentas escrevem e leem, com busca reordenada por LLM.
- Uma fonte só de comportamento, que chega às quatro do mesmo jeito.
- Contexto fixo por sessão do Claude caiu de ~18 KB para ~9 KB ao trocar plugin por skill.
- Um comando (`doctor.sh`) que diz se algo saiu do lugar, incluindo o que o instalador do
  ai-memory reescreveu por baixo.
