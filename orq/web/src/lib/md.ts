import DOMPurify from "dompurify";
import { marked } from "marked";

// Link de fora abre em outra aba; link relativo (o report aponta para arquivos do run dir) vira texto.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName !== "A") return;
  if (/^https?:\/\//.test(node.getAttribute("href") ?? "")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  } else {
    node.removeAttribute("href");
  }
});

// Plano, report e decisões são texto escrito por modelo: nunca entra na página sem sanitizar.
export function md(text: string | null | undefined): string {
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true }) as string, { FORBID_TAGS: ["img", "style", "form"] });
}
