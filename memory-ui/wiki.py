"""Listagem de projetos e páginas da wiki do ai-memory via docker exec."""

import re
import subprocess

PROJECTS_SCRIPT = r"""
for m in /data/wiki/*/*/_meta.md; do
  d=${m%/_meta.md}
  name=$(sed -n 's/^project:[ ]*//p' "$m" | head -n 1)
  n=$(find "$d" -name '*.md' ! -path "$d/_pending/*" ! -name _meta.md | wc -l)
  printf '%s\t%s\n' "$name" "$n"
done
"""

PAGES_SCRIPT = r"""
m=$(grep -lxF -- "project: $1" /data/wiki/*/*/_meta.md | head -n 1)
if [ -z "$m" ]; then
  echo "wiki: projeto '$1' não encontrado → confira o nome na lista de projetos" >&2
  exit 3
fi
cd "${m%/_meta.md}" || exit 1
find . -name '*.md' ! -path './_pending/*' ! -name _meta.md -exec awk '
function emit() { if (path != "") printf "%s\t%s\t%s\n", path, title, kind }
FNR == 1 { emit(); path = substr(FILENAME, 3); title = ""; kind = ""; fm = ($0 == "---"); next }
fm && $0 == "---" { fm = 0; next }
fm && /^title:/ { title = $0; sub(/^title:[ ]*/, "", title); gsub(/\t/, " ", title) }
fm && /^kind:/ { kind = $0; sub(/^kind:[ ]*/, "", kind); gsub(/\t/, " ", kind) }
END { emit() }
' {} +
"""

PROJECT_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


class WikiError(Exception):
    pass


def run(script: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "exec", "ai-memory", "sh", "-c", script, "sh", *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except FileNotFoundError as e:
        raise WikiError(
            "docker: comando não encontrado → instale o docker ou confira o PATH"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise WikiError(
            "docker exec ai-memory: sem resposta em 15 s → confira docker ps"
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        if "is not running" in stderr or "No such container" in stderr:
            raise WikiError(
                "container ai-memory parado → docker start ai-memory"
            ) from e
        # Convenção deste módulo: scripts saem com 3 quando já escreveram em
        # stderr uma mensagem pronta no formato "local: causa → correção".
        if e.returncode == 3:
            raise WikiError(stderr) from e
        raise WikiError(
            f"docker exec ai-memory: {stderr or 'saída ' + str(e.returncode)} → confira docker logs ai-memory"
        ) from e
    return result.stdout


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse_projects(text: str) -> list[dict]:
    projects = []
    for line in text.splitlines():
        if not line:
            continue
        name, pages = line.split("\t")
        projects.append({"name": name, "pages": int(pages)})
    projects.sort(key=lambda p: p["name"])
    return projects


def parse_pages(text: str) -> list[dict]:
    pages = []
    for line in text.splitlines():
        if not line:
            continue
        path, title, kind = line.split("\t")
        title = _strip_quotes(title)
        kind = _strip_quotes(kind)
        if not title:
            title = path.rsplit("/", 1)[-1]
        group = path.split("/", 1)[0] if "/" in path else "(raiz)"
        pages.append({"path": path, "title": title, "kind": kind, "group": group})
    pages.sort(key=lambda p: p["path"])
    return pages


def list_projects() -> list[dict]:
    return parse_projects(run(PROJECTS_SCRIPT))


def list_pages(project: str) -> list[dict]:
    if not PROJECT_NAME_RE.fullmatch(project):
        raise WikiError(
            f"wiki: nome de projeto inválido {project!r} → use só letras, números, . _ -"
        )
    return parse_pages(run(PAGES_SCRIPT, project))
