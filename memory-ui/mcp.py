"""Cliente JSON-RPC para o MCP do ai-memory."""

import json
import urllib.error
import urllib.request

URL = "http://127.0.0.1:49374/mcp"
WORKSPACE = "default"


class McpError(Exception):
    pass


def call(tool: str, args: dict, url: str = URL) -> dict:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise McpError(
            f"ai-memory {tool}: HTTP {e.code} {e.reason} → confira a URL e o header Accept"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise McpError(
            "ai-memory fora do ar em 127.0.0.1:49374 → docker start ai-memory"
        ) from e

    payload = json.loads(raw)

    if "error" in payload:
        message = payload["error"]["message"]
        raise McpError(f"ai-memory {tool}: {message} → confira os argumentos")

    result = payload["result"]
    if result.get("isError"):
        text = "".join(item["text"] for item in result["content"])
        raise McpError(f"ai-memory {tool}: {text} → confira os argumentos")

    return json.loads(result["content"][0]["text"])
