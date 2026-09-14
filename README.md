# ~/.ai-setup

Todo o setup de desenvolvimento assistido por IA desta máquina: a memória que os agentes
escrevem, a fiação que liga as ferramentas a ela, e o estado que só faz sentido aqui.

Três ferramentas usam isto e enxergam a mesma coisa: **Claude Code**, **Codex** e **OpenCode**.

## As três gavetas

A pasta é dividida por **como cada coisa viaja**, não por assunto. Essa é a única regra que
você precisa guardar:

| Gaveta | O que é | Como viaja | Muda |
|---|---|---|---|
| `sync/` | **memória** — o que os agentes aprenderam | Syncthing, via minipc 24/7 | toda sessão |
| `adapters/`, `bin/`, `tests/`, `*.sh` | **fiação e código** — como as ferramentas acham a memória | git | raramente |
| `local/` | **estado desta máquina** | não viaja | toda sessão |

O teste para saber em qual gaveta algo entra:

- Se apagar e você **perde conhecimento que não volta** → `sync/`.
- Se apagar e as ferramentas **param de achar a memória, mas nada se perdeu** → git.
- Se copiar para outra máquina e virar **mentira lá** → `local/`.

Por que duas gavetas viajam de jeitos diferentes: a memória muda a cada sessão e precisa te
seguir sem você pensar — git exigiria lembrar de `pull`/`push`, e um repositório que depende de
memória humana não é backup, é intenção. A fiação muda uma vez por mês, mora junto de 3,7 GB de
transcrição e de arquivos de credencial, e ganha com revisão antes de chegar na outra máquina —
git é lista-branca (só existe o que foi adicionado), Syncthing seria lista-negra.

## Mapa

```
~/.ai-setup/
├── README.md              este arquivo
├── install.sh             põe cada config no lugar (idempotente)
├── doctor.sh              confere tudo, não conserta nada
├── .gitignore             sync/ e local/ ficam fora do git
├── bin/
│   └── agent-memory       resolve qual memória pertence a qual pasta
├── tests/
│   └── agent-memory.test.sh
├── adapters/
│   ├── MANIFEST           o que é symlink, o que é cópia, e para onde
│   ├── claude/            CLAUDE.md, settings.json
│   ├── codex/             AGENTS.md, hooks/load-portable-memory.sh
│   └── opencode/          opencode.jsonc, AGENTS.md, plugin/, package.json
├── sync/                  ← Syncthing cuida daqui para baixo
│   └── memory/
│       ├── GLOBAL.md      quem é o Victor em qualquer máquina
│       ├── PROTOCOL.md    as regras de escrever e resolver memória
│       ├── registry.json  qual pasta de projeto usa qual memória
│       ├── machine/       um arquivo por máquina (pc.md, trabalho.md…)
│       └── projects/<id>/ MEMORY.md (índice) + memórias temáticas
└── local/                 ← nunca sai desta máquina
    ├── machine.md         symlink para machine/<esta máquina>.md
    ├── markers/<id>       "houve sessão neste projeto" (o lembrete do nudge)
    └── notices/<id>       o texto do lembrete, para o OpenCode injetar
```

Repare que `machine/pc.md` fica em `sync/` (é backup, e é útil ver de outra máquina) mas
**qual deles vale** é decidido por `local/machine.md`, que é um symlink e não viaja. É o que
impede a máquina do trabalho de afirmar que tem uma GPU Acer Predator.

## Como cada ferramenta chega na memória

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| `GLOBAL.md` + `machine.md` + `PROTOCOL.md` | `@import` no `CLAUDE.md` | hook `SessionStart` | `instructions` |
| `MEMORY.md` do projeto | `autoMemoryDirectory` | hook `SessionStart` | plugin `config` |
| Lembrete do `nudge` | hook `SessionStart` | hook `SessionStart` | plugin `config` |

Cada ferramenta usa o mecanismo nativo dela. Nenhuma depende de o modelo lembrar de rodar nada.

## O resolvedor

```sh
agent-memory dir   [caminho]   # imprime o diretório de memória do workspace
agent-memory index [caminho]   # imprime o MEMORY.md resolvido
agent-memory nudge [caminho]   # lembrete de início de sessão; cala quando não há o que dizer
agent-memory check [id ...]    # higiene: índice, permissão, raízes, adaptador, conflito de sync
agent-memory stale [dias]      # memórias sem alteração há mais de N dias (padrão 180)
```

Regra de resolução: raiz do Git quando houver Git, senão o diretório da sessão; e a raiz
**mais longa** do `registry.json` que casa vence, para projeto aninhado ganhar do pai. Pasta
que hospeda projetos não relacionados nunca é registrada como raiz.

## Os scripts

**`install.sh`** lê o `adapters/MANIFEST` e põe cada arquivo onde a ferramenta procura. Modo
`link` cria symlink (só nós editamos aqueles arquivos). Modo `copy` copia, porque a ferramenta
reescreve o arquivo sozinha e um symlink sumiria em silêncio na primeira reescrita. Arquivo real
que estiver no caminho vira `<nome>.pre-ai-setup` antes de ser substituído. Rodar de novo não
estraga nada.

**`doctor.sh`** só verifica: symlinks apontando para cá, cópias iguais à referência,
`machine.md` resolvendo, `agent-memory check` limpo, suíte passando. Quando uma cópia diverge,
ele diz qual lado é mais novo e o `cp` para resolver na direção que você escolher.

## Máquina nova

1. Instalar `git`, `jq` e o Syncthing.
2. Clonar este repositório em `~/.ai-setup`.
3. Compartilhar a pasta `sync/` pelo Syncthing a partir do minipc, **com versionamento ligado**.
4. `sh install.sh` — cria os symlinks e o `machine/<hostname>.md` desta máquina, em branco.
5. Preencher o `machine/<hostname>.md`: como root funciona ali, onde mora a documentação dela.
6. Para cada projeto daquela máquina, acrescentar a raiz à entrada que já existe no
   `registry.json` — **a mesma entrada**, nunca uma nova — e criar o
   `.claude/settings.local.json` com `autoMemoryDirectory`.
7. `sh doctor.sh` até sair sem FALHA.

O `registry.json` acumula as raízes de todas as máquinas. Projeto que mudou de pasta ganha a
raiz nova na mesma entrada; a antiga fica como alias enquanto puder ser usada.

## Manutenção

- `doctor.sh` de vez em quando, e sempre depois de mexer em config.
- Índice de projeto acima de ~100 linhas ou 12 KiB pede curadoria: o detalhe vai para arquivo
  temático, o índice fica com ganchos de uma linha.
- `agent-memory stale` na revisão: memória parada há meses é candidata a conferir contra o
  código, não prova de que esteja errada.
- Segredo nunca entra no acervo — nem em memória, nem em config versionada. O `PROTOCOL.md`
  manda guardar uma referência ao lugar seguro, não o valor.

## Pendências

- **`~/.codex/config.toml` está fora do repositório.** Ele tem um GitHub PAT em texto puro em
  `[mcp_servers.github.http_headers]`. Para resolver: revogar o token em
  `github.com/settings/tokens`, trocar o bloco por `bearer_token_env_var = "GITHUB_MCP_TOKEN"`
  (o Codex suporta), exportar o valor de um arquivo fora do sync, e então descomentar a linha
  `copy codex/config.toml` no `MANIFEST`.
- **Windows.** Os arquivos sincronizam, mas `bin/agent-memory` e o hook do Codex são `sh` + `jq`
  e precisam de Git Bash ou WSL no PATH. Não testado.
- **OpenCode** carrega plugins quando a sessão é criada, não quando o servidor sobe. Reiniciar
  depois de mexer em config.
