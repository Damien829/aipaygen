# aipaygen-mcp

[![PyPI version](https://img.shields.io/pypi/v/aipaygen-mcp.svg)](https://pypi.org/project/aipaygen-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)

An open-source [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that gives AI agents access to 100+ tools across research, code generation, web scraping, data transforms, NLP, and more.

Works with **Claude Code**, **Claude Desktop**, **Cursor**, **Windsurf**, **Cline**, and any MCP-compatible client.

## How it works

```
Your AI Agent (Claude, Cursor, etc.)
        |
    MCP protocol (stdio or streamable-http)
        |
aipaygen-mcp (this package — open source client)
        |
    HTTPS requests
        |
Backend API (hosted or self-hosted)
```

`aipaygen-mcp` is a thin MCP server that translates tool calls from your AI agent into API requests. The client itself is fully open source and MIT-licensed. You can point it at the hosted API or run your own backend.

## Installation

```bash
pip install aipaygen-mcp
```

Requires Python 3.10+. The only dependency is `mcp>=1.0.0`.

### Verify it works

```bash
aipaygen-mcp --test
```

## Setup

### Claude Code

```bash
claude mcp add aipaygen -- aipaygen-mcp
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "aipaygen-mcp"
    }
  }
}
```

### Cursor / Windsurf / Cline

Add to your MCP config file:

```json
{
  "aipaygen": {
    "command": "aipaygen-mcp"
  }
}
```

## Configuration

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AIPAYGEN_API_KEY` | No | API key for authenticated access. Without a key, the free tier applies (10 calls/day). |
| `AIPAYGEN_BASE_URL` | No | Override the backend URL. Defaults to `https://api.aipaygen.com`. Set this to point at a self-hosted instance. |

```bash
# Example: use with an API key
export AIPAYGEN_API_KEY="apk_your_key_here"
aipaygen-mcp

# Example: point at a local backend
AIPAYGEN_BASE_URL=http://localhost:5001 aipaygen-mcp
```

### Transport modes

```bash
aipaygen-mcp          # stdio (default, for Claude Desktop / Cursor / etc.)
aipaygen-mcp --http   # streamable-http (for remote MCP clients)
aipaygen-mcp --test   # connectivity self-test
```

## Available tools

The server exposes tools organized into categories:

| Category | Examples | Count |
|----------|----------|-------|
| AI Writing | `research`, `write`, `summarize`, `translate`, `rewrite`, `proofread` | 10 |
| AI Analysis | `analyze`, `sentiment`, `classify`, `compare`, `extract`, `score` | 10 |
| AI Code | `code`, `sql`, `regex`, `test_cases`, `json_schema`, `review_code` | 10 |
| AI Reasoning | `plan`, `decide`, `explain`, `debate`, `think`, `outline` | 9 |
| Advanced AI | `vision`, `rag`, `diagram`, `workflow`, `pipeline`, `batch` | 8 |
| Web Scraping | `scrape_website`, `scrape_tweets`, `scrape_youtube` | 6 |
| Data Feeds | `get_weather`, `get_crypto_prices`, `web_search`, `stock_history` | 7 |
| Agent Memory | `memory_store`, `memory_recall`, `memory_find`, `memory_keys` | 4 |
| Agent Network | `register_my_agent`, `send_agent_message`, `browse_agent_tasks` | 10 |
| API Catalog | `browse_catalog`, `get_catalog_api`, `invoke_catalog_api` | 3 |
| Location & Domain | `geocode`, `whois_lookup`, `domain_profile`, `company_search` | 5 |
| Web Analysis | `url_meta`, `ssl_info`, `security_headers_audit`, `techstack_detect` | 9 |
| NLP & Transforms | `entity_extraction`, `text_similarity`, `json_to_csv`, `xml_to_json` | 10 |
| Finance & Math | `currency_convert`, `math_evaluate`, `unit_convert`, `math_stats` | 7 |
| Date & Time | `datetime_between`, `business_days`, `unix_timestamp` | 3 |

Each tool has full docstrings — your AI agent will see descriptions and parameter types automatically via MCP.

## Architecture

The codebase is intentionally simple:

```
src/aipaygen_mcp/
    __init__.py      # Package version
    server.py        # MCP server — tool definitions and API client
```

`server.py` does two things:
1. Registers MCP tools using `FastMCP` from the official `mcp` SDK
2. Proxies tool calls to a backend API via `urllib` (no extra HTTP dependencies)

Each tool is a thin wrapper:

```python
@mcp.tool()
def research(topic: str) -> dict:
    """Research any topic. Returns structured summary, key points, and sources."""
    return _call("research", {"question": topic})
```

The `_call()` and `_get()` helpers handle HTTP requests, auth headers, and error formatting. That's it.

## Development

### Clone and install in development mode

```bash
git clone https://github.com/Damien829/aipaygen.git
cd aipaygen
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/
```

### Run the server locally

```bash
python -m aipaygen_mcp.server
```

### Adding a new tool

1. Add a function in `src/aipaygen_mcp/server.py` with the `@mcp.tool()` decorator
2. Use `_call()` for POST endpoints or `_get()` for GET endpoints
3. Write a clear docstring (this is what the AI agent sees)
4. Add a test in `tests/`
5. Open a PR

## Self-hosting the backend

The MCP client can point at any compatible backend. Set `AIPAYGEN_BASE_URL` to your own server:

```bash
AIPAYGEN_BASE_URL=http://localhost:5001 aipaygen-mcp
```

The backend expects the same REST endpoint structure (`POST /research`, `GET /data/weather`, etc.). See the [API documentation](https://api.aipaygen.com/discover) for the full endpoint list and expected request/response formats.

## Hosted API

A hosted version of the backend is available at `api.aipaygen.com` and works out of the box with no configuration. Free tier includes 10 calls/day. API keys for higher usage can be obtained at [api.aipaygen.com/buy-credits](https://api.aipaygen.com/buy-credits).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting issues and pull requests.

## License

[MIT](LICENSE) — use it however you want.
