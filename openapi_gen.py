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
                    "content": {
                        config.mime_type: {"schema": {"type": "object"}}
                    },
                },
                "402": {"description": "Payment required — send x402 X-Payment header or use API key"},
                "429": {"description": "Rate limit exceeded"},
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

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "AiPayGen API",
            "version": "1.0.0",
            "description": (
                "155 AI tools in one API. Research, write, code, translate, analyze, scrape — "
                "pay per call with USDC on Base via x402 or use a prepaid API key."
            ),
            "contact": {"url": "https://api.aipaygen.com"},
            "license": {"name": "Proprietary"},
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
                    "description": "Prepaid API key (apk_xxx) — purchased via /buy-credits or /credits/buy",
                },
                "x402Payment": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Payment",
                    "description": "x402 payment header — USDC micropayment on Base (eip155:8453)",
                },
            }
        },
    }

    return spec


def _path_to_operation_id(method, path):
    """Convert method + path to a camelCase operationId."""
    # /scrape/google-maps -> scrape_google_maps
    clean = path.strip("/").replace("/", "_").replace("-", "_")
    return f"{method}_{clean}" if clean else method
