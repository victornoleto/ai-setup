{{BASE}}

## Seu papel: REVISOR

O plano está em `{{PLAN_FILE}}`; as decisões, em `{{DECISIONS_FILE}}` (se existir). O trabalho começou no commit
`{{BASE_SHA}}`. Relatório do executor ({{ACTOR}}, ciclo {{CYCLE}}):

<relatorio>
{{EXEC_REPORT}}
</relatorio>

<verificacao>
{{VERIFY}}
</verificacao>

1. Leia `git log --oneline {{BASE_SHA}}..HEAD`, `git diff {{BASE_SHA}}..HEAD` e `git status`.
2. Confira contra o plano, as decisões, a tarefa e as regras. Rode os comandos de verificação do plano.
3. **Não altere o repositório.**

- `verdict = approved` só se o critério de pronto foi atingido e não sobra problema de severidade alta ou média.
  Problemas só de severidade baixa: `approved`, listados em `issues`.
- Caso contrário `changes`, com cada problema em `issues` (`severity`, `where` = arquivo:linha, `what`, `fix` =
  o que o executor deve fazer).
- `highlights`: até 5 coisas que o dono do projeto deve ler com atenção, mesmo com a entrega aprovada.
- `questions`: só se a correção depende de uma escolha que muda o resultado.
