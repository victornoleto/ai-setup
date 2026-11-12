# Segurança: GitHub, permissões e credenciais

Não é sandbox: é rede de proteção contra o acidente comum, mais o que o `doctor.sh` confere toda vez.

## GitHub pelo `gh`, não por MCP

Agentes acessam o GitHub pelo `gh`. O token fica no keyring do sistema (`gh auth login`), um login serve a
todas as ferramentas, e nenhum segredo fica em arquivo de config. O MCP do GitHub exigia um token no header, e
cada instalador que tocava o config gravava uma cópia dele num `.bak`. Se um harness ainda tiver o MCP
`github` (inclusive o plugin `github@openai-curated` do Codex, que embute o mesmo MCP), remova e revogue o
token.

O controle do que o agente pode fazer é a permissão de shell de cada ferramenta: leitura (`gh pr view`,
`gh issue list`, `gh run view`) liberada; `gh pr merge` e `gh repo delete` pedem aprovação.

| | Onde | `gh api` |
|---|---|---|
| Claude | `permissions` no `adapters/claude/settings.json` | pede aprovação com `-X`, `--method`, `-f`, `-F` |
| Codex | `~/.codex/rules/default.rules` (o Codex grava; fora deste repositório) | pede enquanto não houver regra `allow`; o `doctor.sh` acusa `git push` liberado ali |
| OpenCode | `permission.bash` no `adapters/opencode/opencode.jsonc` | pede sempre |

## Credenciais

Os arquivos de credencial (`~/.claude/.credentials.json`, o da conta 2 em `~/.claude2/`, `~/.codex/auth.json`,
`~/.gemini/oauth_creds.json`, `~/.config/ai-memory/server.env`) têm leitura negada no Claude e no OpenCode. No
Claude, comando de shell que cite um desses caminhos também é negado. É rede contra acidente: um caminho
montado por variável ou glob passa.

O `doctor.sh` procura token em texto puro (GitHub, Anthropic, OpenRouter) no `.claude.json` das duas contas,
no `config.toml` do Codex, no `opencode.jsonc` e no `mcp_config.json` do agy.

Chave de serviço nunca entra neste repositório nem no `sync/`: fica num arquivo `chmod 600` fora dos dois,
como o `server.env` do [ai-memory](ai-memory.md#3-o-servidor).

## Confiança do Codex

`trust_level = "trusted"` em `/home` (ou no `$HOME` inteiro) faz todo diretório da máquina herdar confiança.
Confie por projeto. O `doctor.sh` acusa.

## Sandbox do Codex no Ubuntu 24.04

O sandbox do Codex usa bubblewrap, que precisa de user namespace. O Ubuntu 24.04 bloqueia isso por AppArmor, e
o sandbox fica inerte (com um aviso em toda abertura). O perfil que libera só os dois `bwrap` está em
[`adapters/codex/apparmor/codex-bwrap`](../adapters/codex/apparmor/codex-bwrap); o `doctor.sh` imprime o
comando de instalação (precisa de `sudo`, no seu terminal).

## Orca

O `doctor.sh` acusa hook do Orca IDE que volte aos configs (`hook do Orca voltou`). Ao instalar: o pacote
`orca` do Ubuntu é o leitor de tela do GNOME; o Orca IDE é o `orca-ide`.

## Agentes sem pedir permissão

O `settings.json` público é neutro: o Claude pede permissão no padrão dele. `defaultMode: "auto"` e
`skipDangerousModePermissionPrompt` são escolha de cada um e vão numa cópia pessoal em `sync/claude/settings.json`
([sync.md](sync.md)). O `doctor.sh` também avisa quando o Codex confia em pasta temporária ou em pasta-mãe de
projetos.

Os aliases `x*` ([claude-code.md](claude-code.md)) rodam sem confirmação por ferramenta. O que segura:

- **`git push`** fica com você. No [orq](orq.md), é travado em todas as sessões contra o reflexo do agente, e bloqueado
  de fato só com `sandbox = "home"` no papel (`pushurl` inválido
  no ambiente delas).
- **Teto de RAM e CPU** pelo `claude.slice`, para um processo descontrolado não derrubar a máquina.
- **Plugin ou dado de empresa** nunca entra neste repositório público: vai por projeto ou pelo `sync/`.
