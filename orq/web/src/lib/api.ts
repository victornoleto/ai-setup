// O contrato com orq/src/orq/web/view.py. A página só lê.
export type RunRow = { id: string; queue: string; run: string; ts: string; state: string; done: number; total: number; ask: boolean };
export type TaskRow = { id: string; title: string; glyph: string; status: string; extra: string; phase: string | null; cycle: number | null; result: string | null; cost: number };
export type Entry = { i: number; ts: string; type: string; task: string; kind: string | null; result: string | null; points: number | null; line: string; attention: boolean };
export type Ask = { id: string; task: string; kind: string; question: string; diagnosis: string; options: { id: string; label: string }[]; recommended: string; deadline: number | null; reply: string };
export type Current = { task: string; phase: string; label: string; stage: string; cycle: number; role: string | null; harness: string | null; model: string | null; since: number | null };
export type RunView = {
  id: string; queue: string; repo: string; run: string; state: string; paused: boolean; started: string | null; ended: string | null;
  result: string | null; eta: number | null; cost: number; cost_partial: boolean; roles: Record<string, string>; tasks: TaskRow[];
  current: Current | null; stages: string[]; ask: Ask | null; summary: string | null; n_events: number; timeline: Entry[];
};
export type Step = { label: string; kind: string; cycle: number | null; dur: number | null; ok: boolean | null; running?: boolean; open?: boolean; waited?: number; tools?: Record<string, number> };
export type TaskView = {
  id: string; title: string; status: string; glyph: string; text: string; plan_md: string | null; decisions_md: string | null; report_md: string | null;
  validation: string[]; highlights: string[]; pending: string[]; steps: Step[];
  diff: { add: number; rem: number; nfiles: number; files: { add: number; rem: number; path: string }[] } | null;
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  const body = await r.json().catch(() => ({ error: `resposta inválida do servidor (${r.status})` }));
  if (!r.ok) throw new Error(body.error ?? `erro ${r.status}`);
  return body as T;
}

export const api = {
  runs: () => get<RunRow[]>("/api/runs"),
  run: (id: string) => get<RunView>(`/api/runs/${id}`),
  task: (id: string, tid: string) => get<TaskView>(`/api/runs/${id}/tasks/${encodeURIComponent(tid)}`),
  events: (id: string, after: number) => get<Entry[]>(`/api/runs/${id}/events?after=${after}`),
};
