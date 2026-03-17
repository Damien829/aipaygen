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
    except Exception:
        return {"error": "Invalid CIDR notation"}


# ── Cron / Color / Lorem / Password ─────────────────────────────────────────

@metered_tool("standard")
def cron_explain(expression: Annotated[str, Field(description="Cron expression to explain (e.g. '*/5 * * * *')")]) -> dict:
    """Explain a cron expression in plain English. Supports standard 5-field cron syntax."""
    try:
        parts = expression.strip().split()
        if len(parts) != 5:
            return {"error": "Invalid cron expression. Expected 5 fields: minute hour day_of_month month day_of_week"}

        field_names = ["minute", "hour", "day_of_month", "month", "day_of_week"]
        month_names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
                       7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}
        dow_names = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}

        def _explain_field(val, name):
            if val == "*":
                return f"every {name}"
            if val.startswith("*/"):
                return f"every {val[2:]} {name}s"
            if "," in val:
                return f"{name} {val}"
            if "-" in val:
                lo, hi = val.split("-", 1)
                return f"{name} {lo} through {hi}"
            if name == "month" and val.isdigit():
                return month_names.get(int(val), f"month {val}")
            if name == "day_of_week" and val.isdigit():
                return dow_names.get(int(val), f"day {val}")
            return f"at {name} {val}"

        explanations = [_explain_field(p, n) for p, n in zip(parts, field_names)]
        summary = ", ".join(explanations)

        # Build a more natural description
        minute, hour, dom, month, dow = parts
        natural = "Runs "
        if minute == "*" and hour == "*":
            natural += "every minute"
        elif minute.startswith("*/"):
            natural += f"every {minute[2:]} minutes"
        elif hour == "*":
            natural += f"at minute {minute} of every hour"
        elif minute == "0":
            natural += f"at {hour}:00"
        else:
            natural += f"at {hour}:{minute.zfill(2)}"

        if dom != "*":
            natural += f" on day {dom} of the month"
        if month != "*":
            m = month_names.get(int(month), month) if month.isdigit() else month
            natural += f" in {m}"
        if dow != "*":
            d = dow_names.get(int(dow), dow) if dow.isdigit() else dow
            natural += f" on {d}"

        return {
            "expression": expression,
            "fields": dict(zip(field_names, parts)),
            "explanation": summary,
            "natural": natural,
        }
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def color_palette(base_color: Annotated[str, Field(description="Base color in hex format (e.g. '#3498db' or '3498db')")], count: Annotated[int, Field(description="Number of colors to generate (max 20)")] = 5, palette_type: Annotated[str, Field(description="Palette type: complementary, analogous, or monochromatic")] = "monochromatic") -> dict:
    """Generate a color palette from a base color. Returns hex color codes."""
    import colorsys
    try:
        hex_str = base_color.lstrip("#")
        if len(hex_str) != 6:
            return {"error": "Invalid hex color. Use format '#RRGGBB' or 'RRGGBB'."}
        r, g, b = int(hex_str[:2], 16) / 255, int(hex_str[2:4], 16) / 255, int(hex_str[4:6], 16) / 255
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        n = min(count, 20)
        colors = []

        if palette_type == "complementary":
            for i in range(n):
                new_h = (h + (i / n)) % 1.0
                nr, ng, nb = colorsys.hsv_to_rgb(new_h, s, v)
                colors.append("#{:02x}{:02x}{:02x}".format(int(nr * 255), int(ng * 255), int(nb * 255)))
        elif palette_type == "analogous":
            spread = 0.083  # ~30 degrees
            for i in range(n):
                offset = (i - n // 2) * spread / max(n - 1, 1)
                new_h = (h + offset) % 1.0
                nr, ng, nb = colorsys.hsv_to_rgb(new_h, s, v)
                colors.append("#{:02x}{:02x}{:02x}".format(int(nr * 255), int(ng * 255), int(nb * 255)))
        else:  # monochromatic
            for i in range(n):
                new_v = max(0.1, min(1.0, v - 0.3 + (0.6 * i / max(n - 1, 1))))
                nr, ng, nb = colorsys.hsv_to_rgb(h, s, new_v)
                colors.append("#{:02x}{:02x}{:02x}".format(int(nr * 255), int(ng * 255), int(nb * 255)))

        return {
            "base_color": f"#{hex_str}",
            "palette_type": palette_type,
            "colors": colors,
            "count": len(colors),
        }
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def lorem_ipsum(paragraphs: Annotated[int, Field(description="Number of paragraphs to generate (max 10)")] = 1, style: Annotated[str, Field(description="Style: classic, short, or words")] = "classic") -> dict:
    """Generate Lorem Ipsum placeholder text. Free, no payment needed."""
    _CLASSIC = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore "
        "et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
        "aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse "
        "cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in "
        "culpa qui officia deserunt mollit anim id est laborum."
    )
    _EXTRAS = [
        "Curabitur pretium tincidunt lacus. Nulla gravida orci a odio. Nullam varius, turpis et commodo pharetra.",
        "Praesent dapibus, neque id cursus faucibus, tortor neque egestas augue, eu vulputate magna eros eu erat.",
        "Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis egestas.",
        "Vestibulum tortor quam, feugiat vitae, ultricies eget, tempor sit amet, ante. Donec eu libero sit amet.",
        "Fusce vulputate eleifend sapien. Vestibulum purus quam, scelerisque ut, mollis sed, nonummy id, metus.",
        "Aenean tellus metus, bibendum sed, posuere ac, mattis non, nunc. Vestibulum fringilla pede sit amet augue.",
        "Morbi in sem quis dui placerat ornare. Pellentesque odio nisi, euismod in, pharetra a, ultricies in, diam.",
        "Maecenas malesuada elit lectus felis, malesuada ultricies. Curabitur et ligula. Ut molestie a, ultricies.",
        "Nam adipiscing. Etiam laoreet. Nullam luctus, est a gravida dictum, metus risus vehicula leo, at auctor est.",
    ]
    import random
    n = min(max(paragraphs, 1), 10)
    if style == "words":
        words = _CLASSIC.split()
        return {"text": " ".join(words[:n * 10]), "word_count": min(n * 10, len(words))}
    paras = [_CLASSIC]
    pool = list(_EXTRAS)
    random.shuffle(pool)
    for i in range(1, n):
        paras.append(pool[i % len(pool)])
    return {"text": "\n\n".join(paras[:n]), "paragraphs": n}


@metered_tool("free")
def password_generate(length: Annotated[int, Field(description="Password length (8-128)")] = 16, include_symbols: Annotated[bool, Field(description="Include special characters")] = True, count: Annotated[int, Field(description="Number of passwords to generate (max 20)")] = 1) -> dict:
    """Generate cryptographically secure random passwords. Free, no payment needed."""
    import secrets
    import string
    length = max(8, min(length, 128))
    n = max(1, min(count, 20))
    chars = string.ascii_letters + string.digits
    if include_symbols:
        chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"
    passwords = []
    for _ in range(n):
        pw = "".join(secrets.choice(chars) for _ in range(length))
        passwords.append(pw)
    if n == 1:
        pw = passwords[0]
        strength = "weak" if length < 12 else "moderate" if length < 16 else "strong"
        return {"password": pw, "length": length, "includes_symbols": include_symbols, "strength": strength}
    return {"passwords": passwords, "count": n, "length": length, "includes_symbols": include_symbols}
