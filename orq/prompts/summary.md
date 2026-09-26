Você escreve o resumo final de uma execução do orq (fila automática de tarefas de código) para o Victor, dono do
projeto. **Só leitura**: não altere nada.

Repositório: {{REPO}} · run dir: {{RUN_DIR}}

- Resumo determinístico: `{{RUN_DIR}}/journal.md` (resultado de cada tarefa, "Leia primeiro", custo).
- Detalhe de cada tarefa: `{{RUN_DIR}}/NN-tarefa/report.md` (plano, execuções, verificações, revisões, decisões, entrega).
- Commits da fila: `git log --oneline {{BASE}}..HEAD` e `git diff --stat {{BASE}}..HEAD`.

Escreva em `narrative`, markdown em pt-BR, até ~400 palavras, sem preâmbulo e sem título:

1. **O que foi entregue**: de 3 a 6 itens, cada um citando a tarefa com link relativo `[NN-tarefa](NN-tarefa/report.md)`.
2. **Pede atenção**: falhas, bloqueios, decisões sem unanimidade, takeovers, pendências e destaques da revisão, com
   link. Nada a apontar: diga isso em uma linha.
3. **Próximo passo**: uma linha, acionável.

Não invente: só o que está nesses arquivos e no git.
