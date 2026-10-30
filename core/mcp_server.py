"""
AiPayGen MCP Server — 65+ tools (metered + free)

Exposes all AiPayGen capabilities as MCP tools with usage metering.
Get a free API key with $0.10 trial credits (~16 calls). Unlimited with prepaid credits.

Usage:
  stdio (Claude Code / Cursor / Cline):
    python mcp_server.py

  SSE (deployed):
    python mcp_server.py --http

  With API key (unlimited):
    AIPAYGEN_API_KEY=apk_xxx python mcp_server.py

Add to Claude Code:
  claude mcp add aipaygen -- python /path/to/mcp_server.py
"""

import sys
import os
import json as _json

sys.path.insert(0, os.path.dirname(__file__))

# Import the mcp_tools package — this registers all tools on the shared mcp instance
from mcp_tools import mcp, get_popular_tools  # noqa: F401


def main():
    if "--http" in sys.argv:
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        import uvicorn

        starlette_app = mcp.streamable_http_app()

        async def health(request):
            from helpers import APP_VERSION
            tool_count = len(mcp._tool_manager._tools) if hasattr(mcp, '_tool_manager') and hasattr(mcp._tool_manager, '_tools') else 250
            return JSONResponse({"status": "ok", "server": "AiPayGen MCP", "tools": tool_count, "version": APP_VERSION})

        _tracked_sessions = set()

        @starlette_app.middleware("http")
        async def mcp_connect_tracker(request, call_next):
            """Track unique MCP client connections per session."""
            response = await call_next(request)
            if request.url.path == "/mcp" and request.method == "POST":
                try:
                    from funnel_tracker import log_event
                    ip = request.headers.get("cf-connecting-ip",
                         request.client.host if request.client else "unknown")
                    session_key = f"{ip}:{request.headers.get('mcp-session-id', '')}"
                    if session_key not in _tracked_sessions:
                        _tracked_sessions.add(session_key)
                        client_info = request.headers.get("user-agent", "unknown")
                        log_event("mcp_connection", ip=ip,
                                  metadata=_json.dumps({"client": client_info[:100]}))
                        if len(_tracked_sessions) > 10000:
                            _tracked_sessions.clear()
                except Exception:
                    pass
            return response

        # Mount SSE app for legacy clients at /sse
        sse_app = mcp.sse_app()
        from starlette.routing import Mount
        starlette_app.routes.insert(0, Route("/health", health))
        starlette_app.routes.append(Mount("/sse", app=sse_app))

        uvicorn.run(starlette_app, host="127.0.0.1", port=5002)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
