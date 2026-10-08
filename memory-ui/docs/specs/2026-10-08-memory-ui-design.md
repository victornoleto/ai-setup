# memory-ui — GUI web somente leitura para o ai-memory

Data: 2026-10-08. Status: aprovado em conversa; aguardando revisão desta spec.

## Objetivo

Ver, no navegador, o que o ai-memory gerou: projetos, todas as páginas da wiki de cada projeto,
sessões, handoffs abertos e busca. Uso pessoal, nesta máquina, aberto sob demanda.

Sucesso: abrir qualquer projeto, navegar por **todas** as páginas dele (não só as 100 recentes) e ler
qualquer uma renderizada; buscar em um projeto ou em todos.

## Restrições

- Somente leitura. A GUI nunca chama ferramenta de escrita do MCP, nunca aceita/cancela handoff e
  nunca altera arquivo da wiki.
- Python stdlib no servidor; nenhuma dependência nova. Frontend em HTML + JS sem build.
- Escuta só em `127.0.0.1`.

## Fatos do ai-memory que o desenho assume (verificados em 2026-10-08, ai-memory 2.2.2)

- MCP em `http://127.0.0.1:49374/mcp`, JSON-RPC por POST, sem token. O header
  `Accept: application/json, text/event-stream` é obrigatório (sem ele: `Not Acceptable`). Resposta é
  JSON puro; o resultado útil está em `result.content[0].text`, que é ele mesmo um JSON.
- Erro vem como `{"error": {"code", "message"}}` no lugar de `result`
  (ex.: `project 'nao-existe' not found in workspace 'default'`).
- Não existe ferramenta MCP que liste projetos. Sem `workspace` + `project`, o servidor usa o último
  projeto ativo — por isso toda chamada passa os dois explícitos.
- `memory_recent` devolve no máximo 100 páginas; não serve para listar um projeto inteiro.
- Workspace único: `default`.
- `memory_read_page {workspace, project, path}` → `{path, title, body, frontmatter}`; `body` sem
  frontmatter.
- `memory_query {query, global: true}` → hits em `global_hits[]` com `project_name`, `path`, `title`,
  `snippet` (com `<mark>`). Com `workspace` + `project` → hits em `hits[]`.
- Wiki no container: `/data/wiki/<ws-uuid>/<proj-uuid>/…`. Nome do projeto em
  `<proj-uuid>/_meta.md` (`project: <nome>`). Cada página tem frontmatter com `title` e `kind`.
  `_pending/` guarda propostas não aprovadas. Páginas de sessão em `sessions/<uuidv7>.md`
  (o nome ordena por tempo).

## Arquitetura

```
navegador ──HTTP──> memory-ui (127.0.0.1:49380)
                      ├─ wiki.py ── docker exec ai-memory … /data/wiki   → projetos, listagem de páginas
                      └─ mcp.py ─── POST 127.0.0.1:49374/mcp             → página, busca, handoffs
```

Arquivos em `~/.ai-setup/memory-ui/`:

| Arquivo | Responsabilidade |
|---|---|
| `wiki.py` | `list_projects()` e `list_pages(project)` via `docker exec`; parse da saída e do frontmatter |
| `mcp.py` | `call(tool, args)`: JSON-RPC com `urllib`, desembrulha `content[0].text`, levanta erro legível |
| `server.py` | `http.server`: checagem de `Host`, rotas `/api/*`, serve `static/` |
| `static/index.html` | tela única; JS e CSS inline |
| `tests/` | `unittest` |

Lançador `~/.ai-setup/bin/memory-ui`, no padrão do `bin/orq`: sobe o servidor e imprime a URL.
Porta padrão 49380, sobrescrevível por `--port`.

### wiki.py

- `list_projects()`: uma chamada `docker exec ai-memory sh -c '…'` que imprime, para cada
  `/data/wiki/*/*/_meta.md`, o nome do projeto e a contagem de `.md` fora de `_pending/` e sem
  `_meta.md`. Retorna `[{name, pages}]` ordenado por nome.
- `list_pages(project)`: localiza a pasta do projeto pelo `_meta.md` e imprime, para cada página,
  `path relativo`, `title` e `kind` do frontmatter (uma linha por página, separador TAB). Retorna
  `[{path, title, kind}]`. Grupo = primeiro segmento do `path` (`sessions`, `decisions`, …; raiz →
  `(raiz)`). Sem `title` → usa o nome do arquivo.
- O nome do projeto vai como argumento posicional do `sh -c` (`"$1"`), nunca interpolado no script.
  Nome fora de `[A-Za-z0-9._-]+` → erro sem executar nada.
- Timeout de 15 s por `docker exec`.

### mcp.py

- `call(tool, args) -> dict`. Monta `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{…}}`.
- `error` no JSON-RPC ou `result.isError` → `McpError(message)`. Conexão recusada →
  `McpError("ai-memory fora do ar em 127.0.0.1:49374 → docker start ai-memory")`.
- Timeout de 15 s.

### server.py — rotas

| Rota | Fonte | Resposta |
|---|---|---|
| `GET /` | `static/index.html` | HTML |
| `GET /api/projects` | `wiki.list_projects` | `[{name, pages}]` |
| `GET /api/pages?project=` | `wiki.list_pages` | `[{path, title, kind, group}]` |
| `GET /api/page?project=&path=` | `memory_read_page` | `{path, title, body, frontmatter}` |
| `GET /api/search?q=&project=` | `memory_query` (sem `project` → `global=true`) | `[{project, path, title, snippet}]` |
| `GET /api/handoffs?project=` | `memory_handoff_list` | resposta do MCP repassada |

- Todo request com `Host` diferente de `127.0.0.1:<porta>` ou `localhost:<porta>` → 403
  (defesa contra DNS rebinding).
- Só `GET`. Outros métodos → 405.
- Erro de `wiki` ou `mcp` → `502 {"error": "<local>: <causa> → <correção>"}`. Parâmetro faltando → 400.

## Telas

Tela única, três colunas em desktop; em largura de celular, uma coluna por vez com "voltar".

1. **Projetos** — nome e contagem de páginas.
2. **Páginas** — agrupadas por tipo; grupo `sessions` em ordem decrescente de nome (mais recente
   primeiro); demais grupos por título. Aba **Handoffs** lista os abertos (somente leitura).
3. **Leitor** — título, frontmatter como tabela, corpo Markdown renderizado.

- Busca no topo, com seletor *este projeto* / *todos*. Cada resultado: projeto, caminho, trecho;
  clique abre no leitor.
- Estado na URL: `#/<projeto>/<path>`; voltar e link direto funcionam.
- Markdown e trechos de busca são conteúdo não confiável: renderização com `marked` e sanitização
  com `DOMPurify`, ambos de cdnjs em versão fixa. Nenhum HTML vindo do ai-memory entra no DOM sem
  passar pelo `DOMPurify`.
- Nada depende de cor: item selecionado tem borda e marcador de texto; erro tem rótulo "Erro:".
- Erros aparecem num aviso no topo com local, causa e correção.

## Testes

`python3 -m unittest discover memory-ui/tests`, sem dependência:

- parse da saída de `list_projects` e `list_pages` (fixtures de texto), incluindo página sem `title`;
- rejeição de nome de projeto inválido;
- `mcp.call` contra um servidor HTTP falso: sucesso, `error` JSON-RPC, `isError`, conexão recusada;
- checagem de `Host` (aceita `127.0.0.1:<porta>` e `localhost:<porta>`, recusa o resto);
- rotas `/api/*` com `wiki` e `mcp` substituídos por dublês.

Validação final com `playwright-cli` contra o ai-memory real: abrir `hoobot`, ler uma página,
buscar `sanctum` em *todos*.

## Fora do escopo

Escrita de página, aprovação de `_pending/`, aceitar/cancelar handoff, observações brutas da sessão,
briefing, autenticação, rodar como serviço.
