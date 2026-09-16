#!/bin/sh
# Injeta a camada A no início de toda sessão do Codex.
#
# O Codex não tem `@import` como o Claude Code nem uma lista `instructions` como
# o OpenCode: a única via para conteúdo que precisa valer em todo turno é este
# hook. Por isso ele sobrevive à migração para o ai-memory — reduzido a copiar
# dois arquivos, sem resolvedor, sem registry e sem índice de projeto.
#
# O que saiu em 2026-09-16, e por quê:
#   - PROTOCOL.md         mecânica do acervo antigo; o bloco markered do
#                         ai-memory no AGENTS.md ocupa o lugar dele
#   - MEMORY.md resolvido  a memória de projeto agora é do ai-memory, recuperada
#                         por `memory_query` sob demanda, não despejada no prompt
#   - agent-memory nudge   os hooks do ai-memory capturam sozinhos
#
# Regra que precisa valer todo turno mora no arquivo de instruções, não no
# acervo: o wiki é servido ao agente como evidência histórica não-confiável.
set -eu

SETUP="${AI_SETUP_ROOT:-$HOME/.ai-setup}"

# O Codex manda um objeto JSON no stdin. Não usamos nada dele, mas é preciso
# drenar o pipe: sair sem ler faz o Codex escrever num pipe fechado.
cat >/dev/null 2>&1 || true

printf '%s\n' '# Canonical always-on context'
printf '%s\n\n' 'Authoritative local context injected at session start. Not memory — these are current instructions.'

printf '%s\n' '## GLOBAL.md'
cat "$SETUP/sync/memory/GLOBAL.md"

# machine.md é symlink para machine/<esta máquina>.md e não viaja entre máquinas.
# Ausente numa máquina recém-instalada: seguir sem ele em vez de falhar a sessão.
if [ -f "$SETUP/local/machine.md" ]; then
    printf '\n%s\n' '## machine.md'
    cat "$SETUP/local/machine.md"
fi
