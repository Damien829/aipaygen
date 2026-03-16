"""Data Tools — web search, real-time data, enrichment, NLP, transforms, finance, etc."""

import os
from typing import Annotated
from pydantic import Field

from mcp_tools import mcp, metered_tool, _log
import requests as _mcp_requests


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


# ── Geocoding & Location ─────────────────────────────────────────────────────

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


# ── Company & Domain ─────────────────────────────────────────────────────────

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


# ── Text Analysis ────────────────────────────────────────────────────────────

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


# ── Web & URL ────────────────────────────────────────────────────────────────

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


# ── Compute & Dev ────────────────────────────────────────────────────────────

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


# ── Media & Visual ───────────────────────────────────────────────────────────

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


# ── Blockchain ───────────────────────────────────────────────────────────────

@metered_tool("standard")
def ens_resolve(name: Annotated[str, Field(description="ENS name (e.g. vitalik.eth) or 0x address for reverse lookup")]) -> dict:
    """Resolve ENS name to Ethereum address, or reverse-resolve address to ENS name."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/ens", params={"name": name}, timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Enrichment ───────────────────────────────────────────────────────────────

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


# ── Email ────────────────────────────────────────────────────────────────────

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


# ── Document Extraction ──────────────────────────────────────────────────────

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


# ── Finance ──────────────────────────────────────────────────────────────────

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


# ── NLP ──────────────────────────────────────────────────────────────────────

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


# ── Data Transforms ──────────────────────────────────────────────────────────

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


# ── Date & Time ──────────────────────────────────────────────────────────────

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


# ── Security ─────────────────────────────────────────────────────────────────

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


# ── Math & Statistics ────────────────────────────────────────────────────────

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


# ── Crypto ───────────────────────────────────────────────────────────────────

@metered_tool("standard")
def crypto_trending() -> dict:
    """Get trending cryptocurrency tokens and DeFi data from CoinGecko."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/data/crypto/trending", timeout=15)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── v1.8.1 Data & Utility ───────────────────────────────────────────────────

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
