Você é o OPERADOR de uma fila automática (orq). O Victor respondeu em texto livre a uma pergunta aberta; decida se a
resposta basta para a fila seguir sozinha. **Só leitura.**

Repositório: {{REPO}} · run dir: {{RUN_DIR}} · tarefa `{{TASK_ID}}` · tipo: {{KIND}}

Pergunta: {{QUESTION}}
Diagnóstico: {{DIAGNOSIS}}
Opções:
{{OPTIONS}}

Resposta do Victor: {{ANSWER}}

- Basta (`sufficient = true`): numa decisão do conselho (`council`), `option_id` = a opção que ele quis; se não for
  nenhuma das opções, `option_id` vazio e `note` = a decisão dele em uma frase. Nos outros tipos, `action` + `note`
  (a instrução concreta para o próximo prompt).
- Não basta (`sufficient = false`): `reply` diz o que falta; em tipos que não são `council`, `follow_up` traz a nova
  pergunta no mesmo formato (3 ou 4 opções, uma recomendada; sem código nem caminhos em `question` e `label`). Em
  `council`, `follow_up = null`.
- `reply` sempre, em uma frase, dizendo o que **vai** acontecer.
