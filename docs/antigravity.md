# Antigravity CLI (`agy`): modelos e modos

Como escolher o modelo e o modo de permissão no `agy`. Como as instruções, as skills e a memória chegam até
ele está em [instrucoes.md](instrucoes.md), [skills.md](skills.md) e [ai-memory.md](ai-memory.md).

## Qual modelo para qual tarefa

Fonte: [antigravity.google/docs/models](https://antigravity.google/docs/models), lida em 2026-11-17 com o
plano Google AI Ultra. `agy models` lista o que a sua conta tem.

| Tarefa | Modelo | Por quê |
|---|---|---|
| Padrão: feature, bug, refatoração, debug em vários arquivos | **Orchestrator (Carbon)** | O Carbon planeja só lendo, o Hydrogen implementa, e o controle volta ao Carbon quando algo trava. Termina mais rápido e gasta menos tokens que o Carbon sozinho |
| Raciocínio máximo em cada passo: arquitetura, condição de corrida, migração entre repositórios | **Gemini 4 Carbon (High)** | O planejador sem o executor: profundidade do começo ao fim |
| Tarefa rápida e bem definida: upgrade de pacote, boilerplate, teste unitário, doc, script | **Gemini 4 Hydrogen** | Rápido e leve. Se emperrar, `xhigh` (só ele tem esse nível) |
| Pergunta trivial e fan-out em `run_workflow` | **Gemini 3.8 Flash** | O mais barato. A doc não descreve o uso dele |

- **Argon ou Carbon:** a doc recomenda os dois para as mesmas tarefas e não diz qual é melhor. O Carbon e o
  Orchestrator (Carbon) só existem no Ultra; o Argon é o planejador do Pro. No Ultra, prefira o Carbon.
- **Esforço** (`Low`, `Medium`, `High`): faz parte do nome do modelo. O Orchestrator tem esforço fixo.
- **Claude e GPT:** Claude 4.6 e GPT-OSS 120B saem em 2026-11-18, segundo a doc. O Ultra inclui o
  Claude 5.5; use-o quando aparecer em `agy models`.

### Como trocar

| Onde | Comando | Dura |
|---|---|---|
| Dentro do agy | `/model`, `/effort` | Vira o padrão: o agy grava em `~/.gemini/antigravity-cli/settings.json` |
| Uma sessão | `agy --model <id>` (os ids vêm de `agy models`) | Só aquela sessão |
| Máquina nova | `model` em [`adapters/antigravity/settings.json`](../adapters/antigravity/settings.json) | Até o primeiro `/model` |

### Cota

São dois limites, cada um com janela de 5 horas e semanal: **Gemini Models** (todos os Gemini, inclusive o
Orchestrator) e **Claude and GPT models**. Quando um acaba, o outro continua. `/quota` mostra o que resta, e
o [ai-usage](usage.md) guarda o histórico. O consumo depende do trabalho que o agente faz, não do número de
prompts.

## Modo de permissão

| Comando | Comandos de shell | Quando usar |
|---|---|---|
| `agy` | Pede aprovação; edição mostra o diff antes de gravar | Padrão |
| `agy --mode auto` | Rodam no sandbox sem pedir. Pede só quando o comando precisa sair do sandbox | Tarefa longa em repositório confiável |
| `xagy` | Rodam fora do sandbox, sem pedir | Só quando o sandbox atrapalha |

O sandbox bloqueia escrita fora do workspace e corta a rede. Esconde `~/.ssh` e `.env`. No Ubuntu 24.04, ele e
o modo `auto` dependem do perfil AppArmor `agy-userns` ([seguranca.md](seguranca.md)), e o `doctor.sh`
confere. Até no `xagy`, os bloqueios de leitura de credencial do `settings.json` continuam valendo.
