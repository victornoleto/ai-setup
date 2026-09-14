// Injeta o índice de memória portátil resolvido em toda sessão do OpenCode.
// O Claude Code faz isso nativamente (autoMemoryDirectory) e o Codex faz por hook
// SessionStart; sem este plugin, o OpenCode dependia de o modelo rodar
// `agent-memory index` sozinho, conforme o PROTOCOL.md.
import { execFileSync } from "node:child_process"
import { existsSync, rmSync, writeFileSync } from "node:fs"

const SETUP = `${process.env.HOME}/.ai-setup`
const BIN = `${SETUP}/bin/agent-memory`
const run = (...args) => execFileSync(BIN, args, { encoding: "utf8" }).trim()

export const PortableMemory = async ({ directory, worktree }) => ({
	config: async (config) => {
		const cwd = worktree || directory
		let dir
		try {
			dir = run("dir", cwd)
		} catch {
			return // raiz fora do registro: não inventar memória, conforme a regra 11
		}
		const index = `${dir}/MEMORY.md`
		if (!existsSync(index)) return
		config.instructions = [...(config.instructions ?? []), index]

		// O lembrete do nudge é texto, e instructions só aceita caminho — daí o arquivo.
		// Fica em local/: é estado desta máquina, não conteúdo do acervo.
		const notice = `${SETUP}/local/notices/${dir.split("/").pop()}`
		const text = run("nudge", cwd)
		if (text) {
			writeFileSync(notice, `${text}\n`)
			config.instructions.push(notice)
		} else {
			rmSync(notice, { force: true })
		}
	},
})
