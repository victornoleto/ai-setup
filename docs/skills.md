# Skills: comportamento numa fonte só

Comportamento mora no `GLOBAL.md` e em [`skills/`](../skills/), não em plugin. Plugin só existe em parte das
ferramentas e injeta texto em toda sessão; skill vale nas cinco e só entra no contexto quando o modelo decide
carregar (a descrição dela fica no contexto; o corpo, só quando usada).

Onde cada ferramenta acha as skills: Claude em `~/.claude/skills`, Codex e OpenCode em `~/.agents/skills`,
agy pelo `~/.gemini/config/skills.json`, Kiro em `~/.kiro/skills` (ele não lê `~/.agents/skills`). Uma fonte em `skills/`, um link por diretório, criados pelo
`install.sh` a partir do `adapters/MANIFEST`.

## As skills deste repositório

O que tem, o que ficou de fora e por quê está no [catálogo](catalogo.md). Origem, versão e edições locais das
copiadas: [`skills/UPSTREAM.md`](../skills/UPSTREAM.md).

**Da própria ferramenta:** `playwright-cli` vem dentro da CLI e acompanha a versão dela. O `install.sh` a recopia
para `~/.agents/skills` (Claude e Kiro ganham link) e o `doctor.sh` acusa quando a CLI foi atualizada sem rodar o
install. A config global fica em `adapters/playwright/cli.config.json` (`codegen: none` tira o bloco "Ran
Playwright code" de toda ação; `console.level: warning` deixa os `console.log` de fora).

**Pessoais** ficam no seu `sync/skills/`, com uma linha no `sync/MANIFEST` (ver
[instrucoes.md](instrucoes.md#manifest-como-cada-arquivo-chega-ao-lugar)). Assim uma skill da empresa ou de um
projeto seu não vai para este repositório público.

## Trocar plugin por skill

O que foi feito aqui, e dá para repetir:

1. **Meça o uso antes de decidir.** No Claude, as skills invocadas nos últimos 45 dias:

   ```sh
   find ~/.claude/projects -name '*.jsonl' -mtime -45 | xargs grep -ohE '"skill":"[^"]+"' \
     | sort | uniq -c | sort -rn | head -20
   ```

2. **Copie as skills que você realmente usa** (respeitando a licença) para `skills/` e desinstale o plugin.
3. **Compense o que a injeção do plugin fazia** com linhas de roteamento no `GLOBAL.md`: ~300 B em vez de
   3 KB. Teste: peça "quero adicionar o recurso X" e confira no transcript que a primeira chamada de
   ferramenta foi a skill.
4. **Anote a dívida.** `skills/UPSTREAM.md` guarda origem, versão, data e as edições locais (referências
   cruzadas a skills que você não copiou viram texto). O `doctor.sh` avisa quando a cópia passa de 90 dias.

Resultado aqui: o contexto fixo por sessão do Claude caiu de ~18 KB para ~9 KB.

**Plugins que ficam no Claude:** só `commit-commands`. Os que saíram, e o que ficou no lugar de cada um, estão
no [catálogo](catalogo.md#plugins-do-claude-que-saíram). O `doctor.sh` acusa se algum voltar a ligar.

## Pegadinhas

- **agy não aceita `~` no `skills.json`**, apesar da documentação: o caminho tem que ser absoluto (o erro só
  aparece em `~/.gemini/antigravity-cli/log/`). Aqui ele é `copy` com `@HOME@`.
- **Skill de terceiro instalada por fora** (um `npx skills add`, por exemplo) costuma cair como cópia em
  `~/.claude/skills`. O `doctor.sh` acusa (`skill copiada`): mova a cópia real para `~/.agents/skills` e
  deixe um link em `~/.claude/skills`.
