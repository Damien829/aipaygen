# AiPayGent MCP Server

**65+ AI-powered tools for Claude, Cursor, Windsurf, and any MCP-compatible AI agent.**

Research, write, code, translate, analyze, scrape the web, store agent memory, and more — all through a single MCP server.

## Quick Start

```bash
pip install aipaygent-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aipaygent": {
      "command": "aipaygent-mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add aipaygent -- aipaygent-mcp
```

### Cursor / Windsurf

Add to your MCP config:

```json
{
  "aipaygent": {
    "command": "aipaygent-mcp"
  }
}
```

## What You Get

| Category | Tools |
|----------|-------|
| **AI Writing** | research, write, summarize, translate, rewrite, proofread, email, headline, social |
| **AI Analysis** | analyze, sentiment, classify, compare, score, fact, keywords, extract, tag |
| **AI Code** | code, sql, regex, test_cases, json_schema, mock |
| **AI Reasoning** | plan, decide, explain, debate, outline, questions, action, timeline, pitch |
| **Advanced AI** | vision (image analysis), rag (document Q&A), diagram, workflow, pipeline, chat |
| **Web Scraping** | Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website |
| **Data** | weather, crypto prices, exchange rates, holidays, web search |
| **Agent Memory** | store, recall, search, list — persistent memory across sessions |
| **Marketplace** | list services, post your own agent services for others to discover |

## API Key (Optional)

Free tier gives you 10 calls/day with no key needed.

For unlimited access, set your API key:

```bash
export AIPAYGENT_API_KEY="apk_your_key_here"
```

Get a key at [api.aipaygent.xyz/buy-credits](https://api.aipaygent.xyz/buy-credits) — plans start at $5.

## How It Works

AiPayGent acts as middleware between your AI agent and powerful APIs:

```
Your AI Agent (Claude/Cursor/etc.)
    ↓ MCP protocol
AiPayGent MCP Server (this package)
    ↓ HTTPS
api.aipaygent.xyz (65+ endpoints)
    ↓
Claude, GPT-4, web APIs, scrapers, etc.
```

Your agent gets instant access to research, writing, code generation, web scraping, and more — without managing API keys for each service individually.

## Links

- **API Docs**: [api.aipaygent.xyz/discover](https://api.aipaygent.xyz/discover)
- **GitHub**: [github.com/djautomd-lab/aipaygent](https://github.com/djautomd-lab/aipaygent)
- **Buy Credits**: [api.aipaygent.xyz/buy-credits](https://api.aipaygent.xyz/buy-credits)

## License

MIT
