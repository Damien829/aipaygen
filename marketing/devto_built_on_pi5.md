---
title: How I Built 65+ AI Tools on a Raspberry Pi 5
published: true
tags: ai, mcp, raspberrypi, python
---

There's a gap in the MCP ecosystem that bothered me. If you want to give your AI coding assistant access to tools — web scraping, research, translation, agent memory — you either build everything yourself or cobble together a dozen different services. I wanted one MCP server that handled all of it.

So I built AiPayGen: 65+ tools, installable with `pip install aipaygen-mcp`, running on a Raspberry Pi 5 sitting on my desk.

## Why I built it

MCP (Model Context Protocol) is how AI assistants like Claude Code, Cursor, and Cline access external tools. The protocol is solid, but the tool ecosystem is fragmented. Most MCP servers offer one thing — a file reader, a web search wrapper, a database connector. If you want a full toolkit, you're managing ten different MCP servers.

I wanted a single `pip install` that gives an AI assistant access to research, writing, code generation, web scraping, data feeds, agent memory, and workflow orchestration. One server, one API key, one bill.

## The architecture

The production stack is deliberately simple:

- **Hardware:** Raspberry Pi 5, overclocked to 2.7GHz, with an NVMe SSD in a Pironman 5 case
- **Backend:** Flask application with modular route blueprints
- **Database:** SQLite for user metadata, billing, agent memory. Redis for response caching
- **MCP transport:** FastMCP with streamable-http, built on MCP SDK 1.26
- **Tunnel:** Cloudflare tunnel for HTTPS ingress
- **Package:** Published to PyPI as `aipaygen-mcp`

Here's the key architectural insight: the Pi doesn't run AI models. It routes requests. When you call the `research` tool, the Pi validates your API key, checks your balance, selects the best upstream model for the task (from 15 models across 7 providers), forwards the request, and deducts the cost. The heavy computation happens on OpenAI/Anthropic/Google infrastructure.

This means the Pi's job is essentially: auth, routing, billing, caching. An overclocked Pi 5 with an NVMe handles that fine.

```
User's IDE (Claude Code / Cursor / Cline)
    ↓ MCP protocol
AiPayGen MCP Server (local pip package)
    ↓ HTTPS
Flask API on Pi 5 (Cloudflare tunnel)
    ↓ Routes to best model
OpenAI / Anthropic / Google / DeepSeek / Mistral / Grok
```

## The tools

The 65+ tools break down into categories:

**AI tools (40+):** These are the core. Research, summarize, write, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, headline, keywords, outline, and more. Each tool has a specific prompt template optimized for its task, and the router picks the best model automatically.

```bash
# Example: summarize via REST API
curl -X POST https://api.aipaygen.com/summarize \
  -H "Authorization: Bearer apk_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your long article text here...", "length": "short"}'
```

**Web scraping (6 tools):** Google Maps businesses, Twitter/X posts, Instagram profiles, TikTok videos, YouTube transcripts, and generic website scraping. These use Apify actors under the hood.

**Agent infrastructure:** This is what I'm most interested in building out. Persistent memory (key-value with full-text search), agent-to-agent messaging, shared task boards, a knowledge base with RAG search, and a skills marketplace where agents can create and share reusable capabilities.

```python
# Inside Claude Code, the agent can:
# 1. Store something in memory
#    > Use memory_store with key "user_prefs" and value "prefers concise responses"
#
# 2. Recall it in a future session
#    > Use memory_recall with key "user_prefs"
#
# 3. Search across all memories
#    > Use memory_find with query "user preferences"
```

**Free data feeds:** Weather, crypto prices, exchange rates, holidays, current time, UUIDs, jokes, quotes. These require no API key and cost nothing.

```bash
# No key needed
curl "https://api.aipaygen.com/data/weather?city=London"
curl "https://api.aipaygen.com/data/crypto?symbols=bitcoin,ethereum"
```

## The x402 payment experiment

This is the part I find most technically interesting. Alongside traditional Stripe billing, I integrated the x402 protocol for HTTP-native micropayments.

x402 works like this: you make an API call, the server responds with HTTP 402 (Payment Required) and includes the price and a payment address in the headers. Your client signs a USDC transaction and retries the request with a payment receipt in the headers. The server verifies the payment and fulfills the request.

The result: pay-per-call API access with no signup, no API key, no account. Just a crypto wallet.

```python
# x402 payment flow (simplified)
from x402 import x402ClientSync

session = x402ClientSync(signer=your_wallet)
response = session.get("https://api.aipaygen.com/summarize")
# Payment happens automatically in the HTTP layer
```

I support Base (~2s settlement), Solana (~400ms), and Stellar (~5s). In practice, most users still prefer Stripe. But the x402 integration taught me a lot about how payments could work natively in HTTP, and I think it has real potential for agent-to-agent commerce where there's no human to enter a credit card.

## Challenges and what I learned

**Model routing is harder than it sounds.** Different models are better at different tasks. GPT-4o is strong at code generation, Claude handles nuanced writing well, Gemini has a massive context window for research. I built a routing layer that picks the model based on the tool being called, but there's a lot of room for improvement — ideally it would consider the actual input content too.

**Scraping is a maintenance nightmare.** Twitter, Instagram, and TikTok change their markup regularly. I'm using Apify's managed actors, which helps, but things still break. If you're building scraping into a product, budget significant time for maintenance.

**SQLite is underrated for this scale.** I expected to need Postgres. I don't. SQLite with WAL mode handles concurrent reads fine, and having the database as a single file makes backups trivial. I'll migrate when I need to, but that day hasn't come.

**MCP is a genuine distribution channel.** People discover tools through their IDE. When you type a question in Claude Code and it has access to a `research` tool, it just uses it. The friction is dramatically lower than "go to this website, sign up, read the docs, integrate the API."

**The Pi 5 is surprisingly capable.** I was half-joking when I started running production on it. Four months later, it's still there, still handling traffic, still stable at 2.7GHz. The NVMe SSD was the critical upgrade — SD cards can't handle the write patterns from logging and SQLite.

## What's next

I'm focused on three things:
1. **Better agent memory** — moving beyond simple key-value to support structured documents and vector search
2. **The skills marketplace** — letting agents create, share, and sell reusable capabilities
3. **More upstream models** — adding open-source models via local inference for users who want that option

## Try it

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Two commands, $0.10 free credits, no card needed. If you find it useful, I'd like to hear about it. If you don't, I'd really like to hear about that — the honest feedback is more valuable.

- Website: [aipaygen.com](https://aipaygen.com)
- Docs: [aipaygen.com/docs](https://aipaygen.com/docs)
- GitHub: [github.com/Damien829/aipaygen](https://github.com/Damien829/aipaygen)
- PyPI: [pypi.org/project/aipaygen-mcp](https://pypi.org/project/aipaygen-mcp/)
