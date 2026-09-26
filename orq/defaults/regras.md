<!-- Regras anexadas a TODO prompt desta fila (planejador, executor, revisor, conselho). Curto e verificável. -->

- Repositório: `{{REPO}}`. Antes de trabalhar, leia as instruções do repositório (`.ai/README.md`, `CLAUDE.md` ou
  `AGENTS.md`) e o contexto em `{{ACTIVITY}}`.
- Branch: `<branch>`. Confira com `git branch --show-current`; se estiver em outra, troque para ela. Nunca crie outra
  branch, nunca faça merge nem squash fora do que a tarefa pedir.
- Commits no padrão do `git log` do repositório, um por assunto.
- **Proibido:** `git push`; <o que mais não pode: banco compartilhado, migrate:fresh, serviços externos…>.
- Verificação: <comandos de teste, lint e build que valem para toda tarefa; suítes longas liberadas?>.
- Onde registrar: <TODO, journal, doc que toda tarefa atualiza>.
- Ao terminar a tarefa, deixe a árvore limpa (tudo commitado).
