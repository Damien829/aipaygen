"""Auto-generate OpenAPI 3.1.0 spec from the x402 routes dict."""

import re

# Free endpoints to include in the spec
FREE_ENDPOINTS = [
    {"path": "/free/time", "method": "get", "description": "Get current UTC time (free)"},
    {"path": "/free/uuid", "method": "get", "description": "Generate a UUID v4 (free)"},
    {"path": "/free/ip", "method": "get", "description": "Get your public IP address (free)"},
    {"path": "/free/hash", "method": "post", "description": "Hash text with SHA-256 (free)"},
    {"path": "/free/base64", "method": "post", "description": "Base64 encode/decode text (free)"},
    {"path": "/free/random", "method": "get", "description": "Generate a random number (free)"},
    {"path": "/health", "method": "get", "description": "Service health check"},
    {"path": "/discover", "method": "get", "description": "Discover available endpoints and capabilities"},
    {"path": "/llms.txt", "method": "get", "description": "LLMs.txt manifest for AI agents"},
]

# Additional management endpoints not in x402 routes dict
MANAGEMENT_ENDPOINTS = [
    {
        "path": "/dashboard",
        "method": "get",
        "description": "Self-serve usage dashboard for API key holders",
        "params": [{"name": "key", "in": "query", "schema": {"type": "string"}, "description": "API key (apk_xxx)"}],
    },
    {
        "path": "/api/usage",
        "method": "get",
        "description": "JSON usage data for an API key — balance, call counts, top tools",
        "params": [{"name": "key", "in": "query", "schema": {"type": "string"}, "description": "API key (apk_xxx)"}],
        "response_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Masked API key"},
                "balance_usd": {"type": "number"},
                "total_calls": {"type": "integer"},
                "calls_today": {"type": "integer"},
                "top_tools": {"type": "array", "items": {"type": "object"}},
                "created_at": {"type": "string"},
            },
        },
    },
    {
        "path": "/auth/generate-key",
        "method": "post",
        "description": "Generate a free API key with $0.25 trial credits (~40 calls)",
        "request_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Optional label for the key"},
            },
        },
    },
    {
        "path": "/models",
        "method": "get",
        "description": "List all available AI models with pricing and capabilities",
    },
    {
        "path": "/status",
        "method": "get",
        "description": "Live service health, model status, and 24h statistics",
    },
    {
        "path": "/popular",
        "method": "get",
        "description": "Most popular tools by usage count",
    },
    {
        "path": "/discover/catalog",
        "method": "get",
        "description": "Machine-readable endpoint catalog with pricing, categories, and search",
        "params": [
            {"name": "category", "in": "query", "schema": {"type": "string"}, "description": "Filter by category (ai, data, agent, utility)"},
            {"name": "search", "in": "query", "schema": {"type": "string"}, "description": "Search descriptions and paths"},
            {"name": "page", "in": "query", "schema": {"type": "integer"}, "description": "Page number"},
        ],
    },
    {
        "path": "/openapi.json",
        "method": "get",
        "description": "This OpenAPI 3.1.0 specification",
    },
]

# Standard rate limit response headers
_RATE_LIMIT_HEADERS = {
    "X-RateLimit-Limit": {
        "description": "Maximum requests per window",
        "schema": {"type": "integer", "example": 60},
    },
    "X-RateLimit-Remaining": {
        "description": "Requests remaining in current window",
        "schema": {"type": "integer", "example": 55},
    },
    "X-RateLimit-Reset": {
        "description": "Unix timestamp when the rate limit window resets",
        "schema": {"type": "integer", "example": 1710500000},
    },
    "X-Request-Id": {
        "description": "Unique request ID for debugging and support",
        "schema": {"type": "string", "format": "uuid"},
    },
    "X-API-Version": {
        "description": "Current API version",
        "schema": {"type": "string", "example": "1.9.0"},
    },
}


def generate_openapi_spec(routes=None):
    """Generate a complete OpenAPI 3.1.0 spec from the x402 routes dict.

    Args:
        routes: Optional routes dict. If None, imports lazily from app.
    """
    if routes is None:
        from app import routes as _routes
        routes = _routes

    paths = {}

    # Paid routes from the x402 routes dict
    for route_key, config in routes.items():
        match = re.match(r"(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", route_key)
        if not match:
            continue
        method = match.group(1).lower()
        path = match.group(2)

        # Extract price from first payment option
        price = None
        if config.accepts:
            price = config.accepts[0].price

        operation = {
            "summary": config.description,
            "description": config.description,
            "operationId": _path_to_operation_id(method, path),
            "security": [{"bearerApiKey": []}, {"x402Payment": []}],
            "responses": {
                "200": {
                    "description": "Successful response",
                    "headers": _RATE_LIMIT_HEADERS,
                    "content": {
                        config.mime_type: {"schema": {"type": "object"}}
                    },
                },
                "402": {"description": "Payment required — send x402 X-Payment header or use API key"},
                "429": {
                    "description": "Rate limit exceeded — check X-RateLimit-Reset header for retry time",
                    "headers": _RATE_LIMIT_HEADERS,
                },
            },
        }

        if price:
            operation["x-pricing"] = {
                "price": price,
                "currency": "USDC",
                "network": "Base (eip155:8453)",
            }

        if method == "post":
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"type": "object"}
                    }
                },
            }

        paths.setdefault(path, {})[method] = operation

    # ── /chain endpoint with detailed schema ───────────────────────────────
    if "/chain" in paths and "post" in paths["/chain"]:
        paths["/chain"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["steps"],
                        "properties": {
                            "steps": {
                                "type": "array",
                                "maxItems": 5,
                                "items": {
                                    "type": "object",
                                    "required": ["action"],
                                    "properties": {
                                        "action": {
                                            "type": "string",
                                            "description": "Endpoint name without leading slash (e.g. 'research', 'summarize', 'translate')",
                                        },
                                        "params": {
                                            "type": "object",
                                            "description": "Parameters for this step. Use {{prev_result}} to reference the output of the previous step.",
                                        },
                                    },
                                },
                            },
                        },
                        "example": {
                            "steps": [
                                {"action": "research", "params": {"query": "quantum computing 2026"}},
                                {"action": "summarize", "params": {"text": "{{prev_result}}"}},
                            ]
                        },
                    }
                }
            },
        }
        paths["/chain"]["post"]["responses"]["200"] = {
            "description": "Chain execution results",
            "headers": _RATE_LIMIT_HEADERS,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "results": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step": {"type": "integer"},
                                        "action": {"type": "string"},
                                        "result": {"type": "object"},
                                    },
                                },
                            },
                            "total_steps": {"type": "integer"},
                            "_meta": {"type": "object"},
                        },
                    }
                }
            },
        }

    # Free endpoints
    for ep in FREE_ENDPOINTS:
        operation = {
            "summary": ep["description"],
            "description": ep["description"],
            "operationId": _path_to_operation_id(ep["method"], ep["path"]),
            "security": [],
            "responses": {
                "200": {
                    "description": "Successful response",
                    "headers": _RATE_LIMIT_HEADERS,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
            },
            "x-pricing": {"price": "free"},
        }
        if ep["method"] == "post":
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"type": "object"}}
                },
            }
        paths.setdefault(ep["path"], {})[ep["method"]] = operation

    # Management / non-paid endpoints
    for ep in MANAGEMENT_ENDPOINTS:
        operation = {
            "summary": ep["description"],
            "description": ep["description"],
            "operationId": _path_to_operation_id(ep["method"], ep["path"]),
            "security": [{"bearerApiKey": []}] if ep["path"] not in ("/models", "/status", "/popular", "/discover/catalog", "/openapi.json") else [],
            "responses": {
                "200": {
                    "description": "Successful response",
                    "headers": _RATE_LIMIT_HEADERS,
                    "content": {"application/json": {"schema": ep.get("response_schema", {"type": "object"})}},
                },
            },
        }
        if ep.get("params"):
            operation["parameters"] = ep["params"]
        if ep["method"] == "post" and ep.get("request_schema"):
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": ep["request_schema"]}},
            }
        paths.setdefault(ep["path"], {})[ep["method"]] = operation

    # Deprecation notices for duplicate routes
    _deprecated_paths = {"/free/joke": "/data/joke", "/free/quote": "/data/quote"}
    for old_path, new_path in _deprecated_paths.items():
        if old_path in paths:
            for method_key in paths[old_path]:
                paths[old_path][method_key]["deprecated"] = True
                paths[old_path][method_key]["description"] = (
                    paths[old_path][method_key].get("description", "") +
                    f" [DEPRECATED: use {new_path} instead, sunset 2026-09-01]"
                )

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "AiPayGen API",
            "version": "1.9.0",
            "description": (
                "250 AI tools in one API. Research, write, code, translate, analyze, scrape — "
                "pay per call with USDC on Base via x402, use a prepaid API key, or get $0.25 trial credits.\n\n"
                "## Authentication\n"
                "Three options:\n"
                "1. **API Key** (recommended): `Authorization: Bearer apk_xxx` — get a free key with $0.25 trial credits via `POST /auth/generate-key`\n"
                "2. **x402 Payment**: `X-Payment` header with USDC micropayment on Base (eip155:8453)\n"
                "3. **Free tier**: 3 calls/day per IP, no auth needed\n\n"
                "## Rate Limits\n"
                "- Free tier: 60 requests/minute per IP, 10 AI calls/day\n"
                "- API key: 60 requests/minute per IP (higher limits available)\n"
                "- Rate limit state exposed via `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers\n\n"
                "## Request IDs\n"
                "Every response includes an `X-Request-Id` header (UUID). Include this in support requests for fast resolution. "
                "You can also pass your own `X-Request-Id` header to correlate requests."
            ),
            "contact": {"url": "https://api.aipaygen.com", "email": "hello@aipaygen.com"},
            "license": {"name": "Proprietary"},
            "x-logo": {"url": "https://aipaygen.com/favicon.ico"},
        },
        "servers": [
            {"url": "https://api.aipaygen.com", "description": "Production"},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerApiKey": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "apk_xxx",
                    "description": (
                        "Prepaid API key — generate a free key with $0.25 trial credits via "
                        "`POST /auth/generate-key`, or purchase at /buy-credits. "
                        "Pass as `Authorization: Bearer apk_xxx`."
                    ),
                },
                "x402Payment": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Payment",
                    "description": (
                        "x402 USDC micropayment on Base (eip155:8453). "
                        "See https://x402.org for protocol details. "
                        "Pay-to wallet: 0x366D488a48de1B2773F3a21F1A6972715056Cb30"
                    ),
                },
            },
            "headers": _RATE_LIMIT_HEADERS,
        },
        "tags": [
            {"name": "AI Tools", "description": "AI-powered content generation and analysis"},
            {"name": "Data", "description": "Web scraping, search, and data extraction"},
            {"name": "Agent", "description": "Agent infrastructure — memory, messaging, tasks"},
            {"name": "Utility", "description": "Developer utilities — regex, mock, batch, math"},
            {"name": "Management", "description": "API keys, usage, dashboard, models"},
            {"name": "Free", "description": "No-auth endpoints — time, UUID, IP, hash"},
        ],
    }

    return spec


def _path_to_operation_id(method, path):
    """Convert method + path to a camelCase operationId."""
    # /scrape/google-maps -> scrape_google_maps
    clean = path.strip("/").replace("/", "_").replace("-", "_")
    return f"{method}_{clean}" if clean else method
