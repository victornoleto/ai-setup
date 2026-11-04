# Instalação numa máquina nova

Em ordem, do zero até o `doctor.sh` sair sem falha. Tempo: ~30 min para este repositório, mais ~40 min para o
ai-memory (passo 6).

Os dois pedaços são independentes: o ai-memory funciona sem este repositório, e este repositório funciona sem o
ai-memory. Juntos, a conta fecha assim:

| | O que guarda |
|---|---|
| **ai-setup** (este repositório + o seu `sync/`) | o que vale sempre: instrução, skills, permissões, plugins, modelo |
| **ai-memory** | o que já aconteceu: decisões, pegadinhas, handoffs, buscados sob demanda |

## 1. Pré-requisitos

- `git`, `jq` e Docker (este para o ai-memory).
- Pelo menos um harness: Claude Code, Codex, OpenCode ou Antigravity CLI (`agy`).
- `gh` com login (`gh auth login`): é por ele que os agentes falam com o GitHub ([seguranca.md](seguranca.md)).

## 2. Clonar os dois repositórios

```sh
git clone <url-deste-repositório-ou-do-seu-fork> ~/.ai-setup
git clone git@github.com:<seu-usuario>/<seu-repo-pessoal>.git ~/.ai-setup/sync
```

O `sync/` é **seu e privado**: `GLOBAL.md`, um arquivo por máquina, skills e entradas pessoais. Este
repositório o ignora. Primeira vez, sem repositório pessoal ainda: crie um seguindo
[sync.md](sync.md#1-criar-o-repositório-privado) e volte para o passo 4.

## 3. Escrever o GLOBAL.md

`~/.ai-setup/sync/memory/GLOBAL.md`: quem você é e como trabalha, carregado em todo turno de toda ferramenta.
Curto (o `doctor.sh` avisa acima de 4 KB). O que pôr e o que deixar de fora:
[instrucoes.md](instrucoes.md#o-que-escrever-no-globalmd).

## 4. Rodar o install.sh

```sh
sh ~/.ai-setup/install.sh
```

Cria os links e cópias do `adapters/MANIFEST` (e do `sync/MANIFEST`, se houver), um
`sync/memory/machine/<hostname>.md` em branco e o `local/machine.md` apontando para ele. Arquivo seu que
estiver no caminho vira `<nome>.pre-ai-setup`. Pode rodar de novo quantas vezes quiser.

Depois, preencha o `machine/<hostname>.md` com o que só vale nesta máquina (como o root funciona, onde mora a
documentação dela).

## 5. Ligar os aliases

```sh
echo '. "$HOME/.ai-setup/adapters/shell/aliases.sh"' >> ~/.bashrc   # ou ~/.zshrc
```

Abra um terminal novo. A linha traz os aliases (`claude2`, `xclaude`, `xcodex`…) e põe o `bin/` no PATH
(`orq`, `memory-ui`). Detalhes e o teto de RAM opcional em [claude-code.md](claude-code.md).

## 6. Subir o ai-memory

Servidor em Docker, chaves fora de qualquer repositório, hooks e MCP nas quatro ferramentas:
[ai-memory.md](ai-memory.md), seções 1 a 7.

## 7. Segunda conta do Claude (opcional)

```sh
mkdir -p ~/.claude2 && sh ~/.ai-setup/install.sh
ai-memory install-mcp --client claude-code --apply --config-file ~/.claude2/.claude.json
claude2     # /login com a segunda conta
```

O que é compartilhado e o que não é: [claude-code.md](claude-code.md#duas-contas-logadas-ao-mesmo-tempo).

## 8. Conferir

```sh
sh ~/.ai-setup/doctor.sh
```

Repita até sair sem `FALHA`. Cada linha com problema traz o comando que resolve. No Codex, aprove os hooks em
`codex` → `/hooks`.

O teste final, que prova o arranjo inteiro: **abra uma ferramenta, peça um handoff, abra outra e veja se ela
recebe.**

## Depois

- Quer rodar uma fila de tarefas sem supervisão? [orq.md](orq.md).
- Quer ver o que o ai-memory guardou? [memory-ui.md](memory-ui.md).
- Mudou algo aqui ou rodou um `ai-memory install-*`? `sh doctor.sh` de novo.
