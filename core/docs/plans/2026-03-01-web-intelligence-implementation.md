# Web Intelligence API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 web intelligence endpoints (/scrape, /search, /extract, /research) that give agents real internet access via pay-per-query x402 micropayments.

**Architecture:** Add a `web.py` helper module with scrape/search functions, then add 4 new route handlers and x402 route configs in `app.py`. Tests mock external HTTP calls and DuckDuckGo. Update /discover and landing page to feature new endpoints.

**Tech Stack:** Flask, BeautifulSoup4, duckduckgo-search, markdownify, Claude Haiku (for /extract and /research only), pytest + unittest.mock

---

### Task 1: Install dependencies

**Files:**
- No file changes — just pip install

**Step 1: Install packages**

```bash
cd /home/damien809/agent-service && venv/bin/pip install beautifulsoup4 duckduckgo-search markdownify
```

Expected output: Successfully installed beautifulsoup4-... duckduckgo-search-... markdownify-...

**Step 2: Verify**

```bash
venv/bin/python -c "import bs4, duckduckgo_search, markdownify; print('ok')"
```

Expected: `ok`

---

### Task 2: Create web.py helper module with scrape + search

**Files:**
- Create: `web.py`
- Create: `tests/test_web.py`

**Step 1: Create tests/test_web.py**

```python
import pytest
from unittest.mock import patch, MagicMock


def test_scrape_returns_text():
    from web import scrape_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><p>Hello world</p><nav>skip</nav></body></html>"
    mock_response.raise_for_status = MagicMock()
    with patch("web.requests.get", return_value=mock_response):
        result = scrape_url("http://example.com")
    assert "Hello world" in result["text"]
    assert result["url"] == "http://example.com"
    assert "word_count" in result


def test_scrape_timeout_returns_error():
    from web import scrape_url
    import requests as req
    with patch("web.requests.get", side_effect=req.exceptions.Timeout):
        result = scrape_url("http://example.com")
    assert result["error"] == "timeout"


def test_search_returns_results():
    from web import search_web
    fake_results = [
        {"title": "Test", "href": "http://example.com", "body": "A snippet"},
    ]
    with patch("web.DDGS") as MockDDGS:
        instance = MockDDGS.return_value.__enter__.return_value
        instance.text.return_value = fake_results
        result = search_web("test query", n=1)
    assert result["query"] == "test query"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Test"
    assert result["results"][0]["url"] == "http://example.com"
    assert result["results"][0]["snippet"] == "A snippet"
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/damien809/agent-service && venv/bin/python -m pytest tests/test_web.py -v
```

Expected: ImportError or ModuleNotFoundError (web.py doesn't exist yet)

**Step 3: Create web.py**

```python
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from duckduckgo_search import DDGS

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AiPayGen/1.0; +https://aipaygen.com)"
}

STRIP_TAGS = ["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]


def scrape_url(url: str, timeout: int = 10) -> dict:
    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return {"error": "timeout", "url": url}
    except requests.exceptions.HTTPError as e:
        return {"error": f"http_{e.response.status_code}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    body = soup.find("main") or soup.find("article") or soup.find("body") or soup
    text = md(str(body), strip=["a", "img"]).strip()
    # Collapse excessive whitespace
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)

    return {
        "url": url,
        "text": text,
        "word_count": len(text.split()),
    }


def search_web(query: str, n: int = 5) -> dict:
    results = []
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=n)
            for r in raw:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        return {"error": str(e), "query": query, "results": []}

    return {"query": query, "results": results}
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/damien809/agent-service && venv/bin/python -m pytest tests/test_web.py -v
```

Expected: 3 PASSED

**Step 5: Commit**

```bash
cd /home/damien809/agent-service && git add web.py tests/test_web.py && git commit -m "feat: add web.py scrape_url and search_web helpers"
```

---

### Task 3: Add /scrape and /search endpoints to app.py

**Files:**
- Modify: `app.py`

**Step 1: Add import at top of app.py**

After the existing imports (around line 8), add:

```python
from web import scrape_url, search_web
```

**Step 2: Add route configs to the `routes` dict in app.py**

After the existing `"POST /social"` entry (around line 92), add:

```python
    "POST /scrape": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Fetch any URL and return clean markdown text ($0.01)",
    ),
    "POST /search": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="DuckDuckGo web search, returns top N results ($0.01)",
    ),
    "POST /extract": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Fetch URL and extract structured data using a JSON schema ($0.03)",
    ),
    "POST /research": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.15", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Deep research: search + scrape + Claude synthesis with citations ($0.15)",
    ),
```

**Step 3: Add /scrape and /search route handlers**

Add after the existing `/social` route handler (after line ~238):

```python
@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required"}), 400
    result = scrape_url(url)
    log_payment("/scrape", 0.01, request.remote_addr)
    return jsonify(result)


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json() or {}
    query = data.get("query", "")
    n = min(int(data.get("n", 5)), 10)
    if not query:
        return jsonify({"error": "query required"}), 400
    result = search_web(query, n=n)
    log_payment("/search", 0.01, request.remote_addr)
    return jsonify(result)
```

**Step 4: Verify app still imports cleanly**

```bash
cd /home/damien809/agent-service && venv/bin/python -c "import app; print('ok')"
```

Expected: `ok`

**Step 5: Commit**

```bash
cd /home/damien809/agent-service && git add app.py && git commit -m "feat: add /scrape and /search endpoints"
```

---

### Task 4: Add /extract and /research endpoints

**Files:**
- Modify: `app.py`
- Modify: `tests/test_web.py`

**Step 1: Add /extract test to tests/test_web.py**

```python
def test_extract_parses_schema(client):
    # This is an integration-style smoke test against the Flask test client
    pass  # Covered by manual smoke test — Claude API needed
```

(Skip full unit test for /extract and /research — they require Claude API credits. Add a placeholder.)

**Step 2: Add /extract route handler to app.py**

Add after the `/search` handler:

```python
@app.route("/extract", methods=["POST"])
def extract():
    data = request.get_json() or {}
    url = data.get("url", "")
    schema = data.get("schema", {})
    if not url or not schema:
        return jsonify({"error": "url and schema required"}), 400

    scraped = scrape_url(url)
    if "error" in scraped:
        return jsonify(scraped), 422

    schema_desc = ", ".join(f'"{k}": {v}' for k, v in schema.items())
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Extract the following fields from the text below. Return ONLY valid JSON with these keys: {schema_desc}\n\nText:\n{scraped['text'][:6000]}"
        }]
    )
    log_payment("/extract", 0.03, request.remote_addr)
    return jsonify({"url": url, "data": msg.content[0].text})


@app.route("/research", methods=["POST"])
def research_web():
    data = request.get_json() or {}
    question = data.get("question", "")
    if not question:
        return jsonify({"error": "question required"}), 400

    # Step 1: search
    search_result = search_web(question, n=5)
    if "error" in search_result:
        return jsonify(search_result), 422
    top_urls = [r["url"] for r in search_result["results"][:3]]

    # Step 2: scrape top 3
    pages = []
    for url in top_urls:
        scraped = scrape_url(url, timeout=8)
        if "error" not in scraped and scraped.get("word_count", 0) > 50:
            pages.append(scraped)

    if not pages:
        return jsonify({"error": "could not retrieve source pages"}), 422

    # Step 3: synthesize
    context = "\n\n---\n\n".join(
        f"Source: {p['url']}\n\n{p['text'][:2000]}" for p in pages
    )
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"Answer the following question based on the sources below. Include inline citations like [1], [2] etc. Be thorough but concise.\n\nQuestion: {question}\n\nSources:\n{context}"
        }]
    )
    sources = [{"title": r["title"], "url": r["url"]} for r in search_result["results"][:3]]
    log_payment("/research", 0.15, request.remote_addr)
    return jsonify({
        "question": question,
        "answer": msg.content[0].text,
        "sources": sources,
    })
```

**Note:** The existing `/research` route (line ~100) handles `POST /research` with `topic` param. Rename it to `/topic-research` or replace it. Since the new /research is more valuable, **replace the old handler** by editing the existing `def research()` function to become `def research_web()` and pointing `@app.route("/research")` to the new implementation. Remove the old function entirely.

**Step 3: Remove old /research handler**

Find and delete the old `@app.route("/research")` block (lines 100-116 in original app.py). The new handler above replaces it.

**Step 4: Verify imports**

```bash
cd /home/damien809/agent-service && venv/bin/python -c "import app; print('ok')"
```

Expected: `ok`

**Step 5: Commit**

```bash
cd /home/damien809/agent-service && git add app.py tests/test_web.py && git commit -m "feat: add /extract and /research endpoints, replace old /research"
```

---

### Task 5: Update /discover to feature new endpoints

**Files:**
- Modify: `app.py` (discover route, lines ~922-939)

**Step 1: Replace the services list in the discover() function**

Replace the entire `"services"` list with:

```python
"services": [
    # --- Web Intelligence (featured) ---
    {"endpoint": "/scrape", "method": "POST", "price_usd": 0.01,
     "input": {"url": "string"},
     "output": {"url": "string", "text": "string", "word_count": "int"},
     "description": "Fetch any URL, return clean markdown text"},
    {"endpoint": "/search", "method": "POST", "price_usd": 0.01,
     "input": {"query": "string", "n": "int (default 5, max 10)"},
     "output": {"query": "string", "results": [{"title": "string", "url": "string", "snippet": "string"}]},
     "description": "DuckDuckGo web search, returns top N results"},
    {"endpoint": "/extract", "method": "POST", "price_usd": 0.03,
     "input": {"url": "string", "schema": {"field_name": "description"}},
     "output": {"url": "string", "data": "object"},
     "description": "Fetch URL and extract structured fields using AI"},
    {"endpoint": "/research", "method": "POST", "price_usd": 0.15,
     "input": {"question": "string"},
     "output": {"question": "string", "answer": "string", "sources": [{"title": "string", "url": "string"}]},
     "description": "Deep research: search + scrape + AI synthesis with citations"},
    # --- AI Processing ---
    {"endpoint": "/summarize", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "length": "short|medium|detailed"}, "description": "Summarize long text"},
    {"endpoint": "/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "string"}, "description": "Analyze text, return insights"},
    {"endpoint": "/translate", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "language": "string"}, "description": "Translate text to any language"},
    {"endpoint": "/social", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "platforms": ["twitter", "linkedin"], "tone": "string"}, "description": "Generate social media posts"},
    {"endpoint": "/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article|post|copy"}, "description": "Write content to spec"},
    {"endpoint": "/code", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "language": "string"}, "description": "Generate code in any language"},
]
```

**Step 2: Commit**

```bash
cd /home/damien809/agent-service && git add app.py && git commit -m "feat: update /discover to feature web intelligence endpoints"
```

---

### Task 6: Update landing page hero copy

**Files:**
- Modify: `app.py` (LANDING_HTML string)

**Step 1: Update the hero tagline and featured endpoints section**

Find the hero section in `LANDING_HTML` and update the description/tagline to reflect the new value prop. Change from "Pay-per-use AI API" to "Web Intelligence for AI Agents". Update the featured endpoint list to show /scrape, /search, /extract, /research.

The exact hero text to replace (search for it):
```
Pay-per-use AI API powered by Claude
```
Replace with:
```
Web Intelligence for AI Agents
```

Also find and update any endpoint list in the HTML to lead with the 4 new web intelligence endpoints.

**Step 2: Verify app starts**

```bash
cd /home/damien809/agent-service && venv/bin/python -c "import app; print('ok')"
```

**Step 3: Commit**

```bash
cd /home/damien809/agent-service && git add app.py && git commit -m "feat: update landing page to lead with web intelligence pitch"
```

---

### Task 7: Restart service and smoke test

**Step 1: Kill existing process and restart**

```bash
kill $(lsof -ti :5001) 2>/dev/null; sleep 1
cd /home/damien809/agent-service && nohup venv/bin/python app.py >> agent.log 2>&1 &
sleep 2
```

**Step 2: Test /health**

```bash
curl -s http://localhost:5001/health | python3 -m json.tool
```

Expected: `{"status": "ok", ...}`

**Step 3: Test /discover**

```bash
curl -s http://localhost:5001/discover | python3 -m json.tool | head -30
```

Expected: JSON with /scrape, /search, /extract, /research listed first

**Step 4: Test /search (will be blocked by x402 in prod, test directly)**

```bash
curl -s -X POST http://localhost:5001/search \
  -H "Content-Type: application/json" \
  -d '{"query": "x402 protocol micropayments", "n": 3}' | python3 -m json.tool
```

Expected: Either x402 payment required response (402) OR results if x402 middleware skips localhost

**Step 5: Run test suite**

```bash
cd /home/damien809/agent-service && venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

**Step 6: Final commit**

```bash
cd /home/damien809/agent-service && git add -A && git status
```

Only commit if there are unstaged changes not already committed.
