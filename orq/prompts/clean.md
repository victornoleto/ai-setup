A execução terminou, mas a árvore de trabalho não está limpa (`git status --porcelain`):

```
{{FILES}}
```

A próxima tarefa só começa com a árvore limpa. Para cada arquivo: se é parte da tarefa, commite seguindo as
convenções; se é lixo (temporário, saída de ferramenta, rascunho), apague. Se deveria ser ignorado pelo git e não
é, diga em `pending` em vez de mexer no `.gitignore` por conta própria. Não use `git stash`, `git reset --hard` nem
`git checkout -- .`: não descarte trabalho sem saber o que é. Mesma saída estruturada.
