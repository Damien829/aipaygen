"""Utility Tools — free tools (time, UUID, jokes, quotes, holidays) + encoding/hashing."""

import hashlib
import json as _json
from typing import Annotated
from pydantic import Field

from mcp_tools import mcp, metered_tool, _log
import requests as _mcp_requests


# ── Free Utility Tools ───────────────────────────────────────────────────────

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


# ── Encoding Tools (free tier) ───────────────────────────────────────────────

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
