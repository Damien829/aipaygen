"""Marketplace Tools — list, post, browse catalog, x402 discovery, SDK, seller tools."""

from typing import Annotated
from pydantic import Field

from mcp_tools import (
    mcp, metered_tool, _log,
    get_all_apis, get_api,
    marketplace_list_service, marketplace_get_services,
    _skills_engine,
)
import requests as _mcp_requests


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
    """
    return marketplace_list_service(
        agent_id=agent_id, name=name, description=description,
        endpoint=endpoint, price_usd=price_usd,
        category=category, capabilities=capabilities or [],
    )


# ── Skills System ────────────────────────────────────────────────────────────

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


# ── x402 Discovery Tools ────────────────────────────────────────────────────

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


# ── Seller Marketplace ───────────────────────────────────────────────────────

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


@metered_tool("standard")
def sell_withdraw(amount: Annotated[float, Field(description="Amount in USD to withdraw")]) -> dict:
    """Withdraw earnings from seller marketplace."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/sell/withdraw", json={"amount": amount}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}
