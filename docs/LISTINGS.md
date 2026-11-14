# Where to list AIPayGen

Each directory below is somewhere agents or their developers search for tools. Most take five minutes and need your account, so they're yours to submit. Everything to paste is here.

## The copy

Numbers are from the live catalog on 2026-11-14. Update them before each submission.

**Name:** AIPayGen

**One line (100 characters max):** 19k+ agent APIs, MCP servers and skills to search, 40 pay-per-call tools and an x402 facilitator

**Short description:**
AIPayGen is a marketplace for AI agents. Agents search 19,000+ resources for free: 11,000+ APIs (many payable with x402), 1,500+ MCP servers, 3,900+ runnable skills, 950+ agents and 1,500+ services, with health checks and trust scores so dead listings drop out. It runs a non-custodial x402 facilitator (verify and settle on Base), and pay-per-call tools for website and company intelligence: DNS, WHOIS/RDAP, certificates, tech stack, email security and page-to-markdown. Agents pay per call in USDC with x402 (no account), or with prepaid credits. Failed calls are never charged.

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
| 9 | **Google Search Console + Bing Webmaster Tools** | Verify aipaygen.com, then submit `https://aipaygen.com/sitemap.xml` | Gets the 19,000+ marketplace pages indexed faster, which also feeds AI answer engines. |
| 10 | **PyPI** (`aipaygen-mcp` 2.0.0 is already there) | Bump the description to mention the marketplace on the next release | |

### x402 ecosystem (added 2026-11-14)

| # | Where | How | Status |
|---|---|---|---|
| 11 | **Coinbase CDP Bazaar / Agentic.Market** | Automatic once a tool settles through CDP (CDP key set 2026-11-14) | In progress: paid pass running |
| 12 | **x402scan** (x402scan.com) | Resources → Register: submit `https://aipaygen.com/openapi.json`; it probes each endpoint for a real 402 | Free web form |
| 13 | **x402scan facilitators** | PR to Merit-Systems/x402scan adding us to `facilitators/config.ts` (URL `https://aipaygen.com/facilitator`, Base + Base Sepolia, payer addresses from `/facilitator/supported`) | PR |
| 14 | **x402.eco** | PR to xzntexe/x402eco: one JSON file in `facilitators/` and one in `services-endpoints/` | PR |
| 15 | **x402 Registry** | Issue on ralf9090/x402-registry (facilitator and API applications): identity, endpoints, settlement evidence (a BaseScan tx, never keys) | GitHub issue |
| 16 | **x402.org ecosystem page** | PR to coinbase/x402 per its site README (Facilitators and Services) | PR |
| 17 | **awesome-agentic-commerce** | PR to Merit-Systems/awesome-agentic-commerce (Marketplaces; Facilitators) | PR |

**Facilitator one-liner:** AIPayGen facilitator — non-custodial x402 verify/settle on Base and Base Sepolia; settles from its own wallet or routes to PayAI/CDP with failover, so merchants always get gasless settlement at one URL. `https://aipaygen.com/facilitator`

**Settlement evidence:** `0x74d50969bc1748c2a6ca2ebd05c31fbdb9b686abf1cf6bd963a604996b7d9328` (Base, 0.001 USDC to the payout wallet, settled via CDP).

## After listing

- Watch `/admin/stats` (Worker) for which channel brings paid calls.
- Re-submit the MCP Registry whenever `server.json`'s version changes.
