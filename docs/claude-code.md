# Claude Code: contas e aliases

Os atalhos dos agentes moram em [`adapters/shell/aliases.sh`](../adapters/shell/aliases.sh), carregado pelo
rc do shell. Ele também põe o `bin/` deste repositório no PATH (`orq`, `memory-ui`, `entrega-verifica`,
`handoff-copia`). Uma linha liga tudo:

```sh
echo '. "$HOME/.ai-setup/adapters/shell/aliases.sh"' >> ~/.bashrc   # ou ~/.zshrc
```

O `install.sh` lembra dessa linha enquanto ela faltar, e o `doctor.sh` confere.

## Os aliases

| Comando | O que roda | Conta |
|---|---|---|
| `claude` | o Claude Code puro (não é alias) | 1 (`~/.claude`) |
| `claude2` | `CLAUDE_CONFIG_DIR=$HOME/.claude2 claude` | 2 (`~/.claude2`) |
| `xclaude` | `claude --dangerously-skip-permissions`, dentro do `claude.slice` se ele existir | 1 |
| `xclaude2` | o mesmo, na conta 2 | 2 |
| `xcodex` | `codex --yolo` | — |
| `xagy` | `agy --dangerously-skip-permissions` | — |
| `xkiro` | `kiro-cli chat --trust-all-tools` | — |

Os `x*` não pedem permissão a cada ferramenta. Use em repositório onde você confia no que o agente vai fazer;
o `git push` continua com você (e, no [orq](orq.md), bloqueado).

## Duas contas logadas ao mesmo tempo

Quando uma assinatura bate no limite de uso, a outra continua, sem `/logout` e `/login`.

O Claude Code guarda tudo (credenciais, `.claude.json`, sessões) no diretório de `CLAUDE_CONFIG_DIR`. A conta
2 é um esqueleto de **symlinks** para `~/.claude`, então as duas veem a mesma configuração:

| Compartilhado (symlink para `~/.claude`) | Separado (arquivo real em cada conta) |
|---|---|
| `CLAUDE.md`, `settings.json`, `plugins/`, `skills/`, `commands/`, `agents/`, `projects/` (histórico das sessões) | `.credentials.json` (o token), `.claude.json` (conta, MCPs, pastas confiáveis, onboarding), `sessions/`, `session-env/` |

Montar:

```sh
mkdir -p ~/.claude2 && sh ~/.ai-setup/install.sh     # o install só monta os links se ~/.claude2 existir
ai-memory install-mcp --client claude-code --apply --config-file ~/.claude2/.claude.json
claude2                                              # /login com a segunda conta, uma vez
sh ~/.ai-setup/doctor.sh                             # linhas "claude2: ..." todas ok
```

O MCP vai à parte porque mora no `.claude.json`, que é um por conta. Os hooks do ai-memory vêm de graça: estão
no `settings.json` compartilhado.

**Nunca aponte `CLAUDE_CONFIG_DIR` para `~/.claude`.** Com a variável, o Claude passa a ler
`~/.claude/.claude.json` em vez de `~/.claude.json` e some com MCPs, pastas confiáveis e onboarding. Por isso
a conta 1 é o `claude` puro, sem alias, e o orq faz o mesmo (`[accounts.claude]` em [orq.md](orq.md)).

**Se o Claude reescrever um dos links** (salvando o `settings.json` pela conta 2, por exemplo), o link vira
arquivo e as contas divergem em silêncio. O `doctor.sh` acusa (`claude2: link ausente ou quebrado`) e o
`install.sh` refaz, guardando o arquivo como `.pre-ai-setup`.

## Teto de RAM e CPU: `claude.slice`

Uma sessão do Claude dispara testes, builds e servidores. Sem limite, um `ng build` descontrolado trava o
desktop. Com uma unit de slice do systemd, o `xclaude`/`xclaude2` rodam dentro dela, e tudo o que a sessão
dispara divide o mesmo teto: passou do limite, o OOM mata um processo de dentro, não a máquina.

Os números dependem da máquina, então a unit não fica neste repositório. Ela mora no seu `sync/` e chega ao
lugar por uma linha do `sync/MANIFEST` (ver [instrucoes.md](instrucoes.md)):

```ini
# sync/systemd/claude.slice
[Slice]
MemoryHigh=14G      # começa a apertar
MemoryMax=18G       # o OOM age aqui dentro
MemorySwapMax=4G    # não joga tudo no swap
CPUQuota=1600%      # 16 núcleos
```

```
link	systemd/claude.slice	.config/systemd/user/claude.slice
```

Depois: `sh ~/.ai-setup/install.sh && systemctl --user daemon-reload`. Sem o arquivo, os aliases rodam sem
slice.

## settings.json

O `settings.json` do Claude é cópia, não link (modo `copy`): o Claude e o instalador do ai-memory reescrevem o
arquivo vivo. A referência em `adapters/claude/settings.json` guarda `@HOME@` no lugar do seu `$HOME`, e o
`doctor.sh` mostra a diferença quando o vivo muda (um `/effort`, um plugin novo) e imprime o comando para
aceitar.

A status line é o [ccstatusline](https://github.com/sirmalloc/ccstatusline) (npm global; o `install.sh`
instala se faltar). A config fica em `adapters/claude/ccstatusline/`: `settings.json` é cópia (a TUI do
ccstatusline reescreve), `reset-left.sh` é link e mostra quanto falta para o reset dos limites de 5 h e 7 dias.

**Plugin interno de empresa não entra no `settings.json` versionado**, porque este repositório é público.
Ligue por projeto, no repositório da empresa:

```sh
claude plugin install <plugin>@<marketplace> --scope project
```
