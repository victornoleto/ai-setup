O plano em `{{PLAN_FILE}}` é o rascunho que você escreveu antes de a fila começar. Releia o arquivo: o dono pode
tê-lo editado. Confira o plano contra o que vale agora e deixe-o pronto para o executor.

Texto atual da tarefa (pode ter mudado desde o rascunho):
<tarefa>
{{TASK}}
</tarefa>

O que aconteceu na fila desde então:
<progresso>
{{PROGRESS}}
</progresso>

Pedidos do dono sobre este plano (são restrições: o plano final obedece a cada um):
<restricoes>
{{EDITS}}
</restricoes>

1. Confira cada item da seção **Premissas** no código real (`git log`, os arquivos). **Não altere o repositório**
   (só o arquivo do plano).
2. Premissa que falhou, tarefa que mudou ou restrição ainda não atendida: reescreva os passos afetados no arquivo.
   Trecho que o dono editou à mão fica como ele escreveu, salvo se uma premissa falhada o tornar impossível; nesse
   caso mantenha a intenção dele e registre a adaptação numa linha.
3. Nada mudou: deixe o arquivo como está.

Saída: `summary` (o que será feito e, numa linha, **o que mudou em relação ao rascunho**, ou "rascunho confirmado")
e `questions` (vazia, salvo dúvida nova que muda o resultado).
