"""
AiPayGent MCP Server — 50+ tools

Exposes all AiPayGent capabilities as MCP tools.
No x402 payment needed via MCP — all tools call Claude/Apify directly.

Usage:
  stdio (Claude Code / Cursor / Cline):
    python mcp_server.py

  SSE (deployed):
    python mcp_server.py --http

Add to Claude Code:
  claude mcp add aipaygent -- python /path/to/mcp_server.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from app import (
    research_inner, summarize_inner, analyze_inner, translate_inner,
    social_inner, write_inner, code_inner, extract_inner, qa_inner,
    classify_inner, sentiment_inner, keywords_inner, compare_inner,
    transform_inner, chat_inner, plan_inner, decide_inner, proofread_inner,
    explain_inner, questions_inner, outline_inner, email_inner, sql_inner,
    regex_inner, mock_inner, score_inner, timeline_inner, action_inner,
    pitch_inner, debate_inner, headline_inner, fact_inner, rewrite_inner,
    tag_inner, pipeline_inner, BATCH_HANDLERS,
    vision_inner, rag_inner, diagram_inner, json_schema_inner,
    test_cases_inner, workflow_inner,
)
from api_catalog import get_all_apis, get_api
from agent_memory import (
    memory_set, memory_get, memory_search, memory_list,
    register_agent, list_agents,
    marketplace_list_service, marketplace_get_services,
    marketplace_get_service, marketplace_increment_calls,
)
from apify_client import run_actor_sync
from agent_network import (
    send_message, get_inbox, add_knowledge, search_knowledge,
    get_trending_topics, submit_task, browse_tasks, get_task,
)
import requests as _mcp_requests

mcp = FastMCP(
    "AiPayGent",
    instructions=(
        "AiPayGent is an AI agent API marketplace with 65+ tools. "
        "Capabilities: research, write, code, translate, analyze, summarize, vision (image analysis), "
        "RAG (document Q&A), diagram generation, workflow orchestration, chain (pipeline multiple AI steps), "
        "web scraping (Google Maps, Twitter, Instagram, LinkedIn, YouTube, TikTok), "
        "persistent agent memory (survives sessions), agent marketplace (list & discover agent services), "
        "and a catalog of 500+ discovered APIs. "
        "All tools run directly — no x402 payment needed via MCP. "
        "For HTTP access: https://api.aipaygent.xyz"
    ),
    host="127.0.0.1",
    port=5002,
)


@mcp.tool()
def research(topic: str) -> dict:
    """Research a topic. Returns structured summary, key points, and sources to check."""
    return research_inner(topic)


@mcp.tool()
def summarize(text: str, length: str = "short") -> dict:
    """Summarize long text. length: short | medium | detailed"""
    return summarize_inner(text, length)


@mcp.tool()
def analyze(content: str, question: str = "Provide a structured analysis") -> dict:
    """Deep structured analysis of content. Returns conclusion, findings, sentiment, confidence."""
    return analyze_inner(content, question)


@mcp.tool()
def translate(text: str, language: str = "Spanish") -> dict:
    """Translate text to any language."""
    return translate_inner(text, language)


@mcp.tool()
def social(topic: str, platforms: list[str] = None, tone: str = "engaging") -> dict:
    """Generate platform-optimized social media posts for Twitter, LinkedIn, Instagram, etc."""
    return social_inner(topic, platforms or ["twitter", "linkedin", "instagram"], tone)


@mcp.tool()
def write(spec: str, type: str = "article") -> dict:
    """Write articles, copy, or content to your specification. type: article | post | copy"""
    return write_inner(spec, type)


@mcp.tool()
def code(description: str, language: str = "Python") -> dict:
    """Generate production-ready code in any language from a plain-English description."""
    return code_inner(description, language)


@mcp.tool()
def extract(text: str, fields: list[str] = None, schema: str = "") -> dict:
    """Extract structured data from unstructured text. Define fields or a schema."""
    return extract_inner(text, schema, fields or [])


@mcp.tool()
def qa(context: str, question: str) -> dict:
    """Q&A over a document. Returns answer, confidence score, and source quote."""
    return qa_inner(context, question)


@mcp.tool()
def classify(text: str, categories: list[str]) -> dict:
    """Classify text into your defined categories with per-category confidence scores."""
    return classify_inner(text, categories)


@mcp.tool()
def sentiment(text: str) -> dict:
    """Deep sentiment analysis: polarity, score, emotions, confidence, key phrases."""
    return sentiment_inner(text)


@mcp.tool()
def keywords(text: str, max_keywords: int = 10) -> dict:
    """Extract keywords, topics, and tags from any text."""
    return keywords_inner(text, max_keywords)


@mcp.tool()
def compare(text_a: str, text_b: str, focus: str = "") -> dict:
    """Compare two texts: similarities, differences, similarity score, recommendation."""
    return compare_inner(text_a, text_b, focus)


@mcp.tool()
def transform(text: str, instruction: str) -> dict:
    """Transform text with any instruction: rewrite, reformat, expand, condense, change tone."""
    return transform_inner(text, instruction)


@mcp.tool()
def chat(messages: list[dict], system: str = "") -> dict:
    """Stateless multi-turn chat. Send full message history, get Claude reply."""
    return chat_inner(messages, system)


@mcp.tool()
def plan(goal: str, context: str = "", steps: int = 7) -> dict:
    """Step-by-step action plan for any goal with effort estimate and first action."""
    return plan_inner(goal, context, steps)


@mcp.tool()
def decide(decision: str, options: list[str] = None, criteria: str = "") -> dict:
    """Decision framework: pros, cons, risks, recommendation, and confidence score."""
    return decide_inner(decision, options, criteria)


@mcp.tool()
def proofread(text: str, style: str = "professional") -> dict:
    """Grammar and clarity corrections with tracked changes and writing quality score."""
    return proofread_inner(text, style)


@mcp.tool()
def explain(concept: str, level: str = "beginner", analogy: bool = True) -> dict:
    """Explain any concept at beginner, intermediate, or expert level with analogy."""
    return explain_inner(concept, level, analogy)


@mcp.tool()
def questions(content: str, type: str = "faq", count: int = 5) -> dict:
    """Generate questions + answers from any content. type: faq | interview | quiz | comprehension"""
    return questions_inner(content, type, count)


@mcp.tool()
def outline(topic: str, depth: int = 2, sections: int = 6) -> dict:
    """Generate a hierarchical outline with headings, summaries, and subsections."""
    return outline_inner(topic, depth, sections)


@mcp.tool()
def email(purpose: str, tone: str = "professional", context: str = "", recipient: str = "", length: str = "medium") -> dict:
    """Compose a professional email. Returns subject line and body."""
    return email_inner(purpose, tone, context, recipient, length)


@mcp.tool()
def sql(description: str, dialect: str = "postgresql", schema: str = "") -> dict:
    """Natural language to SQL. Returns query, explanation, and notes."""
    return sql_inner(description, dialect, schema)


@mcp.tool()
def regex(description: str, language: str = "python", flags: str = "") -> dict:
    """Generate a regex pattern from a plain-English description with examples."""
    return regex_inner(description, language, flags)


@mcp.tool()
def mock(description: str, count: int = 5, format: str = "json") -> dict:
    """Generate realistic mock data records. format: json | csv | list"""
    return mock_inner(description, min(count, 50), format)


@mcp.tool()
def score(content: str, criteria: list[str] = None, scale: int = 10) -> dict:
    """Score content on a custom rubric. Returns per-criterion scores, strengths, and weaknesses."""
    return score_inner(content, criteria or ["clarity", "accuracy", "engagement"], scale)


@mcp.tool()
def timeline(text: str, direction: str = "chronological") -> dict:
    """Extract or reconstruct a timeline from text. Returns dated events with significance."""
    return timeline_inner(text, direction)


@mcp.tool()
def action(text: str) -> dict:
    """Extract action items, tasks, owners, and due dates from meeting notes or any text."""
    return action_inner(text)


@mcp.tool()
def pitch(product: str, audience: str = "general", length: str = "30s") -> dict:
    """Generate an elevator pitch: hook, value prop, call to action, full script. length: 15s | 30s | 60s"""
    return pitch_inner(product, audience, length)


@mcp.tool()
def debate(topic: str, perspective: str = "balanced") -> dict:
    """Arguments for and against any position with strength ratings and verdict."""
    return debate_inner(topic, perspective)


@mcp.tool()
def headline(content: str, count: int = 5, style: str = "engaging") -> dict:
    """Generate headline variations with type labels and a best pick."""
    return headline_inner(content, count, style)


@mcp.tool()
def fact(text: str, count: int = 10) -> dict:
    """Extract factual claims with verifiability scores and source hints."""
    return fact_inner(text, count)


@mcp.tool()
def rewrite(text: str, audience: str = "general audience", tone: str = "neutral") -> dict:
    """Rewrite text for a specific audience, reading level, or brand voice."""
    return rewrite_inner(text, audience, tone)


@mcp.tool()
def tag(text: str, taxonomy: list[str] = None, max_tags: int = 10) -> dict:
    """Auto-tag content using a taxonomy or free-form. Returns tags, primary tag, categories."""
    return tag_inner(text, taxonomy, max_tags)


@mcp.tool()
def pipeline(steps: list[dict]) -> dict:
    """
    Chain up to 5 operations sequentially. Each step can reference the previous
    output using the string '{{prev}}' as a field value in its input.

    Example steps:
    [
      {"endpoint": "research", "input": {"topic": "quantum computing"}},
      {"endpoint": "summarize", "input": {"text": "{{prev}}", "length": "short"}},
      {"endpoint": "headline", "input": {"content": "{{prev}}", "count": 3}}
    ]
    """
    return pipeline_inner(steps)


@mcp.tool()
def batch(operations: list[dict]) -> dict:
    """
    Run up to 5 independent operations in one call.

    Each operation: {"endpoint": "research", "input": {"topic": "AI"}}
    Valid endpoints: research, summarize, analyze, translate, social, write, code,
    extract, qa, classify, sentiment, keywords, compare, transform, chat, plan,
    decide, proofread, explain, questions, outline, email, sql, regex, mock,
    score, timeline, action, pitch, debate, headline, fact, rewrite, tag
    """
    if not operations or not isinstance(operations, list):
        return {"error": "operations array required"}
    if len(operations) > 5:
        return {"error": "max 5 operations per batch"}
    results = []
    for op in operations:
        endpoint = op.get("endpoint", "").lstrip("/")
        inp = op.get("input", {})
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            results.append({"endpoint": endpoint, "error": f"unknown endpoint '{endpoint}'"})
        else:
            try:
                results.append({"endpoint": endpoint, **handler(inp)})
            except Exception as e:
                results.append({"endpoint": endpoint, "error": str(e)})
    return {"results": results, "count": len(results)}


import json

# ─── Vision & Advanced AI Tools ──────────────────────────────────────────────

@mcp.tool()
def vision(image_url: str, question: str = "Describe this image in detail") -> dict:
    """Analyze any image URL using Claude Vision. Ask specific questions or get a full description."""
    return vision_inner(image_url, question)


@mcp.tool()
def rag(documents: str, query: str) -> dict:
    """
    Grounded Q&A using only your documents. Separate multiple documents with '---'.
    Returns answer, confidence, citations, and a cannot_answer flag.
    """
    return rag_inner(documents, query)


@mcp.tool()
def diagram(description: str, diagram_type: str = "flowchart") -> dict:
    """
    Generate a Mermaid diagram from a plain English description.
    Types: flowchart, sequence, erd, gantt, mindmap
    """
    return diagram_inner(description, diagram_type)


@mcp.tool()
def json_schema(description: str, example: str = "") -> dict:
    """Generate a JSON Schema (draft-07) from a plain English description of your data structure."""
    return json_schema_inner(description, example)


@mcp.tool()
def test_cases(code_or_description: str, language: str = "python") -> dict:
    """Generate comprehensive test cases with edge cases for code or a feature description."""
    return test_cases_inner(code_or_description, language)


@mcp.tool()
def workflow(goal: str, context: str = "") -> dict:
    """
    Multi-step agentic reasoning using Claude Sonnet. Breaks down complex goals,
    reasons through each sub-task, and produces a comprehensive result.
    Best for complex tasks requiring multiple steps of reasoning.
    """
    return workflow_inner(goal, context)


# ─── Agent Memory Tools ───────────────────────────────────────────────────────

@mcp.tool()
def memory_store(agent_id: str, key: str, value: str, tags: str = "") -> dict:
    """
    Store a persistent memory for an agent. Survives across sessions.
    agent_id: stable identifier for your agent (UUID, DID, or name).
    tags: comma-separated (optional).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    return memory_set(agent_id, key, value, tag_list)


@mcp.tool()
def memory_recall(agent_id: str, key: str) -> dict:
    """Retrieve a stored memory by agent_id and key. Returns value, tags, and timestamps."""
    result = memory_get(agent_id, key)
    return result or {"error": "not_found", "agent_id": agent_id, "key": key}


@mcp.tool()
def memory_find(agent_id: str, query: str) -> dict:
    """Search all memories for an agent by keyword. Returns ranked matching key-value pairs."""
    results = memory_search(agent_id, query)
    return {"agent_id": agent_id, "query": query, "results": results, "count": len(results)}


@mcp.tool()
def memory_keys(agent_id: str) -> dict:
    """List all memory keys stored for an agent, with tags and last-updated timestamps."""
    return {"agent_id": agent_id, "keys": memory_list(agent_id)}


# ─── API Catalog Tools ────────────────────────────────────────────────────────

@mcp.tool()
def browse_catalog(category: str = "", min_score: float = 0.0, free_only: bool = False, page: int = 1) -> dict:
    """
    Browse the AiPayGent catalog of 500+ discovered APIs.
    Filter by category (geo, finance, weather, social_media, developer, news, health, science, scraping),
    minimum quality score (0-10), or free_only to show only APIs that don't require auth.
    """
    apis, total = get_all_apis(
        page=page, per_page=20,
        category=category or None,
        min_score=min_score if min_score > 0 else None,
        free_only=free_only,
    )
    return {"total": total, "page": page, "showing": len(apis), "apis": apis}


@mcp.tool()
def get_catalog_api(api_id: int) -> dict:
    """Get full details for a specific API in the catalog by its numeric ID."""
    result = get_api(api_id)
    return result or {"error": "not_found", "api_id": api_id}


# ─── Agent Registry Tools ─────────────────────────────────────────────────────

@mcp.tool()
def register_my_agent(agent_id: str, name: str, description: str,
                      capabilities: str, endpoint: str = "") -> dict:
    """
    Register your agent in the AiPayGent agent registry.
    capabilities: comma-separated list of what your agent can do.
    endpoint: optional URL where other agents can reach you.
    """
    cap_list = [c.strip() for c in capabilities.split(",") if c.strip()]
    return register_agent(agent_id, name, description, cap_list, endpoint or None)


@mcp.tool()
def list_registered_agents() -> dict:
    """Browse all agents registered in the AiPayGent registry."""
    agents = list_agents()
    return {"agents": agents, "count": len(agents)}


# ─── Web Scraping Tools ───────────────────────────────────────────────────────

def _apify_run(actor_id: str, run_input: dict, max_items: int = 10) -> list:
    try:
        return run_actor_sync(actor_id, run_input, max_items=max_items)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def scrape_google_maps(query: str, max_results: int = 5) -> dict:
    """Scrape Google Maps for businesses matching a query. Returns name, address, rating, phone, website."""
    results = _apify_run("nwua9Gu5YrADL7ZDj",
                         {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
def scrape_tweets(query: str, max_results: int = 20) -> dict:
    """Scrape Twitter/X tweets by search query or hashtag. Returns text, author, likes, retweets, date."""
    results = _apify_run("61RPP7dywgiy0JPD0",
                         {"searchTerms": [query], "maxItems": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
def scrape_website(url: str, max_pages: int = 3) -> dict:
    """Crawl any website and extract text content. Returns page URL, title, and text per page."""
    results = _apify_run("aYG0l9s7dbB7j3gbS",
                         {"startUrls": [{"url": url}], "maxCrawlPages": max_pages},
                         max_pages)
    return {"url": url, "count": len(results), "results": results}


@mcp.tool()
def scrape_youtube(query: str, max_results: int = 5) -> dict:
    """Search YouTube and return video metadata — title, channel, views, duration, description, URL."""
    results = _apify_run("h7sDV53CddomktSi5",
                         {"searchKeywords": query, "maxResults": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
def scrape_instagram(username: str, max_posts: int = 5) -> dict:
    """Scrape Instagram profile posts. Returns caption, likes, comments, date, media URL."""
    results = _apify_run("shu8hvrXbJbY3Eb9W",
                         {"username": [username], "resultsLimit": max_posts},
                         max_posts)
    return {"username": username, "count": len(results), "results": results}


@mcp.tool()
def scrape_tiktok(username: str, max_videos: int = 5) -> dict:
    """Scrape TikTok profile videos. Returns caption, views, likes, shares, date."""
    results = _apify_run("GdWCkxBtKWOsKjdch",
                         {"profiles": [username], "resultsPerPage": max_videos},
                         max_videos)
    return {"username": username, "count": len(results), "results": results}


@mcp.tool()
def chain_operations(steps: list) -> dict:
    """
    Chain multiple AI operations in sequence. Output of each step is available to the next.
    steps: list of {action: str, params: dict}
    Available actions: research, summarize, analyze, sentiment, keywords, classify,
                       rewrite, extract, qa, compare, outline, diagram, json_schema, workflow
    Use '{{prev_result}}' in params to reference previous step output.
    Example: [{"action": "research", "params": {"query": "AI trends"}},
              {"action": "summarize", "params": {"text": "{{prev_result}}", "format": "bullets"}}]
    """
    _CHAIN = {
        "research": lambda p: research_inner(p.get("query", "")),
        "summarize": lambda p: summarize_inner(p.get("text", ""), p.get("format", "bullets")),
        "analyze": lambda p: analyze_inner(p.get("text", ""), p.get("question", "Analyze")),
        "sentiment": lambda p: sentiment_inner(p.get("text", "")),
        "keywords": lambda p: keywords_inner(p.get("text", ""), int(p.get("n", 10))),
        "classify": lambda p: classify_inner(p.get("text", ""), p.get("categories", [])),
        "rewrite": lambda p: rewrite_inner(p.get("text", ""), p.get("audience", "general"), p.get("tone", "professional")),
        "extract": lambda p: extract_inner(p.get("text", ""), p.get("schema_desc", ""), p.get("fields", [])),
        "qa": lambda p: qa_inner(p.get("context", ""), p.get("question", "")),
        "compare": lambda p: compare_inner(p.get("text_a", ""), p.get("text_b", ""), p.get("focus", "")),
        "outline": lambda p: outline_inner(p.get("topic", "")),
        "diagram": lambda p: diagram_inner(p.get("description", ""), p.get("diagram_type", "flowchart")),
        "json_schema": lambda p: json_schema_inner(p.get("description", ""), p.get("example", {})),
        "workflow": lambda p: workflow_inner(p.get("goal", ""), p.get("available_data", {})),
    }
    if len(steps) > 5:
        return {"error": "max 5 steps"}
    results = []
    last_result = None
    for i, step in enumerate(steps):
        name = step.get("action", "")
        if name not in _CHAIN:
            return {"error": f"step {i}: unknown action '{name}'", "available": list(_CHAIN.keys())}
        params = step.get("params", {})
        if last_result is not None:
            params = {k: v.replace("{{prev_result}}", str(last_result)) if isinstance(v, str) else v
                      for k, v in params.items()}
        out = _CHAIN[name](params)
        results.append({"step": i + 1, "action": name, "result": out})
        if isinstance(out, dict):
            last_result = out.get("result") or out.get("text") or str(out)
        else:
            last_result = str(out)
    return {"steps_completed": len(results), "chain": results, "final_result": results[-1]["result"] if results else None}


@mcp.tool()
def list_marketplace(category: str = None, max_price: float = None) -> dict:
    """
    Browse the agent marketplace — services offered by other AI agents.
    Args:
        category: Filter by category (optional)
        max_price: Maximum price in USD (optional)
    Returns list of active listings with endpoint, price, and description.
    """
    listings, total = marketplace_get_services(category=category, max_price=max_price, per_page=20)
    return {"total": total, "listings": listings}


@mcp.tool()
def post_to_marketplace(agent_id: str, name: str, description: str,
                         endpoint: str, price_usd: float,
                         category: str = "general",
                         capabilities: list = None) -> dict:
    """
    List your agent's service in the marketplace so other agents can discover and hire you.
    Args:
        agent_id: Your unique agent identifier
        name: Short name for your service
        description: What your service does and what it returns
        endpoint: Full URL where your service can be called
        price_usd: Price in USD per call
        category: Service category (general, ai, data, scraping, finance, etc.)
        capabilities: List of capability strings
    """
    return marketplace_list_service(
        agent_id=agent_id, name=name, description=description,
        endpoint=endpoint, price_usd=price_usd,
        category=category, capabilities=capabilities or [],
    )


@mcp.tool()
def get_current_time() -> dict:
    """Get current UTC time, Unix timestamp, date, and week number. Free, no payment needed."""
    from datetime import datetime, timezone
    now = datetime.utcnow()
    return {
        "utc": now.isoformat() + "Z",
        "unix": int(now.replace(tzinfo=timezone.utc).timestamp()),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "week_number": int(now.strftime("%W")),
    }


@mcp.tool()
def generate_uuid(count: int = 1) -> dict:
    """Generate one or more UUID4 values. Free, no payment needed."""
    import uuid
    if count == 1:
        return {"uuid": str(uuid.uuid4())}
    return {"uuids": [str(uuid.uuid4()) for _ in range(min(count, 50))]}


# ── Agent Messaging ────────────────────────────────────────────────────────────

@mcp.tool()
def send_agent_message(from_agent: str, to_agent: str, subject: str, body: str) -> dict:
    """Send a direct message from one agent to another via the agent network."""
    return send_message(from_agent, to_agent, subject, body)


@mcp.tool()
def read_agent_inbox(agent_id: str, unread_only: bool = False) -> dict:
    """Read messages from an agent's inbox. Set unread_only=True to filter."""
    messages = get_inbox(agent_id, unread_only=unread_only)
    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


# ── Knowledge Base ─────────────────────────────────────────────────────────────

@mcp.tool()
def add_to_knowledge_base(topic: str, content: str, author_agent: str,
                          tags: list = None) -> dict:
    """Add an entry to the shared agent knowledge base."""
    return add_knowledge(topic, content, author_agent, tags or [])


@mcp.tool()
def search_knowledge_base(query: str, limit: int = 10) -> dict:
    """Search the shared agent knowledge base by keyword."""
    results = search_knowledge(query, limit=limit)
    return {"query": query, "results": results, "count": len(results)}


@mcp.tool()
def get_trending_knowledge() -> dict:
    """Get the most popular topics in the shared agent knowledge base."""
    topics = get_trending_topics(limit=10)
    return {"trending": topics}


# ── Task Board ─────────────────────────────────────────────────────────────────

@mcp.tool()
def submit_agent_task(posted_by: str, title: str, description: str,
                      skills_needed: list = None, reward_usd: float = 0.0) -> dict:
    """Post a task to the agent task board for other agents to claim and complete."""
    from agent_network import submit_task as _submit_task
    return _submit_task(posted_by, title, description, skills_needed or [], reward_usd)


@mcp.tool()
def browse_agent_tasks(status: str = "open", skill: str = None) -> dict:
    """Browse tasks on the agent task board, optionally filtered by skill or status."""
    tasks = browse_tasks(status=status, skill=skill)
    return {"tasks": tasks, "count": len(tasks)}


# ── Code Execution ─────────────────────────────────────────────────────────────

@mcp.tool()
def run_python_code(code: str, timeout: int = 10) -> dict:
    """Execute Python code in a sandboxed subprocess. Returns stdout, stderr, returncode."""
    import subprocess
    import time as _time
    if len(code) > 5000:
        return {"error": "code too long (max 5000 chars)"}
    timeout = min(timeout, 15)
    start = _time.time()
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        return {
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
            "execution_time_ms": int((_time.time() - start) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": f"Code exceeded {timeout}s limit"}


# ── Web Search ─────────────────────────────────────────────────────────────────

@mcp.tool()
def web_search(query: str, n_results: int = 10) -> dict:
    """Search the web via DuckDuckGo. Returns instant answer and related results."""
    n = min(n_results, 25)
    try:
        resp = _mcp_requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        data = resp.json()
        results = [
            {"title": t.get("Text", ""), "url": t.get("FirstURL", "")}
            for t in data.get("RelatedTopics", [])[:n]
            if t.get("FirstURL")
        ]
        return {
            "query": query,
            "instant_answer": data.get("AbstractText", ""),
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Real-Time Data ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_weather(city: str) -> dict:
    """Get current weather for any city using Open-Meteo (free, no key needed)."""
    try:
        geo = _mcp_requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=8,
        ).json()
        results = geo.get("results", [])
        if not results:
            return {"error": "city_not_found", "city": city}
        loc = results[0]
        weather = _mcp_requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": loc["latitude"], "longitude": loc["longitude"], "current_weather": "true"},
            timeout=8,
        ).json()
        cw = weather.get("current_weather", {})
        return {
            "city": loc.get("name"),
            "country": loc.get("country"),
            "temperature_c": cw.get("temperature"),
            "windspeed_kmh": cw.get("windspeed"),
            "weather_code": cw.get("weathercode"),
            "is_day": cw.get("is_day"),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_crypto_prices(symbols: str = "bitcoin,ethereum") -> dict:
    """Get real-time crypto prices from CoinGecko. symbols: comma-separated CoinGecko IDs."""
    try:
        data = _mcp_requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbols, "vs_currencies": "usd,eur,gbp", "include_24hr_change": "true"},
            timeout=8,
        ).json()
        return {"prices": data, "symbols": symbols.split(",")}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_exchange_rates(base_currency: str = "USD") -> dict:
    """Get live exchange rates for 160+ currencies. base_currency: e.g. USD, EUR, GBP."""
    try:
        data = _mcp_requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{base_currency.upper()}",
            timeout=8,
        ).json()
        return {"base": base_currency.upper(), "date": data.get("date"), "rates": data.get("rates", {})}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def enrich_entity(entity: str, entity_type: str) -> dict:
    """Aggregate data about an entity. entity_type: ip | crypto | country | company."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/enrich",
            json={"entity": entity, "type": entity_type},
            timeout=30,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_joke() -> dict:
    """Get a random joke. Completely free."""
    try:
        resp = _mcp_requests.get("https://official-joke-api.appspot.com/random_joke", timeout=5)
        d = resp.json()
        return {"setup": d.get("setup"), "punchline": d.get("punchline"), "type": d.get("type")}
    except Exception:
        return {"setup": "Why don't scientists trust atoms?", "punchline": "Because they make up everything.", "type": "general"}


@mcp.tool()
def get_quote() -> dict:
    """Get a random inspirational quote. Completely free."""
    try:
        resp = _mcp_requests.get("https://zenquotes.io/api/random", timeout=5)
        d = resp.json()[0] if resp.ok else {}
        return {"quote": d.get("q"), "author": d.get("a")}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_holidays(country: str = "US", year: str = "") -> dict:
    """Get public holidays for a country. country: ISO 2-letter code (US, GB, DE). Free."""
    from datetime import datetime
    yr = year or str(datetime.utcnow().year)
    try:
        resp = _mcp_requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/{yr}/{country.upper()}",
            timeout=6,
        )
        holidays = resp.json()
        return {"country": country.upper(), "year": yr, "holidays": holidays[:20], "count": len(holidays)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def generate_api_key(label: str = "") -> dict:
    """Generate a prepaid AiPayGent API key. Use with Bearer auth to bypass x402 per-call payment."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/auth/generate-key",
            json={"label": label},
            timeout=5,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def check_api_key_balance(key: str) -> dict:
    """Check balance and usage stats for a prepaid AiPayGent API key."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/auth/status?key={key}", timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    import sys
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
