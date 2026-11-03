# Where to list AIPayGen

Each directory below is somewhere agents or their developers search for tools. Most take five minutes and need your account, so they're yours to submit. Everything to paste is here.

## The copy

**Name:** AIPayGen

**One line (100 characters max):** Free search of 11k+ agent APIs, skills and agents, plus pay-per-call site intel via x402

**Short description:**
AIPayGen gives AI agents a free, searchable marketplace of 11,000+ resources (4,300+ APIs with docs and auth details, 4,300+ reusable skills, 950+ agents, 1,500+ agent services), plus pay-per-call tools for website and company intelligence: DNS, WHOIS/RDAP, SSL and subdomains, tech stack, email security, page-to-markdown and company profiles. Agents pay per call in USDC with x402 (no account, no API key), or use prepaid credits. Failed calls are never charged.

**Links:**
- MCP (Streamable HTTP): `https://mcp.aipaygen.com/mcp`
- Website: `https://aipaygen.com`
- Marketplace: `https://aipaygen.com/market`
- OpenAPI: `https://aipaygen.com/openapi.json`
- llms.txt: `https://aipaygen.com/llms.txt`
- A2A agent card: `https://aipaygen.com/.well-known/agent-card.json`
- x402 resources: `https://aipaygen.com/.well-known/x402`
- Repository: `https://github.com/Damien829/aipaygen`

**Tags:** mcp, x402, ai-agents, marketplace, api-directory, web-intelligence, dns, whois, tech-stack, pay-per-call, usdc, base

## Directories, most valuable first

| # | Where | How | Notes |
|---|---|---|---|
| 1 | **Official MCP Registry** | `mcp-publisher login github` then `mcp-publisher publish` (uses `server.json`, already updated to 2.1.0) | Feeds many MCP clients and other directories automatically. |
| 2 | **x402 Bazaar** | Automatic. Our 402 responses carry Bazaar metadata, and resources are cataloged once paid calls settle through the facilitator. | Make one real paid call after deploy to get listed. |
| 3 | **Smithery** | smithery.ai → Add server → remote URL `https://mcp.aipaygen.com/mcp` | Large MCP audience. |
| 4 | **Glama** | glama.ai/mcp/servers → Add; `glama.json` is already in the repo | Claims via GitHub. |
| 5 | **PulseMCP** | pulsemcp.com → Submit | Curated list, read by many developers. |
| 6 | **mcp.so** | mcp.so → Submit | |
| 7 | **x402 ecosystem list** | Pull request to the x402 Foundation's ecosystem/awesome list on GitHub | Lists x402-enabled services. |
| 8 | **awesome-mcp-servers** | Pull request on GitHub, under "Search" or "Marketplace" | |
| 9 | **Google Search Console + Bing Webmaster Tools** | Verify aipaygen.com, then submit `https://aipaygen.com/sitemap.xml` | Gets the 11,246 marketplace pages indexed faster, which also feeds AI answer engines. |
| 10 | **PyPI** (`aipaygen-mcp` 2.0.0 is already there) | Bump the description to mention the marketplace on the next release | |

## After listing

- Watch `/admin/stats` (Worker) for which channel brings paid calls.
- Re-submit the MCP Registry whenever `server.json`'s version changes.
