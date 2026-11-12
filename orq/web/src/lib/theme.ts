export type Theme = "light" | "dark";

export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem("orq:theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* sem storage: segue o sistema */
  }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem("orq:theme", t);
  } catch {
    /* idem */
  }
}
