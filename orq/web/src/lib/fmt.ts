export function hms(s: number | null | undefined): string {
  if (s == null) return "";
  const n = Math.max(0, Math.floor(s));
  const p = (v: number) => String(v).padStart(2, "0");
  return `${p(Math.floor(n / 3600))}:${p(Math.floor((n % 3600) / 60))}:${p(n % 60)}`;
}

export function dur(s: number | null | undefined): string {
  if (s == null) return "em curso";
  const n = Math.floor(s);
  if (n < 60) return `${n} s`;
  if (n < 3600) return `${Math.floor(n / 60)} min`;
  return `${Math.floor(n / 3600)} h ${String(Math.floor((n % 3600) / 60)).padStart(2, "0")}`;
}

export function clock(epoch: number | null): string {
  return epoch ? new Date(epoch * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";
}

export function ago(seconds: number): string {
  if (seconds < 90) return "agora há pouco";
  if (seconds < 3600) return `há ${Math.round(seconds / 60)} min`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h < 48 ? `há ${h} h${m ? ` ${m} min` : ""}` : `há ${Math.round(h / 24)} dias`;
}
