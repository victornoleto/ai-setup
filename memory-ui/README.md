# memory-ui

GUI web **somente leitura** para o [ai-memory](https://github.com/akitaonrails/ai-memory): projetos,
todas as páginas da wiki de cada um (não só as 100 mais recentes), leitor de página, busca num
projeto ou em todos, e handoffs abertos. Uso pessoal, em `127.0.0.1`, aberta sob demanda.

## Uso

```sh
bin/memory-ui [--port N]   # padrão: 49380
```

Imprime a URL e sobe o servidor; `Ctrl-C` encerra. O estado fica na URL (`#/<projeto>/<path>`): link
direto e "voltar" do navegador funcionam.

## De onde vem cada dado

| Dado | Fonte |
|---|---|
| Lista de projetos, lista de páginas de um projeto | `wiki.py` → `docker exec ai-memory` lendo `/data/wiki/` (o MCP não lista projetos, e `memory_recent` para em 100) |
| Página, busca, handoffs | `mcp.py` → MCP do ai-memory em `127.0.0.1:49374` |

## Por que é só leitura

A GUI é para ver, não para mudar nada: nenhum arquivo chama ferramenta de escrita do MCP (gravar ou
apagar página, aceitar/cancelar handoff, consolidar, etc.), não aceita nem cancela handoff, e não
toca arquivo da wiki. `server.py` só atende `GET` (outros métodos levam 405) e confere o header
`Host` contra `127.0.0.1:<porta>`/`localhost:<porta>` (defesa contra DNS rebinding). No navegador,
todo Markdown e trecho de busca passa por `DOMPurify` antes de entrar no DOM.

Detalhe de arquitetura e das rotas: [`docs/specs/2026-10-08-memory-ui-design.md`](docs/specs/2026-10-08-memory-ui-design.md).

## Testes

```sh
python3 -m unittest discover -s memory-ui/tests -t memory-ui   # da raiz do ai-setup
```

Usam dublês de `docker` e do MCP — não tocam o ai-memory real.
