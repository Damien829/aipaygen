"""
AiPayGen MCP Server — thin client that proxies 65+ AI tools via api.aipaygen.com.

Install:
    pip install aipaygen-mcp

Add to Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "aipaygen": {
          "command": "aipaygen-mcp",
          "env": { "AIPAYGEN_API_KEY": "apk_xxx" }
        }
      }
    }

Add to Claude Code:
    claude mcp add aipaygen -- aipaygen-mcp

Set AIPAYGEN_API_KEY for unlimited access, or use the free tier (10 calls/day).
"""

import os
import sys
import json
import urllib.request
import urllib.error

from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("AIPAYGEN_BASE_URL", "https://api.aipaygen.com")
API_KEY = os.environ.get("AIPAYGEN_API_KEY", "")

mcp = FastMCP(
    "AiPayGen",
    instructions=(
        "AiPayGen provides 65+ AI-powered tools: research, write, code, translate, "
        "analyze, summarize, vision, RAG, web scraping, agent memory, marketplace, "
        "data lookups (weather, crypto, stocks, news), and more. "
        "Free tier: 10 calls/day. Set AIPAYGEN_API_KEY for unlimited access."
    ),
)


def _call(endpoint: str, payload: dict) -> dict:
    """Call an AiPayGen API endpoint and return the JSON response."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "aipaygen-mcp/1.4"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": e.reason, "status": e.code, "detail": body[:500]}
    except Exception as e:
        return {"error": str(e)}


def _get(endpoint: str, params: dict = None) -> dict:
    """GET an AiPayGen API endpoint."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += f"?{qs}"
    headers = {"User-Agent": "aipaygen-mcp/1.4"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": e.reason, "status": e.code, "detail": body[:500]}
    except Exception as e:
        return {"error": str(e)}


# ── AI Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def research(topic: str) -> dict:
    """Research any topic. Returns structured summary, key points, and sources."""
    return _call("research", {"question": topic})


@mcp.tool()
def summarize(text: str, length: str = "short") -> dict:
    """Summarize text. Length: short, medium, or long."""
    return _call("summarize", {"text": text, "length": length})


@mcp.tool()
def analyze(content: str, question: str = "Provide a structured analysis") -> dict:
    """Analyze content with a specific question or lens."""
    return _call("analyze", {"content": content, "question": question})


@mcp.tool()
def translate(text: str, language: str = "Spanish") -> dict:
    """Translate text to any language."""
    return _call("translate", {"text": text, "language": language})


@mcp.tool()
def write(spec: str, type: str = "article") -> dict:
    """Generate written content. Types: article, blog, report, story, etc."""
    return _call("write", {"spec": spec, "type": type})


@mcp.tool()
def code(description: str, language: str = "Python") -> dict:
    """Generate code from a description."""
    return _call("code", {"description": description, "language": language})


@mcp.tool()
def explain(concept: str, level: str = "beginner", analogy: bool = True) -> dict:
    """Explain a concept at a given level with optional analogy."""
    return _call("explain", {"concept": concept, "level": level, "analogy": analogy})


@mcp.tool()
def qa(context: str, question: str) -> dict:
    """Answer a question given context text."""
    return _call("qa", {"context": context, "question": question})


@mcp.tool()
def sentiment(text: str) -> dict:
    """Analyze sentiment of text."""
    return _call("sentiment", {"text": text})


@mcp.tool()
def keywords(text: str, max_keywords: int = 10) -> dict:
    """Extract keywords from text."""
    return _call("keywords", {"text": text, "max_keywords": max_keywords})


@mcp.tool()
def classify(text: str, categories: list[str]) -> dict:
    """Classify text into provided categories."""
    return _call("classify", {"text": text, "categories": categories})


@mcp.tool()
def compare(text_a: str, text_b: str, focus: str = "") -> dict:
    """Compare two texts with optional focus area."""
    return _call("compare", {"text_a": text_a, "text_b": text_b, "focus": focus})


@mcp.tool()
def transform(text: str, instruction: str) -> dict:
    """Transform text according to an instruction."""
    return _call("transform", {"text": text, "instruction": instruction})


@mcp.tool()
def extract(text: str, fields: list[str] = None, schema: str = "") -> dict:
    """Extract structured data from text."""
    return _call("extract", {"text": text, "fields": fields or [], "schema": schema})


@mcp.tool()
def chat(messages: list[dict], system: str = "") -> dict:
    """Multi-turn chat with Claude. Messages: [{"role":"user","content":"..."}]."""
    return _call("chat", {"messages": messages, "system": system})


@mcp.tool()
def plan(goal: str, context: str = "", steps: int = 7) -> dict:
    """Generate a step-by-step plan to achieve a goal."""
    return _call("plan", {"goal": goal, "context": context, "steps": steps})


@mcp.tool()
def decide(decision: str, options: list[str] = None, criteria: str = "") -> dict:
    """Help make a decision by analyzing options against criteria."""
    return _call("decide", {"decision": decision, "options": options or [], "criteria": criteria})


@mcp.tool()
def proofread(text: str, style: str = "professional") -> dict:
    """Proofread and suggest corrections."""
    return _call("proofread", {"text": text, "style": style})


@mcp.tool()
def outline(topic: str, depth: int = 2, sections: int = 6) -> dict:
    """Generate a structured outline for a topic."""
    return _call("outline", {"topic": topic, "depth": depth, "sections": sections})


@mcp.tool()
def email(purpose: str, tone: str = "professional", context: str = "", recipient: str = "", length: str = "medium") -> dict:
    """Draft an email."""
    return _call("email", {"purpose": purpose, "tone": tone, "context": context, "recipient": recipient, "length": length})


@mcp.tool()
def sql(description: str, dialect: str = "postgresql", schema: str = "") -> dict:
    """Generate SQL from a natural language description."""
    return _call("sql", {"description": description, "dialect": dialect, "schema": schema})


@mcp.tool()
def regex(description: str, language: str = "python", flags: str = "") -> dict:
    """Generate regex from a description."""
    return _call("regex", {"description": description, "language": language, "flags": flags})


@mcp.tool()
def mock(description: str, count: int = 5, format: str = "json") -> dict:
    """Generate mock/sample data."""
    return _call("mock", {"description": description, "count": count, "format": format})


@mcp.tool()
def score(content: str, criteria: list[str] = None, scale: int = 10) -> dict:
    """Score content against criteria."""
    return _call("score", {"content": content, "criteria": criteria, "scale": scale})


@mcp.tool()
def timeline(text: str, direction: str = "chronological") -> dict:
    """Extract a timeline of events from text."""
    return _call("timeline", {"text": text, "direction": direction})


@mcp.tool()
def action(text: str) -> dict:
    """Extract action items from text."""
    return _call("action", {"text": text})


@mcp.tool()
def pitch(product: str, audience: str = "general", length: str = "30s") -> dict:
    """Generate a pitch for a product/idea."""
    return _call("pitch", {"product": product, "audience": audience, "length": length})


@mcp.tool()
def debate(topic: str, perspective: str = "balanced") -> dict:
    """Generate a structured debate on a topic."""
    return _call("debate", {"topic": topic, "perspective": perspective})


@mcp.tool()
def headline(content: str, count: int = 5, style: str = "engaging") -> dict:
    """Generate headlines for content."""
    return _call("headline", {"content": content, "count": count, "style": style})


@mcp.tool()
def fact(text: str, count: int = 10) -> dict:
    """Extract or generate facts from text."""
    return _call("fact", {"text": text, "count": count})


@mcp.tool()
def rewrite(text: str, audience: str = "general audience", tone: str = "neutral") -> dict:
    """Rewrite text for a target audience and tone."""
    return _call("rewrite", {"text": text, "audience": audience, "tone": tone})


@mcp.tool()
def tag(text: str, taxonomy: list[str] = None, max_tags: int = 10) -> dict:
    """Tag text with categories from a taxonomy."""
    return _call("tag", {"text": text, "taxonomy": taxonomy, "max_tags": max_tags})


@mcp.tool()
def questions(content: str, type: str = "faq", count: int = 5) -> dict:
    """Generate questions from content."""
    return _call("questions", {"content": content, "type": type, "count": count})


@mcp.tool()
def social(topic: str, platforms: list[str] = None, tone: str = "engaging") -> dict:
    """Generate social media posts for a topic."""
    return _call("social", {"topic": topic, "platforms": platforms or ["twitter", "linkedin"], "tone": tone})


# ── Advanced AI ───────────────────────────────────────────────────────────

@mcp.tool()
def vision(image_url: str, question: str = "Describe this image in detail") -> dict:
    """Analyze an image by URL. Supports any image format."""
    return _call("vision", {"image_url": image_url, "question": question})


@mcp.tool()
def rag(documents: str, query: str) -> dict:
    """RAG: Answer a query using provided documents as context."""
    return _call("rag", {"documents": documents, "query": query})


@mcp.tool()
def diagram(description: str, diagram_type: str = "flowchart") -> dict:
    """Generate a Mermaid diagram from a description."""
    return _call("diagram", {"description": description, "type": diagram_type})


@mcp.tool()
def json_schema(description: str, example: str = "") -> dict:
    """Generate a JSON schema from a description."""
    return _call("json_schema", {"description": description, "example": example})


@mcp.tool()
def test_cases(code_or_description: str, language: str = "python") -> dict:
    """Generate test cases for code or a feature description."""
    return _call("test_cases", {"code": code_or_description, "language": language})


@mcp.tool()
def workflow(goal: str, context: str = "") -> dict:
    """Design a multi-step workflow to achieve a goal."""
    return _call("workflow", {"goal": goal, "context": context})


@mcp.tool()
def pipeline(steps: list[dict]) -> dict:
    """Chain multiple AI operations. Each step: {"tool":"research","input":{"topic":"X"}}."""
    return _call("pipeline", {"steps": steps})


# ── Data & Web ────────────────────────────────────────────────────────────

@mcp.tool()
def web_search(query: str, n_results: int = 10) -> dict:
    """Search the web and return results."""
    return _call("search", {"query": query, "n_results": n_results})


@mcp.tool()
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return _get("data/weather", {"city": city})


@mcp.tool()
def get_crypto_prices(symbols: str = "bitcoin,ethereum") -> dict:
    """Get current cryptocurrency prices."""
    return _get("data/crypto", {"symbols": symbols})


@mcp.tool()
def get_exchange_rates(base_currency: str = "USD") -> dict:
    """Get current exchange rates."""
    return _get("data/exchange-rates", {"base": base_currency})


@mcp.tool()
def get_joke() -> dict:
    """Get a random joke."""
    return _get("data/joke")


@mcp.tool()
def get_quote() -> dict:
    """Get an inspirational quote."""
    return _get("data/quote")


@mcp.tool()
def get_holidays(country: str = "US", year: str = "2026") -> dict:
    """Get public holidays for a country."""
    return _get("data/holidays", {"country": country, "year": year})


# ── Web Scraping ──────────────────────────────────────────────────────────

@mcp.tool()
def scrape_google_maps(query: str, max_results: int = 5) -> dict:
    """Scrape Google Maps for businesses matching a query."""
    return _call("scrape", {"actor": "google_maps", "query": query, "max_results": max_results})


@mcp.tool()
def scrape_tweets(query: str, max_results: int = 20) -> dict:
    """Scrape tweets matching a query."""
    return _call("scrape", {"actor": "twitter", "query": query, "max_results": max_results})


@mcp.tool()
def scrape_website(url: str, max_pages: int = 3) -> dict:
    """Scrape a website's content."""
    return _call("scrape", {"actor": "website", "url": url, "max_pages": max_pages})


@mcp.tool()
def scrape_youtube(query: str, max_results: int = 5) -> dict:
    """Search and scrape YouTube videos."""
    return _call("scrape", {"actor": "youtube", "query": query, "max_results": max_results})


@mcp.tool()
def scrape_instagram(username: str, max_posts: int = 5) -> dict:
    """Scrape Instagram posts from a user."""
    return _call("scrape", {"actor": "instagram", "username": username, "max_posts": max_posts})


@mcp.tool()
def scrape_tiktok(username: str, max_videos: int = 5) -> dict:
    """Scrape TikTok videos from a user."""
    return _call("scrape", {"actor": "tiktok", "username": username, "max_videos": max_videos})


# ── Agent Memory ──────────────────────────────────────────────────────────

@mcp.tool()
def memory_store(agent_id: str, key: str, value: str, tags: str = "") -> dict:
    """Store a value in persistent agent memory. Survives across sessions."""
    return _call("memory/set", {"agent_id": agent_id, "key": key, "value": value, "tags": tags})


@mcp.tool()
def memory_recall(agent_id: str, key: str) -> dict:
    """Recall a specific memory by key."""
    return _call("memory/get", {"agent_id": agent_id, "key": key})


@mcp.tool()
def memory_find(agent_id: str, query: str) -> dict:
    """Search agent memory by semantic query."""
    return _call("memory/search", {"agent_id": agent_id, "query": query})


@mcp.tool()
def memory_keys(agent_id: str) -> dict:
    """List all memory keys for an agent."""
    return _call("memory/list", {"agent_id": agent_id})


# ── Marketplace ───────────────────────────────────────────────────────────

@mcp.tool()
def list_marketplace(category: str = None) -> dict:
    """Browse the agent services marketplace."""
    params = {}
    if category:
        params["category"] = category
    return _get("marketplace/services", params)


@mcp.tool()
def post_to_marketplace(agent_id: str, name: str, description: str,
                        category: str = "general", price: float = 0.0,
                        endpoint: str = "") -> dict:
    """List your agent service on the marketplace for other agents to discover."""
    return _call("marketplace/list", {
        "agent_id": agent_id, "name": name, "description": description,
        "category": category, "price": price, "endpoint": endpoint,
    })


# ── Utility ───────────────────────────────────────────────────────────────

@mcp.tool()
def generate_api_key(label: str = "") -> dict:
    """Generate a free AiPayGen API key. Top up at https://api.aipaygen.com/buy-credits."""
    return _call("keys/generate", {"label": label})


@mcp.tool()
def check_balance(key: str) -> dict:
    """Check the balance of an AiPayGen API key."""
    return _get("keys/balance", {"key": key})


@mcp.tool()
def list_models() -> dict:
    """List all available AI models and their pricing."""
    return _get("models")


# ── Skills System ─────────────────────────────────────────────────────────

@mcp.tool()
def ask(question: str) -> dict:
    """Universal endpoint — ask anything. AiPayGen picks the best skill and model automatically."""
    return _call("ask", {"question": question})


@mcp.tool()
def list_skills(category: str = "") -> dict:
    """List all available skills. AiPayGen has 65+ built-in skills and absorbs new ones dynamically."""
    params = {}
    if category:
        params["category"] = category
    return _get("skills", params)


@mcp.tool()
def execute_skill(skill_name: str, input_text: str) -> dict:
    """Execute a specific skill by name. Use list_skills to see available skills."""
    return _call("skills/execute", {"skill": skill_name, "input": input_text})


@mcp.tool()
def create_skill(name: str, description: str, prompt_template: str, category: str = "general") -> dict:
    """Create a new reusable skill. prompt_template must contain {{input}} placeholder."""
    return _call("skills/create", {
        "name": name, "description": description,
        "prompt_template": prompt_template, "category": category,
    })


@mcp.tool()
def absorb_skill(url: str = "", text: str = "") -> dict:
    """Absorb a new skill from a URL or text description. AiPayGen reads it and creates a callable skill."""
    return _call("skills/absorb", {"url": url, "text": text})


@mcp.tool()
def search_skills(query: str) -> dict:
    """Search for skills by keyword."""
    return _get("skills/search", {"q": query})


# ── Utilities ────────────────────────────────────────────────────────────────


@mcp.tool()
def get_current_time() -> dict:
    """Get current UTC time, Unix timestamp, date, and week number. Free."""
    return _get("free/time", {})


@mcp.tool()
def generate_uuid(count: int = 1) -> dict:
    """Generate one or more UUID4 values. Free."""
    return _get("free/uuid", {"count": count})


@mcp.tool()
def check_api_key_balance(key: str) -> dict:
    """Check balance and usage stats for a prepaid AiPayGen API key."""
    return _get("auth/status", {"key": key})


@mcp.tool()
def run_python_code(code: str, timeout: int = 10) -> dict:
    """Execute Python code in a sandboxed subprocess. Returns stdout, stderr, returncode."""
    return _call("code/run", {"code": code, "timeout": timeout})


@mcp.tool()
def enrich_entity(entity: str, entity_type: str) -> dict:
    """Aggregate data about an entity. entity_type: ip | crypto | country | company."""
    return _call("enrich", {"entity": entity, "type": entity_type})


@mcp.tool()
def batch(operations: list[dict]) -> dict:
    """Run up to 5 independent operations in one call. Each: {"endpoint": "research", "input": {"topic": "AI"}}."""
    return _call("batch", {"operations": operations})


@mcp.tool()
def chain_operations(steps: list[dict]) -> dict:
    """Chain multiple AI operations in sequence. Output of each step feeds the next. steps: [{action, params}]."""
    return _call("chain", {"steps": steps})


# ── API Catalog ──────────────────────────────────────────────────────────────


@mcp.tool()
def browse_catalog(category: str = "", min_score: float = 0.0, free_only: bool = False, page: int = 1) -> dict:
    """Browse 500+ discovered APIs. Filter by category, quality score, or free_only."""
    return _get("catalog", {"category": category, "min_score": min_score, "free_only": free_only, "page": page})


@mcp.tool()
def get_catalog_api(api_id: int) -> dict:
    """Get full details for a specific API in the catalog by its numeric ID."""
    return _get(f"catalog/{api_id}", {})


@mcp.tool()
def invoke_catalog_api(api_id: int, endpoint: str = "/", params: str = "{}") -> dict:
    """Call a catalog API. Get api_id from browse_catalog first. params: JSON string of query params."""
    return _call(f"catalog/{api_id}/invoke", {"endpoint": endpoint, "params": params})


# ── Agent Network ────────────────────────────────────────────────────────────


@mcp.tool()
def register_my_agent(agent_id: str, name: str, description: str,
                      capabilities: str, endpoint: str = "") -> dict:
    """Register your agent in the AiPayGen agent registry."""
    return _call("agents/register", {
        "agent_id": agent_id, "name": name, "description": description,
        "capabilities": capabilities, "endpoint": endpoint,
    })


@mcp.tool()
def list_registered_agents() -> dict:
    """Browse all agents registered in the AiPayGen registry."""
    return _get("agents", {})


@mcp.tool()
def send_agent_message(from_agent: str, to_agent: str, subject: str, body: str) -> dict:
    """Send a direct message from one agent to another via the agent network."""
    return _call("agents/message", {
        "from": from_agent, "to": to_agent, "subject": subject, "body": body,
    })


@mcp.tool()
def read_agent_inbox(agent_id: str, unread_only: bool = False) -> dict:
    """Read messages from an agent's inbox."""
    return _get(f"agents/{agent_id}/inbox", {"unread_only": unread_only})


@mcp.tool()
def submit_agent_task(posted_by: str, title: str, description: str,
                      skills_needed: list[str] = None, reward_usd: float = 0.0) -> dict:
    """Post a task to the agent task board for other agents to claim."""
    return _call("agents/tasks", {
        "posted_by": posted_by, "title": title, "description": description,
        "skills_needed": skills_needed or [], "reward_usd": reward_usd,
    })


@mcp.tool()
def browse_agent_tasks(status: str = "open", skill: str = None) -> dict:
    """Browse tasks on the agent task board, optionally filtered by skill or status."""
    params = {"status": status}
    if skill:
        params["skill"] = skill
    return _get("agents/tasks", params)


# ── Knowledge Base ───────────────────────────────────────────────────────────


@mcp.tool()
def add_to_knowledge_base(topic: str, content: str, author_agent: str,
                          tags: list[str] = None) -> dict:
    """Add an entry to the shared agent knowledge base."""
    return _call("knowledge", {
        "topic": topic, "content": content, "author_agent": author_agent, "tags": tags or [],
    })


@mcp.tool()
def search_knowledge_base(query: str, limit: int = 10) -> dict:
    """Search the shared agent knowledge base by keyword."""
    return _get("knowledge/search", {"q": query, "limit": limit})


@mcp.tool()
def get_trending_knowledge() -> dict:
    """Get the most popular topics in the shared agent knowledge base."""
    return _get("knowledge/trending", {})


def _run_self_test():
    """Quick smoke test: hit a free endpoint to verify connectivity."""
    print(f"AiPayGen MCP self-test")
    print(f"  Base URL: {BASE_URL}")
    print(f"  API Key:  {'set' if API_KEY else 'not set (free tier)'}")
    try:
        result = _get("data/weather", {"city": "London"})
        if "error" in result:
            print(f"  FAIL: {result['error']}")
            sys.exit(1)
        temp = result.get("temperature_c", "?")
        print(f"  OK: London weather = {temp}°C")
        print(f"  65+ tools ready. Run 'aipaygen-mcp' to start the server.")
    except Exception as e:
        print(f"  FAIL: {e}")
        sys.exit(1)


def main():
    if "--test" in sys.argv:
        _run_self_test()
    elif "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
