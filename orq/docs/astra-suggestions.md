# Revisão do orq — sugestões do Astra

Data: 2026-09-27. Código revisado: commit `dad617c`.

## Aplicação das sugestões — 2026-09-27

Os achados abaixo são o registro da revisão original. A implementação posterior corrigiu os cinco problemas
prioritários e os cinco itens da tabela de oportunidades: preservação de permissões, configuração e sessões;
entrega de comandos e intervenção; notificações externas genéricas; relatórios de tentativas; encerramento de
processos, locks, custo desconhecido, maioria absoluta e espera interrompível.

Também foram adicionados cache de estado invalidado por metadados, leitura incremental de eventos, cache dos
títulos e um snapshot de estado por atualização do painel. Um teste mede dez consultas sucessivas ao estado:
antes havia dez leituras de conteúdo; depois, uma, com invalidação após escrita por outra instância. Relatórios
continuam sendo atualizados imediatamente por evento; agrupamento de renderizações não foi aplicado sem uma
medição que justifique alterar essa garantia.

Os testes passaram a rodar em sandbox local com Bubblewrap (`bash tests/run-isolated.sh -q`), sem rede ou
credenciais. Foram acrescentadas regressões para os cenários descritos, incluindo execução e retomada pela CLI
em processos reais com harness falso. Isso não valida uma chamada paga aos provedores reais.

As cinco funcionalidades da seção “Funcionalidades com maior retorno” permanecem propostas para uma etapa
separada. Não foram adicionados doctor, orçamento, worktree automática, conselho por votante ou exportação.

## Avaliação geral

Eu priorizaria confiabilidade da retomada e preservação de permissões. O `orq` já tem uma estrutura funcional bem definida; os maiores riscos aparecem quando a execução é interrompida ou repetida.

A arquitetura é enxuta: CLI → motor por fases → adaptadores dos harnesses. O diretório da execução conecta motor, painel e relatórios. Eu preservaria essa separação, a verificação determinística antes da revisão e o harness falso para testes. A interface também usa texto, glifos e intensidade, além de cores.

Esta revisão foi feita por leitura do código, sem alterações na implementação nem chamadas pagas a harnesses. Os achados são de análise estática; não foram reproduzidos em execução.

## Cinco problemas prioritários

### 1. Uma retomada do Codex perde a restrição de só leitura

O adaptador usa `--dangerously-bypass-approvals-and-sandbox` sempre que `resume=True`, independentemente de `read_only`. Isso é alcançável quando uma chamada do conselho ou operador retorna sem saída estruturada e o motor tenta novamente na mesma sessão.

A correção deve preservar a política de acesso em toda tentativa.

Referência: [`src/orq/harness/codex.py`](../src/orq/harness/codex.py), linha 17.

### 2. O resume não preserva integralmente a execução original

A CLI recarrega a configuração da fila e não recupera o `--repo` usado no início. Uma fila externa ao repositório pode retomar em outro diretório.

Além disso, os IDs das sessões de planejamento e execução só são persistidos depois que a chamada termina; uma interrupção durante a primeira chamada pode iniciar outra sessão na retomada.

Eu persistiria a configuração efetiva e a identificação da chamada antes de executá-la, registrando o ID da sessão assim que disponível.

Referências: [`src/orq/cli.py`](../src/orq/cli.py), linha 134; [`src/orq/engine.py`](../src/orq/engine.py), linha 163.

### 3. Há janelas de perda de comandos e decisões

`take_inbox()` avança o cursor de todos os comandos antes de aplicá-los. Uma queda nesse intervalo perde comandos ainda não executados.

Outro caso: escolher **“Parar a fila”** numa intervenção apaga a pergunta antes de parar; o próximo `resume` pode repetir a fase sem reapresentar a pergunta, contrariando o README.

A solução precisa combinar confirmação por comando, deduplicação e persistência da intervenção pendente.

Referências: [`src/orq/store.py`](../src/orq/store.py), linha 180; [`src/orq/intervene.py`](../src/orq/intervene.py), linha 156.

### 4. A promessa de não enviar caminhos ao ntfy não está garantida

A pergunta de fallback incorpora `p.reason`, que pode conter nomes de arquivos da árvore suja. O payload envia essa pergunta ao serviço. Nas decisões do conselho, pergunta e rótulos também seguem diretamente para a notificação.

Eu usaria uma mensagem externa fixa e mínima, mantendo o diagnóstico no painel.

Referências: [`src/orq/intervene.py`](../src/orq/intervene.py), linha 117; [`src/orq/notify.py`](../src/orq/notify.py), linha 58.

### 5. Os relatórios podem mostrar um encerramento antigo depois de um retry

Painel e journal procuram o primeiro `run_end`; relatórios também usam o primeiro `task_end`. Depois de `resume --retry`, podem continuar mostrando resultado, duração e entrega anteriores.

Vale identificar cada tentativa e derivar o estado atual dela, preservando as anteriores como histórico.

Referências: [`src/orq/tui/model.py`](../src/orq/tui/model.py), linha 119; [`src/orq/journal.py`](../src/orq/journal.py), linha 140.

## Outras oportunidades concretas

| Área | Situação atual | Melhoria | Referência |
|---|---|---|---|
| Processos | Cancelamento envia `SIGTERM`, sem aguardar saída nem escalar | Esperar por prazo curto e encerrar o grupo remanescente | [`harness/base.py`](../src/orq/harness/base.py), linha 157 |
| Exclusividade | PID é verificado, mas não há lock exclusivo durante toda a execução | Lock por execução e por árvore de trabalho para impedir motores concorrentes | [`cli.py`](../src/orq/cli.py), linha 48 |
| Custo | Codex retorna custo padrão zero; tentativas com erro não entram na soma | Distinguir custo desconhecido de zero e contabilizar tentativas com consumo informado | [`engine.py`](../src/orq/engine.py), linha 194 |
| Conselho | `2–1–1–1` é aceito como “maioria” | Definir maioria absoluta ou assumir explicitamente pluralidade; testar mais de três votantes | [`council.py`](../src/orq/council.py), linha 15 |
| Espera por quota | `/stop` não interrompe o `sleep` do retry | Tornar a espera sensível aos comandos, verificando pausa/parada antes de chamar novamente | [`engine.py`](../src/orq/engine.py), linha 216 |

## Desempenho

Começaria pelo I/O repetido: cada evento relê o histórico e regenera relatórios; o painel atualiza a cada 500 ms, relendo estado e arquivos das tarefas.

Cache por alteração de arquivo, um snapshot de estado por atualização e geração de relatórios agrupada devem reduzir trabalho. Não medi lentidão, então trataria isso como otimização a validar.

Referências: [`src/orq/store.py`](../src/orq/store.py), linha 100; [`src/orq/tui/app.py`](../src/orq/tui/app.py), linha 145.

## Funcionalidades com maior retorno

1. **`orq doctor`**: diagnóstico local de configuração, recursos instalados e capacidades exigidas dos harnesses.
2. **Orçamento por execução**: limite de tempo e chamadas, mais teto financeiro quando houver estimativa disponível.
3. **Worktree dedicada por execução**: isolamento do trabalho manual, com branch e repositório registrados.
4. **Conselho configurável por votante**: permitir modelos diferentes e explicitar quais decisões podem seguir automaticamente.
5. **Exportação de diagnóstico sanitizado**: estado, versões e falhas relevantes para investigar uma execução.

## Testes e limites da revisão

Localizei 80 funções de teste, incluindo retomada, takeover e intervenção. Faltam cenários especialmente valiosos:

1. Retomada pela CLI com `--repo`.
2. Retry de chamada somente leitura.
3. Queda entre consumo e aplicação de comando.
4. Parada pela opção da intervenção.
5. Relatórios após nova tentativa.

Os testes existentes de retomada reutilizam a configuração em memória e não exercitam esses caminhos completos da CLI.

Não executei testes: a skill local `security-audit` (`/home/victor/.agents/skills/security-audit/SKILL.md`) determina “Run target-controlled builds, tests […] only inside an OS-enforced sandbox”; esse isolamento não foi validado nesta sessão. Não há afirmação de que a suíte passou, nem de reprodução dinâmica dos achados.

## Prioridade sugerida

Começar pelos problemas 1–3: permissões na retomada, preservação da execução original e entrega durável de comandos e decisões.
