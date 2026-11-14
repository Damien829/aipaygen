# Where to list AIPayGen

Each directory below is somewhere agents or their developers search for tools. Most take five minutes and need your account, so they're yours to submit. Everything to paste is here.

## The copy

Numbers are from the live catalog on 2026-11-14. Update them before each submission.

**Name:** AIPayGen

**One line (100 characters max):** 17k+ agent APIs, MCP servers and skills to search, plus an x402 facilitator and pay-per-call tools

**Short description:**
AIPayGen is a marketplace for AI agents. Agents search 17,000+ resources for free: 9,700+ APIs (many payable with x402), 1,200+ MCP servers, 4,000+ runnable skills, 950+ agents and 1,500+ services, with health checks and trust scores so dead listings drop out. It runs a non-custodial x402 facilitator (verify and settle on Base), and pay-per-call tools for website and company intelligence: DNS, WHOIS/RDAP, certificates, tech stack, email security and page-to-markdown. Agents pay per call in USDC with x402 (no account), or with prepaid credits. Failed calls are never charged.

**Links:**
- MCP (Streamable HTTP): `https://mcp.aipaygen.com/mcp`
- Website: `https://aipaygen.com`
- Marketplace: `https://aipaygen.com/market`
- x402 facilitator: `https://aipaygen.com/facilitator`
- OpenAPI: `https://aipaygen.com/openapi.json`
- llms.txt: `https://aipaygen.com/llms.txt`
- A2A agent card: `https://aipaygen.com/.well-known/agent-card.json`
- x402 resources: `https://aipaygen.com/.well-known/x402`
- Repository: `https://github.com/Damien829/aipaygen`

**Tags:** mcp, x402, x402-facilitator, a2a, ai-agents, marketplace, api-directory, skills, web-intelligence, pay-per-call, usdc, base

### Ready-to-paste entries

**awesome-mcp-servers** (punkpeye/awesome-mcp-servers, section "Aggregators", needs the Glama listing first for the badge):

```
- [Damien829/aipaygen](https://github.com/Damien829/aipaygen) [![Damien829/aipaygen MCP server](https://glama.ai/mcp/servers/Damien829/aipaygen/badges/score.svg)](https://glama.ai/mcp/servers/Damien829/aipaygen) 📇 ☁️ - Free search of 17k+ APIs, MCP servers and skills, health-checked and trust-ranked. Runs skills, sells web intel via x402 and hosts an x402 facilitator.
```

**awesome-x402** (xpaysh/awesome-x402, section "Facilitators", hosted). Submit once the Base mainnet fee wallet is funded, so merchants who read it can settle real payments:

```
- [AIPayGen](https://aipaygen.com/facilitator) - Non-custodial x402 facilitator on Base and Base Sepolia (exact scheme, USDC). Open /verify, /settle with a free API key, per-merchant settlement stats, and a 17k-listing agent marketplace on the same domain.
```

## Directories, most valuable first

| # | Where | How | Notes |
|---|---|---|---|
| 1 | **Official MCP Registry** | `mcp-publisher login github` then `mcp-publisher publish` (uses `server.json`, already updated to 2.1.0) | Feeds many MCP clients and other directories automatically. |
| 2 | **x402 Bazaar** | Automatic. Our 402 responses carry Bazaar metadata, and resources are cataloged once paid calls settle through the facilitator. | Make one real paid call after deploy to get listed. |
| 3 | **Smithery** | Closed to new submissions (curated-only since 2026-10-31, now part of Arcade) | Skip. |
| 4 | **Glama** | glama.ai/mcp/servers → Add; `glama.json` is already in the repo | Claims via GitHub. |
| 5 | **PulseMCP** | Submissions paused (checked 2026-11-14); it imports from the MCP Registry, where we're already published | Nothing to do. |
| 6 | **mcp.so** | Only a $39 paid listing is offered (checked 2026-11-14) | Skip (free hosting only). |
| 7 | **awesome-x402** | Pull request to xpaysh/awesome-x402 (Facilitators section; entry above) | After the mainnet fee wallet is funded. |
| 8 | **awesome-mcp-servers** | Pull request to punkpeye/awesome-mcp-servers (Aggregators; entry above) | Needs the Glama listing first. |
| 9 | **Google Search Console + Bing Webmaster Tools** | Verify aipaygen.com, then submit `https://aipaygen.com/sitemap.xml` | Gets the 17,000+ marketplace pages indexed faster, which also feeds AI answer engines. |
| 10 | **PyPI** (`aipaygen-mcp` 2.0.0 is already there) | Bump the description to mention the marketplace on the next release | |

## After listing

- Watch `/admin/stats` (Worker) for which channel brings paid calls.
- Re-submit the MCP Registry whenever `server.json`'s version changes.
