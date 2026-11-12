# ai-setup

As instruções que valem em toda sessão de agente, e a fiação que as leva a cada ferramenta. Cinco ferramentas
usam isto: **Claude Code**, **Codex**, **OpenCode**, **Antigravity CLI** (`agy`) e **Kiro CLI**.

A ideia: **cada coisa tem um dono só**, e um script diz quando algo saiu do lugar. Regra vai para instrução,
história vai para memória ([ai-memory](https://github.com/akitaonrails/ai-memory)).

## O que tem aqui

| Funcionalidade | Doc |
|---|---|
| **orq**: fila de tarefas sem supervisão. Opus planeja e revisa, Sonnet executa, as dúvidas vão a um conselho, e você só é chamado quando precisa | [docs/orq.md](docs/orq.md) |
| **Instruções**: um `GLOBAL.md` e um `machine.md` que chegam às cinco ferramentas pelo mecanismo nativo de cada uma | [docs/instrucoes.md](docs/instrucoes.md) |
| **ai-memory**: memória de longo prazo compartilhada entre as ferramentas, e as escolhas para ele conviver com este repositório | [docs/ai-memory.md](docs/ai-memory.md) |
| **sync/**: seus arquivos pessoais e de empresa num repositório privado, sobrepostos a este na instalação | [docs/sync.md](docs/sync.md) |
| **Claude Code**: duas contas logadas ao mesmo tempo, aliases (`claude2`, `xclaude`…) e teto de RAM | [docs/claude-code.md](docs/claude-code.md) |
| **Skills**: comportamento numa fonte só, em vez de plugin | [docs/skills.md](docs/skills.md) |
| **Catálogo**: o que o ai-setup tem e o que não tem (skills, regras absorvidas, plugins que saíram e skills que ficaram no pacote de origem) | [docs/catalogo.md](docs/catalogo.md) |
| **Segurança**: GitHub pelo `gh`, permissões, credenciais negadas, sandbox do Codex | [docs/seguranca.md](docs/seguranca.md) |
| **memory-ui**: o que o ai-memory guardou, no navegador, só leitura | [docs/memory-ui.md](docs/memory-ui.md) |

## Instalar

```sh
git clone <url-deste-repositório> ~/.ai-setup
git clone <seu-repositório-privado> ~/.ai-setup/sync      # GLOBAL.md, máquinas, skills pessoais
sh ~/.ai-setup/install.sh
echo '. "$HOME/.ai-setup/adapters/shell/aliases.sh"' >> ~/.bashrc
sh ~/.ai-setup/doctor.sh                                   # até sair sem FALHA
```

Passo a passo, com o ai-memory e a segunda conta do Claude: [docs/instalacao.md](docs/instalacao.md).

## Mapa

```
~/.ai-setup/
├── install.sh             põe cada arquivo no lugar (idempotente)
├── doctor.sh              confere tudo, não conserta nada
├── adapters/
│   ├── MANIFEST           o que é symlink, o que é cópia, e para onde
│   ├── claude/            CLAUDE.md, settings.json, ccstatusline/ (status line)
│   ├── codex/             AGENTS.md, hook SessionStart, perfil AppArmor
│   ├── opencode/          opencode.jsonc, AGENTS.md
│   ├── antigravity/       skills.json
│   ├── kiro/              ai-memory.md (steering)
│   ├── playwright/        cli.config.json (config global do playwright-cli)
│   ├── git/ignore         gitignore global
│   └── shell/aliases.sh   claude2, xclaude, xclaude2, xcodex, xagy, xkiro
├── skills/                skills nossas e copiadas (UPSTREAM.md: origem e versão)
├── bin/                   orq, memory-ui, entrega-verifica, handoff-copia, verbosidade
├── orq/                   o motor do orq e seus testes
├── memory-ui/             o servidor do memory-ui
├── docs/                  um doc por funcionalidade
├── tests/                 test_install.sh (install.sh com HOME falso)
├── sync/                  seu repositório privado, ignorado por este
│   ├── memory/GLOBAL.md   quem você é, em qualquer máquina
│   ├── memory/machine/    um <host>.md por máquina
│   ├── MANIFEST           entradas pessoais (lido antes do adapters/MANIFEST)
│   └── skills/            skills pessoais
└── local/                 estado desta máquina (machine.md, handoffs)
```

## Princípios

- **Uma fonte por coisa.** Instrução no `GLOBAL.md`, comportamento em `skills/`, memória no ai-memory. Nada
  repetido em plugin ou em memória nativa de ferramenta.
- **Mecanismo nativo de cada ferramenta.** Nenhuma depende de o modelo lembrar de ler um arquivo.
- **Neutro.** Este repositório não guarda nada pessoal nem de empresa: isso vai no seu `sync/`.
- **Verificável.** O `doctor.sh` aponta o que saiu do lugar, inclusive o que um instalador reescreveu por baixo,
  e imprime o comando que resolve.

## Resultado

- Uma memória só, que as cinco ferramentas escrevem e leem, com busca reordenada por LLM.
- Uma fonte só de comportamento, que chega às cinco do mesmo jeito.
- Contexto fixo por sessão do Claude caiu de ~18 KB para ~9 KB ao trocar plugin por skill.
- Filas inteiras de tarefas rodando sem supervisão, com revisão e conselho, e o `git push` com você.
