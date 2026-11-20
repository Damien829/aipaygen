# aipaygen-mcp

[AIPayGen](https://aipaygen.com) tools for any MCP client that speaks stdio: Claude Desktop, Cursor,
Claude Code, VS Code, Windsurf and others. It relays to the hosted server at
`https://mcp.aipaygen.com/mcp` and has no dependencies.

**Read pages that charge AI agents.** `paid_fetch` buys a page that answers HTTP 402 (x402) for your agent from
credit you buy (card or USDC): no wallet. It costs the site's price plus 15%, plus $0.001 a call; set
`AIPAYGEN_API_KEY` to your key. One free key per person, with $0.05 of trial credit for tools (not for paying sites):
`curl -X POST https://aipaygen.com/v1/keys`. `ai_terms` (free) says what a site's AI Terms allow before you read.

**Plus 100+ tools for AI agents**, most paid per call: web search and page-to-markdown, company and domain
data (DNS, WHOIS, SSL, tech stack, email security), crypto and DeFi data, image, speech and document
tools, plus memory, watches, schedules and notifications for agents. Search 22,000+ APIs and MCP
servers for free with `search_marketplace`.

## Install

Node 18+:

```json
{
  "mcpServers": {
    "aipaygen": { "command": "npx", "args": ["-y", "aipaygen-mcp"] }
  }
}
```

Python 3.8+ (same tools):

```json
{
  "mcpServers": {
    "aipaygen": { "command": "uvx", "args": ["aipaygen-mcp"] }
  }
}
```

Claude Code: `claude mcp add aipaygen -- npx -y aipaygen-mcp`

Prefer a remote server? Point your client at `https://mcp.aipaygen.com/mcp` directly (streamable HTTP).

## Pay as you go

- **No key:** 3 calls a day are free on tools up to $0.005. Paid tools answer with an
  [x402](https://aipaygen.com/x402) price your agent can pay in USDC on Base, wallet to wallet.
- **Prepaid key:** add `"env": { "AIPAYGEN_API_KEY": "apg_..." }`. One free key per person, with $0.05 of trial
  credit for tools (not for paying sites), from the `create_api_key` tool or at [aipaygen.com/tools](https://aipaygen.com/tools); top up at
  [aipaygen.com/billing](https://aipaygen.com/billing). Prepaid credit is held by us until you spend it.

Failed calls are never charged, with one exception: `paid_fetch` (buying a page from another site)
can't refund the site's price once the site was sent the payment. Prices for every tool:
[aipaygen.com/tools](https://aipaygen.com/tools).

## Fewer tools, better choices

Agents pick tools more reliably from a short list. Load just one set with `--toolset`
(or `AIPAYGEN_TOOLSET`):

| Set | For |
|---|---|
| `web` | search, page to markdown, crawl, summaries, papers, news |
| `company` | company profiles, domains, DNS, WHOIS, SSL, tech stack, email checks |
| `crypto` | prices, wallets, tokens, DeFi, gas, sanctions checks |
| `media` | images, speech, transcription, documents, plus AI text tools (ask an LLM, classify, embed) |
| `agent` | memory, watches, schedules, notifications, asking a human, your account |
| `data` | weather, geocoding, currencies, economics, stocks, books, drugs, clinical trials, regulations |
| `dev` | text utilities, JWT decode, data conversion, packages and vulnerabilities, IPs, redirects |
| `site` | AI crawler and AI visibility checks, verify a bot, AI Terms |

```json
{ "mcpServers": { "aipaygen-web": { "command": "npx", "args": ["-y", "aipaygen-mcp", "--toolset", "web"] } } }
```

Every set also includes the free `search_marketplace`, `find_tool`, `create_api_key` and `account_balance`.

## Options

| Variable / flag | |
|---|---|
| `AIPAYGEN_API_KEY` | optional prepaid key (`apg_...`) |
| `AIPAYGEN_TOOLSET`, `--toolset` | `web`, `company`, `crypto`, `media`, `agent`, `data`, `dev` or `site` |
| `AIPAYGEN_MCP_URL` | override the server URL |
| `--version`, `--help` | |

Docs: [aipaygen.com/docs](https://aipaygen.com/docs) · Source: [github.com/Damien829/aipaygen](https://github.com/Damien829/aipaygen/tree/rebuild/npm/aipaygen-mcp) · MIT licence
