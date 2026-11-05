# ai-memory: como ele está ligado aqui

O [ai-memory](https://github.com/akitaonrails/ai-memory) é um projeto de terceiros e tem documentação
própria: [README](https://github.com/akitaonrails/ai-memory#readme),
[instalação por agente](https://github.com/akitaonrails/ai-memory/blob/main/docs/install.md) e
[atualização](https://github.com/akitaonrails/ai-memory/blob/main/docs/install.md#keeping-ai-memory-up-to-date).
Este doc cobre só a **adequação**: as escolhas feitas para ele conviver com este repositório (servidor em
Docker com chaves fora de qualquer repo, cinco ferramentas, duas contas do Claude) e as pegadinhas que
apareceram no caminho.

Por que ele existe aqui: **regra vai para instrução, história vai para memória** (ver
[instrucoes.md](instrucoes.md)). O ai-memory guarda o que já aconteceu (decisões, pegadinhas, handoffs);
o agente busca sob demanda e trata o resultado como **evidência não-confiável**, nunca como ordem.

Versão em uso: **3.4.2** (servidor e cliente).

## 1. Antes de começar

- Docker, `jq` e `git`.
- Pelo menos um harness instalado (Claude Code, Codex, OpenCode, `agy` ou Kiro CLI).
- Uma chave de LLM. Aqui é OpenRouter com `z-ai/glm-5.3-flash`: o servidor usa o LLM para consolidar
  sessões e para reordenar resultados de busca. Sem chave, a busca por texto continua funcionando.

## 2. O CLI

Siga o **Quick start → Docker** do README oficial: ele baixa o wrapper para `~/.local/bin/ai-memory`
conferindo o sha256. O wrapper roda o binário em container, com o seu `$HOME` montado.

> **Nunca exporte `AI_MEMORY_SERVER_URL` no shell.** O wrapper roda o container com `--network host`; com a
> variável setada, o CLI responde `local spool` em vez de erro, e você demora a perceber que estava
> escrevendo num lugar que ninguém lê.

## 3. O servidor

As chaves ficam fora de qualquer repositório, em `~/.config/ai-memory/server.env`, com `chmod 600`:

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

- **`REASONING_EFFORT=low`, nunca `none`.** O `glm-5.3-flash` exige raciocínio e a OpenRouter recusa com
  400. Pior: **o servidor degrada em silêncio**: o reranker mantém a ordem original e a consolidação cai
  para um resumo por regra. O `llm-test` passa mesmo assim, porque não manda esse parâmetro. A falha só
  aparece em `docker logs`.
- **`AI_MEMORY_RERANKER=llm` vale a pena.** Medido em 30 perguntas parafraseadas sobre um acervo de 136
  notas: a memória certa em 1º lugar passou de 15 para 26, sem piorar nenhuma. Custa uma chamada por busca
  (mediana 2,4 s). Sem ele, o multiplicador de autoridade por tipo (`rule` +0,15, `fact` 0, fixo no código)
  enterra notas `fact` que casam melhor com a pergunta.

## 4. Ligar cada ferramenta

Três pontas por ferramenta: **hooks** (captura), **MCP** (consulta) e **instrução de uso**. Rode **a
partir de `~`**, nunca de dentro de um repositório:

```sh
for a in claude-code codex open-code antigravity-cli; do
  ai-memory install-hooks --agent $a --project-strategy repo-root --apply
done
# Kiro CLI, engine v3 (a padrão da 3.x; na engine v2 o agente é `kiro-cli`):
ai-memory install-hooks --agent kiro-cli-v3 --project-strategy repo-root --apply

ai-memory install-mcp --client claude-code --apply
ai-memory install-mcp --client codex --apply
ai-memory install-mcp --client open-code --apply --config-file ~/.config/opencode/opencode.jsonc
ai-memory install-mcp --client antigravity-cli --apply
ai-memory install-mcp --client kiro-cli --apply
# Só com a segunda conta do Claude (claude-code.md): o MCP mora no .claude.json, um por conta.
ai-memory install-mcp --client claude-code --apply --config-file ~/.claude2/.claude.json

# Bloco de instruções, sempre no arquivo real deste repositório (nunca no symlink):
ai-memory install-instructions --compact --skills-scope global --skills-agent claude-code \
  --target ~/.ai-setup/adapters/claude/CLAUDE.md
for t in codex opencode; do
  ai-memory install-instructions --compact --skills-scope global --skills-agent agents \
    --target ~/.ai-setup/adapters/$t/AGENTS.md
done
# Kiro: o bloco vira um arquivo de steering; ele não lê ~/.agents/skills, então as ai-memory-* vão para o dele.
ai-memory install-instructions --compact --skills-scope global --skills-target-dir ~/.kiro/skills \
  --target ~/.ai-setup/adapters/kiro/ai-memory.md
```

Depois: `sh ~/.ai-setup/doctor.sh`. O instalador grava no `~/.claude/settings.json` vivo; o doctor acusa a
diferença e imprime o comando que a aceita no repositório (um `sed` que devolve `@HOME@` no lugar do seu
`$HOME`). Revise o diff e faça o commit. No Codex, aprove os hooks em `codex` → `/hooks`.

Pegadinhas dos instaladores:

1. **`--skills-scope global` sempre.** Sem isso, as Agent Skills caem em `$PWD/.claude/skills`, dentro do
   repositório onde você estiver.
2. **`install-instructions` nunca aponta para symlink.** Ele grava com arquivo temporário + rename, e o
   rename troca o link por arquivo comum. Aqui `~/.claude/CLAUDE.md` é link: o alvo é `adapters/`.
3. **`install-mcp --client open-code` recusa JSONC com comentário.** Mantenha o `opencode.jsonc` sem `//`.
4. **O agy não recebe o bloco de instruções.** Ele lê exatamente dois arquivos globais
   (`~/.gemini/GEMINI.md` e `~/.gemini/AGENTS.md`), e as instruções do próprio servidor MCP cobrem escopo e
   dado não-confiável.

## 5. Desligar a memória nativa dos harnesses

Senão você fica com dois acervos, e o que a outra ferramenta não enxerga some do mapa.

- **Claude Code**, no `settings.json`: `"autoMemoryEnabled": false` (já vem assim em `adapters/`).
- **Codex**, em `~/.codex/config.toml`: `[features]` com `memories = false`.

## 6. Dizer a que projeto cada diretório pertence

O projeto é o nome da raiz do repositório. Quando o nome não serve, ou a raiz não é um repositório git, ponha
um marcador `.ai-memory.toml` na raiz:

```toml
workspace = "default"
project = "nome-do-projeto"
```

A busca do marcador sobe até `$HOME`. Em repositório de time, exclua localmente:
`echo .ai-memory.toml >> .git/info/exclude`.

## 7. Validar (não pule)

```sh
ai-memory status                 # servidor e cliente na mesma versão, páginas e sessões
ai-memory audit-contamination    # nenhuma sessão no projeto errado
docker logs ai-memory 2>&1 | grep -iE 'provider error|reranker failed'   # vazio
```

Depois, o teste que realmente prova o arranjo: **abra uma ferramenta, peça um handoff, abra outra e veja se
ela recebe.** Handoff é consumido uma vez só; encadear A → B → C funciona se cada sessão escrever o seu.

## 8. Atualizar

Desde a 3.x os hooks chamam um cliente nativo (`~/.local/share/ai-memory/native-runner/ai-memory hook --event
…`) que o wrapper baixa e confere pelo sha256. O wrapper usa a imagem `:latest`; compare
`ai-memory --version` com a tag do container (`docker inspect ai-memory --format '{{.Config.Image}}'`) para
saber se o servidor ficou para trás.

```sh
ai-memory upgrade     # wrapper, imagem e cliente nativo
```

Duas coisas que o `upgrade` não faz direito neste arranjo:

1. **Só refaz os hooks dos agentes que já tinham hooks.** Ele mantém o `--project-strategy` de quem já
   estava ligado, mas cria com o padrão os que faltavam. Rode o laço de `install-hooks` da seção 4 de novo:
   é idempotente.
2. **Não recria o container.** O script que ele grava em `~/.cache/ai-memory/` leva as chaves inline (apague
   depois); com `--env-file` é mais limpo recriar à mão: `docker rm -f ai-memory` e o mesmo `docker run` da
   seção 3.

Depois, os `install-instructions` da seção 4 e o `doctor.sh`.

## 9. Quem é dono de quê

O ai-memory e este repositório mexem nos mesmos arquivos de config, então a fronteira é por **trecho**: quem
grava é o dono, e o outro só confere.

| Trecho | Dono | Como muda |
|---|---|---|
| Entradas de hook (`native-runner/ai-memory hook --event …`) | ai-memory | `install-hooks --apply` |
| Servidor MCP `ai-memory` nos configs das ferramentas e no `~/.claude2/.claude.json` | ai-memory | `install-mcp --apply` |
| Bloco `<!-- ai-memory:start/end -->` nos adaptadores (no Kiro, `adapters/kiro/ai-memory.md`) | ai-memory | `install-instructions` (arquivo real) |
| Skills `ai-memory-*` (também em `~/.kiro/skills`), plugin `opencode/plugins/ai-memory.ts` e `~/.kiro/hooks/ai-memory.json` | ai-memory | `install-instructions` / `install-hooks` |
| Todo o resto | ai-setup | editar em `~/.ai-setup` e rodar `install.sh` |

O `doctor.sh` confere as três pontas em cada ferramenta: hooks, MCP e instrução de uso.

## 10. Pegadinhas que só aparecem com o tempo

- **Codex só roda hook aprovado, e a aprovação é por posição.** Mexer no `hooks.json` renumera as entradas e
  derruba a confiança de todas, em silêncio; em `codex exec` elas viram `Failed`. Reaprovar em `codex` →
  `/hooks`. Isso já deixou o Codex sem captura e sem as instruções globais por dias.
- **Mantenha os hooks num arquivo só.** O Codex aceita `hooks.json` e `config.toml`, e avisa quando você usa
  os dois.
- **`agy -p` (modo print) não manda o diretório**, e a sessão cai num projeto `scratch`. Para testar o agy,
  use o modo interativo.
- **OpenCode carrega plugin quando a sessão é criada**, não quando o servidor sobe.
- Sessão de teste suja o acervo: `ai-memory purge-session --session-id <uuid> --confirm`.
- Para ver o que o ai-memory guardou, sem risco de mudar nada: [memory-ui.md](memory-ui.md).
