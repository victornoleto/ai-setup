# Skills copiadas de fora

Estas skills não se atualizam sozinhas. **Revise a cada 90 dias**: o `doctor.sh` avisa quando
a data abaixo passa disso.

| Skill | Origem | Versão | Copiada em |
|---|---|---|---|
| brainstorming | github.com/obra/superpowers (MIT, `LICENSE.superpowers`) | 6.3.0 | 2026-09-17 |
| systematic-debugging | idem | 6.3.0 | 2026-09-17 |
| writing-plans | idem | 6.3.0 | 2026-09-17 |
| test-driven-development | idem | 6.3.0 | 2026-09-17 |
| security-audit | github.com/cloudflare/security-audit-skill (MIT, `LICENSE.cloudflare-security-audit`) | c1c8a8c | 2026-09-20 |

copiado-em: 2026-09-17

## Por que cópia e não plugin

O plugin só existe no Claude Code e no Codex, e injeta em toda sessão ~3 KB mandando invocar
skill antes de qualquer resposta. A cópia chega aos quatro harnesses, e quem roteia é a seção
"Skills" do `GLOBAL.md`.

## Edições locais (reaplicar depois de atualizar)

1. `systematic-debugging/SKILL.md`: `superpowers:test-driven-development` →
   `test-driven-development`; a referência a `verification-before-completion` vira "rode a
   verificação e leia a saída antes de declarar sucesso".
2. `test-driven-development/writing-good-tests.md`: `superpowers:writing-skills` →
   "skill authoring".
3. `writing-plans/SKILL.md`:
   - A menção a `using-git-worktrees` sai.
   - O cabeçalho "REQUIRED SUB-SKILL" vira "execute tarefa por tarefa".
   - A seção **Execution Handoff** é trocada por execução nesta mesma sessão (sem
     `subagent-driven-development` nem `executing-plans`, que não foram copiadas).
4. `security-audit/SKILL.md` (as três levam a marca `(ai-setup)`, para o diff achar):
   - O diretório de saída padrão sai de `~/security-audit-skill/` para
     `/var/www/victor/security-audits/`, com a proibição de cair direto em `$HOME`.
   - Em **Universal execution safety**, o parágrafo *Local sandbox reality*: sem root por tool
     call, análise só de fonte é o caminho normal, e o resto vira `needs_validation`.
   - Em **Cost budget**, o parágrafo *Local cap*: 2 subagents em paralelo, salvo pedido
     explícito de auditoria completa com o `budget` registrado.

## Como atualizar

```sh
d=$(mktemp -d) && git clone --depth 1 https://github.com/obra/superpowers "$d"
for s in brainstorming systematic-debugging writing-plans test-driven-development; do
  diff -ru "$d/skills/$s" ~/.ai-setup/skills/$s
done

c=$(mktemp -d) && git clone --depth 1 https://github.com/cloudflare/security-audit-skill "$c"
diff -ru "$c/skills/security-audit" ~/.ai-setup/skills/security-audit
```

1. Leia o diff. O que não estiver na lista de edições locais é novidade do upstream: traga.
2. Reaplique as edições locais e confira com
   `grep -rn 'superpowers:' ~/.ai-setup/skills` (tem que voltar vazio).
3. Atualize a versão e as datas acima, inclusive a linha `copiado-em:`, e faça o commit.
