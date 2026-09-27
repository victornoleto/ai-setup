"""Hook PreToolUse do claude nas chamadas do orq: nega subagent em background. O `claude -p` termina quando o
modelo devolve a saída e mata o que ficou em background depois de 600 s, e o trabalho do subagent se perde.
Bash em background segue liberado (testes e `make dev`, que o modelo espera)."""
import json
import sys

MESSAGE = ("Nesta fila a sessão termina quando você devolve a saída, e o que estiver em background é morto. "
           "Rode o subagent em primeiro plano (run_in_background=false) ou faça você mesmo.")


def main() -> int:
    try:
        tool_input = json.load(sys.stdin).get("tool_input") or {}
    except (json.JSONDecodeError, AttributeError):
        return 0
    if tool_input.get("run_in_background"):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
