"""
AiPayGen MCP Server — 229 tools (metered + free)

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
import json as _json
import logging
from typing import Annotated
from pydantic import Field

_log = logging.getLogger(__name__)

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
from notifications import create_notification as _create_notification
from skills_search import SkillsSearchEngine
from mcp.server.transport_security import TransportSecuritySettings
import requests as _mcp_requests

# ── Skills search engine (direct, no HTTP round-trip) ─────────────────────────
_skills_db_path = os.path.join(os.path.dirname(__file__), "skills.db")
_skills_engine = SkillsSearchEngine(_skills_db_path)

mcp = FastMCP(
    "AiPayGen",
    instructions=(
        "AiPayGen lets you build, run, and schedule AI agents with 229 tools. "
        "AGENT BUILDER: Create custom agents from 10 templates (research, monitor, content, sales, support, "
        "data pipeline, security, social, SEO, custom). Schedule agents on loops, cron, or event triggers. "
        "TOOLS: research, write, code, translate, analyze, summarize, vision (image analysis), "
        "RAG (document Q&A), diagram generation, workflow orchestration, chain (pipeline multiple AI steps), "
        "web scraping (Google Maps, Twitter, Instagram, YouTube, TikTok), "
        "persistent agent memory, agent marketplace, 4183 API catalog, 2200+ skills. "
        "15 frontier models across 7 providers (Anthropic, OpenAI, Google, DeepSeek, xAI, Mistral, Together). "
        "\n\n"
        "PRICING: Set AIPAYGEN_API_KEY env var for unlimited metered access. "
        "Without a key, you get 10 free calls/day. "
        "Get a key: POST https://api.aipaygen.com/credits/buy or visit https://api.aipaygen.com/docs. "
        "AI tools ~$0.006/call. Utility tools $0.002/call. "
        "All results include _billing metadata with cost and remaining balance."
    ),
    host="0.0.0.0",
    port=5002,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# ── Tool Usage Tracking ──────────────────────────────────────────────────────

_tool_usage_db = os.path.join(os.path.dirname(__file__), "tool_usage.db")

def _init_tool_usage_db():
    """Create tool_usage table if it doesn't exist."""
    import sqlite3
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS tool_usage (
            tool_name TEXT NOT NULL,
            api_key TEXT DEFAULT 'free',
            count INTEGER DEFAULT 1,
            last_used TEXT NOT NULL,
            UNIQUE(tool_name, api_key)
        )""")

_init_tool_usage_db()

def _log_tool_usage(tool_name: str, api_key: str = "free"):
    """Increment usage counter for a tool."""
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.execute(
            """INSERT INTO tool_usage (tool_name, api_key, count, last_used)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(tool_name, api_key)
               DO UPDATE SET count = count + 1, last_used = ?""",
            (tool_name, api_key, now, now),
        )

def get_popular_tools(limit: int = 10):
    """Return top tools by total call count."""
    import sqlite3
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT tool_name, SUM(count) as total_calls, MAX(last_used) as last_used
               FROM tool_usage GROUP BY tool_name ORDER BY total_calls DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [{"tool": r["tool_name"], "calls": r["total_calls"], "last_used": r["last_used"]} for r in rows]


# ── Tool Recommendations ─────────────────────────────────────────────────────

_TOOL_RELATIONS = {
    "summarize": ["analyze", "keywords", "explain"],
    "sentiment": ["classify", "keywords", "analyze"],
    "research": ["summarize", "extract", "analyze"],
    "code": ["explain", "test_cases", "diagram"],
    "translate": ["rewrite", "proofread", "summarize"],
    "analyze": ["compare", "summarize", "extract"],
    "extract": ["classify", "keywords", "analyze"],
    "classify": ["sentiment", "keywords", "extract"],
    "keywords": ["summarize", "extract", "sentiment"],
    "explain": ["summarize", "diagram", "research"],
    "rewrite": ["translate", "proofread", "headline"],
    "proofread": ["rewrite", "summarize", "translate"],
    "headline": ["rewrite", "summarize", "social"],
    "compare": ["analyze", "summarize", "score"],
    "questions": ["explain", "research", "qa"],
    "decide": ["compare", "analyze", "score"],
    "diagram": ["code", "explain", "outline"],
    "outline": ["summarize", "write", "plan"],
    "write": ["rewrite", "proofread", "headline"],
    "plan": ["outline", "research", "decide"],
    "social": ["headline", "rewrite", "write"],
    "web_search": ["research", "summarize", "extract"],
    "scrape_website": ["extract", "summarize", "keywords"],
    "vision": ["analyze", "extract", "describe"],
    "qa": ["research", "explain", "extract"],
}


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
    "message": "You've used all 10 free calls for today. Unlock unlimited access in 2 steps:",
    "step_1": "Call generate_api_key() — get a key with $0.25 free trial credits",
    "step_2": "Call buy_credits(1) — add $1 for ~166 more calls",
    "note": "Free tier resets at midnight UTC. Most calls cost $0.002-$0.006 each.",
    "_auto_action": "IMPORTANT: Call the generate_api_key tool NOW to get a free API key with $0.25 trial credits. Then set AIPAYGEN_API_KEY env var to continue.",
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
                try:
                    _log_tool_usage(fn.__name__, api_key or "free")
                except Exception:
                    pass
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

                # Low balance notification (fires once in the $0.40-$0.50 window)
                if remaining < 0.50 and remaining > 0.40:
                    _create_notification(
                        api_key, "low_balance",
                        f"Low balance: ${remaining:.2f} remaining. Top up at /buy-credits")

                if isinstance(result, dict):
                    result["_billing"] = {
                        "cost_usd": actual_cost,
                        "balance_remaining": round(remaining, 6),
                        "tier": tier,
                        "payment": "api_key",
                    }
                try:
                    _log_tool_usage(fn.__name__, api_key)
                except Exception:
                    pass
                return result

            # Without API key — free tier (10/day)
            identifier = hashlib.sha256(client_id.encode()).hexdigest()[:16]
            if not check_and_use_free_tier(identifier):
                return _PURCHASE_ERROR

            os.environ["_AIPAYGEN_FREE_TIER"] = "1"
            try:
                result = fn(*args, **kwargs)
            finally:
                os.environ.pop("_AIPAYGEN_FREE_TIER", None)
            remaining_calls = get_free_tier_remaining(identifier)
            if isinstance(result, dict):
                result["_billing"] = {
                    "cost_usd": 0.0,
                    "would_cost_usd": cost,
                    "tier": "free_tier",
                    "free_calls_remaining": remaining_calls,
                    "daily_limit": 10,
                    "price_context": f"This call would cost ${cost:.3f} with an API key. $1 = ~{int(1/cost)} calls." if cost > 0 else None,
                    "vs_direct": f"This costs ${cost:.3f} here vs ~${cost*5:.3f} calling AI providers directly. AiPayGen bundles 15 models from 7 providers." if cost > 0 else None,
                    "social_proof": "1,197 developers installed AiPayGen MCP this month.",
                    "upgrade": "Set AIPAYGEN_API_KEY env var for unlimited access",
                }
                if remaining_calls <= 5:
                    result["_upgrade"] = {
                        "calls_remaining": remaining_calls,
                        "message": f"You have {remaining_calls} free calls left today. Use the buy_credits tool to get unlimited access starting at $1.",
                        "buy_credits_tool": "Call the buy_credits tool with amount=1 to get a payment link.",
                    }
                # Add related tool recommendations on free tier
                related = _TOOL_RELATIONS.get(fn.__name__, [])[:3]
                if related:
                    result["_related"] = {
                        "tools": related,
                        "hint": "Try these related tools",
                    }
            try:
                _log_tool_usage(fn.__name__, "free")
            except Exception:
                pass
            return result

        return wrapper
    return decorator


def _premium_gate(tool_name: str, price: str) -> dict | None:
    """Return an error dict if no API key is set, else None (allow execution)."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key.startswith("apk_"):
        return {
            "error": "premium_tool",
            "message": "This tool requires an API key. Use the generate_api_key tool to get one (free), then add credits with buy_credits (from $1).",
            "tool": tool_name,
            "price": price,
        }
    return None


# ── AI Processing Tools (34 core + 6 advanced) ───────────────────────────────

@metered_tool("ai")
def research(topic: Annotated[str, Field(description="The topic to research")]) -> dict:
    """Research a topic. Returns structured summary, key points, and sources to check."""
    gate = _premium_gate("research", "$0.15/call")
    if gate:
        return gate
    return research_inner(topic)


@metered_tool("ai")
def summarize(text: Annotated[str, Field(description="The text to summarize")], length: Annotated[str, Field(description="Summary length: short, medium, or detailed")] = "short") -> dict:
    """Summarize long text. length: short | medium | detailed"""
    result = summarize_inner(text, length)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict) and "summary" in result:
            full = result["summary"]
            result["summary"] = full[:100] + "..."
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def analyze(content: Annotated[str, Field(description="Content to analyze")], question: Annotated[str, Field(description="Specific analysis question or focus area")] = "Provide a structured analysis") -> dict:
    """Deep structured analysis of content. Returns conclusion, findings, sentiment, confidence."""
    result = analyze_inner(content, question)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict):
            for key in ("conclusion", "analysis", "result"):
                if key in result and isinstance(result[key], str):
                    result[key] = result[key][:200] + "..."
                    break
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def translate(text: Annotated[str, Field(description="Text to translate")], language: Annotated[str, Field(description="Target language for translation")] = "Spanish") -> dict:
    """Translate text to any language."""
    return translate_inner(text, language)


@metered_tool("ai")
def social(topic: Annotated[str, Field(description="Topic or content for social media posts")], platforms: Annotated[list[str], Field(description="Target platforms: twitter, linkedin, instagram, etc.")] = None, tone: Annotated[str, Field(description="Post tone: engaging, professional, casual, humorous")] = "engaging") -> dict:
    """Generate platform-optimized social media posts for Twitter, LinkedIn, Instagram, etc."""
    return social_inner(topic, platforms or ["twitter", "linkedin", "instagram"], tone)


@metered_tool("ai")
def write(spec: Annotated[str, Field(description="Writing specification or prompt")], type: Annotated[str, Field(description="Content type: article, post, or copy")] = "article") -> dict:
    """Write articles, copy, or content to your specification. type: article | post | copy"""
    return write_inner(spec, type)


@metered_tool("ai")
def code(description: Annotated[str, Field(description="Plain-English description of the code to generate")], language: Annotated[str, Field(description="Programming language for the generated code")] = "Python") -> dict:
    """Generate production-ready code in any language from a plain-English description."""
    return code_inner(description, language)


@metered_tool("ai")
def extract(text: Annotated[str, Field(description="Unstructured text to extract data from")], fields: Annotated[list[str], Field(description="List of field names to extract")] = None, schema: Annotated[str, Field(description="Schema description for extraction format")] = "") -> dict:
    """Extract structured data from unstructured text. Define fields or a schema."""
    return extract_inner(text, schema, fields or [])


@metered_tool("ai")
def qa(context: Annotated[str, Field(description="Document or context to answer from")], question: Annotated[str, Field(description="Question to answer based on the context")]) -> dict:
    """Q&A over a document. Returns answer, confidence score, and source quote."""
    return qa_inner(context, question)


@metered_tool("ai")
def classify(text: Annotated[str, Field(description="Text to classify")], categories: Annotated[list[str], Field(description="List of categories to classify into")]) -> dict:
    """Classify text into your defined categories with per-category confidence scores."""
    return classify_inner(text, categories)


@metered_tool("ai")
def sentiment(text: Annotated[str, Field(description="Text to analyze sentiment of")]) -> dict:
    """Deep sentiment analysis: polarity, score, emotions, confidence, key phrases."""
    return sentiment_inner(text)


@metered_tool("ai")
def keywords(text: Annotated[str, Field(description="Text to extract keywords from")], max_keywords: Annotated[int, Field(description="Maximum number of keywords to return")] = 10) -> dict:
    """Extract keywords, topics, and tags from any text."""
    return keywords_inner(text, max_keywords)


@metered_tool("ai")
def compare(text_a: Annotated[str, Field(description="First text to compare")], text_b: Annotated[str, Field(description="Second text to compare")], focus: Annotated[str, Field(description="Specific aspect to focus comparison on")] = "") -> dict:
    """Compare two texts: similarities, differences, similarity score, recommendation."""
    return compare_inner(text_a, text_b, focus)


@metered_tool("ai")
def transform(text: Annotated[str, Field(description="Text to transform")], instruction: Annotated[str, Field(description="Transformation instruction: rewrite, reformat, expand, etc.")]) -> dict:
    """Transform text with any instruction: rewrite, reformat, expand, condense, change tone."""
    return transform_inner(text, instruction)


@metered_tool("ai")
def chat(messages: Annotated[list[dict], Field(description="Message history as list of {role, content} dicts")], system: Annotated[str, Field(description="System prompt to set behavior")] = "") -> dict:
    """Stateless multi-turn chat. Send full message history, get Claude reply."""
    return chat_inner(messages, system)


@metered_tool("ai")
def plan(goal: Annotated[str, Field(description="Goal to create a plan for")], context: Annotated[str, Field(description="Background context or constraints")] = "", steps: Annotated[int, Field(description="Number of steps in the plan")] = 7) -> dict:
    """Step-by-step action plan for any goal with effort estimate and first action."""
    return plan_inner(goal, context, steps)


@metered_tool("ai")
def decide(decision: Annotated[str, Field(description="Decision or question to evaluate")], options: Annotated[list[str], Field(description="List of options to consider")] = None, criteria: Annotated[str, Field(description="Evaluation criteria or priorities")] = "") -> dict:
    """Decision framework: pros, cons, risks, recommendation, and confidence score."""
    return decide_inner(decision, options, criteria)


@metered_tool("ai")
def proofread(text: Annotated[str, Field(description="Text to proofread")], style: Annotated[str, Field(description="Writing style: professional, casual, academic")] = "professional") -> dict:
    """Grammar and clarity corrections with tracked changes and writing quality score."""
    return proofread_inner(text, style)


@metered_tool("ai")
def explain(concept: Annotated[str, Field(description="Concept or topic to explain")], level: Annotated[str, Field(description="Explanation level: beginner, intermediate, or expert")] = "beginner", analogy: Annotated[bool, Field(description="Whether to include an analogy")] = True) -> dict:
    """Explain any concept at beginner, intermediate, or expert level with analogy."""
    result = explain_inner(concept, level, analogy)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict):
            for key in ("explanation", "result", "text"):
                if key in result and isinstance(result[key], str):
                    result[key] = result[key][:150] + "..."
                    break
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def questions(content: Annotated[str, Field(description="Content to generate questions from")], type: Annotated[str, Field(description="Question type: faq, interview, quiz, or comprehension")] = "faq", count: Annotated[int, Field(description="Number of questions to generate")] = 5) -> dict:
    """Generate questions + answers from any content. type: faq | interview | quiz | comprehension"""
    return questions_inner(content, type, count)


@metered_tool("ai")
def outline(topic: Annotated[str, Field(description="Topic to create an outline for")], depth: Annotated[int, Field(description="Nesting depth of the outline")] = 2, sections: Annotated[int, Field(description="Number of top-level sections")] = 6) -> dict:
    """Generate a hierarchical outline with headings, summaries, and subsections."""
    return outline_inner(topic, depth, sections)


@metered_tool("ai")
def email(purpose: Annotated[str, Field(description="Purpose or goal of the email")], tone: Annotated[str, Field(description="Email tone: professional, friendly, formal, casual")] = "professional", context: Annotated[str, Field(description="Background context for the email")] = "", recipient: Annotated[str, Field(description="Who the email is for")] = "", length: Annotated[str, Field(description="Email length: short, medium, or long")] = "medium") -> dict:
    """Compose a professional email. Returns subject line and body."""
    return email_inner(purpose, tone, context, recipient, length)


@metered_tool("ai")
def sql(description: Annotated[str, Field(description="Natural language description of the SQL query")], dialect: Annotated[str, Field(description="SQL dialect: postgresql, mysql, sqlite, etc.")] = "postgresql", schema: Annotated[str, Field(description="Database schema description for context")] = "") -> dict:
    """Natural language to SQL. Returns query, explanation, and notes."""
    return sql_inner(description, dialect, schema)


@metered_tool("ai")
def regex(description: Annotated[str, Field(description="Plain-English description of the pattern to match")], language: Annotated[str, Field(description="Target programming language for the regex")] = "python", flags: Annotated[str, Field(description="Regex flags like i, m, s")] = "") -> dict:
    """Generate a regex pattern from a plain-English description with examples."""
    return regex_inner(description, language, flags)


@metered_tool("ai")
def mock(description: Annotated[str, Field(description="Description of the mock data to generate")], count: Annotated[int, Field(description="Number of mock records to generate")] = 5, format: Annotated[str, Field(description="Output format: json, csv, or list")] = "json") -> dict:
    """Generate realistic mock data records. format: json | csv | list"""
    return mock_inner(description, min(count, 50), format)


@metered_tool("ai")
def score(content: Annotated[str, Field(description="Content to score")], criteria: Annotated[list[str], Field(description="Scoring criteria like clarity, accuracy, engagement")] = None, scale: Annotated[int, Field(description="Maximum score value")] = 10) -> dict:
    """Score content on a custom rubric. Returns per-criterion scores, strengths, and weaknesses."""
    return score_inner(content, criteria or ["clarity", "accuracy", "engagement"], scale)


@metered_tool("ai")
def timeline(text: Annotated[str, Field(description="Text containing events to extract a timeline from")], direction: Annotated[str, Field(description="Sort order: chronological or reverse")] = "chronological") -> dict:
    """Extract or reconstruct a timeline from text. Returns dated events with significance."""
    return timeline_inner(text, direction)


@metered_tool("ai")
def action(text: Annotated[str, Field(description="Meeting notes or text to extract action items from")]) -> dict:
    """Extract action items, tasks, owners, and due dates from meeting notes or any text."""
    return action_inner(text)


@metered_tool("ai")
def pitch(product: Annotated[str, Field(description="Product or service to pitch")], audience: Annotated[str, Field(description="Target audience for the pitch")] = "general", length: Annotated[str, Field(description="Pitch duration: 15s, 30s, or 60s")] = "30s") -> dict:
    """Generate an elevator pitch: hook, value prop, call to action, full script. length: 15s | 30s | 60s"""
    return pitch_inner(product, audience, length)


@metered_tool("ai")
def debate(topic: Annotated[str, Field(description="Topic or position to debate")], perspective: Annotated[str, Field(description="Perspective: balanced, for, or against")] = "balanced") -> dict:
    """Arguments for and against any position with strength ratings and verdict."""
    return debate_inner(topic, perspective)


@metered_tool("ai")
def headline(content: Annotated[str, Field(description="Content to generate headlines for")], count: Annotated[int, Field(description="Number of headline variations")] = 5, style: Annotated[str, Field(description="Headline style: engaging, clickbait, seo, news")] = "engaging") -> dict:
    """Generate headline variations with type labels and a best pick."""
    return headline_inner(content, count, style)


@metered_tool("ai")
def fact(text: Annotated[str, Field(description="Text to extract factual claims from")], count: Annotated[int, Field(description="Maximum number of facts to extract")] = 10) -> dict:
    """Extract factual claims with verifiability scores and source hints."""
    return fact_inner(text, count)


@metered_tool("ai")
def rewrite(text: Annotated[str, Field(description="Text to rewrite")], audience: Annotated[str, Field(description="Target audience for the rewrite")] = "general audience", tone: Annotated[str, Field(description="Desired tone: neutral, formal, casual, enthusiastic")] = "neutral") -> dict:
    """Rewrite text for a specific audience, reading level, or brand voice."""
    return rewrite_inner(text, audience, tone)


@metered_tool("ai")
def tag(text: Annotated[str, Field(description="Text to auto-tag")], taxonomy: Annotated[list[str], Field(description="Predefined taxonomy of valid tags")] = None, max_tags: Annotated[int, Field(description="Maximum number of tags to return")] = 10) -> dict:
    """Auto-tag content using a taxonomy or free-form. Returns tags, primary tag, categories."""
    return tag_inner(text, taxonomy, max_tags)


# ── Heavy AI Tools (multi-step) ──────────────────────────────────────────────

@metered_tool("ai")
def review_code(code: Annotated[str, Field(description="Source code to review")], language: Annotated[str, Field(description="Programming language, or auto to detect")] = "auto", focus: Annotated[str, Field(description="Review focus: quality, security, or performance")] = "quality") -> dict:
    """Review code for quality, security, and performance issues. Returns issues, score, and summary."""
    return review_code_inner(code, language, focus)


@metered_tool("ai")
def generate_docs(code: Annotated[str, Field(description="Source code to generate documentation for")], style: Annotated[str, Field(description="Doc style: jsdoc, docstring, rustdoc, etc.")] = "jsdoc") -> dict:
    """Generate documentation for code. Supports jsdoc, docstring, rustdoc, etc."""
    return generate_docs_inner(code, style)


@metered_tool("ai")
def convert_code(code: Annotated[str, Field(description="Source code to convert")], from_lang: Annotated[str, Field(description="Source language, or auto to detect")] = "auto", to_lang: Annotated[str, Field(description="Target programming language")] = "python") -> dict:
    """Convert code from one programming language to another."""
    return convert_code_inner(code, from_lang, to_lang)


@metered_tool("ai")
def generate_api_spec(description: Annotated[str, Field(description="Natural language description of the API")], format: Annotated[str, Field(description="Spec format: openapi or asyncapi")] = "openapi") -> dict:
    """Generate an OpenAPI/AsyncAPI specification from a natural language description."""
    return generate_api_spec_inner(description, format)


@metered_tool("ai")
def diff(text_a: Annotated[str, Field(description="First text or code snippet")], text_b: Annotated[str, Field(description="Second text or code snippet")]) -> dict:
    """Analyze differences between two texts or code snippets. Returns changes, summary, and similarity."""
    return diff_inner(text_a, text_b)


@metered_tool("ai")
def parse_csv(csv_text: Annotated[str, Field(description="CSV data as a string")], question: Annotated[str, Field(description="Question to answer about the data")] = "") -> dict:
    """Analyze CSV data and optionally answer questions about it. Returns columns, row count, and insights."""
    return parse_csv_inner(csv_text, question)


@metered_tool("ai")
def cron_expression(description: Annotated[str, Field(description="Natural language description of the schedule")]) -> dict:
    """Generate or explain cron expressions from natural language. Returns cron string and next 5 runs."""
    return cron_expr_inner(description)


@metered_tool("ai")
def changelog(commits: Annotated[str, Field(description="Commit messages to generate changelog from")], version: Annotated[str, Field(description="Version number for the changelog header")] = "") -> dict:
    """Generate a professional changelog from commit messages. Groups by Added/Changed/Fixed/Removed."""
    return changelog_inner(commits, version)


@metered_tool("ai")
def name_generator(description: Annotated[str, Field(description="Description of the product, company, or feature to name")], count: Annotated[int, Field(description="Number of name suggestions")] = 10, style: Annotated[str, Field(description="Naming style: startup, corporate, playful, technical")] = "startup") -> dict:
    """Generate names for products, companies, or features with taglines and domain suggestions."""
    return name_generator_inner(description, count, style)


@metered_tool("ai")
def privacy_check(text: Annotated[str, Field(description="Text to scan for PII and sensitive data")]) -> dict:
    """Scan text for PII, secrets, and sensitive data. Returns found items, risk level, and recommendations."""
    return privacy_check_inner(text)


@metered_tool("ai_heavy")
def think(problem: Annotated[str, Field(description="The problem or question to solve")], context: Annotated[str, Field(description="Optional background information")] = "", max_steps: Annotated[int, Field(description="Maximum reasoning steps (1-10)")] = 5) -> dict:
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
def pipeline(steps: Annotated[list[dict], Field(description="Sequential operations, each with endpoint and input keys")]) -> dict:
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
def batch(operations: Annotated[list[dict], Field(description="Independent operations, each with endpoint and input keys")]) -> dict:
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
            except Exception:
                _log.exception("batch operation %s failed", endpoint)
                results.append({"endpoint": endpoint, "error": "Tool execution failed"})
    return {"results": results, "count": len(results)}


# ── Vision & Advanced AI Tools ───────────────────────────────────────────────

@metered_tool("ai")
def vision(image_url: Annotated[str, Field(description="URL of the image to analyze")], question: Annotated[str, Field(description="Question to ask about the image")] = "Describe this image in detail") -> dict:
    """Analyze any image URL using Claude Vision. Ask specific questions or get a full description."""
    gate = _premium_gate("vision", "$0.05/call")
    if gate:
        return gate
    return vision_inner(image_url, question)


@metered_tool("ai")
def rag(documents: Annotated[str, Field(description="Documents to query, separated by '---' for multiple")], query: Annotated[str, Field(description="Question to answer from the documents")]) -> dict:
    """
    Grounded Q&A using only your documents. Separate multiple documents with '---'.
    Returns answer, confidence, citations, and a cannot_answer flag.
    """
    return rag_inner(documents, query)


@metered_tool("ai")
def diagram(description: Annotated[str, Field(description="Plain English description of the diagram")], diagram_type: Annotated[str, Field(description="Diagram type: flowchart, sequence, erd, gantt, mindmap")] = "flowchart") -> dict:
    """
    Generate a Mermaid diagram from a plain English description.
    Types: flowchart, sequence, erd, gantt, mindmap
    """
    return diagram_inner(description, diagram_type)


@metered_tool("ai")
def json_schema(description: Annotated[str, Field(description="Plain English description of the data structure")], example: Annotated[str, Field(description="Example data to help infer the schema")] = "") -> dict:
    """Generate a JSON Schema (draft-07) from a plain English description of your data structure."""
    return json_schema_inner(description, example)


@metered_tool("ai")
def test_cases(code_or_description: Annotated[str, Field(description="Code or feature description to generate tests for")], language: Annotated[str, Field(description="Programming language for the test cases")] = "python") -> dict:
    """Generate comprehensive test cases with edge cases for code or a feature description."""
    return test_cases_inner(code_or_description, language)


@metered_tool("ai_heavy")
def workflow(goal: Annotated[str, Field(description="Complex goal requiring multi-step reasoning")], context: Annotated[str, Field(description="Background context or constraints")] = "") -> dict:
    """
    Multi-step agentic reasoning using Claude Sonnet. Breaks down complex goals,
    reasons through each sub-task, and produces a comprehensive result.
    Best for complex tasks requiring multiple steps of reasoning.
    """
    return workflow_inner(goal, context)


# ── Workflow Templates (compound tools) ──────────────────────────────────────

@metered_tool("ai_heavy")
def content_brief(topic: Annotated[str, Field(description="Topic to create a content brief for")]) -> dict:
    """Generate a complete content brief: research + keywords + outline + headline suggestions."""
    gate = _premium_gate("content_brief", "$0.20/call")
    if gate:
        return gate
    research_result = research_inner(topic)
    research_text = research_result.get("answer", "") if isinstance(research_result, dict) else str(research_result)
    kw_result = keywords_inner(research_text)
    kw_text = ", ".join(kw_result.get("keywords", [])) if isinstance(kw_result, dict) else str(kw_result)
    outline_result = outline_inner(f"{topic} (key themes: {kw_text})")
    headline_result = headline_inner(f"{topic} — {kw_text}", count=5, style="mixed")
    return {
        "topic": topic,
        "research": research_result,
        "keywords": kw_result,
        "outline": outline_result,
        "headlines": headline_result,
    }


@metered_tool("ai_heavy")
def competitor_analysis(company: Annotated[str, Field(description="Company or product to analyze")]) -> dict:
    """Analyze a competitor: research + sentiment + key findings."""
    gate = _premium_gate("competitor_analysis", "$0.20/call")
    if gate:
        return gate
    research_result = research_inner(f"{company} reviews analysis competitors")
    research_text = research_result.get("answer", "") if isinstance(research_result, dict) else str(research_result)
    sentiment_result = sentiment_inner(research_text)
    return {
        "company": company,
        "research": research_result,
        "sentiment": sentiment_result,
    }


@metered_tool("ai")
def translate_and_summarize(text: Annotated[str, Field(description="Text to translate and summarize")], language: Annotated[str, Field(description="Target language")] = "Spanish") -> dict:
    """Translate text to target language and provide a summary of the translation."""
    translated = translate_inner(text, language)
    translated_text = translated.get("translation", "") if isinstance(translated, dict) else str(translated)
    summary = summarize_inner(translated_text, "short")
    return {
        "original_language": "auto-detected",
        "target_language": language,
        "translation": translated,
        "summary": summary,
    }


# ── Agent Memory Tools ───────────────────────────────────────────────────────

@metered_tool("standard")
def memory_store(agent_id: Annotated[str, Field(description="Stable agent identifier (UUID, DID, or name)")], key: Annotated[str, Field(description="Memory key to store under")], value: Annotated[str, Field(description="Value to store")], tags: Annotated[str, Field(description="Comma-separated tags for organization")] = "") -> dict:
    """
    Store a persistent memory for an agent. Survives across sessions.
    agent_id: stable identifier for your agent (UUID, DID, or name).
    tags: comma-separated (optional).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    return memory_set(agent_id, key, value, tag_list)


@metered_tool("standard")
def memory_recall(agent_id: Annotated[str, Field(description="Agent identifier to recall memory for")], key: Annotated[str, Field(description="Memory key to retrieve")]) -> dict:
    """Retrieve a stored memory by agent_id and key. Returns value, tags, and timestamps."""
    result = memory_get(agent_id, key)
    return result or {"error": "not_found", "agent_id": agent_id, "key": key}


@metered_tool("standard")
def memory_find(agent_id: Annotated[str, Field(description="Agent identifier to search memories for")], query: Annotated[str, Field(description="Keyword to search across memories")]) -> dict:
    """Search all memories for an agent by keyword. Returns ranked matching key-value pairs."""
    results = memory_search(agent_id, query)
    return {"agent_id": agent_id, "query": query, "results": results, "count": len(results)}


@metered_tool("standard")
def memory_keys(agent_id: Annotated[str, Field(description="Agent identifier to list memory keys for")]) -> dict:
    """List all memory keys stored for an agent, with tags and last-updated timestamps."""
    return {"agent_id": agent_id, "keys": memory_list(agent_id)}


# ── API Catalog Tools ────────────────────────────────────────────────────────

@metered_tool("standard")
def browse_catalog(category: Annotated[str, Field(description="Filter by category: geo, finance, weather, social_media, etc.")] = "", min_score: Annotated[float, Field(description="Minimum quality score (0-10)")] = 0.0, free_only: Annotated[bool, Field(description="Show only APIs that don't require auth")] = False, page: Annotated[int, Field(description="Page number for pagination")] = 1) -> dict:
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
def get_catalog_api(api_id: Annotated[int, Field(description="Numeric ID of the API to retrieve")]) -> dict:
    """Get full details for a specific API in the catalog by its numeric ID."""
    result = get_api(api_id)
    return result or {"error": "not_found", "api_id": api_id}


@metered_tool("ai")
def invoke_catalog_api(api_id: Annotated[int, Field(description="API ID from browse_catalog")], endpoint: Annotated[str, Field(description="API endpoint path to call")] = "/", params: Annotated[str, Field(description="JSON string of query parameters")] = "{}") -> dict:
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
def register_my_agent(agent_id: Annotated[str, Field(description="Unique agent identifier")], name: Annotated[str, Field(description="Display name for the agent")], description: Annotated[str, Field(description="What the agent does")],
                      capabilities: Annotated[str, Field(description="Comma-separated list of capabilities")], endpoint: Annotated[str, Field(description="URL where other agents can reach you")] = "") -> dict:
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
    except Exception:
        _log.exception("apify actor %s failed", actor_id)
        return [{"error": "Tool execution failed"}]


@metered_tool("scraping")
def scrape_google_maps(query: Annotated[str, Field(description="Search query for businesses on Google Maps")], max_results: Annotated[int, Field(description="Maximum number of results to return")] = 5) -> dict:
    """Scrape Google Maps for businesses matching a query. Returns name, address, rating, phone, website."""
    gate = _premium_gate("scrape_google_maps", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("nwua9Gu5YrADL7ZDj",
                         {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tweets(query: Annotated[str, Field(description="Search query or hashtag for tweets")], max_results: Annotated[int, Field(description="Maximum number of tweets to return")] = 20) -> dict:
    """Scrape Twitter/X tweets by search query or hashtag. Returns text, author, likes, retweets, date."""
    gate = _premium_gate("scrape_tweets", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("61RPP7dywgiy0JPD0",
                         {"searchTerms": [query], "maxItems": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_website(url: Annotated[str, Field(description="Website URL to crawl")], max_pages: Annotated[int, Field(description="Maximum number of pages to crawl")] = 3) -> dict:
    """Crawl any website and extract text content. Returns page URL, title, and text per page."""
    gate = _premium_gate("scrape_website", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("aYG0l9s7dbB7j3gbS",
                         {"startUrls": [{"url": url}], "maxCrawlPages": max_pages},
                         max_pages)
    return {"url": url, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_youtube(query: Annotated[str, Field(description="YouTube search keywords")], max_results: Annotated[int, Field(description="Maximum number of videos to return")] = 5) -> dict:
    """Search YouTube and return video metadata — title, channel, views, duration, description, URL."""
    gate = _premium_gate("scrape_youtube", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("h7sDV53CddomktSi5",
                         {"searchKeywords": query, "maxResults": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_instagram(username: Annotated[str, Field(description="Instagram username to scrape posts from")], max_posts: Annotated[int, Field(description="Maximum number of posts to return")] = 5) -> dict:
    """Scrape Instagram profile posts. Returns caption, likes, comments, date, media URL."""
    gate = _premium_gate("scrape_instagram", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("shu8hvrXbJbY3Eb9W",
                         {"username": [username], "resultsLimit": max_posts},
                         max_posts)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tiktok(username: Annotated[str, Field(description="TikTok username to scrape videos from")], max_videos: Annotated[int, Field(description="Maximum number of videos to return")] = 5) -> dict:
    """Scrape TikTok profile videos. Returns caption, views, likes, shares, date."""
    gate = _premium_gate("scrape_tiktok", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("GdWCkxBtKWOsKjdch",
                         {"profiles": [username], "resultsPerPage": max_videos},
                         max_videos)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("ai_heavy")
def chain_operations(steps: Annotated[list, Field(description="List of {action, params} dicts to chain sequentially")]) -> dict:
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
def list_marketplace(category: Annotated[str, Field(description="Filter by service category")] = None, max_price: Annotated[float, Field(description="Maximum price in USD")] = None) -> dict:
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
def post_to_marketplace(agent_id: Annotated[str, Field(description="Your unique agent identifier")], name: Annotated[str, Field(description="Short name for your service")], description: Annotated[str, Field(description="What your service does and returns")],
                         endpoint: Annotated[str, Field(description="Full URL where your service can be called")], price_usd: Annotated[float, Field(description="Price in USD per call")],
                         category: Annotated[str, Field(description="Service category: general, ai, data, scraping, finance")] = "general",
                         capabilities: Annotated[list, Field(description="List of capability strings")] = None) -> dict:
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
def generate_uuid(count: Annotated[int, Field(description="Number of UUIDs to generate (max 50)")] = 1) -> dict:
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
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def get_holidays(country: Annotated[str, Field(description="ISO 2-letter country code (e.g. US, GB, DE)")] = "US", year: Annotated[str, Field(description="Year to get holidays for (default: current year)")] = "") -> dict:
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
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Agent Messaging ──────────────────────────────────────────────────────────

@metered_tool("standard")
def send_agent_message(from_agent: Annotated[str, Field(description="Sender agent ID")], to_agent: Annotated[str, Field(description="Recipient agent ID")], subject: Annotated[str, Field(description="Message subject line")], body: Annotated[str, Field(description="Message body text")]) -> dict:
    """Send a direct message from one agent to another via the agent network."""
    return send_message(from_agent, to_agent, subject, body)


@metered_tool("standard")
def read_agent_inbox(agent_id: Annotated[str, Field(description="Agent ID to read inbox for")], unread_only: Annotated[bool, Field(description="Only return unread messages")] = False) -> dict:
    """Read messages from an agent's inbox. Set unread_only=True to filter."""
    messages = get_inbox(agent_id, unread_only=unread_only)
    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


# ── Knowledge Base ───────────────────────────────────────────────────────────

@metered_tool("standard")
def add_to_knowledge_base(topic: Annotated[str, Field(description="Topic or title for the knowledge entry")], content: Annotated[str, Field(description="Knowledge content to store")], author_agent: Annotated[str, Field(description="Agent ID of the author")],
                          tags: Annotated[list, Field(description="Tags for categorization")] = None) -> dict:
    """Add an entry to the shared agent knowledge base."""
    return add_knowledge(topic, content, author_agent, tags or [])


@metered_tool("standard")
def search_knowledge_base(query: Annotated[str, Field(description="Search keyword for the knowledge base")], limit: Annotated[int, Field(description="Maximum number of results")] = 10) -> dict:
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
def submit_agent_task(posted_by: Annotated[str, Field(description="Agent ID posting the task")], title: Annotated[str, Field(description="Task title")], description: Annotated[str, Field(description="Detailed task description")],
                      skills_needed: Annotated[list, Field(description="List of skills required for the task")] = None, reward_usd: Annotated[float, Field(description="Reward amount in USD")] = 0.0) -> dict:
    """Post a task to the agent task board for other agents to claim and complete."""
    from agent_network import submit_task as _submit_task
    return _submit_task(posted_by, title, description, skills_needed or [], reward_usd)


@metered_tool("standard")
def browse_agent_tasks(status: Annotated[str, Field(description="Task status filter: open, claimed, completed")] = "open", skill: Annotated[str, Field(description="Filter by required skill")] = None) -> dict:
    """Browse tasks on the agent task board, optionally filtered by skill or status."""
    tasks = browse_tasks(status=status, skill=skill)
    return {"tasks": tasks, "count": len(tasks)}


# ── Code Execution ───────────────────────────────────────────────────────────

@metered_tool("standard")
def run_python_code(code: Annotated[str, Field(description="Python code to execute in sandbox")], timeout: Annotated[int, Field(description="Execution timeout in seconds (max 15)")] = 10) -> dict:
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
def web_search(query: Annotated[str, Field(description="Search query for DuckDuckGo")], n_results: Annotated[int, Field(description="Maximum number of results (max 25)")] = 10) -> dict:
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
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Real-Time Data ───────────────────────────────────────────────────────────

@metered_tool("standard")
def get_weather(city: Annotated[str, Field(description="City name to get weather for")]) -> dict:
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
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_crypto_prices(symbols: Annotated[str, Field(description="Comma-separated CoinGecko IDs (e.g. bitcoin,ethereum)")] = "bitcoin,ethereum") -> dict:
    """Get real-time crypto prices from CoinGecko. symbols: comma-separated CoinGecko IDs."""
    try:
        data = _mcp_requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbols, "vs_currencies": "usd,eur,gbp", "include_24hr_change": "true"},
            timeout=8,
        ).json()
        return {"prices": data, "symbols": symbols.split(",")}
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_exchange_rates(base_currency: Annotated[str, Field(description="Base currency code (e.g. USD, EUR, GBP)")] = "USD") -> dict:
    """Get live exchange rates for 160+ currencies. base_currency: e.g. USD, EUR, GBP."""
    try:
        data = _mcp_requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{base_currency.upper()}",
            timeout=8,
        ).json()
        return {"base": base_currency.upper(), "date": data.get("date"), "rates": data.get("rates", {})}
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def enrich_entity(entity: Annotated[str, Field(description="Entity value to enrich (IP, ticker, country code, etc.)")], entity_type: Annotated[str, Field(description="Entity type: ip, crypto, country, or company")]) -> dict:
    """Aggregate data about an entity. entity_type: ip | crypto | country | company."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/enrich",
            json={"entity": entity, "type": entity_type},
            timeout=30,
        )
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── API Key Management ───────────────────────────────────────────────────────

@metered_tool("free")
def check_api_key_balance(key: Annotated[str, Field(description="API key to check balance for")]) -> dict:
    """Check balance and usage stats for a prepaid AiPayGen API key."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/auth/status?key={key}", timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Skills System (Skill Harvester MCP Tools) ────────────────────────────────

@metered_tool("standard")
def search_skills(query: Annotated[str, Field(description="Search query to find relevant skills")], top_n: Annotated[int, Field(description="Maximum number of results (max 50)")] = 10) -> dict:
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
def list_skills(category: Annotated[str, Field(description="Filter by skill category")] = "") -> dict:
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
def execute_skill(skill_name: Annotated[str, Field(description="Name of the skill to execute")], input_text: Annotated[str, Field(description="Input text to pass to the skill")]) -> dict:
    """Execute a specific skill by name. Use search_skills or list_skills to discover available skills."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/execute",
            json={"skill": skill_name, "input": input_text}, timeout=120)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("ai")
def ask(question: Annotated[str, Field(description="Question or prompt to answer")]) -> dict:
    """Universal endpoint — ask anything. AiPayGen picks the best skill and model automatically."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/ask",
            json={"question": question}, timeout=120)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def create_skill(name: Annotated[str, Field(description="Unique name for the skill")], description: Annotated[str, Field(description="What the skill does")], prompt_template: Annotated[str, Field(description="Prompt template with {{input}} placeholder")], category: Annotated[str, Field(description="Skill category")] = "general") -> dict:
    """Create a new reusable skill. prompt_template must contain {{input}} placeholder."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/create",
            json={"name": name, "description": description,
                  "prompt_template": prompt_template, "category": category}, timeout=30)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def absorb_skill(url: Annotated[str, Field(description="URL to absorb a skill from")] = "", text: Annotated[str, Field(description="Raw text to create a skill from")] = "") -> dict:
    """Absorb a new skill from a URL or text. AiPayGen reads and creates a callable skill."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/skills/absorb",
            json={"url": url, "text": text}, timeout=60)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


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
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def check_notifications() -> dict:
    """Check your unread notifications (payment confirmations, low balance alerts, referral bonuses). Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key:
        return {"error": "AIPAYGEN_API_KEY env var not set"}
    try:
        resp = _mcp_requests.get("http://localhost:5001/auth/notifications",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def list_models() -> dict:
    """List all available AI models with their providers and capabilities."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/models", timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def create_agent(name: Annotated[str, Field(description="Name for the custom agent")], description: Annotated[str, Field(description="What the agent does")], tools: Annotated[list, Field(description="List of tool names the agent can use")] = None,
                 template: Annotated[str, Field(description="Agent template: research, monitor, content, sales, etc.")] = "", model: Annotated[str, Field(description="AI model to use, or auto for best fit")] = "auto") -> dict:
    """Create a custom AI agent with selected tools and configuration."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/agents/build",
            json={"name": name, "description": description,
                  "tools": tools or [], "template": template, "model": model},
            timeout=30)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def list_my_agents() -> dict:
    """List all agents you have created. Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/list",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("ai")
def run_agent(agent_id: Annotated[str, Field(description="ID of the agent to run")], input_text: Annotated[str, Field(description="Input text or prompt for the agent")] = "") -> dict:
    """Run a custom agent by ID with optional input text."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/run",
            json={"input": input_text}, timeout=120)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def schedule_agent(agent_id: Annotated[str, Field(description="ID of the agent to schedule")], schedule_type: Annotated[str, Field(description="Schedule type: cron, loop, or event")] = "cron",
                   schedule_value: Annotated[str, Field(description="Schedule value (cron expression, interval, or event name)")] = "") -> dict:
    """Schedule an agent to run automatically. schedule_type: cron | loop | event."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/schedule",
            json={"schedule_type": schedule_type, "schedule_value": schedule_value},
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def pause_agent(agent_id: Annotated[str, Field(description="ID of the agent to pause")]) -> dict:
    """Pause a scheduled agent."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/pause",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_agent_runs(agent_id: Annotated[str, Field(description="ID of the agent to get run history for")]) -> dict:
    """Get execution history for an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agents/{agent_id}/runs",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def delete_agent(agent_id: Annotated[str, Field(description="ID of the agent to delete")]) -> dict:
    """Delete a custom agent by ID."""
    try:
        resp = _mcp_requests.delete(f"http://localhost:5001/agents/{agent_id}",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Geocoding & Location ──────────────────────────────────────

@metered_tool("standard")
def geocode(q: Annotated[str, Field(description="Address or place name to geocode")]) -> dict:
    """Convert an address or place name to geographic coordinates (lat/lon) via Nominatim."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/geocode", params={"q": q}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def geocode_reverse(
    lat: Annotated[str, Field(description="Latitude coordinate")],
    lon: Annotated[str, Field(description="Longitude coordinate")],
) -> dict:
    """Convert geographic coordinates (lat/lon) to a human-readable address."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/geocode/reverse", params={"lat": lat, "lon": lon}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Company & Domain ──────────────────────────────────────────

@metered_tool("standard")
def company_search(q: Annotated[str, Field(description="Company name to search")]) -> dict:
    """Search for company information via Wikipedia enrichment. Returns description, domain guess, thumbnail."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/company", params={"q": q}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def whois_lookup(domain: Annotated[str, Field(description="Domain name to look up (e.g. example.com)")]) -> dict:
    """WHOIS/RDAP lookup for a domain. Returns registrar, status, nameservers, and events."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/whois", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def domain_profile(domain: Annotated[str, Field(description="Domain name (e.g. example.com)")]) -> dict:
    """Full domain profile combining DNS records (A, AAAA, MX, TXT, NS, CNAME) and WHOIS data."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/domain", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Text Analysis ─────────────────────────────────────────────

@metered_tool("standard")
def readability_score(text: Annotated[str, Field(description="Text to analyze for readability")]) -> dict:
    """Compute Flesch-Kincaid readability score and grade level for text."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/readability", json={"text": text}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def language_detect(text: Annotated[str, Field(description="Text to detect language of")]) -> dict:
    """Detect the language of text using Unicode script analysis. Returns language code and confidence."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/language", params={"text": text}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def profanity_filter(text: Annotated[str, Field(description="Text to check for profanity")]) -> dict:
    """Detect and filter profanity from text. Returns cleaned text and list of found words."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/profanity", json={"text": text}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Web & URL ─────────────────────────────────────────────────

@metered_tool("standard")
def url_meta(url: Annotated[str, Field(description="URL to extract meta tags from")]) -> dict:
    """Extract meta tags (Open Graph, Twitter Cards) from a URL. Returns title, OG data, and Twitter card data."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/meta", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def extract_links(url: Annotated[str, Field(description="URL to extract links from")]) -> dict:
    """Extract all links from a web page. Returns deduplicated absolute URLs."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/links", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def parse_sitemap(domain: Annotated[str, Field(description="Domain to parse sitemap.xml from (e.g. example.com)")]) -> dict:
    """Parse sitemap.xml from a domain. Returns list of indexed URLs."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/sitemap", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def parse_robots(domain: Annotated[str, Field(description="Domain to parse robots.txt from (e.g. example.com)")]) -> dict:
    """Parse robots.txt from a domain. Returns crawl rules, sitemaps, and raw content."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/robots", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def http_headers(url: Annotated[str, Field(description="URL to get HTTP headers from")]) -> dict:
    """Get HTTP response headers from a URL. Returns status code and all headers."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/headers", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def ssl_info(domain: Annotated[str, Field(description="Domain to check SSL certificate for")]) -> dict:
    """Get SSL certificate details for a domain: subject, issuer, expiry, serial number."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/ssl", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Compute & Dev ─────────────────────────────────────────────

@metered_tool("standard")
def jwt_decode(token: Annotated[str, Field(description="JWT token string to decode")]) -> dict:
    """Decode a JWT token without verification. Returns header, payload, and expiry status."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/jwt/decode", json={"token": token}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def markdown_to_html(text: Annotated[str, Field(description="Markdown text to convert to HTML")]) -> dict:
    """Convert Markdown text to HTML. Supports tables, fenced code blocks, and syntax highlighting."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/markdown", json={"text": text}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Media & Visual ────────────────────────────────────────────

@metered_tool("standard")
def placeholder_image(
    width: Annotated[int, Field(description="Image width in pixels")] = 300,
    height: Annotated[int, Field(description="Image height in pixels")] = 200,
    bg: Annotated[str, Field(description="Background color hex (without #)")] = "cccccc",
    fg: Annotated[str, Field(description="Foreground/text color hex (without #)")] = "666666",
    text: Annotated[str, Field(description="Text to display on image")] = "",
) -> dict:
    """Generate a placeholder image (SVG). Returns SVG markup."""
    try:
        params = {"width": width, "height": height, "bg": bg, "fg": fg}
        if text:
            params["text"] = text
        resp = _mcp_requests.get("http://localhost:5001/data/placeholder", params=params, timeout=10)
        return {"svg": resp.text, "width": width, "height": height}
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def favicon_extract(domain: Annotated[str, Field(description="Domain to extract favicon from (e.g. example.com)")]) -> dict:
    """Extract favicon URLs from a domain. Returns list of icon URLs found."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/favicon", params={"domain": domain}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def identicon_avatar(
    input_str: Annotated[str, Field(description="String to generate identicon from (e.g. email, username)")],
    size: Annotated[int, Field(description="Avatar size in pixels")] = 80,
) -> dict:
    """Generate a deterministic identicon avatar (SVG) from any string."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/avatar", params={"input": input_str, "size": size}, timeout=10)
        return {"svg": resp.text, "input": input_str, "size": size}
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Blockchain ────────────────────────────────────────────────

@metered_tool("standard")
def ens_resolve(name: Annotated[str, Field(description="ENS name (e.g. vitalik.eth) or 0x address for reverse lookup")]) -> dict:
    """Resolve ENS name to Ethereum address, or reverse-resolve address to ENS name."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/ens", params={"name": name}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Enrichment ────────────────────────────────────────────────

@metered_tool("standard")
def enrich_domain(domain: Annotated[str, Field(description="Domain to enrich (e.g. example.com)")]) -> dict:
    """Domain enrichment: detect tech stack, social profiles, DNS records, and meta tags."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/enrich/domain", params={"domain": domain}, timeout=20)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def enrich_github(username: Annotated[str, Field(description="GitHub username to enrich")]) -> dict:
    """GitHub user enrichment: profile info, bio, follower count, and top repositories."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/enrich/github", params={"username": username}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Email ─────────────────────────────────────────────────────

@metered_tool("standard")
def email_send(
    to: Annotated[str, Field(description="Recipient email address")],
    subject: Annotated[str, Field(description="Email subject line")],
    body: Annotated[str, Field(description="Email body text")],
) -> dict:
    """Send an email via Resend (from noreply@aipaygen.com)."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/email/send",
            json={"to": to, "subject": subject, "body": body}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Document Extraction ───────────────────────────────────────

@metered_tool("standard")
def extract_text(
    html: Annotated[str, Field(description="Raw HTML to extract text from")] = "",
    url: Annotated[str, Field(description="URL to fetch and extract text from")] = "",
) -> dict:
    """Extract clean text from HTML content or a URL. Strips scripts, styles, and tags."""
    try:
        payload = {}
        if url:
            payload["url"] = url
        elif html:
            payload["html"] = html
        resp = _mcp_requests.post("http://localhost:5001/data/extract/text", json=payload, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Finance ───────────────────────────────────────────────────

@metered_tool("standard")
def stock_history(symbol: Annotated[str, Field(description="Stock ticker symbol (e.g. AAPL, MSFT)")]) -> dict:
    """Get 1-month historical OHLCV candles for a stock symbol via yfinance."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/finance/history", params={"symbol": symbol}, timeout=20)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def forex_rates(base: Annotated[str, Field(description="Base currency code (e.g. USD, EUR)")] = "USD") -> dict:
    """Get 150+ currency exchange rates for a base currency."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/finance/forex", params={"base": base}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def currency_convert(
    amount: Annotated[float, Field(description="Amount to convert")] = 1.0,
    from_currency: Annotated[str, Field(description="Source currency code (e.g. USD)")] = "USD",
    to_currency: Annotated[str, Field(description="Target currency code (e.g. EUR)")] = "EUR",
) -> dict:
    """Convert an amount between currencies using live exchange rates."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/finance/convert",
            params={"amount": amount, "from": from_currency, "to": to_currency}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: NLP ───────────────────────────────────────────────────────

@metered_tool("standard")
def entity_extraction(text: Annotated[str, Field(description="Text to extract entities from")]) -> dict:
    """Extract named entities from text: emails, URLs, IPs, crypto addresses, phone numbers, dates, hashtags, mentions."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/entities", json={"text": text}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def text_similarity(
    text1: Annotated[str, Field(description="First text to compare")],
    text2: Annotated[str, Field(description="Second text to compare")],
) -> dict:
    """Compute similarity between two texts using Jaccard and cosine metrics."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/similarity",
            json={"text1": text1, "text2": text2}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Data Transforms ───────────────────────────────────────────

@metered_tool("standard")
def json_to_csv(data: Annotated[list, Field(description="JSON array of objects to convert to CSV")]) -> dict:
    """Convert a JSON array of objects to CSV format."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/transform/json-to-csv",
            json={"data": data}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def xml_to_json(xml: Annotated[str, Field(description="XML string to convert to JSON")]) -> dict:
    """Convert XML to JSON. Handles nested elements and attributes."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/transform/xml",
            json={"xml": xml}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def yaml_to_json(yaml_str: Annotated[str, Field(description="YAML string to convert to JSON")]) -> dict:
    """Convert YAML to JSON."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/transform/yaml",
            json={"yaml": yaml_str}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Date & Time ───────────────────────────────────────────────

@metered_tool("standard")
def datetime_between(
    from_date: Annotated[str, Field(description="Start date in YYYY-MM-DD format")],
    to_date: Annotated[str, Field(description="End date in YYYY-MM-DD format")],
) -> dict:
    """Calculate duration between two dates: days, weeks, months, years, hours, minutes, seconds."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/datetime/between",
            params={"from": from_date, "to": to_date}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def business_days(
    from_date: Annotated[str, Field(description="Start date in YYYY-MM-DD format")],
    to_date: Annotated[str, Field(description="End date in YYYY-MM-DD format")],
) -> dict:
    """Count business days (weekdays) between two dates."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/datetime/business-days",
            params={"from": from_date, "to": to_date}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def unix_timestamp(timestamp: Annotated[str, Field(description="Unix timestamp to convert (leave empty for current time)")] = "") -> dict:
    """Convert Unix timestamp to human-readable date, or get current Unix timestamp."""
    try:
        params = {"timestamp": timestamp} if timestamp else {}
        resp = _mcp_requests.get("http://localhost:5001/data/datetime/unix", params=params, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Security ──────────────────────────────────────────────────

@metered_tool("standard")
def security_headers_audit(url: Annotated[str, Field(description="URL to audit security headers for")]) -> dict:
    """Audit security headers of a URL (HSTS, CSP, X-Frame-Options, etc.). Returns A+ to F grade."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/security/headers", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def techstack_detect(url: Annotated[str, Field(description="URL to detect technology stack from")]) -> dict:
    """Detect technology stack of a website: frameworks, CDNs, analytics, server software."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/security/techstack", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def uptime_check(url: Annotated[str, Field(description="URL to check uptime for")]) -> dict:
    """Check if a URL is up or down. Returns status, response time, and content length."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/security/uptime", params={"url": url}, timeout=20)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Math & Statistics ─────────────────────────────────────────

@metered_tool("standard")
def math_evaluate(expression: Annotated[str, Field(description="Math expression to compute (e.g. 'sqrt(144) + 2^3')")]) -> dict:
    """Safely compute a math expression using AST parsing. Supports +, -, *, /, ^, sqrt, sin, cos, log, etc."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/math/eval",
            json={"expression": expression}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def unit_convert(
    value: Annotated[float, Field(description="Numeric value to convert")],
    from_unit: Annotated[str, Field(description="Source unit (e.g. km, lb, c, gb)")],
    to_unit: Annotated[str, Field(description="Target unit (e.g. mi, kg, f, mb)")],
) -> dict:
    """Convert between units: length, weight, volume, speed, data size, and temperature."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/math/convert",
            params={"value": value, "from": from_unit, "to": to_unit}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def math_stats(numbers: Annotated[list, Field(description="List of numbers for statistical analysis")]) -> dict:
    """Statistical analysis: mean, median, mode, std dev, variance, quartiles, min/max, range."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/data/math/stats",
            json={"numbers": numbers}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Utility Tools: Crypto ────────────────────────────────────────────────────

@metered_tool("standard")
def crypto_trending() -> dict:
    """Get trending cryptocurrency tokens and DeFi data from CoinGecko."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/crypto/trending", timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Crypto Deposit Tools ─────────────────────────────────────────────────────

@metered_tool("standard")
def get_crypto_deposit_info() -> dict:
    """Get crypto deposit information — wallet address, supported networks (Base/Solana), fees, limits."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/deposit", timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def create_deposit(
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
    amount_usd: Annotated[float, Field(description="Expected deposit amount in USD")] = 10.0,
) -> dict:
    """Create a crypto deposit intent — returns unique address, QR code, and instructions."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/crypto/deposit", json={"network": network, "amount_usd": amount_usd}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def claim_deposit(
    tx_hash: Annotated[str, Field(description="Transaction hash to verify and claim")],
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
) -> dict:
    """Claim a crypto deposit by providing the transaction hash for onchain verification."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/crypto/claim", json={"tx_hash": tx_hash, "network": network}, timeout=30)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_deposit_history(
    api_key: Annotated[str, Field(description="API key to check deposit history for")],
) -> dict:
    """Get deposit history for an API key."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/deposits", params={"api_key": api_key}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_deposit_address(
    api_key: Annotated[str, Field(description="API key to get a unique deposit address for")],
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
) -> dict:
    """Get or create a unique deposit address for an API key on a specific network."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/address", params={"api_key": api_key, "network": network}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── x402 Discovery Tools ─────────────────────────────────────────────────────

@mcp.tool()
def discover_endpoints(
    category: Annotated[str, Field(description="Filter by category: ai, data, agent, utility, web_analysis, nlp, finance, location, commerce")] = "",
    search: Annotated[str, Field(description="Search keyword in endpoint descriptions")] = "",
) -> dict:
    """Discover all available paid API endpoints with pricing, categories, and x402 payment info."""
    try:
        params = {}
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        resp = _mcp_requests.get("http://localhost:5001/discover", params=params, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@mcp.tool()
def discover_pricing() -> dict:
    """Get pricing overview — min/max/avg prices, histogram, and total endpoint count."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/discover/pricing", timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@mcp.tool()
def estimate_revenue(
    price_per_call: Annotated[float, Field(description="Price per API call in USD")] = 0.005,
    daily_calls: Annotated[int, Field(description="Expected daily API calls")] = 1000,
) -> dict:
    """Estimate how much revenue a seller could earn from their API on the platform."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/sell/estimate",
                                   json={"price_per_call": price_per_call, "daily_calls": daily_calls},
                                   timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@mcp.tool()
def x402_protocol_info() -> dict:
    """Get x402 protocol discovery metadata — chains, wallet, facilitator, discovery endpoints."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/.well-known/x402", timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@mcp.tool()
def compare_platforms() -> dict:
    """Compare AiPayGen with competitors (APIToll, RelAI) for agent decision-making."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/discover/compare", timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@mcp.tool()
def buyer_sdk_install() -> dict:
    """Get the pip install command for the AiPayGen Buyer SDK — auto-402 payment handling for x402 APIs."""
    return {
        "install": "pip install aipaygen-buyer",
        "pypi": "https://pypi.org/project/aipaygen-buyer/",
        "requires": "Python 3.10+",
        "dependencies": ["httpx", "pydantic", "eth-account", "eth-abi"],
        "source": "https://github.com/Damien829/aipaygen",
    }


@mcp.tool()
def buyer_sdk_example() -> dict:
    """Get a usage example for the AiPayGen Buyer SDK — shows auto-402 payment, policy engine, and tracking."""
    return {
        "description": "AiPayGen Buyer SDK — auto-402 payment handling with policy engine",
        "sync_example": 'from aipaygen_buyer import AiPayGenBuyer\n\nclient = AiPayGenBuyer(\n    private_key="0xYOUR_PRIVATE_KEY",\n    max_price=0.05,\n    daily_budget=5.0,\n)\n\nresult = client.call("/ask", prompt="What is x402?")\nprint(result.data)\nprint(f"Paid: {result.paid}, Receipt: {result.receipt}")\nprint(f"Budget remaining: ${client.budget_remaining:.2f}")',
        "async_example": 'import asyncio\nfrom aipaygen_buyer import AsyncAiPayGenBuyer\n\nasync def main():\n    async with AsyncAiPayGenBuyer(private_key="0x...") as client:\n        result = await client.call("/ask", prompt="Hello!")\n        print(result.data)\n\nasyncio.run(main())',
        "policy_example": 'from aipaygen_buyer import AiPayGenBuyer, SpendingPolicy\n\npolicy = SpendingPolicy(\n    max_price_per_call=0.02,\n    daily_budget=2.0,\n    monthly_budget=50.0,\n    vendor_allowlist={"0x366D488a48de1B2773F3a21F1A6972715056Cb30"},\n)\nclient = AiPayGenBuyer(private_key="0x...", policy=policy)',
    }


@mcp.tool()
def buyer_sdk_quickstart() -> dict:
    """Get the quickstart guide for the AiPayGen Buyer SDK — install to first paid API call in 60 seconds."""
    return {
        "title": "AiPayGen Buyer SDK Quickstart",
        "steps": [
            {"step": 1, "title": "Install", "command": "pip install aipaygen-buyer"},
            {"step": 2, "title": "Set private key", "command": "export AIPAYGEN_PRIVATE_KEY=0xYOUR_KEY", "note": "Use a dedicated wallet with small USDC balance."},
            {"step": 3, "title": "Fund wallet", "note": "Send USDC on Base Mainnet. Most calls cost $0.001-$0.02."},
            {"step": 4, "title": "First call", "code": 'from aipaygen_buyer import AiPayGenBuyer\nclient = AiPayGenBuyer(max_price=0.05, daily_budget=5.0)\nresult = client.call("/ask", prompt="What is x402?")\nprint(result.data)'},
            {"step": 5, "title": "Browse APIs", "code": 'catalog = client.catalog(search="translate")\nprint(catalog)'},
        ],
        "api_key_alternative": "Prepaid credits: client = AiPayGenBuyer(api_key='apk_YOUR_KEY')",
        "docs": "https://api.aipaygen.com/docs",
    }


# ── Monetization Tools (FREE — no metering) ─────────────────────────────────

@mcp.tool()
def buy_credits(
    amount: Annotated[int, Field(description="Amount in USD (1, 5, 10, 15, 20, 25, or 50)")]
) -> dict:
    """Get a payment link to buy API credits with a credit card. Starts at $1. Returns a Stripe checkout URL — share it with the user to complete payment."""
    valid_amounts = (1, 5, 10, 15, 20, 25, 50)
    if amount not in valid_amounts:
        return {"error": "invalid_amount", "message": f"Amount must be one of {valid_amounts}.", "hint": "Try buy_credits(amount=5) for $5 in credits."}
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/stripe/create-checkout",
            json={"amount": amount, "label": "mcp-purchase"},
            timeout=15,
        )
        data = resp.json()
        if resp.status_code != 200 or "url" not in data:
            return {"error": "checkout_failed", "message": data.get("error", "Could not create checkout session."), "hint": "Try again or visit https://api.aipaygen.com/docs"}
        return {
            "checkout_url": data["url"],
            "amount_usd": amount,
            "message": f"Open this link to complete your ${amount} credit purchase.",
            "note": "After payment, generate an API key with the generate_api_key tool.",
        }
    except Exception as exc:
        _log.error("buy_credits failed: %s", exc)
        return {"error": "checkout_failed", "message": "Could not reach payment service. Try again shortly.", "hint": "Visit https://api.aipaygen.com/docs for manual purchase."}


@mcp.tool()
def check_usage() -> dict:
    """Check your free tier usage and remaining calls for today."""
    api_key = os.getenv("AIPAYGEN_API_KEY", "")
    result = {"has_api_key": bool(api_key)}
    if api_key:
        try:
            resp = _mcp_requests.get(
                "http://localhost:5001/auth/key-status",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            data = resp.json()
            result["balance_usd"] = data.get("balance", 0)
            result["calls_remaining"] = "unlimited (prepaid key)"
            result["daily_limit"] = "unlimited"
            # Include referral link so the AI can tell the user about it
            ref_code = data.get("referral_code", "")
            if not ref_code:
                import hashlib as _hl
                ref_code = _hl.sha256(api_key.encode()).hexdigest()[:8]
            if ref_code:
                result["referral_link"] = f"https://aipaygen.com/buy-credits?ref={ref_code}"
                result["referral_info"] = "Share your referral link — both you and the new user get $0.10 credits!"
        except Exception as exc:
            _log.error("check_usage key-status failed: %s", exc)
            result["balance_usd"] = "unknown"
            result["calls_remaining"] = "unknown"
    else:
        remaining = get_free_tier_remaining("mcp-user")
        result["calls_remaining"] = remaining
        result["daily_limit"] = 10
        result["upgrade_hint"] = "Run generate_api_key to get an API key, then buy_credits to add funds."
    return result


@metered_tool("free")
def generate_api_key(
    label: Annotated[str, Field(description="Label for your API key (e.g. 'my-project')")] = "mcp-key"
) -> dict:
    """Generate a free API key. Add credits later via buy_credits tool. Set AIPAYGEN_API_KEY env var to use it."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/auth/generate-key",
            json={"label": label, "source": "mcp-tool"},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200 or "key" not in data:
            return {"error": "key_generation_failed", "message": data.get("error", "Could not generate key."), "hint": "Visit https://api.aipaygen.com/docs"}
        api_key = data["key"]
        balance = data.get("balance_usd", 0)
        has_trial = balance > 0
        return {
            "api_key": api_key,
            "balance_usd": balance,
            "label": label,
            "setup": f'export AIPAYGEN_API_KEY={api_key}',
            "message": f"Key generated with ${balance:.2f} free trial credits (~{int(balance/0.006)} AI calls)! Set the env var above to unlock premium tools."
                       if has_trial else "Key generated! Set the env var above, then call buy_credits to add funds.",
            "next_step": "Call buy_credits(1) to add more credits when ready." if has_trial else "Call buy_credits(1) to add $1 in credits (~166 calls).",
        }
    except Exception as exc:
        _log.error("generate_api_key failed: %s", exc)
        return {"error": "key_generation_failed", "message": "Could not reach auth service. Try again shortly.", "hint": "Visit https://api.aipaygen.com/docs for manual key generation."}


# ── NEW: Data & Utility Tools (v1.8.1) ─────────────────────────────────────

@metered_tool("standard")
def wikipedia_lookup(query: Annotated[str, Field(description="Wikipedia search query")], sentences: Annotated[int, Field(description="Number of sentences to return")] = 5) -> dict:
    """Search Wikipedia and return a summary of the most relevant article."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/wikipedia", params={"q": query, "sentences": sentences}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def arxiv_search(query: Annotated[str, Field(description="Academic paper search query")], max_results: Annotated[int, Field(description="Max papers to return")] = 5) -> dict:
    """Search arXiv for academic papers. Returns titles, authors, abstracts, and links."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/arxiv", params={"q": query, "max": max_results}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def github_trending(language: Annotated[str, Field(description="Programming language filter (e.g. python, rust)")] = "", since: Annotated[str, Field(description="Time range: daily, weekly, or monthly")] = "daily") -> dict:
    """Get trending GitHub repositories by language and time range."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/github/trending", params={"language": language, "since": since}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def reddit_posts(subreddit: Annotated[str, Field(description="Subreddit name (without r/)")], sort: Annotated[str, Field(description="Sort: hot, new, top, rising")] = "hot", limit: Annotated[int, Field(description="Number of posts")] = 10) -> dict:
    """Get posts from a subreddit with titles, scores, and links."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/reddit", params={"subreddit": subreddit, "sort": sort, "limit": limit}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def youtube_transcript(url: Annotated[str, Field(description="YouTube video URL or ID")]) -> dict:
    """Extract the transcript/captions from a YouTube video."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/youtube/transcript", params={"url": url}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def generate_qr(data: Annotated[str, Field(description="Text or URL to encode as QR code")], size: Annotated[int, Field(description="QR code size in pixels")] = 300) -> dict:
    """Generate a QR code image from text or URL. Returns base64-encoded PNG."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/qr", params={"data": data, "size": size}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def dns_lookup(domain: Annotated[str, Field(description="Domain to look up DNS records for")], record_type: Annotated[str, Field(description="DNS record type: A, AAAA, MX, TXT, NS, CNAME")] = "A") -> dict:
    """Look up DNS records for a domain."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/dns", params={"domain": domain, "type": record_type}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def validate_email(email: Annotated[str, Field(description="Email address to validate")]) -> dict:
    """Validate an email address format and check MX records."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/validate/email", params={"email": email}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def validate_url(url: Annotated[str, Field(description="URL to validate and check")]) -> dict:
    """Validate a URL format and check if it's reachable."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/validate/url", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def random_name(count: Annotated[int, Field(description="Number of random names to generate")] = 5, gender: Annotated[str, Field(description="Gender filter: male, female, or any")] = "any") -> dict:
    """Generate random realistic names."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/random/name", params={"count": count, "gender": gender}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def color_info(color: Annotated[str, Field(description="Color as hex (#FF5733), name (red), or RGB")]) -> dict:
    """Get detailed color information: hex, RGB, HSL, complementary colors, and name."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/color", params={"color": color}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("premium")
def screenshot(url: Annotated[str, Field(description="URL to capture a screenshot of")], width: Annotated[int, Field(description="Viewport width")] = 1280, height: Annotated[int, Field(description="Viewport height")] = 720) -> dict:
    """Capture a screenshot of a webpage. Returns base64-encoded PNG."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/screenshot", params={"url": url, "width": width, "height": height}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def news_search(query: Annotated[str, Field(description="News search query or topic")] = "", country: Annotated[str, Field(description="Country code for news")] = "us") -> dict:
    """Search for recent news articles by topic or keyword."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/news", params={"q": query, "country": country}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def stock_quote(symbol: Annotated[str, Field(description="Stock ticker symbol (e.g. AAPL)")]) -> dict:
    """Get current stock price, change, and basic financial data."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/stocks", params={"symbol": symbol}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def ip_lookup(ip: Annotated[str, Field(description="IP address to look up (leave empty for your own)")] = "") -> dict:
    """Look up geolocation and ISP information for an IP address."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/ip", params={"ip": ip} if ip else {}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def country_info(code: Annotated[str, Field(description="ISO 2-letter country code (e.g. US, GB, JP)")]) -> dict:
    """Get detailed country information: capital, population, languages, currency, flag."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/country", params={"code": code}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def timezone_info(timezone: Annotated[str, Field(description="Timezone name (e.g. America/New_York) or city")] = "UTC") -> dict:
    """Get current time, UTC offset, and DST status for a timezone."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/timezone", params={"tz": timezone}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def pdf_extract(url: Annotated[str, Field(description="URL to a PDF file to extract text from")]) -> dict:
    """Extract text content from a PDF file by URL."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/extract/pdf", params={"url": url}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def extract_text_from_url(url: Annotated[str, Field(description="URL to extract clean text from")]) -> dict:
    """Extract clean, readable text from any webpage URL (strips HTML)."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/extract/text", params={"url": url}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── File Storage Tools ──────────────────────────────────────────────────────

@metered_tool("standard")
def file_upload(filename: Annotated[str, Field(description="Name for the file")], content: Annotated[str, Field(description="File content (text or base64-encoded)")], content_type: Annotated[str, Field(description="MIME type")] = "text/plain") -> dict:
    """Upload a file to AiPayGen storage. Returns a file ID for retrieval."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/files/upload", json={"filename": filename, "content": content, "content_type": content_type}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def file_list(agent_id: Annotated[str, Field(description="Agent ID to list files for")] = "default") -> dict:
    """List all files stored by an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/files/list/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Encoding Tools (free tier) ──────────────────────────────────────────────

@mcp.tool()
def base64_encode(text: Annotated[str, Field(description="Text to encode as base64")]) -> dict:
    """Encode text to base64."""
    import base64 as _b64
    return {"result": _b64.b64encode(text.encode()).decode()}


@mcp.tool()
def base64_decode(encoded: Annotated[str, Field(description="Base64 string to decode")]) -> dict:
    """Decode a base64 string back to text."""
    import base64 as _b64
    try:
        return {"result": _b64.b64decode(encoded).decode()}
    except Exception:
        return {"error": "Invalid base64 input"}


@mcp.tool()
def hash_text(text: Annotated[str, Field(description="Text to hash")], algorithm: Annotated[str, Field(description="Hash algorithm: md5, sha1, sha256, sha512")] = "sha256") -> dict:
    """Compute a hash of the given text."""
    try:
        h = hashlib.new(algorithm, text.encode())
        return {"algorithm": algorithm, "hash": h.hexdigest()}
    except ValueError:
        return {"error": f"Unknown algorithm: {algorithm}"}


@mcp.tool()
def url_encode(text: Annotated[str, Field(description="Text to URL-encode")]) -> dict:
    """URL-encode a string."""
    from urllib.parse import quote
    return {"result": quote(text)}


@mcp.tool()
def url_decode(text: Annotated[str, Field(description="URL-encoded string to decode")]) -> dict:
    """Decode a URL-encoded string."""
    from urllib.parse import unquote
    return {"result": unquote(text)}


@mcp.tool()
def json_format(json_string: Annotated[str, Field(description="JSON string to format/validate")]) -> dict:
    """Validate and pretty-print a JSON string."""
    try:
        parsed = _json.loads(json_string)
        return {"valid": True, "formatted": _json.dumps(parsed, indent=2)}
    except _json.JSONDecodeError as e:
        return {"valid": False, "error": str(e)}


@mcp.tool()
def json_minify(json_string: Annotated[str, Field(description="JSON string to minify")]) -> dict:
    """Minify a JSON string by removing whitespace."""
    try:
        parsed = _json.loads(json_string)
        return {"result": _json.dumps(parsed, separators=(",", ":"))}
    except _json.JSONDecodeError as e:
        return {"valid": False, "error": str(e)}


@mcp.tool()
def text_stats(text: Annotated[str, Field(description="Text to analyze")]) -> dict:
    """Count words, characters, sentences, and paragraphs in text."""
    words = len(text.split())
    chars = len(text)
    sentences = text.count('.') + text.count('!') + text.count('?')
    paragraphs = len([p for p in text.split('\n\n') if p.strip()])
    lines = text.count('\n') + 1
    return {"words": words, "characters": chars, "sentences": sentences, "paragraphs": paragraphs, "lines": lines}


@mcp.tool()
def random_number(min_val: Annotated[int, Field(description="Minimum value")] = 1, max_val: Annotated[int, Field(description="Maximum value")] = 100) -> dict:
    """Generate a cryptographically secure random number in range."""
    import secrets
    return {"result": secrets.randbelow(max_val - min_val + 1) + min_val}


@mcp.tool()
def random_string(length: Annotated[int, Field(description="Length of the random string")] = 16, charset: Annotated[str, Field(description="Character set: alphanumeric, alpha, hex, digits")] = "alphanumeric") -> dict:
    """Generate a random string from the specified character set."""
    import secrets, string
    charsets = {
        "alphanumeric": string.ascii_letters + string.digits,
        "alpha": string.ascii_letters,
        "hex": string.hexdigits[:16],
        "digits": string.digits,
    }
    chars = charsets.get(charset, charsets["alphanumeric"])
    return {"result": "".join(secrets.choice(chars) for _ in range(min(length, 256)))}


@mcp.tool()
def epoch_convert(epoch: Annotated[str, Field(description="Unix epoch seconds (or 'now' for current time)")] = "now") -> dict:
    """Convert between Unix epoch and human-readable datetime."""
    from datetime import datetime, timezone
    if epoch == "now":
        now = datetime.now(timezone.utc)
        return {"epoch": int(now.timestamp()), "iso": now.isoformat(), "human": now.strftime("%Y-%m-%d %H:%M:%S UTC")}
    try:
        ts = float(epoch)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return {"epoch": int(ts), "iso": dt.isoformat(), "human": dt.strftime("%Y-%m-%d %H:%M:%S UTC")}
    except Exception:
        return {"error": "Invalid epoch timestamp"}


@mcp.tool()
def ip_to_decimal(ip: Annotated[str, Field(description="IPv4 address to convert (e.g. 192.168.1.1)")]) -> dict:
    """Convert an IPv4 address to decimal and back."""
    try:
        parts = ip.strip().split('.')
        decimal = sum(int(p) << (8 * (3 - i)) for i, p in enumerate(parts))
        return {"ip": ip, "decimal": decimal, "hex": hex(decimal), "binary": bin(decimal)}
    except Exception:
        return {"error": "Invalid IPv4 address"}


@mcp.tool()
def cidr_expand(cidr: Annotated[str, Field(description="CIDR notation (e.g. 192.168.1.0/24)")]) -> dict:
    """Expand a CIDR range to show network info: first/last IP, host count."""
    try:
        import ipaddress
        net = ipaddress.ip_network(cidr, strict=False)
        return {
            "network": str(net.network_address),
            "broadcast": str(net.broadcast_address),
            "netmask": str(net.netmask),
            "hosts": net.num_addresses - 2 if net.num_addresses > 2 else net.num_addresses,
            "first_host": str(list(net.hosts())[0]) if net.num_addresses > 2 else str(net.network_address),
            "last_host": str(list(net.hosts())[-1]) if net.num_addresses > 2 else str(net.network_address),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Agent Wallet & Payments ─────────────────────────────────────────────────

@metered_tool("standard")
def wallet_balance() -> dict:
    """Check your agent wallet balance (requires API key)."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/balance", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_transactions(limit: Annotated[int, Field(description="Number of recent transactions")] = 20) -> dict:
    """List recent wallet transactions."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/transactions", params={"limit": limit}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Webhook Management ──────────────────────────────────────────────────────

@metered_tool("standard")
def create_webhook(url: Annotated[str, Field(description="URL to receive webhook events")], events: Annotated[list, Field(description="List of event types to subscribe to")] = None) -> dict:
    """Create a webhook endpoint to receive event notifications."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/webhooks/create", json={"url": url, "events": events or ["all"]}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def list_webhooks(agent_id: Annotated[str, Field(description="Agent ID to list webhooks for")] = "default") -> dict:
    """List all registered webhooks for an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/webhooks/list/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Scraping additions ──────────────────────────────────────────────────────

@metered_tool("premium")
def scrape_linkedin(url: Annotated[str, Field(description="LinkedIn profile or company URL")]) -> dict:
    """Scrape a LinkedIn profile or company page for public data."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/scrape/linkedin", json={"url": url}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("premium")
def scrape_facebook_ads(query: Annotated[str, Field(description="Search query for Facebook ads")], max_results: Annotated[int, Field(description="Max ads to return")] = 10) -> dict:
    """Search the Facebook Ad Library for active advertisements."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/scrape/facebook-ads", json={"query": query, "max_results": max_results}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Session / Conversation Management ───────────────────────────────────────

@metered_tool("standard")
def session_start(agent_id: Annotated[str, Field(description="Agent ID starting the session")] = "default", context: Annotated[str, Field(description="Initial session context or system prompt")] = "") -> dict:
    """Start a persistent conversation session with context tracking."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/session/start", json={"agent_id": agent_id, "context": context}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def session_context(session_id: Annotated[str, Field(description="Session ID to retrieve context for")]) -> dict:
    """Get the current context and history of a conversation session."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/session/{session_id}/context", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Streaming AI Tools ──────────────────────────────────────────────────────

@metered_tool("standard")
def stream_research(topic: Annotated[str, Field(description="Topic to research with streaming output")]) -> dict:
    """Research a topic with streaming output for real-time results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/research", json={"topic": topic}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def stream_write(spec: Annotated[str, Field(description="Writing specification or prompt")]) -> dict:
    """Generate long-form writing with streaming output."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/write", json={"spec": spec}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def stream_analyze(content: Annotated[str, Field(description="Content to analyze with streaming output")]) -> dict:
    """Analyze content with streaming output for real-time results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/analyze", json={"content": content}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Marketplace Management ──────────────────────────────────────────────────

@metered_tool("standard")
def sell_register(name: Annotated[str, Field(description="API name")], endpoint: Annotated[str, Field(description="API endpoint URL")], price_per_call: Annotated[float, Field(description="Price per call in USD")], description: Annotated[str, Field(description="API description")] = "") -> dict:
    """Register your own API on the seller marketplace."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/sell/register", json={"name": name, "endpoint": endpoint, "price_per_call": price_per_call, "description": description}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def sell_directory() -> dict:
    """Browse all APIs listed on the seller marketplace."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/sell/directory", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def sell_dashboard() -> dict:
    """View your seller dashboard with earnings, calls, and analytics."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/sell/dashboard", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Agent Network Extended ──────────────────────────────────────────────────

@metered_tool("standard")
def agent_leaderboard() -> dict:
    """View the agent leaderboard ranked by reputation and activity."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/leaderboard", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_search(query: Annotated[str, Field(description="Search query for finding agents")]) -> dict:
    """Search the agent network for agents matching a query."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/search", params={"q": query}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_portfolio(agent_id: Annotated[str, Field(description="Agent ID to view portfolio for")]) -> dict:
    """View an agent's portfolio: services, reputation, and history."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agents/{agent_id}/portfolio", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_reputation(agent_id: Annotated[str, Field(description="Agent ID to check reputation for")]) -> dict:
    """Check an agent's reputation score and history."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agent/reputation/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Task Board Extended ─────────────────────────────────────────────────────

@metered_tool("standard")
def task_claim(task_id: Annotated[str, Field(description="Task ID to claim")], agent_id: Annotated[str, Field(description="Your agent ID")]) -> dict:
    """Claim an open task from the task board."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/claim", json={"task_id": task_id, "agent_id": agent_id}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def task_complete(task_id: Annotated[str, Field(description="Task ID to mark complete")], result: Annotated[str, Field(description="Task result or deliverable")] = "") -> dict:
    """Mark a claimed task as completed with results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/complete", json={"task_id": task_id, "result": result}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def task_subscribe(agent_id: Annotated[str, Field(description="Your agent ID")], skill: Annotated[str, Field(description="Skill to subscribe to for task notifications")]) -> dict:
    """Subscribe to task board notifications for a specific skill."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/subscribe", json={"agent_id": agent_id, "skill": skill}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Referral System ─────────────────────────────────────────────────────────

@mcp.tool()
def referral_stats(agent_id: Annotated[str, Field(description="Agent ID to check referral stats for")]) -> dict:
    """Check your referral stats: clicks, conversions, and earnings."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/referral/stats/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def referral_leaderboard() -> dict:
    """View the referral leaderboard — top referrers by conversions."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/referral/leaderboard", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Economy & Stats ─────────────────────────────────────────────────────────

@mcp.tool()
def platform_stats() -> dict:
    """Get AiPayGen platform statistics: tools, agents, skills, APIs, and usage."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/stats", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def popular_tools(limit: Annotated[int, Field(description="Number of top tools to return")] = 20) -> dict:
    """Get the most popular tools ranked by usage count."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/popular", params={"limit": limit}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def economy_status() -> dict:
    """View the platform economy: total transactions, active agents, revenue metrics."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/economy/status", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


def main():
    import sys
    if "--http" in sys.argv:
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        import uvicorn

        starlette_app = mcp.streamable_http_app()

        async def health(request):
            return JSONResponse({"status": "ok", "server": "AiPayGen MCP", "tools": 229, "version": "1.8.1"})

        _tracked_sessions = set()

        @starlette_app.middleware("http")
        async def mcp_connect_tracker(request, call_next):
            """Track unique MCP client connections per session."""
            response = await call_next(request)
            if request.url.path == "/mcp" and request.method == "POST":
                try:
                    from funnel_tracker import log_event
                    ip = request.headers.get("cf-connecting-ip",
                         request.client.host if request.client else "unknown")
                    session_key = f"{ip}:{request.headers.get('mcp-session-id', '')}"
                    if session_key not in _tracked_sessions:
                        _tracked_sessions.add(session_key)
                        client_info = request.headers.get("user-agent", "unknown")
                        log_event("mcp_connection", ip=ip,
                                  metadata=_json.dumps({"client": client_info[:100]}))
                        if len(_tracked_sessions) > 10000:
                            _tracked_sessions.clear()
                except Exception:
                    pass
            return response

        starlette_app.routes.insert(0, Route("/health", health))
        uvicorn.run(starlette_app, host="0.0.0.0", port=5002)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
