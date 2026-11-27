# AIPayGen

[![AIPayGen on MCPRush](https://mcprush.com/badge/aipaygen-65-ai-tools-as-an-mcp/score.svg)](https://mcprush.com/to/aipaygen-65-ai-tools-as-an-mcp?ref=badge)
[![Damien829/aipaygen MCP server](https://glama.ai/mcp/servers/Damien829/aipaygen/badges/score.svg)](https://glama.ai/mcp/servers/Damien829/aipaygen)

**Let your agent read pages that charge AI agents.** Some sites answer AI agents with HTTP 402 and an
[x402](https://aipaygen.com/x402) price per page. [AIPayGen](https://aipaygen.com)'s `paid_fetch` tool buys the
page for your agent, so your agent needs no wallet: it pays from credit you top up (USDC today). It costs the site's
price plus 15%, plus $0.001 a call. One free key per person, with up to $0.05 of trial credit for tools (not for paying sites).
Details: [aipaygen.com/docs#paid-fetch](https://aipaygen.com/docs#paid-fetch).

**Check a site's AI Terms first.** The free `ai_terms` tool reads a site's
[AI Terms](https://aipaygen.com/ai-terms) file (`/.well-known/ai-terms`) and says whether a use (search, answers,
training, agents) is allowed, priced or refused.

**Find a service before you pay.** The free `find_tool` and `search_marketplace` tools search 150,000+ APIs, MCP
servers and skills for the one that fits a job. The [x402 directory](https://aipaygen.com/x402/services) lists
4,600+ sites that sell calls over x402, each with its quoted price, our own health checks, its last check and whether its owner
proved the domain; it is also a free JSON API ([aipaygen.com/x402/api](https://aipaygen.com/x402/api)), and
[x402 for agents](https://aipaygen.com/x402/for-agents) shows how to find, judge and pay a service from code.

Plus 108 pay-per-call tools for agents (111 listed over MCP with the free helpers): web, company and domain data,
crypto, media, memory, watches and notifications.

```json
{ "mcpServers": { "aipaygen": { "command": "npx", "args": ["-y", "aipaygen-mcp"], "env": { "AIPAYGEN_API_KEY": "apg_..." } } } }
```

That works in Claude Desktop, Cursor, VS Code, Windsurf and other stdio clients. Get your free key with
`curl -X POST https://aipaygen.com/v1/keys`; paid_fetch pays sites only from credit you add to it
([aipaygen.com/billing#topup](https://aipaygen.com/billing#topup)). Claude Code connects directly:
`claude mcp add --transport http aipaygen https://aipaygen.com/mcp --header "Authorization: Bearer apg_..."`

This repository holds the open-source MCP packages. The hosted service itself is not open source.

| Package | Install | Source |
|---|---|---|
| `aipaygen-mcp` on npm | `npx -y aipaygen-mcp` | [npm/aipaygen-mcp](npm/aipaygen-mcp) |
| `aipaygen-mcp` on PyPI | `uvx aipaygen-mcp` | [python/aipaygen-mcp](python/aipaygen-mcp) |
| `aipaygent-mcp` on PyPI (old name, forwards to the above) | | [python/aipaygent-mcp-moved](python/aipaygent-mcp-moved) |

Both packages relay a stdio MCP client (Claude Desktop, Cursor, Claude Code, VS Code, Windsurf and others) to
the hosted server at `https://aipaygen.com/mcp`. You can also point a client at that URL directly.

```json
{ "mcpServers": { "aipaygen": { "command": "npx", "args": ["-y", "aipaygen-mcp"] } } }
```

Tools, prices and docs: [aipaygen.com/tools](https://aipaygen.com/tools) and [aipaygen.com/docs](https://aipaygen.com/docs).

## For websites

The site integrations (WordPress, Cloudflare Workers, Nginx, Apache, Caddy, Next.js, Express, Django), the
AI Terms spec, its JSON Schema, test vectors and a Python reader are in
[Damien829/pay-per-crawl](https://github.com/Damien829/pay-per-crawl).

## Contact

Questions, bugs and security reports: hello@aipaygen.com, or open an issue here.

## License

MIT ([LICENSE](LICENSE)) for everything in this repository.

## Name and trademarks

AIPayGen™ and the AIPayGen logo are trademarks of AIPayGen. The licence covers the code, not the name: please
don't use the name or logo for another product or package, or in a way that suggests we run or endorse it.
Saying that your tool "works with AIPayGen" is fine.
