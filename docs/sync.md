# sync/: o que é seu, fora deste repositório

Este repositório é público e neutro: nada de nome, empresa, cliente ou projeto pessoal. Tudo o que é seu mora em
`~/.ai-setup/sync/`, um **repositório git privado seu**, que este ignora (`.gitignore`). Os dois se juntam na
hora de instalar: o `install.sh` lê o `sync/MANIFEST` antes do público.

A regra para decidir: **se outra pessoa clonasse este repositório, isto seria verdade e útil para ela?** Se sim,
vai aqui. Se fala de você, da sua empresa ou de um projeto seu, vai no `sync/`. Se só vale nesta máquina, vai em
`local/` ([instrucoes.md](instrucoes.md#as-três-gavetas)).

## 1. Criar o repositório privado

Uma vez, na primeira máquina:

```sh
mkdir -p ~/.ai-setup/sync/memory && cd ~/.ai-setup/sync
git init -b main
printf '*.pre-ai-setup\n*.bak-*\n' > .gitignore
$EDITOR memory/GLOBAL.md                  # quem você é, como trabalha (instrucoes.md)
sh ~/.ai-setup/install.sh                 # cria memory/machine/<hostname>.md e o liga
$EDITOR memory/machine/$(hostname).md
git add .gitignore memory/GLOBAL.md memory/machine/$(hostname).md
git commit -m "sync: GLOBAL.md e a primeira máquina"
gh repo create <seu-repo-pessoal> --private --source . --push
```

Confira que ficou privado: `gh repo view --json visibility -q .visibility` deve dizer `PRIVATE`.

## 2. O que mora lá

```
sync/
├── memory/
│   ├── GLOBAL.md          quem você é, em qualquer máquina (carregado em todo turno)
│   └── machine/
│       ├── casa.md        um arquivo por máquina, pelo hostname
│       └── trabalho.md
├── MANIFEST               entradas pessoais, mesmo formato do adapters/MANIFEST
├── skills/                skills suas ou da empresa
├── systemd/, claude/...   qualquer arquivo de config seu que o MANIFEST ponha no lugar
└── docs/                  specs, planos, roteiros de trabalho
```

Só `memory/GLOBAL.md` é obrigatório. O resto aparece quando você precisa.

**Nunca no `sync/`:** chave de API, token, senha. Mesmo privado, um repositório git copia o segredo para todo
clone e todo backup. Segredo fica num arquivo `chmod 600` fora dos dois repositórios
([seguranca.md](seguranca.md#credenciais)).

## 3. Outra máquina

```sh
git clone <url-deste-repositório> ~/.ai-setup
git clone git@github.com:<seu-usuario>/<seu-repo-pessoal>.git ~/.ai-setup/sync
sh ~/.ai-setup/install.sh                 # cria o machine/<hostname>.md desta máquina
$EDITOR ~/.ai-setup/sync/memory/machine/$(hostname).md
cd ~/.ai-setup/sync && git add memory/machine/$(hostname).md && git commit -m "sync: máquina $(hostname)" && git push
```

As duas máquinas compartilham o `GLOBAL.md`; cada uma carrega só o próprio `machine/<host>.md`, escolhido por
`local/machine.md`. Depois de mudar algo numa máquina: `git push` lá, `git pull` e `sh install.sh` na outra.

## 4. Pôr um arquivo seu no lugar

Toda entrada pessoal é uma linha no `sync/MANIFEST`: modo, origem (relativa a `sync/`) e destino (relativo a
`$HOME`), separados por TAB. Modos `link` e `copy`, os mesmos do público
([instrucoes.md](instrucoes.md#manifest-como-cada-arquivo-chega-ao-lugar)).

**Uma skill sua ou da empresa:**

```sh
mkdir -p ~/.ai-setup/sync/skills/minha-skill && $EDITOR ~/.ai-setup/sync/skills/minha-skill/SKILL.md
printf 'skill\tskills/minha-skill\n' >> ~/.ai-setup/sync/MANIFEST   # Claude, ~/.agents (Codex, OpenCode, agy) e Kiro
# só em parte das ferramentas: uma linha `link` por destino, ex. link<TAB>skills/minha-skill<TAB>.claude/skills/minha-skill
sh ~/.ai-setup/install.sh
```

**Um arquivo de config que só você usa** (uma unit do systemd, por exemplo): mesma coisa, com o destino real.
Exemplo completo em [claude-code.md](claude-code.md#teto-de-ram-e-cpu-claudeslice).

**Trocar um arquivo público por uma versão sua.** Ponha no `sync/MANIFEST` uma entrada com o **mesmo destino**
da pública: a pessoal vence, e a pública é ignorada nesta instalação. Exemplo, um `settings.json` do Claude com
seus plugins de empresa:

```sh
mkdir -p ~/.ai-setup/sync/claude
cp ~/.ai-setup/adapters/claude/settings.json ~/.ai-setup/sync/claude/settings.json
$EDITOR ~/.ai-setup/sync/claude/settings.json
printf 'copy\tclaude/settings.json\t.claude/settings.json\n' >> ~/.ai-setup/sync/MANIFEST
sh ~/.ai-setup/install.sh
```

A partir daí, o `doctor.sh` compara o arquivo vivo com a **sua** cópia, e o comando de aceitar que ele imprime
grava no `sync/`. O preço: melhorias que chegarem no `settings.json` público não chegam ao seu sozinhas. Compare
de vez em quando com `diff adapters/claude/settings.json sync/claude/settings.json`. Quando der, prefira ligar o
plugin por projeto (`claude plugin install <plugin>@<marketplace> --scope project`) a manter um fork do arquivo.

## 5. Antes de contribuir com este repositório

Fork ou pull request aqui leva o histórico junto. Monte uma lista com os termos que **não podem** sair do seu
computador (seu nome, usuário, empresa, clientes, projetos, hostnames) e rode antes de cada push:

```sh
T='seu-nome|seu-usuario|sua-empresa|cliente-x|projeto-y'
git grep -n -i -E "$T"                                       # arquivos atuais
git log -p @{upstream}.. | grep -i -E "^[+-].*($T)"          # o que você vai enviar
git log -p --all | grep -E 'github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-|sk-or-v1-'   # tokens
```

As três saídas devem vir vazias. Se algo vazou num commit já enviado, apagar no commit seguinte não basta: o
histórico precisa ser reescrito (`git filter-repo`) e o token, revogado.
