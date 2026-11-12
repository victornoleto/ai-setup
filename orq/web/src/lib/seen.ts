// "Desde a sua última visita": por execução, quantos eventos já tinham sido vistos e quando. Fica no navegador.
type Seen = { n: number; at: number };
const key = (run: string) => `orq:seen:${run}`;

export function readSeen(run: string): Seen | null {
  try {
    const v = JSON.parse(localStorage.getItem(key(run)) ?? "null");
    return v && typeof v.n === "number" ? v : null;
  } catch {
    return null;
  }
}

export function writeSeen(run: string, n: number): void {
  try {
    localStorage.setItem(key(run), JSON.stringify({ n, at: Date.now() }));
  } catch {
    /* navegação privada: a tela segue sem o resumo */
  }
}
