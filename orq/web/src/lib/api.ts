// O contrato com orq/src/orq/web/view.py e server.py. Toda ação é um comando do orq (`send`), menos o texto de
// tarefa pendente (`setText`).
export type RunRow = { id: string; queue: string; run: string; ts: string; state: string; done: number; total: number; ask: boolean };
export type TaskRow = { id: string; title: string; glyph: string; status: string; extra: string; phase: string | null; cycle: number | null; result: string | null; cost: number };
export type Entry = { i: number; ts: string; type: string; task: string; kind: string | null; result: string | null; points: number | null; line: string; attention: boolean };
export type Ask = { id: string; task: string; kind: string; question: string; diagnosis: string; options: { id: string; label: string }[]; recommended: string; deadline: number | null; reply: string };
export type Current = { task: string; phase: string; label: string; stage: string; cycle: number; role: string | null; harness: string | null; model: string | null; since: number | null };
export type RunView = {
  id: string; queue: string; repo: string; run: string; state: string; paused: boolean; started: string | null; ended: string | null;
  result: string | null; eta: number | null; cost: number; cost_partial: boolean; roles: Record<string, string>; tasks: TaskRow[];
  current: Current | null; stages: string[]; ask: Ask | null; summary: string | null; n_events: number; timeline: Entry[];
  alive: boolean; pending_ops: { id: string; text: string }[]; ops: Op[]; acks: Ack[];
};
export type Op = { id: string; ts: string; text: string; reply: string; commands: string[]; applied: boolean };
export type Ack = { id: string; command: string; ok: boolean; result: string };
export type Decision = { qid: string; question: string; options: { id: string; label: string }[]; choice: string; label: string; why: string; points: number | null; by_user: boolean };
export type Step = { label: string; kind: string; cycle: number | null; dur: number | null; ok: boolean | null; running?: boolean; open?: boolean; waited?: number; tools?: Record<string, number> };
export type TaskView = {
  id: string; title: string; status: string; glyph: string; text: string; plan_md: string | null; decisions_md: string | null; report_md: string | null;
  validation: string[]; highlights: string[]; pending: string[]; steps: Step[]; decisions: Decision[]; editable: boolean; skipped: boolean;
  diff: { add: number; rem: number; nfiles: number; files: { add: number; rem: number; path: string }[] } | null;
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  const body = await r.json().catch(() => ({ error: `resposta inválida do servidor (${r.status})` }));
  if (!r.ok) throw new Error(body.error ?? `erro ${r.status}`);
  return body as T;
}

// O servidor só aceita ação com o token que veio na página: outra aba do navegador não o tem.
const token = document.querySelector<HTMLMetaElement>('meta[name="orq-token"]')?.content ?? "";

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Orq-Token": token }, body: JSON.stringify(body) });
  const out = await r.json().catch(() => ({ error: `resposta inválida do servidor (${r.status})` }));
  if (!r.ok) throw new Error(out.error ?? `erro ${r.status}`);
  return out as T;
}

export const api = {
  send: (id: string, text: string, op?: string) => post<{ id: string; alive: boolean }>(`/api/runs/${id}/send`, { text, ...(op ? { op } : {}) }),
  setText: (id: string, tid: string, text: string) => post<{ ok: true }>(`/api/runs/${id}/tasks/${encodeURIComponent(tid)}/text`, { text }),
  runs: () => get<RunRow[]>("/api/runs"),
  run: (id: string) => get<RunView>(`/api/runs/${id}`),
  task: (id: string, tid: string) => get<TaskView>(`/api/runs/${id}/tasks/${encodeURIComponent(tid)}`),
  events: (id: string, after: number) => get<Entry[]>(`/api/runs/${id}/events?after=${after}`),
};
