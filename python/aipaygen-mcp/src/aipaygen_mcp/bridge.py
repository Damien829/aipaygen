"""
Relay MCP JSON-RPC messages between stdio and the hosted AIPayGen server.

MCP clients that only speak stdio (`uvx aipaygen-mcp`) get the same tools as
connecting to https://mcp.aipaygen.com/mcp directly. Standard library only.

Environment:
  AIPAYGEN_API_KEY   optional API key (apg_...), sent as a Bearer token
  AIPAYGEN_MCP_URL   override the endpoint (default https://mcp.aipaygen.com/mcp)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from . import __version__

DEFAULT_URL = "https://mcp.aipaygen.com/mcp"
TIMEOUT_SECONDS = 120


class Bridge:
    def __init__(self, url: str, api_key: str | None) -> None:
        self.url = url
        self.api_key = api_key
        self.session_id: str | None = None
        self.protocol_version: str | None = None

    def headers(self) -> dict[str, str]:
        h = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "user-agent": f"aipaygen-mcp/{__version__} (stdio bridge)",
        }
        if self.api_key:
            h["authorization"] = f"Bearer {self.api_key}"
        if self.session_id:
            h["mcp-session-id"] = self.session_id
        if self.protocol_version:
            h["mcp-protocol-version"] = self.protocol_version
        return h

    def forward(self, message: dict) -> list[dict]:
        """POST one JSON-RPC message; return the JSON-RPC messages in the reply."""
        req = urllib.request.Request(self.url, data=json.dumps(message).encode(), headers=self.headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
                sid = res.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                body = res.read().decode("utf-8", errors="replace")
                ctype = res.headers.get("content-type", "")
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            return [self.error(message, f"AIPayGen server returned HTTP {err.code}: {body[:300]}")]
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return [self.error(message, f"Could not reach {self.url}: {err}")]

        replies = parse_body(body, ctype)
        for r in replies:
            result = r.get("result")
            if message.get("method") == "initialize" and isinstance(result, dict) and result.get("protocolVersion"):
                self.protocol_version = result["protocolVersion"]
        return replies

    @staticmethod
    def error(message: dict, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": text}}


def parse_body(body: str, content_type: str) -> list[dict]:
    """Accept either a JSON body or an SSE stream of `data:` events."""
    body = body.strip()
    if not body:
        return []
    if "text/event-stream" in content_type or body.startswith(("event:", "data:")):
        out: list[dict] = []
        data_lines: list[str] = []
        for line in body.splitlines() + [""]:
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line == "" and data_lines:
                try:
                    out.append(json.loads("\n".join(data_lines)))
                except json.JSONDecodeError:
                    pass
                data_lines = []
        return out
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print(f"aipaygen-mcp {__version__}")
        return
    bridge = Bridge(os.environ.get("AIPAYGEN_MCP_URL", DEFAULT_URL), os.environ.get("AIPAYGEN_API_KEY") or None)
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        messages = message if isinstance(message, list) else [message]
        for m in messages:
            for reply in bridge.forward(m):
                # Notifications (no id) get no reply; only write real responses/requests.
                out.write(json.dumps(reply) + "\n")
                out.flush()


if __name__ == "__main__":
    main()
