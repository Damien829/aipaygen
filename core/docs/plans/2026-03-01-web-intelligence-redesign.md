# Web Intelligence API — Redesign Design Doc
Date: 2026-03-01

## Problem
All 7 current endpoints are generic Claude Haiku wrappers. Other agents already have LLM access, so there's no reason to pay for ours. No differentiation, no real value.

## Solution
Replace the featured endpoints with a **web intelligence tier** — real internet access packaged as pay-per-query API endpoints. Many agents run in sandboxed environments without web access. A Pi with unrestricted internet + Claude for structuring is genuinely useful.

## Endpoints

### Tier 1 — Raw Data (no Claude, cheap)
- `POST /scrape` — $0.01 — Fetch URL, strip boilerplate, return clean markdown text
- `POST /search` — $0.01 — DuckDuckGo query, return top N results (title, url, snippet)

### Tier 2 — Structured Intelligence (Claude, mid-price)
- `POST /extract` — $0.03 — URL + JSON schema → Claude extracts structured fields from page
- `POST /research` — $0.15 — Question → search → scrape top 3 → Claude synthesizes cited answer

### Existing endpoints
Keep as-is (`/write`, `/analyze`, `/code`, `/summarize`, `/translate`, `/social`). De-emphasize in docs and landing page but leave running.

## Data Flow

### /scrape
1. Receive `{"url": "..."}`
2. `requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0..."})`
3. BeautifulSoup: remove script/style/nav/footer, extract body text
4. markdownify: convert to clean markdown
5. Return `{"url", "text", "word_count"}`

### /search
1. Receive `{"query": "...", "n": 5}`
2. `duckduckgo_search.DDGS().text(query, max_results=n)`
3. Return `{"query", "results": [{"title", "url", "snippet"}]}`

### /extract
1. Receive `{"url": "...", "schema": {"price": "product price", "title": "..."}}`
2. Scrape URL (reuse scrape logic)
3. Claude: "Extract these fields from the text: {schema}. Return valid JSON only."
4. Return `{"url", "data": {...}}`

### /research
1. Receive `{"question": "..."}`
2. Search DuckDuckGo for question (top 5)
3. Scrape top 3 URLs (parallel, timeout 8s each)
4. Claude: synthesize all text into answer with inline citations
5. Return `{"question", "answer", "sources": [{"title", "url"}]}`

## Dependencies to Add
```
beautifulsoup4
duckduckgo-search
markdownify
```
All free, no API keys required.

## Error Handling
- Scrape timeout: 10s, return `{"error": "timeout"}` with 408
- Blocked/403 pages: return `{"error": "blocked"}` with 422
- Bad URL: return `{"error": "invalid url"}` with 400
- Research: if <2 pages scrape successfully, still synthesize with what's available

## Pricing Rationale
- /scrape, /search: $0.01 — no Claude cost, just compute. Competitive with SerpAPI ($0.01/call)
- /extract: $0.03 — Claude Haiku ~$0.0002/call, 15x margin
- /research: $0.15 — ~3 Claude calls + compute, ~$0.001 cost, 150x margin

## Success Criteria
- All 4 new endpoints functional and returning useful data
- /research chains search → scrape → synthesize correctly
- Existing endpoints unaffected
- /discover updated to feature new endpoints
- Landing page updated to feature new value proposition
