# AIPayGen

[![AiPayGen — 65+ AI Tools as an MCP on mcprush](https://mcprush.com/badge/aipaygen-65-ai-tools-as-an-mcp/score.svg)](https://mcprush.com/to/aipaygen-65-ai-tools-as-an-mcp?ref=badge)

**Let your agent read pages that charge AI agents.** Some sites answer AI agents with HTTP 402 and an
[x402](https://aipaygen.com/x402) price per page. [AIPayGen](https://aipaygen.com)'s `paid_fetch` tool buys the
page for your agent from credit you buy (card or USDC): no wallet, no crypto setup. It costs the site's price plus
15%, plus $0.001 a call. One free key per person, with $0.05 of trial credit for tools (not for paying sites).
Details: [aipaygen.com/docs#paid-fetch](https://aipaygen.com/docs#paid-fetch).

**Check a site's AI Terms first.** The free `ai_terms` tool reads a site's
[AI Terms](https://aipaygen.com/ai-terms) file (`/.well-known/ai-terms`) and says whether a use (search, answers,
training, agents) is allowed, priced or refused.

Plus 100+ tools for agents, most paid per call: web, company and domain data, crypto, media,
memory, watches and notifications.

```json
{ "mcpServers": { "aipaygen": { "command": "npx", "args": ["-y", "aipaygen-mcp"], "env": { "AIPAYGEN_API_KEY": "apg_..." } } } }
```

That works in Claude Desktop, Cursor, VS Code, Windsurf and other stdio clients. Get your free key with
`curl -X POST https://aipaygen.com/v1/keys`; paid_fetch pays sites only from credit you add to it
([aipaygen.com/billing#topup](https://aipaygen.com/billing#topup)). Claude Code connects directly:
`claude mcp add --transport http aipaygen https://mcp.aipaygen.com/mcp --header "Authorization: Bearer apg_..."`

This repository holds the open-source MCP packages. The hosted service itself is not open source.

| Package | Install | Source |
|---|---|---|
| `aipaygen-mcp` on npm | `npx -y aipaygen-mcp` | [npm/aipaygen-mcp](npm/aipaygen-mcp) |
| `aipaygen-mcp` on PyPI | `uvx aipaygen-mcp` | [python/aipaygen-mcp](python/aipaygen-mcp) |
| `aipaygent-mcp` on PyPI (old name, forwards to the above) | | [python/aipaygent-mcp-moved](python/aipaygent-mcp-moved) |

Both packages relay a stdio MCP client (Claude Desktop, Cursor, Claude Code, VS Code, Windsurf and others) to
the hosted server at `https://mcp.aipaygen.com/mcp`. You can also point a client at that URL directly.

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
