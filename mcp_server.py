"""
AiPayGen MCP Server — 106 metered tools

Exposes all AiPayGen capabilities as MCP tools with usage metering.
10 free calls/day without an API key. Unlimited with a prepaid key.

Usage:
  stdio (Claude Code / Cursor / Cline):
    python mcp_server.py

  SSE (deployed):
    python mcp_server.py --http

  With API key (unlimited):
    AIPAYGEN_API_KEY=apk_xxx python mcp_server.py

Add to Claude Code:
  claude mcp add aipaygen -- python /path/to/mcp_server.py
"""

import sys
import os
import functools
import hashlib

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from routes.ai_tools import (
    research_inner, summarize_inner, analyze_inner, translate_inner,
    social_inner, write_inner, code_inner, extract_inner, qa_inner,
    classify_inner, sentiment_inner, keywords_inner, compare_inner,
    transform_inner, chat_inner, plan_inner, decide_inner, proofread_inner,
    explain_inner, questions_inner, outline_inner, email_inner, sql_inner,
    regex_inner, mock_inner, score_inner, timeline_inner, action_inner,
    pitch_inner, debate_inner, headline_inner, fact_inner, rewrite_inner,
    tag_inner, think_inner, review_code_inner, generate_docs_inner,
    convert_code_inner, generate_api_spec_inner, diff_inner, parse_csv_inner,
    cron_expr_inner, changelog_inner, name_generator_inner, privacy_check_inner,
    pipeline_inner, BATCH_HANDLERS,
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
    check_and_use_free_tier, get_free_tier_remaining,
)
from api_keys import validate_key, deduct
from skills_search import SkillsSearchEngine
from mcp.server.transport_security import TransportSecuritySettings
import requests as _mcp_requests

# ── Skills search engine (direct, no HTTP round-trip) ─────────────────────────
_skills_db_path = os.path.join(os.path.dirname(__file__), "skills.db")
_skills_engine = SkillsSearchEngine(_skills_db_path)

mcp = FastMCP(
    "AiPayGen",
    instructions=(
        "AiPayGen is an AI agent API marketplace with 106 tools. "
        "Capabilities: research, write, code, translate, analyze, summarize, vision (image analysis), "
        "RAG (document Q&A), diagram generation, workflow orchestration, chain (pipeline multiple AI steps), "
        "web scraping (Google Maps, Twitter, Instagram, LinkedIn, YouTube, TikTok), "
        "persistent agent memory (survives sessions), agent marketplace (list & discover agent services), "
        "a catalog of 4100+ APIs, and 1500+ searchable skills. "
        "\n\n"
        "PRICING: Set AIPAYGEN_API_KEY env var for unlimited metered access. "
        "Without a key, you get 10 free calls/day. "
        "Get a key: POST https://api.aipaygen.com/credits/buy or visit https://api.aipaygen.com/docs. "
        "AI tools cost ~$0.006/call (3x model cost markup). Utility tools cost $0.002/call. "
        "All results include _billing metadata with cost and remaining balance."
    ),
    host="0.0.0.0",
    port=5002,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# ── Metered Tool Decorator ────────────────────────────────────────────────────

# Flat costs per tier (USD)
_TIER_COSTS = {
    "ai": 0.006,        # AI tools (LLM calls) — ~3x typical model cost
    "ai_heavy": 0.02,   # Heavy AI (workflow, pipeline, batch, chain)
    "scraping": 0.01,   # Web scraping (Apify costs)
    "standard": 0.002,  # Non-AI tools (data lookups, memory, etc.)
    "free": 0.0,        # Always free (time, uuid, jokes)
}

_PURCHASE_ERROR = {
    "error": "free_tier_exhausted",
    "message": "You've used all 10 free calls for today. Get unlimited access with an API key.",
    "how_to_get_key": {
        "stripe": "POST https://api.aipaygen.com/credits/buy with {\"amount_usd\": 5.0}",
        "mcp_tool": "Call the generate_api_key tool right here",
        "docs": "https://api.aipaygen.com/docs",
    },
    "note": "Free tier resets at midnight UTC. API keys get 20% bulk discount at $2+ balance.",
}


def metered_tool(tier: str = "standard"):
    """Decorator that wraps @mcp.tool() with API key validation and free-tier metering."""
    cost = _TIER_COSTS.get(tier, 0.002)

    def decorator(fn):
        @mcp.tool()
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            api_key = os.environ.get("AIPAYGEN_API_KEY", "")
            client_id = os.environ.get("AIPAYGEN_CLIENT_ID", "mcp_anonymous")

            # Free tier tools — always pass through
            if tier == "free":
                result = fn(*args, **kwargs)
                if isinstance(result, dict):
                    result["_billing"] = {"cost_usd": 0.0, "tier": "free"}
                return result

            # With API key — validate and deduct
            if api_key.startswith("apk_"):
                key_data = validate_key(api_key)
                if not key_data:
                    return {"error": "invalid_api_key", "message": "API key is invalid or inactive."}
                if key_data.get("balance_usd", 0) < cost:
                    return {
                        "error": "insufficient_balance",
                        "balance_usd": key_data.get("balance_usd", 0),
                        "cost_usd": cost,
                        "topup": "POST https://api.aipaygen.com/credits/buy",
                    }

                # Execute the tool
                result = fn(*args, **kwargs)

                # Calculate actual cost: use cost_usd from result if AI tool, else flat
                actual_cost = cost
                if tier in ("ai", "ai_heavy") and isinstance(result, dict):
                    model_cost = result.get("cost_usd", 0)
                    if model_cost and model_cost > 0:
                        actual_cost = round(model_cost * 3, 6)  # 3x markup on actual model cost
                        actual_cost = max(actual_cost, 0.001)    # floor

                # Deduct
                deducted = deduct(api_key, actual_cost)
                remaining = (key_data.get("balance_usd", 0) - actual_cost) if deducted else key_data.get("balance_usd", 0)

                if isinstance(result, dict):
                    result["_billing"] = {
                        "cost_usd": actual_cost,
                        "balance_remaining": round(remaining, 6),
                        "tier": tier,
                        "payment": "api_key",
                    }
                return result

            # Without API key — free tier (10/day)
            identifier = hashlib.sha256(client_id.encode()).hexdigest()[:16]
            if not check_and_use_free_tier(identifier):
                return _PURCHASE_ERROR

            result = fn(*args, **kwargs)
            remaining_calls = get_free_tier_remaining(identifier)
            if isinstance(result, dict):
                result["_billing"] = {
                    "cost_usd": 0.0,
                    "tier": "free_tier",
                    "free_calls_remaining": remaining_calls,
                    "daily_limit": 10,
                    "upgrade": "Set AIPAYGEN_API_KEY env var for unlimited access",
                }
            return result

        return wrapper
    return decorator


# ── AI Processing Tools (34 core + 6 advanced) ───────────────────────────────

@metered_tool("ai")
def research(topic: str) -> dict:
    """Research a topic. Returns structured summary, key points, and sources to check."""
    return research_inner(topic)


@metered_tool("ai")
def summarize(text: str, length: str = "short") -> dict:
    """Summarize long text. length: short | medium | detailed"""
    return summarize_inner(text, length)


@metered_tool("ai")
def analyze(content: str, question: str = "Provide a structured analysis") -> dict:
    """Deep structured analysis of content. Returns conclusion, findings, sentiment, confidence."""
    return analyze_inner(content, question)


@metered_tool("ai")
def translate(text: str, language: str = "Spanish") -> dict:
    """Translate text to any language."""
    return translate_inner(text, language)


@metered_tool("ai")
def social(topic: str, platforms: list[str] = None, tone: str = "engaging") -> dict:
    """Generate platform-optimized social media posts for Twitter, LinkedIn, Instagram, etc."""
    return social_inner(topic, platforms or ["twitter", "linkedin", "instagram"], tone)


@metered_tool("ai")
def write(spec: str, type: str = "article") -> dict:
    """Write articles, copy, or content to your specification. type: article | post | copy"""
    return write_inner(spec, type)


@metered_tool("ai")
def code(description: str, language: str = "Python") -> dict:
    """Generate production-ready code in any language from a plain-English description."""
    return code_inner(description, language)


@metered_tool("ai")
def extract(text: str, fields: list[str] = None, schema: str = "") -> dict:
    """Extract structured data from unstructured text. Define fields or a schema."""
    return extract_inner(text, schema, fields or [])


@metered_tool("ai")
def qa(context: str, question: str) -> dict:
    """Q&A over a document. Returns answer, confidence score, and source quote."""
    return qa_inner(context, question)


@metered_tool("ai")
def classify(text: str, categories: list[str]) -> dict:
    """Classify text into your defined categories with per-category confidence scores."""
    return classify_inner(text, categories)


@metered_tool("ai")
def sentiment(text: str) -> dict:
    """Deep sentiment analysis: polarity, score, emotions, confidence, key phrases."""
    return sentiment_inner(text)


@metered_tool("ai")
def keywords(text: str, max_keywords: int = 10) -> dict:
    """Extract keywords, topics, and tags from any text."""
    return keywords_inner(text, max_keywords)


@metered_tool("ai")
def compare(text_a: str, text_b: str, focus: str = "") -> dict:
    """Compare two texts: similarities, differences, similarity score, recommendation."""
    return compare_inner(text_a, text_b, focus)


@metered_tool("ai")
def transform(text: str, instruction: str) -> dict:
    """Transform text with any instruction: rewrite, reformat, expand, condense, change tone."""
    return transform_inner(text, instruction)


@metered_tool("ai")
def chat(messages: list[dict], system: str = "") -> dict:
    """Stateless multi-turn chat. Send full message history, get Claude reply."""
    return chat_inner(messages, system)


@metered_tool("ai")
def plan(goal: str, context: str = "", steps: int = 7) -> dict:
    """Step-by-step action plan for any goal with effort estimate and first action."""
    return plan_inner(goal, context, steps)


@metered_tool("ai")
def decide(decision: str, options: list[str] = None, criteria: str = "") -> dict:
    """Decision framework: pros, cons, risks, recommendation, and confidence score."""
    return decide_inner(decision, options, criteria)


@metered_tool("ai")
def proofread(text: str, style: str = "professional") -> dict:
    """Grammar and clarity corrections with tracked changes and writing quality score."""
    return proofread_inner(text, style)


@metered_tool("ai")
def explain(concept: str, level: str = "beginner", analogy: bool = True) -> dict:
    """Explain any concept at beginner, intermediate, or expert level with analogy."""
    return explain_inner(concept, level, analogy)


@metered_tool("ai")
def questions(content: str, type: str = "faq", count: int = 5) -> dict:
    """Generate questions + answers from any content. type: faq | interview | quiz | comprehension"""
    return questions_inner(content, type, count)


@metered_tool("ai")
def outline(topic: str, depth: int = 2, sections: int = 6) -> dict:
    """Generate a hierarchical outline with headings, summaries, and subsections."""
    return outline_inner(topic, depth, sections)


@metered_tool("ai")
def email(purpose: str, tone: str = "professional", context: str = "", recipient: str = "", length: str = "medium") -> dict:
    """Compose a professional email. Returns subject line and body."""
    return email_inner(purpose, tone, context, recipient, length)


@metered_tool("ai")
def sql(description: str, dialect: str = "postgresql", schema: str = "") -> dict:
    """Natural language to SQL. Returns query, explanation, and notes."""
    return sql_inner(description, dialect, schema)


@metered_tool("ai")
def regex(description: str, language: str = "python", flags: str = "") -> dict:
    """Generate a regex pattern from a plain-English description with examples."""
    return regex_inner(description, language, flags)


@metered_tool("ai")
def mock(description: str, count: int = 5, format: str = "json") -> dict:
    """Generate realistic mock data records. format: json | csv | list"""
    return mock_inner(description, min(count, 50), format)


@metered_tool("ai")
def score(content: str, criteria: list[str] = None, scale: int = 10) -> dict:
    """Score content on a custom rubric. Returns per-criterion scores, strengths, and weaknesses."""
    return score_inner(content, criteria or ["clarity", "accuracy", "engagement"], scale)


@metered_tool("ai")
def timeline(text: str, direction: str = "chronological") -> dict:
    """Extract or reconstruct a timeline from text. Returns dated events with significance."""
    return timeline_inner(text, direction)


@metered_tool("ai")
def action(text: str) -> dict:
    """Extract action items, tasks, owners, and due dates from meeting notes or any text."""
    return action_inner(text)


@metered_tool("ai")
def pitch(product: str, audience: str = "general", length: str = "30s") -> dict:
    """Generate an elevator pitch: hook, value prop, call to action, full script. length: 15s | 30s | 60s"""
    return pitch_inner(product, audience, length)


@metered_tool("ai")
def debate(topic: str, perspective: str = "balanced") -> dict:
    """Arguments for and against any position with strength ratings and verdict."""
    return debate_inner(topic, perspective)


@metered_tool("ai")
def headline(content: str, count: int = 5, style: str = "engaging") -> dict:
    """Generate headline variations with type labels and a best pick."""
    return headline_inner(content, count, style)


@metered_tool("ai")
def fact(text: str, count: int = 10) -> dict:
    """Extract factual claims with verifiability scores and source hints."""
    return fact_inner(text, count)


@metered_tool("ai")
def rewrite(text: str, audience: str = "general audience", tone: str = "neutral") -> dict:
    """Rewrite text for a specific audience, reading level, or brand voice."""
    return rewrite_inner(text, audience, tone)


@metered_tool("ai")
def tag(text: str, taxonomy: list[str] = None, max_tags: int = 10) -> dict:
    """Auto-tag content using a taxonomy or free-form. Returns tags, primary tag, categories."""
    return tag_inner(text, taxonomy, max_tags)


# ── Heavy AI Tools (multi-step) ──────────────────────────────────────────────

@metered_tool("ai")
def review_code(code: str, language: str = "auto", focus: str = "quality") -> dict:
    """Review code for quality, security, and performance issues. Returns issues, score, and summary."""
    return review_code_inner(code, language, focus)


@metered_tool("ai")
def generate_docs(code: str, style: str = "jsdoc") -> dict:
    """Generate documentation for code. Supports jsdoc, docstring, rustdoc, etc."""
    return generate_docs_inner(code, style)


@metered_tool("ai")
def convert_code(code: str, from_lang: str = "auto", to_lang: str = "python") -> dict:
    """Convert code from one programming language to another."""
    return convert_code_inner(code, from_lang, to_lang)


@metered_tool("ai")
def generate_api_spec(description: str, format: str = "openapi") -> dict:
    """Generate an OpenAPI/AsyncAPI specification from a natural language description."""
    return generate_api_spec_inner(description, format)


@metered_tool("ai")
def diff(text_a: str, text_b: str) -> dict:
    """Analyze differences between two texts or code snippets. Returns changes, summary, and similarity."""
    return diff_inner(text_a, text_b)


@metered_tool("ai")
def parse_csv(csv_text: str, question: str = "") -> dict:
    """Analyze CSV data and optionally answer questions about it. Returns columns, row count, and insights."""
    return parse_csv_inner(csv_text, question)


@metered_tool("ai")
def cron_expression(description: str) -> dict:
    """Generate or explain cron expressions from natural language. Returns cron string and next 5 runs."""
    return cron_expr_inner(description)


@metered_tool("ai")
def changelog(commits: str, version: str = "") -> dict:
    """Generate a professional changelog from commit messages. Groups by Added/Changed/Fixed/Removed."""
    return changelog_inner(commits, version)


@metered_tool("ai")
def name_generator(description: str, count: int = 10, style: str = "startup") -> dict:
    """Generate names for products, companies, or features with taglines and domain suggestions."""
    return name_generator_inner(description, count, style)


@metered_tool("ai")
def privacy_check(text: str) -> dict:
    """Scan text for PII, secrets, and sensitive data. Returns found items, risk level, and recommendations."""
    return privacy_check_inner(text)


@metered_tool("ai_heavy")
def think(problem: str, context: str = "", max_steps: int = 5) -> dict:
    """
    Autonomous chain-of-thought reasoning. Breaks down a problem, reasons
    step-by-step, optionally calls internal tools, and returns a structured
    solution with confidence score.

    problem: The problem or question to solve.
    context: Optional background information.
    max_steps: Maximum reasoning steps (1-10, default 5).
    """
    return think_inner(problem, context, max_steps=min(max_steps, 10))


@metered_tool("ai_heavy")
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


@metered_tool("ai_heavy")
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


# ── Vision & Advanced AI Tools ───────────────────────────────────────────────

@metered_tool("ai")
def vision(image_url: str, question: str = "Describe this image in detail") -> dict:
    """Analyze any image URL using Claude Vision. Ask specific questions or get a full description."""
    return vision_inner(image_url, question)


@metered_tool("ai")
def rag(documents: str, query: str) -> dict:
    """
    Grounded Q&A using only your documents. Separate multiple documents with '---'.
    Returns answer, confidence, citations, and a cannot_answer flag.
    """
    return rag_inner(documents, query)


@metered_tool("ai")
def diagram(description: str, diagram_type: str = "flowchart") -> dict:
    """
    Generate a Mermaid diagram from a plain English description.
    Types: flowchart, sequence, erd, gantt, mindmap
    """
    return diagram_inner(description, diagram_type)


@metered_tool("ai")
def json_schema(description: str, example: str = "") -> dict:
    """Generate a JSON Schema (draft-07) from a plain English description of your data structure."""
    return json_schema_inner(description, example)


@metered_tool("ai")
def test_cases(code_or_description: str, language: str = "python") -> dict:
    """Generate comprehensive test cases with edge cases for code or a feature description."""
    return test_cases_inner(code_or_description, language)


@metered_tool("ai_heavy")
def workflow(goal: str, context: str = "") -> dict:
    """
    Multi-step agentic reasoning using Claude Sonnet. Breaks down complex goals,
    reasons through each sub-task, and produces a comprehensive result.
    Best for complex tasks requiring multiple steps of reasoning.
    """
    return workflow_inner(goal, context)


# ── Agent Memory Tools ───────────────────────────────────────────────────────

@metered_tool("standard")
def memory_store(agent_id: str, key: str, value: str, tags: str = "") -> dict:
    """
    Store a persistent memory for an agent. Survives across sessions.
    agent_id: stable identifier for your agent (UUID, DID, or name).
    tags: comma-separated (optional).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    return memory_set(agent_id, key, value, tag_list)


@metered_tool("standard")
def memory_recall(agent_id: str, key: str) -> dict:
    """Retrieve a stored memory by agent_id and key. Returns value, tags, and timestamps."""
    result = memory_get(agent_id, key)
    return result or {"error": "not_found", "agent_id": agent_id, "key": key}


@metered_tool("standard")
def memory_find(agent_id: str, query: str) -> dict:
    """Search all memories for an agent by keyword. Returns ranked matching key-value pairs."""
    results = memory_search(agent_id, query)
    return {"agent_id": agent_id, "query": query, "results": results, "count": len(results)}


@metered_tool("standard")
def memory_keys(agent_id: str) -> dict:
    """List all memory keys stored for an agent, with tags and last-updated timestamps."""
    return {"agent_id": agent_id, "keys": memory_list(agent_id)}


# ── API Catalog Tools ────────────────────────────────────────────────────────

@metered_tool("standard")
def browse_catalog(category: str = "", min_score: float = 0.0, free_only: bool = False, page: int = 1) -> dict:
    """
    Browse the AiPayGen catalog of 4100+ APIs.
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


@metered_tool("standard")
def get_catalog_api(api_id: int) -> dict:
    """Get full details for a specific API in the catalog by its numeric ID."""
    result = get_api(api_id)
    return result or {"error": "not_found", "api_id": api_id}


@metered_tool("ai")
def invoke_catalog_api(api_id: int, endpoint: str = "/", params: str = "{}") -> dict:
    """
    Actually call a catalog API and return its response.
    Get api_id from browse_catalog first. endpoint is the path to hit.
    params is a JSON string of query parameters (e.g. '{"q":"test"}').
    """
    from security import validate_url, SSRFError, safe_fetch
    from api_catalog import record_api_economics
    import json as _json
    api = get_api(api_id)
    if not api:
        return {"error": "not_found", "api_id": api_id}
    url = api["base_url"].rstrip("/") + "/" + endpoint.lstrip("/")
    try:
        validate_url(url, allow_http=False)
    except SSRFError as e:
        return {"error": f"Blocked: {e}"}
    try:
        qp = _json.loads(params) if params and params != "{}" else {}
    except Exception:
        qp = {}
    if qp:
        qs = "&".join(f"{k}={v}" for k, v in qp.items())
        url += ("&" if "?" in url else "?") + qs
    result = safe_fetch(url, timeout=15, max_size=50000)
    if "error" in result:
        return {"api": api["name"], "error": result["error"]}
    record_api_economics(api_id, 0.006, 0)
    return {"api": api["name"], "url": url, "status": result.get("status"),
            "response": result.get("body", "")[:3000]}


# ── Agent Registry Tools ─────────────────────────────────────────────────────

@metered_tool("standard")
def register_my_agent(agent_id: str, name: str, description: str,
                      capabilities: str, endpoint: str = "") -> dict:
    """
    Register your agent in the AiPayGen agent registry.
    capabilities: comma-separated list of what your agent can do.
    endpoint: optional URL where other agents can reach you.
    """
    cap_list = [c.strip() for c in capabilities.split(",") if c.strip()]
    return register_agent(agent_id, name, description, cap_list, endpoint or None)


@metered_tool("standard")
def list_registered_agents() -> dict:
    """Browse all agents registered in the AiPayGen registry."""
    agents = list_agents()
    return {"agents": agents, "count": len(agents)}


# ── Web Scraping Tools ───────────────────────────────────────────────────────

def _apify_run(actor_id: str, run_input: dict, max_items: int = 10) -> list:
    try:
        return run_actor_sync(actor_id, run_input, max_items=max_items)
    except Exception as e:
        return [{"error": str(e)}]


@metered_tool("scraping")
def scrape_google_maps(query: str, max_results: int = 5) -> dict:
    """Scrape Google Maps for businesses matching a query. Returns name, address, rating, phone, website."""
    results = _apify_run("nwua9Gu5YrADL7ZDj",
                         {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tweets(query: str, max_results: int = 20) -> dict:
    """Scrape Twitter/X tweets by search query or hashtag. Returns text, author, likes, retweets, date."""
    results = _apify_run("61RPP7dywgiy0JPD0",
                         {"searchTerms": [query], "maxItems": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_website(url: str, max_pages: int = 3) -> dict:
    """Crawl any website and extract text content. Returns page URL, title, and text per page."""
    results = _apify_run("aYG0l9s7dbB7j3gbS",
                         {"startUrls": [{"url": url}], "maxCrawlPages": max_pages},
                         max_pages)
    return {"url": url, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_youtube(query: str, max_results: int = 5) -> dict:
    """Search YouTube and return video metadata — title, channel, views, duration, description, URL."""
    results = _apify_run("h7sDV53CddomktSi5",
                         {"searchKeywords": query, "maxResults": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_instagram(username: str, max_posts: int = 5) -> dict:
    """Scrape Instagram profile posts. Returns caption, likes, comments, date, media URL."""
    results = _apify_run("shu8hvrXbJbY3Eb9W",
                         {"username": [username], "resultsLimit": max_posts},
                         max_posts)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tiktok(username: str, max_videos: int = 5) -> dict:
    """Scrape TikTok profile videos. Returns caption, views, likes, shares, date."""
    results = _apify_run("GdWCkxBtKWOsKjdch",
                         {"profiles": [username], "resultsPerPage": max_videos},
                         max_videos)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("ai_heavy")
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
        "research": lambda p: research_inner(p.get("topic", "")),
        "summarize": lambda p: summarize_inner(p.get("text", ""), p.get("length", "short")),
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
        "json_schema": lambda p: json_schema_inner(p.get("description", ""), str(p.get("example", ""))),
        "workflow": lambda p: workflow_inner(p.get("goal", ""), str(p.get("available_data", ""))),
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


# ── Marketplace ──────────────────────────────────────────────────────────────

@metered_tool("standard")
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


@metered_tool("standard")
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


# ── Free Utility Tools ──────────────────────────────────────────────────────

@metered_tool("free")
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


@metered_tool("free")
def generate_uuid(count: int = 1) -> dict:
    """Generate one or more UUID4 values. Free, no payment needed."""
    import uuid
    if count == 1:
        return {"uuid": str(uuid.uuid4())}
    return {"uuids": [str(uuid.uuid4()) for _ in range(min(count, 50))]}


@metered_tool("free")
def get_joke() -> dict:
    """Get a random joke. Completely free."""
    try:
        resp = _mcp_requests.get("https://official-joke-api.appspot.com/random_joke", timeout=5)
        d = resp.json()
        return {"setup": d.get("setup"), "punchline": d.get("punchline"), "type": d.get("type")}
    except Exception:
        return {"setup": "Why don't scientists trust atoms?", "punchline": "Because they make up everything.", "type": "general"}


@metered_tool("free")
def get_quote() -> dict:
    """Get a random inspirational quote. Completely free."""
    try:
        resp = _mcp_requests.get("https://zenquotes.io/api/random", timeout=5)
        d = resp.json()[0] if resp.ok else {}
        return {"quote": d.get("q"), "author": d.get("a")}
    except Exception as e:
        return {"error": str(e)}


@metered_tool("free")
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


# ── Agent Messaging ──────────────────────────────────────────────────────────

@metered_tool("standard")
def send_agent_message(from_agent: str, to_agent: str, subject: str, body: str) -> dict:
    """Send a direct message from one agent to another via the agent network."""
    return send_message(from_agent, to_agent, subject, body)


@metered_tool("standard")
def read_agent_inbox(agent_id: str, unread_only: bool = False) -> dict:
    """Read messages from an agent's inbox. Set unread_only=True to filter."""
    messages = get_inbox(agent_id, unread_only=unread_only)
    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


# ── Knowledge Base ───────────────────────────────────────────────────────────

@metered_tool("standard")
def add_to_knowledge_base(topic: str, content: str, author_agent: str,
                          tags: list = None) -> dict:
    """Add an entry to the shared agent knowledge base."""
    return add_knowledge(topic, content, author_agent, tags or [])


@metered_tool("standard")
def search_knowledge_base(query: str, limit: int = 10) -> dict:
    """Search the shared agent knowledge base by keyword."""
    results = search_knowledge(query, limit=limit)
    return {"query": query, "results": results, "count": len(results)}


@metered_tool("standard")
def get_trending_knowledge() -> dict:
    """Get the most popular topics in the shared agent knowledge base."""
    topics = get_trending_topics(limit=10)
    return {"trending": topics}


# ── Task Board ───────────────────────────────────────────────────────────────

@metered_tool("standard")
def submit_agent_task(posted_by: str, title: str, description: str,
                      skills_needed: list = None, reward_usd: float = 0.0) -> dict:
    """Post a task to the agent task board for other agents to claim and complete."""
    from agent_network import submit_task as _submit_task
    return _submit_task(posted_by, title, description, skills_needed or [], reward_usd)


@metered_tool("standard")
def browse_agent_tasks(status: str = "open", skill: str = None) -> dict:
    """Browse tasks on the agent task board, optionally filtered by skill or status."""
    tasks = browse_tasks(status=status, skill=skill)
    return {"tasks": tasks, "count": len(tasks)}


# ── Code Execution ───────────────────────────────────────────────────────────

@metered_tool("standard")
def run_python_code(code: str, timeout: int = 10) -> dict:
    """Execute Python code in a sandboxed subprocess. Returns stdout, stderr, returncode.
    Imports, file I/O, network access, and OS commands are blocked."""
    import subprocess
    import time as _time
    from security import validate_code_safety, SandboxViolation, get_sandbox_env
    if len(code) > 5000:
        return {"error": "code too long (max 5000 chars)"}
    try:
        validate_code_safety(code)
    except SandboxViolation as e:
        return {"error": f"Sandbox violation: {e}"}
    timeout = min(timeout, 15)
    start = _time.time()
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_sandbox_env(),
            cwd="/tmp",
        )
        return {
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
            "execution_time_ms": int((_time.time() - start) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": f"Code exceeded {timeout}s limit"}


# ── Web Search ───────────────────────────────────────────────────────────────

@metered_tool("standard")
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


# ── Real-Time Data ───────────────────────────────────────────────────────────

@metered_tool("standard")
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


@metered_tool("standard")
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


@metered_tool("standard")
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


@metered_tool("standard")
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


# ── API Key Management ───────────────────────────────────────────────────────

@metered_tool("free")
def generate_api_key(label: str = "") -> dict:
    """Generate a prepaid AiPayGen API key. Use with Bearer auth to bypass x402 per-call payment."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/auth/generate-key",
            json={"label": label},
            timeout=5,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("free")
def check_api_key_balance(key: str) -> dict:
    """Check balance and usage stats for a prepaid AiPayGen API key."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/auth/status?key={key}", timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ── Skills System (Skill Harvester MCP Tools) ────────────────────────────────

@metered_tool("standard")
def search_skills(query: str, top_n: int = 10) -> dict:
    """Search 646+ skills using TF-IDF semantic search. Returns ranked skills with scores.
    Use this to discover capabilities before calling execute_skill."""
    _skills_engine.build_index()
    results = _skills_engine.search(query, top_n=min(top_n, 50))
    return {
        "query": query,
        "results": [
            {
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "category": s.get("category", ""),
                "score": s.get("score", 0),
                "calls": s.get("calls", 0),
            }
            for s in results
        ],
        "count": len(results),
        "total_skills": len(_skills_engine.skills) if _skills_engine._built else 0,
    }


@metered_tool("standard")
def list_skills(category: str = "") -> dict:
    """List available skills, optionally filtered by category. Shows name, description, and usage count."""
    _skills_engine.build_index()
    skills = list(_skills_engine.skills.values())
    if category:
        cat_lower = category.lower()
        skills = [s for s in skills if (s.get("category") or "").lower() == cat_lower]
    # Sort by call count descending
    skills.sort(key=lambda s: s.get("calls", 0), reverse=True)
    skills = skills[:20]
    categories = list({s.get("category", "general") for s in _skills_engine.skills.values()})
    return {
        "skills": [
            {
                "name": s.get("name", ""),
                "description": s.get("description", "")[:200],
                "category": s.get("category", ""),
                "calls": s.get("calls", 0),
            }
            for s in skills
        ],
        "count": len(skills),
        "categories": sorted(categories),
        "total_skills": len(_skills_engine.skills) if _skills_engine._built else 0,
    }


@metered_tool("ai")
def execute_skill(skill_name: str, input_text: str) -> dict:
    """Execute a specific skill by name. Use search_skills or list_skills to discover available skills."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/execute",
            json={"skill": skill_name, "input": input_text}, timeout=120)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("ai")
def ask(question: str) -> dict:
    """Universal endpoint — ask anything. AiPayGen picks the best skill and model automatically."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/ask",
            json={"question": question}, timeout=120)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def create_skill(name: str, description: str, prompt_template: str, category: str = "general") -> dict:
    """Create a new reusable skill. prompt_template must contain {{input}} placeholder."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/create",
            json={"name": name, "description": description,
                  "prompt_template": prompt_template, "category": category}, timeout=30)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def absorb_skill(url: str = "", text: str = "") -> dict:
    """Absorb a new skill from a URL or text. AiPayGen reads and creates a callable skill."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/absorb",
            json={"url": url, "text": text}, timeout=60)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ── Agent Builder & Account Tools ─────────────────────────────────────────────

@metered_tool("free")
def check_balance() -> dict:
    """Check your API key balance and usage stats. Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key:
        return {"error": "AIPAYGEN_API_KEY env var not set"}
    try:
        resp = _mcp_requests.get("http://localhost:5001/auth/status",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("free")
def list_models() -> dict:
    """List all available AI models with their providers and capabilities."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/models", timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def create_agent(name: str, description: str, tools: list = None,
                 template: str = "", model: str = "auto") -> dict:
    """Create a custom AI agent with selected tools and configuration."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/agents/build",
            json={"name": name, "description": description,
                  "tools": tools or [], "template": template, "model": model},
            timeout=30)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def list_my_agents() -> dict:
    """List all agents you have created. Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/list",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("ai")
def run_agent(agent_id: str, input_text: str = "") -> dict:
    """Run a custom agent by ID with optional input text."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/run",
            json={"input": input_text}, timeout=120)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def schedule_agent(agent_id: str, schedule_type: str = "cron",
                   schedule_value: str = "") -> dict:
    """Schedule an agent to run automatically. schedule_type: cron | loop | event."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/schedule",
            json={"schedule_type": schedule_type, "schedule_value": schedule_value},
            timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def pause_agent(agent_id: str) -> dict:
    """Pause a scheduled agent."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/pause",
            timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def get_agent_runs(agent_id: str) -> dict:
    """Get execution history for an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agents/{agent_id}/runs",
            timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@metered_tool("standard")
def delete_agent(agent_id: str) -> dict:
    """Delete a custom agent by ID."""
    try:
        resp = _mcp_requests.delete(f"http://localhost:5001/agents/{agent_id}",
            timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    import sys
    if "--http" in sys.argv:
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        import uvicorn

        starlette_app = mcp.streamable_http_app()

        async def health(request):
            tool_count = len([m for m in dir() if callable(getattr(__import__(__name__), m, None)) and hasattr(getattr(__import__(__name__), m, None), '__wrapped__')])
            return JSONResponse({"status": "ok", "server": "AiPayGen MCP", "tools": 106, "version": "1.6.0"})

        starlette_app.routes.insert(0, Route("/health", health))
        uvicorn.run(starlette_app, host="0.0.0.0", port=5002)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
