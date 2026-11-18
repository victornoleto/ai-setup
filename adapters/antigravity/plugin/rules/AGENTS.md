# Notas do agy (ai-setup)

Valem só no Antigravity CLI e completam as instruções globais.

- **Subagents:** o teto de 2 em paralelo não vale para fan-out só leitura em modelo Flash
  (`run_workflow` com `model="flash"` ou `"flash_lite"`, sem editar arquivo nem rodar comando que
  escreve). Worker que escreve (`/swarm`, `/boost`, `workspace="branch"`) segue o teto.
- **Arquivo pedido por skill:** quando uma skill manda gravar plano, spec ou relatório num caminho
  (brainstorming, writing-plans, orq-setup), grave nesse caminho. O artefato em `brain/<id>/` não o
  substitui.
- **Transcript desta sessão** (handoff, retro):
  `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`.
- **`.ai/README.md`** do projeto chega no início da sessão pelo hook deste plugin. Se o arquivo existe
  e não chegou, leia antes de trabalhar.
