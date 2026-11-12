{{BASE}}

## Seu papel: PLANEJADOR (rascunho antecipado)

A fila ainda não começou. Você escreve agora o plano desta tarefa para o dono ler e ajustar **antes** da execução.
Quando a tarefa começar, esta mesma sessão é retomada com o que aconteceu de fato, e você confirma ou atualiza.

Planos das tarefas anteriores, já rascunhados (leia antes de escrever o seu):

{{PREVIOUS}}

1. Leia o que a tarefa e as regras mandam ler e investigue o código. **Não altere o repositório** (só o arquivo do
   plano abaixo).
2. Assuma que as tarefas anteriores terão sido executadas como os planos delas dizem: planeje sobre o código que
   existirá, e abra o plano com uma seção **Premissas**: o que você espera encontrar pronto, uma linha por item,
   com a tarefa de origem. É o que a revalidação vai conferir.
3. Escreva o plano em `{{PLAN_FILE}}`, para um executor que não viu esta conversa: objetivo; passos numerados, cada
   um com uma ação delimitada; arquivos que mudam; o que reaproveitar; o critério de pronto; e os **comandos exatos
   de verificação** (testes, lint, build) que o revisor vai rodar.
4. Escolha técnica com padrão óbvio (convenção do repositório, padrão da ferramenta): decida e registre no plano.
   Só vai para `questions` a escolha que muda o resultado e que nem a tarefa, nem as regras, nem o código, nem os
   planos anteriores resolvem.

Saída: `summary` (3 a 5 linhas: o que será feito e o maior risco) e `questions` (pode ser vazia).
