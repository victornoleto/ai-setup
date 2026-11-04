# Aliases dos agentes e o bin/ do repositório no PATH. Carregue no rc do shell (bash ou zsh):
#   . "$HOME/.ai-setup/adapters/shell/aliases.sh"
# O que cada um faz e por quê: docs/claude-code.md.

# bin/: orq, memory-ui, entrega-verifica, handoff-copia. Sem duplicar ao recarregar o rc.
case ":$PATH:" in
	*":$HOME/.ai-setup/bin:"*) ;;
	*) PATH="$HOME/.ai-setup/bin:$PATH"; export PATH ;;
esac

# Conta 2 do Claude Code: ~/.claude2 compartilha tudo com ~/.claude, menos a identidade.
# A conta 1 é o `claude` puro: CLAUDE_CONFIG_DIR=~/.claude trocaria ~/.claude.json por
# ~/.claude/.claude.json e sumiria com MCPs, pastas confiáveis e onboarding.
alias claude2='CLAUDE_CONFIG_DIR=$HOME/.claude2 claude'

# x*: sem pedir permissão. Se existir ~/.config/systemd/user/claude.slice, as sessões do Claude
# rodam dentro dele: teto de RAM e CPU para a sessão e tudo o que ela dispara (testes, builds).
if [ -f "$HOME/.config/systemd/user/claude.slice" ] && command -v systemd-run >/dev/null 2>&1; then
	_ai_slice='systemd-run --user --scope --quiet --slice=claude.slice '
else
	_ai_slice=''
fi
alias xclaude="${_ai_slice}claude --dangerously-skip-permissions"
alias xclaude2="CLAUDE_CONFIG_DIR=\$HOME/.claude2 ${_ai_slice}claude --dangerously-skip-permissions"
alias xcodex='codex --yolo'
alias xagy='agy --dangerously-skip-permissions'
unset _ai_slice
