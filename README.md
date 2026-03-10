# AiPayGen

<!-- mcp-name: io.github.Damien829/aipaygen -->

**Pay-per-use Claude AI API for autonomous agents.** 155 tools and 140+ endpoints, USDC micropayments on Base via [x402](https://www.x402.org/), no API keys or signups required. Crypto deposits (Base + Solana), seller marketplace, and agent builder included.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI - MCP](https://img.shields.io/pypi/v/aipaygen-mcp)](https://pypi.org/project/aipaygen-mcp/)
[![PyPI - langchain](https://img.shields.io/pypi/v/aipaygen-langchain)](https://pypi.org/project/aipaygen-langchain/)
[![PyPI - llamaindex](https://img.shields.io/pypi/v/aipaygen-llamaindex)](https://pypi.org/project/aipaygen-llamaindex/)
[![npm](https://img.shields.io/npm/v/aipaygen)](https://www.npmjs.com/package/aipaygen)

## How it works

1. Agent calls any endpoint (e.g. `POST /research`)
2. First 10 calls/day are **free** — no payment needed
3. After that, the server returns **HTTP 402** with payment instructions
4. Agent signs a USDC transaction on Base and retries with an `X-Payment` header
5. Server verifies payment via [CDP x402](https://docs.cdp.coinbase.com/x402/docs/overview) and returns the result

```
Agent ──POST /research──▶ AiPayGen ──402 + payment info──▶ Agent
Agent ──POST /research + X-Payment──▶ AiPayGen ──200 + result──▶ Agent
```

## Quick start

### Try free (no setup)

```bash
curl -X POST https://api.aipaygen.com/preview \
  -H "Content-Type: application/json" \
  -d '{"query": "What is x402?"}'
```

### Python

```bash
pip install aipaygen-langchain
```

```python
from aipaygen_langchain import AiPayGenToolkit

tools = AiPayGenToolkit(x402_token="your_token").get_tools()
# Use with LangChain agents, CrewAI, etc.
```

### JavaScript / TypeScript

```bash
npm install aipaygen
```

```javascript
import { AiPayGen } from "aipaygen";
const client = new AiPayGen({ token: "your_token" });
const result = await client.research("quantum computing trends");
```

### MCP Server (Claude Desktop, Cursor, etc.)

Connect as a remote MCP server — no local install:

```
https://mcp.aipaygen.com/mcp
```

Or run locally:

```bash
pip install aipaygen-mcp
aipaygen-mcp
```

Claude Desktop config:
```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "aipaygen-mcp"
    }
  }
}
```

## Endpoints

### AI / NLP

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/research` | POST | Deep research on any topic |
| `/summarize` | POST | Compress text (bullets, paragraph, TLDR) |
| `/analyze` | POST | Structured analysis with findings |
| `/translate` | POST | Translate to any language |
| `/sentiment` | POST | Polarity, score, emotions |
| `/keywords` | POST | Extract keywords and topics |
| `/classify` | POST | Classify into custom categories |
| `/rewrite` | POST | Rewrite for audience or voice |
| `/extract` | POST | Pull structured JSON from text |
| `/qa` | POST | Q&A over a document |
| `/code` | POST | Generate code in any language |
| `/diagram` | POST | Generate Mermaid diagrams |
| `/chain` | POST | Multi-step AI pipelines |

### Web Intelligence

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scrape` | POST | Scrape any webpage |
| `/search` | POST | Web search with AI summary |
| `/research` | POST | Deep multi-source research |
| `/extract/{url}` | GET | Extract structured data from URL |
| `/scrape/tweets` | POST | Search and scrape tweets |
| `/scrape/google-maps` | POST | Google Maps business data |

### Agent Memory

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/memory/set` | POST | Store persistent key-value data |
| `/memory/get` | POST | Retrieve stored data |
| `/memory/search` | POST | Search memories by keyword |

### Discovery

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/discover` | GET | Full endpoint catalog |
| `/catalog` | GET | Browse discovered APIs |
| `/openapi.json` | GET | OpenAPI 3.0 spec |
| `/llms.txt` | GET | LLMs.txt for AI agents |
| `/.well-known/agent.json` | GET | Agent discovery manifest |
| `/preview` | POST | Free 120-token Claude demo |

Full list: [api.aipaygen.com/discover](https://api.aipaygen.com/discover)

## Architecture

- **Runtime**: Flask + Gunicorn on Raspberry Pi 5
- **AI**: Claude Haiku 4.5 via Anthropic API
- **Payments**: x402 protocol, USDC on Base Mainnet, verified via CDP
- **Tunnel**: Cloudflare Tunnel → `api.aipaygen.com`
- **Storage**: SQLite (memory, usage tracking, API keys)
- **Discovery**: OpenAPI, LLMs.txt, MCP, agents.json, ai-plugin.json

## Links

| Resource | URL |
|----------|-----|
| Live API | https://api.aipaygen.com |
| Discover endpoints | https://api.aipaygen.com/discover |
| OpenAPI spec | https://api.aipaygen.com/openapi.json |
| LLMs.txt | https://api.aipaygen.com/llms.txt |
| MCP server | https://mcp.aipaygen.com/mcp |
| Blog | https://api.aipaygen.com/blog |
| npm SDK | https://www.npmjs.com/package/aipaygen |
| PyPI (LangChain) | https://pypi.org/project/aipaygen-langchain/ |
| PyPI (LlamaIndex) | https://pypi.org/project/aipaygen-llamaindex/ |

## License

[MIT](LICENSE)
