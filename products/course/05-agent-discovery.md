# Lesson 05: Agent Discovery

## What You Will Build

A discovery system that makes your agents findable: a categorized endpoint catalog, an OpenAPI specification, an MCP (Model Context Protocol) server, SEO-friendly pages, and a `/discover` endpoint for programmatic agent discovery.

## The Discovery Engine

The AiPayGen codebase organizes all paid endpoints into categories. This isn't just for documentation — it powers the discovery API, the OpenAPI spec, and the SEO pages:

```python
_CATEGORIES = {
    "ai": {
        "description": "AI-powered content generation and analysis",
        "routes": [
            "/research", "/write", "/analyze", "/code", "/summarize",
            "/translate", "/social", "/chat", "/plan", "/explain",
        ],
    },
    "data": {
        "description": "Web scraping, search, and data extraction",
        "routes": [
            "/scrape", "/search", "/extract", "/qa", "/classify",
            "/sentiment", "/keywords", "/compare",
        ],
    },
    "agent": {
        "description": "Agent infrastructure — memory, messaging, tasks",
        "routes": [
            "/memory/set", "/memory/get", "/memory/search",
            "/message/send", "/task/submit", "/marketplace/call",
        ],
    },
    "finance": {
        "description": "Financial data — stocks, forex, crypto",
        "routes": [
            "/data/finance/history", "/data/finance/forex",
            "/data/crypto/trending",
        ],
    },
}
```

## The /discover Endpoint

This endpoint lets other AI agents and developers programmatically discover what your platform offers:

```python
@discovery_bp.route("/discover", methods=["GET"])
def discover():
    """Agent-friendly discovery endpoint. Returns all capabilities."""
    categories = {}
    total_endpoints = 0
    
    for cat_id, cat_info in _CATEGORIES.items():
        routes = cat_info["routes"]
        categories[cat_id] = {
            "description": cat_info["description"],
            "endpoint_count": len(routes),
            "endpoints": routes,
        }
        total_endpoints += len(routes)
    
    return jsonify({
        "name": "AiPayGen",
        "version": APP_VERSION,
        "description": "AI agent marketplace and API platform",
        "total_endpoints": total_endpoints,
        "categories": categories,
        "auth": {
            "type": "bearer",
            "header": "Authorization",
            "prefix": "Bearer apk_",
            "get_key": "/quick-key",
        },
        "pricing": {
            "model": "prepaid",
            "min_topup": "$0.50",
            "avg_cost_per_call": "$0.006",
        },
        "links": {
            "docs": "/docs",
            "openapi": "/openapi.json",
            "marketplace": "/market",
            "status": "/health",
        },
    })
```

This is the single most important endpoint for growth. When an AI agent needs to find tools, it hits `/discover` and gets a structured overview of everything available. Include auth instructions, pricing, and links to further resources.

## OpenAPI Specification

An OpenAPI spec makes your API consumable by thousands of tools — Postman, OpenAPI clients, other AI agents, and API directories. Generate it from your route data:

```python
@app.route("/openapi.json")
def openapi_spec():
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "AiPayGen API",
            "version": APP_VERSION,
            "description": "AI Agent Marketplace — 65+ tools",
            "contact": {"url": "https://aipaygen.com"},
        },
        "servers": [{"url": "https://api.aipaygen.com"}],
        "paths": {},
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API key with apk_ prefix",
                }
            }
        },
        "security": [{"ApiKeyAuth": []}],
    }
    
    for cat_id, cat_info in _CATEGORIES.items():
        for route in cat_info["routes"]:
            spec["paths"][route] = {
                "post": {
                    "summary": f"{route.strip('/').replace('/', ' ').title()}",
                    "tags": [cat_id],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Success"},
                        "401": {"description": "Invalid API key"},
                        "402": {"description": "Insufficient credits"},
                    },
                }
            }
    
    return jsonify(spec)
```

## MCP Server

The Model Context Protocol (MCP) is how AI assistants like Claude discover and use tools. Building an MCP server makes your tools natively accessible:

```python
# mcp_server.py — simplified from the real codebase
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("aipaygen")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="research",
            description="Deep research on any topic with citations",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="web_search",
            description="Search the web and return structured results",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        # ... 65+ more tools
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    # Route to the Flask API
    import requests
    resp = requests.post(
        f"http://localhost:5001/{name}",
        json=arguments,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=60,
    )
    return [TextContent(type="text", text=resp.text)]
```

The MCP server is a thin wrapper — it describes the tools and routes calls to the same Flask API that handles HTTP requests. One codebase, two interfaces.

## SEO: Sitemap and Blog Posts

Generate a sitemap dynamically from your routes and marketplace listings:

```python
@app.route("/sitemap.xml")
def sitemap():
    urls = []
    base = "https://aipaygen.com"
    
    # Static pages
    for page in ["/", "/docs", "/market", "/buy-credits", "/quick-key"]:
        urls.append(f"<url><loc>{base}{page}</loc><priority>0.9</priority></url>")
    
    # Category pages
    for cat_id in _CATEGORIES:
        urls.append(f"<url><loc>{base}/docs/{cat_id}</loc><priority>0.7</priority></url>")
    
    # Marketplace agent pages
    listings, _ = marketplace_get_services(page=1, per_page=500)
    for listing in listings:
        urls.append(
            f"<url><loc>{base}/market/{listing['listing_id']}</loc>"
            f"<priority>0.6</priority></url>"
        )
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += "".join(urls)
    xml += '</urlset>'
    return xml, 200, {"Content-Type": "application/xml"}
```

The AiPayGen codebase also auto-generates blog posts for each tool category using LLM calls, then serves them as static pages. Automated SEO content at zero marginal cost.

## Directory Submissions

Once your `/discover` and `/openapi.json` endpoints are live, submit to directories:

- **MCP Directory**: Submit your MCP server URL for AI assistant integration
- **APIs.guru**: Submit your OpenAPI spec for the largest API directory
- **RapidAPI**: List individual endpoints as micro-APIs
- **Product Hunt**: Launch day for the marketplace itself

The discovery engine in the real codebase automates this with scheduled jobs that re-submit updated specs daily.

## Exercise

1. Create the `_CATEGORIES` dict for your endpoints.
2. Build a `/discover` endpoint that returns structured capabilities.
3. Generate an `/openapi.json` from your route categories.
4. Create a `/sitemap.xml` that includes all marketplace listings.
5. Bonus: Set up a basic MCP server that wraps 3 of your endpoints.

Next lesson: building a trading engine with strategies and backtesting.
