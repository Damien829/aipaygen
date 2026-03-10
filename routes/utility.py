"""Blueprint for utility endpoints — inspired by API Toll's 75-endpoint catalog.
Adds ~40 new compute, web, NLP, finance, security, math, transform, and media tools.
"""

import io
import os
import re
import json
import math
import time
import socket
import struct
import hashlib
import base64
import ast
import operator
import statistics
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree

import yaml
import jwt as pyjwt
import markdown as md_lib
import requests as _requests
from flask import Blueprint, request, jsonify, send_file

from helpers import cache_get as _cache_get, cache_set as _cache_set, get_client_ip as _get_client_ip

utility_bp = Blueprint("utility", __name__)

# ─────────────────────────────────────────────────────────────────────────────
# GEOCODING
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/geocode", methods=["GET"])
def geocode():
    """Address to coordinates via Nominatim."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    cache_key = f"geocode:{q}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        r = _requests.get("https://nominatim.openstreetmap.org/search",
                          params={"q": q, "format": "json", "limit": 5},
                          headers={"User-Agent": "AiPayGen/1.0"}, timeout=10)
        results = [{"lat": float(x["lat"]), "lon": float(x["lon"]),
                     "display_name": x.get("display_name", ""),
                     "type": x.get("type", "")} for x in r.json()[:5]]
        out = {"query": q, "results": results}
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/geocode/reverse", methods=["GET"])
def geocode_reverse():
    """Coordinates to address via Nominatim."""
    lat = request.args.get("lat", "")
    lon = request.args.get("lon", "")
    if not lat or not lon:
        return jsonify({"error": "lat and lon parameters required"}), 400
    cache_key = f"geocode_rev:{lat}:{lon}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        r = _requests.get("https://nominatim.openstreetmap.org/reverse",
                          params={"lat": lat, "lon": lon, "format": "json"},
                          headers={"User-Agent": "AiPayGen/1.0"}, timeout=10)
        data = r.json()
        out = {"lat": float(lat), "lon": float(lon),
               "address": data.get("display_name", ""),
               "details": data.get("address", {})}
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY SEARCH
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/company", methods=["GET"])
def company_search():
    """Company/corporate entity search via Wikipedia + Clearbit-style enrichment."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    cache_key = f"company:{q}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        wiki = _requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + q.replace(" ", "_"),
                             timeout=10).json()
        domain_guess = q.lower().replace(" ", "") + ".com"
        out = {
            "query": q,
            "name": wiki.get("title", q),
            "description": wiki.get("extract", "No description found"),
            "domain_guess": domain_guess,
            "wikipedia_url": wiki.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "thumbnail": wiki.get("thumbnail", {}).get("source", ""),
        }
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# WHOIS / DOMAIN
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/whois", methods=["GET"])
def whois_lookup():
    """Domain WHOIS/RDAP data."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    cache_key = f"whois:{domain}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        r = _requests.get(f"https://rdap.org/domain/{domain}", timeout=10)
        data = r.json()
        out = {
            "domain": domain,
            "status": data.get("status", []),
            "events": [{"action": e.get("eventAction"), "date": e.get("eventDate")}
                       for e in data.get("events", [])],
            "nameservers": [ns.get("ldhName", "") for ns in data.get("nameservers", [])],
            "registrar": next((e.get("vcardArray", [[],[]])[1][0][-1]
                              for e in data.get("entities", [])
                              if "registrar" in e.get("roles", [])), "Unknown"),
        }
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/domain", methods=["GET"])
def domain_profile():
    """Full domain profile (DNS + WHOIS combined)."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    cache_key = f"domain_profile:{domain}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    import subprocess
    out = {"domain": domain, "dns": {}, "whois": {}}
    try:
        for rtype in ["A", "AAAA", "MX", "TXT", "NS", "CNAME"]:
            try:
                result = subprocess.run(["dig", "+short", rtype, domain],
                                       capture_output=True, text=True, timeout=5)
                records = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                if records:
                    out["dns"][rtype] = records
            except Exception:
                pass
    except Exception:
        pass
    try:
        r = _requests.get(f"https://rdap.org/domain/{domain}", timeout=10)
        data = r.json()
        out["whois"]["status"] = data.get("status", [])
        out["whois"]["nameservers"] = [ns.get("ldhName", "") for ns in data.get("nameservers", [])]
        out["whois"]["events"] = [{"action": e.get("eventAction"), "date": e.get("eventDate")}
                                   for e in data.get("events", [])]
    except Exception:
        pass
    _cache_set(cache_key, out, ttl=3600)
    return jsonify(out)


# ─────────────────────────────────────────────────────────────────────────────
# TEXT ANALYSIS: Readability, Language Detection, Profanity
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/readability", methods=["POST"])
def readability_score():
    """Readability score (Flesch-Kincaid)."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text field required"}), 400
    sentences = max(1, len(re.split(r'[.!?]+', text)))
    words_list = text.split()
    word_count = max(1, len(words_list))
    syllable_count = sum(_count_syllables(w) for w in words_list)
    flesch = 206.835 - 1.015 * (word_count / sentences) - 84.6 * (syllable_count / word_count)
    grade = 0.39 * (word_count / sentences) + 11.8 * (syllable_count / word_count) - 15.59
    levels = {(90, 101): "Very Easy", (80, 90): "Easy", (70, 80): "Fairly Easy",
              (60, 70): "Standard", (50, 60): "Fairly Difficult",
              (30, 50): "Difficult", (-100, 30): "Very Difficult"}
    level = next((v for (lo, hi), v in levels.items() if lo <= flesch < hi), "Unknown")
    return jsonify({
        "flesch_reading_ease": round(flesch, 2),
        "flesch_kincaid_grade": round(grade, 2),
        "level": level,
        "sentences": sentences,
        "words": word_count,
        "syllables": syllable_count,
    })


def _count_syllables(word):
    word = word.lower().strip(".,!?;:'\"")
    if len(word) <= 3:
        return 1
    word = re.sub(r'(?:es|ed|e)$', '', word) or word
    vowels = re.findall(r'[aeiouy]+', word)
    return max(1, len(vowels))


@utility_bp.route("/data/language", methods=["GET"])
def language_detect():
    """Language detection using character analysis."""
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "text parameter required"}), 400
    scripts = {}
    for char in text:
        try:
            name = unicodedata.name(char, "UNKNOWN").split()[0]
            scripts[name] = scripts.get(name, 0) + 1
        except Exception:
            pass
    total = sum(scripts.values()) or 1
    script_map = {"LATIN": "en", "CJK": "zh", "HIRAGANA": "ja", "KATAKANA": "ja",
                  "HANGUL": "ko", "ARABIC": "ar", "DEVANAGARI": "hi", "CYRILLIC": "ru",
                  "THAI": "th", "HEBREW": "he", "GREEK": "el"}
    top_script = max(scripts, key=scripts.get) if scripts else "LATIN"
    lang = script_map.get(top_script, "en")
    return jsonify({
        "text_sample": text[:100],
        "detected_language": lang,
        "script": top_script,
        "confidence": round(scripts.get(top_script, 0) / total, 3),
        "scripts": {k: round(v / total, 3) for k, v in sorted(scripts.items(), key=lambda x: -x[1])[:5]},
    })


_PROFANITY_WORDS = set(["damn", "hell", "ass", "shit", "fuck", "bitch", "bastard",
                         "crap", "dick", "piss", "cock", "pussy", "slut", "whore"])

@utility_bp.route("/data/profanity", methods=["POST"])
def profanity_filter():
    """Profanity filter/detection."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text field required"}), 400
    words = re.findall(r'\b\w+\b', text.lower())
    found = [w for w in words if w in _PROFANITY_WORDS]
    cleaned = text
    for w in _PROFANITY_WORDS:
        cleaned = re.sub(r'\b' + w + r'\b', '*' * len(w), cleaned, flags=re.IGNORECASE)
    return jsonify({
        "contains_profanity": len(found) > 0,
        "profanity_count": len(found),
        "words_found": list(set(found)),
        "cleaned_text": cleaned,
    })


# ─────────────────────────────────────────────────────────────────────────────
# WEB & URL TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/meta", methods=["GET"])
def url_meta():
    """Extract meta tags (OG, Twitter Cards) from URL."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
        html = r.text[:50000]
        meta = {}
        for match in re.finditer(r'<meta\s+(?:property|name)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']', html, re.I):
            meta[match.group(1)] = match.group(2)
        for match in re.finditer(r'<meta\s+content=["\']([^"\']*)["\'].*?(?:property|name)=["\']([^"\']+)["\']', html, re.I):
            meta[match.group(2)] = match.group(1)
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        return jsonify({
            "url": url,
            "title": title_m.group(1).strip() if title_m else "",
            "meta_tags": meta,
            "og": {k.replace("og:", ""): v for k, v in meta.items() if k.startswith("og:")},
            "twitter": {k.replace("twitter:", ""): v for k, v in meta.items() if k.startswith("twitter:")},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/links", methods=["GET"])
def extract_links():
    """Extract all links from a URL."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
        links = re.findall(r'href=["\']([^"\']+)["\']', r.text)
        absolute = []
        for link in links:
            if link.startswith("http"):
                absolute.append(link)
            elif link.startswith("/"):
                absolute.append(urljoin(url, link))
        return jsonify({
            "url": url,
            "total_links": len(absolute),
            "links": list(dict.fromkeys(absolute))[:200],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/sitemap", methods=["GET"])
def parse_sitemap():
    """Parse sitemap.xml from a domain."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    if not domain.startswith("http"):
        domain = "https://" + domain
    try:
        r = _requests.get(domain.rstrip("/") + "/sitemap.xml", timeout=10,
                          headers={"User-Agent": "AiPayGen/1.0"})
        urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
        return jsonify({
            "domain": domain,
            "url_count": len(urls),
            "urls": urls[:200],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/robots", methods=["GET"])
def parse_robots():
    """Parse robots.txt from a domain."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    if not domain.startswith("http"):
        domain = "https://" + domain
    try:
        r = _requests.get(domain.rstrip("/") + "/robots.txt", timeout=10,
                          headers={"User-Agent": "AiPayGen/1.0"})
        lines = r.text.strip().split("\n")
        rules = []
        current_agent = "*"
        for line in lines:
            line = line.strip()
            if line.lower().startswith("user-agent:"):
                current_agent = line.split(":", 1)[1].strip()
            elif line.lower().startswith(("allow:", "disallow:", "sitemap:", "crawl-delay:")):
                directive, value = line.split(":", 1)
                rules.append({"agent": current_agent, "directive": directive.strip(),
                              "value": value.strip()})
        sitemaps = [r["value"] for r in rules if r["directive"].lower() == "sitemap"]
        return jsonify({
            "domain": domain,
            "rules": rules,
            "sitemaps": sitemaps,
            "raw": r.text[:5000],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/headers", methods=["GET"])
def http_headers():
    """Get HTTP response headers from a URL."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        r = _requests.head(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"},
                           allow_redirects=True)
        return jsonify({
            "url": url,
            "status_code": r.status_code,
            "headers": dict(r.headers),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/ssl", methods=["GET"])
def ssl_info():
    """SSL certificate info for a domain."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    import ssl
    import OpenSSL.crypto as crypto
    try:
        cert_pem = ssl.get_server_certificate((domain, 443), timeout=10)
        x509 = crypto.load_certificate(crypto.FILETYPE_PEM, cert_pem)
        subject = dict(x509.get_subject().get_components())
        issuer = dict(x509.get_issuer().get_components())
        return jsonify({
            "domain": domain,
            "subject": {k.decode(): v.decode() for k, v in subject.items()},
            "issuer": {k.decode(): v.decode() for k, v in issuer.items()},
            "serial_number": str(x509.get_serial_number()),
            "not_before": x509.get_notBefore().decode(),
            "not_after": x509.get_notAfter().decode(),
            "has_expired": x509.has_expired(),
            "version": x509.get_version(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE & DEV
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/jwt/decode", methods=["POST"])
def jwt_decode():
    """JWT token decode (without verification)."""
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"error": "token field required"}), 400
    try:
        header = pyjwt.get_unverified_header(token)
        payload = pyjwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        expired = datetime.utcfromtimestamp(exp) < datetime.utcnow() if exp else None
        return jsonify({
            "header": header,
            "payload": payload,
            "expired": expired,
            "expiry": datetime.utcfromtimestamp(exp).isoformat() if exp else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@utility_bp.route("/data/markdown", methods=["POST"])
def markdown_to_html():
    """Convert Markdown to HTML."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text field required"}), 400
    html = md_lib.markdown(text, extensions=["tables", "fenced_code", "codehilite"])
    return jsonify({"markdown": text, "html": html})


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA & VISUAL
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/placeholder", methods=["GET"])
def placeholder_image():
    """Generate a placeholder image (SVG)."""
    width = int(request.args.get("width", 300))
    height = int(request.args.get("height", 200))
    bg = request.args.get("bg", "cccccc")
    fg = request.args.get("fg", "666666")
    text = request.args.get("text", f"{width}x{height}")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
  <rect width="100%" height="100%" fill="#{bg}"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        font-family="sans-serif" font-size="{min(width, height) // 6}px" fill="#{fg}">{text}</text>
</svg>'''
    return svg, 200, {"Content-Type": "image/svg+xml"}


@utility_bp.route("/data/favicon", methods=["GET"])
def favicon_extract():
    """Extract favicon from a domain."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    if not domain.startswith("http"):
        domain = "https://" + domain
    try:
        r = _requests.get(domain, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
        icons = []
        for match in re.finditer(r'<link[^>]+rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]+href=["\']([^"\']+)["\']', r.text, re.I):
            href = match.group(1)
            if not href.startswith("http"):
                href = urljoin(domain, href)
            icons.append(href)
        if not icons:
            icons.append(urljoin(domain, "/favicon.ico"))
        return jsonify({"domain": domain, "icons": icons})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/avatar", methods=["GET"])
def identicon_avatar():
    """Generate deterministic identicon avatar (SVG)."""
    input_str = request.args.get("input", "").strip()
    if not input_str:
        return jsonify({"error": "input parameter required"}), 400
    size = int(request.args.get("size", 80))
    h = hashlib.md5(input_str.encode()).hexdigest()
    color = f"#{h[:6]}"
    grid = []
    for i in range(25):
        grid.append(int(h[i % len(h)], 16) % 2 == 0)
    cells = []
    cell_size = size / 5
    for i, filled in enumerate(grid):
        if filled:
            row, col = divmod(i, 5)
            cells.append(f'<rect x="{col * cell_size}" y="{row * cell_size}" '
                        f'width="{cell_size}" height="{cell_size}" fill="{color}"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
    svg += f'<rect width="100%" height="100%" fill="#f0f0f0"/>'
    svg += "".join(cells)
    svg += "</svg>"
    return svg, 200, {"Content-Type": "image/svg+xml"}


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKCHAIN
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/ens", methods=["GET"])
def ens_resolve():
    """ENS name to address resolution."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name parameter required"}), 400
    cache_key = f"ens:{name}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        base_rpc = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
        if name.endswith(".eth"):
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://eth.llamarpc.com"))
            address = w3.ens.address(name)
            out = {"name": name, "address": address, "resolved": address is not None}
        elif name.startswith("0x"):
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://eth.llamarpc.com"))
            ens_name = w3.ens.name(name)
            out = {"address": name, "name": ens_name, "resolved": ens_name is not None}
        else:
            return jsonify({"error": "Provide .eth name or 0x address"}), 400
        _cache_set(cache_key, out, ttl=300)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# ENRICHMENT
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/enrich/domain", methods=["GET"])
def enrich_domain():
    """Domain enrichment — tech stack, socials, DNS."""
    domain = request.args.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "domain parameter required"}), 400
    cache_key = f"enrich_domain:{domain}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    url = f"https://{domain}" if not domain.startswith("http") else domain
    out = {"domain": domain, "tech_stack": [], "socials": [], "dns": {}, "meta": {}}
    try:
        r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
        html = r.text[:100000]
        headers_dict = dict(r.headers)
        tech = []
        tech_patterns = {
            "React": r'react', "Vue": r'vue\.', "Angular": r'angular',
            "jQuery": r'jquery', "WordPress": r'wp-content', "Shopify": r'cdn\.shopify',
            "Next.js": r'_next/', "Nuxt": r'__nuxt', "Svelte": r'svelte',
            "Tailwind": r'tailwind', "Bootstrap": r'bootstrap',
            "Cloudflare": r'cloudflare', "Vercel": r'vercel',
            "Nginx": r'nginx', "Apache": r'apache',
            "Google Analytics": r'google-analytics|gtag', "Stripe": r'stripe\.com',
        }
        for name, pattern in tech_patterns.items():
            if re.search(pattern, html, re.I) or re.search(pattern, str(headers_dict), re.I):
                tech.append(name)
        out["tech_stack"] = tech
        server = headers_dict.get("Server", headers_dict.get("server", ""))
        if server:
            out["server"] = server
        social_patterns = {
            "twitter": r'twitter\.com/([a-zA-Z0-9_]+)',
            "github": r'github\.com/([a-zA-Z0-9_-]+)',
            "linkedin": r'linkedin\.com/(?:company|in)/([a-zA-Z0-9_-]+)',
            "facebook": r'facebook\.com/([a-zA-Z0-9._-]+)',
            "instagram": r'instagram\.com/([a-zA-Z0-9._-]+)',
        }
        for platform, pattern in social_patterns.items():
            match = re.search(pattern, html)
            if match:
                out["socials"].append({"platform": platform, "handle": match.group(1)})
        for match in re.finditer(r'<meta\s+(?:property|name)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']', html, re.I):
            out["meta"][match.group(1)] = match.group(2)
    except Exception:
        pass
    try:
        import subprocess
        for rtype in ["A", "MX", "NS"]:
            result = subprocess.run(["dig", "+short", rtype, domain],
                                   capture_output=True, text=True, timeout=5)
            records = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if records:
                out["dns"][rtype] = records
    except Exception:
        pass
    _cache_set(cache_key, out, ttl=1800)
    return jsonify(out)


@utility_bp.route("/data/enrich/github", methods=["GET"])
def enrich_github():
    """GitHub user profile + top repos."""
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"error": "username parameter required"}), 400
    cache_key = f"enrich_github:{username}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        user = _requests.get(f"https://api.github.com/users/{username}", timeout=10).json()
        repos = _requests.get(f"https://api.github.com/users/{username}/repos?sort=stars&per_page=10",
                              timeout=10).json()
        out = {
            "username": username,
            "name": user.get("name"),
            "bio": user.get("bio"),
            "avatar_url": user.get("avatar_url"),
            "public_repos": user.get("public_repos"),
            "followers": user.get("followers"),
            "following": user.get("following"),
            "created_at": user.get("created_at"),
            "top_repos": [{"name": r.get("name"), "stars": r.get("stargazers_count"),
                           "language": r.get("language"), "description": r.get("description"),
                           "url": r.get("html_url")}
                          for r in repos[:10]] if isinstance(repos, list) else [],
        }
        _cache_set(cache_key, out, ttl=1800)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/email/send", methods=["POST"])
def email_send():
    """Send email via Resend."""
    data = request.get_json(silent=True) or {}
    to = data.get("to", "").strip()
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    if not to or not subject or not body:
        return jsonify({"error": "to, subject, body fields required"}), 400
    resend_key = os.getenv("RESEND_API_KEY")
    if not resend_key:
        return jsonify({"error": "Email service not configured"}), 503
    try:
        r = _requests.post("https://api.resend.com/emails", json={
            "from": "AiPayGen <noreply@aipaygen.com>",
            "to": [to],
            "subject": subject,
            "text": body,
        }, headers={"Authorization": f"Bearer {resend_key}"}, timeout=10)
        return jsonify({"sent": r.status_code == 200, "response": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/extract/text", methods=["POST"])
def extract_text():
    """HTML to clean text extraction."""
    data = request.get_json(silent=True) or {}
    html = data.get("html", "")
    url = data.get("url", "")
    if url:
        try:
            r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
            html = r.text
        except Exception as e:
            return jsonify({"error": str(e)}), 502
    if not html:
        return jsonify({"error": "html or url field required"}), 400
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return jsonify({"text": text, "word_count": len(text.split()), "char_count": len(text)})


@utility_bp.route("/data/extract/pdf", methods=["POST"])
def extract_pdf():
    """PDF to text extraction."""
    if "file" not in request.files:
        return jsonify({"error": "file upload required (multipart form)"}), 400
    file = request.files["file"]
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(file)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append({"page": i + 1, "text": text})
        full_text = "\n".join(p["text"] for p in pages)
        return jsonify({
            "pages": len(pages),
            "text": full_text,
            "page_texts": pages,
            "word_count": len(full_text.split()),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# FINANCE
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/finance/history", methods=["GET"])
def finance_history():
    """Historical OHLCV candles for a stock symbol."""
    symbol = request.args.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol parameter required"}), 400
    cache_key = f"finance_hist:{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        out = {"symbol": symbol, "period": "1mo", "candles": candles}
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/finance/forex", methods=["GET"])
def finance_forex():
    """150+ currency exchange rates."""
    base = request.args.get("base", "USD").strip().upper()
    cache_key = f"forex:{base}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        r = _requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10)
        data = r.json()
        out = {
            "base": base,
            "rates": data.get("rates", {}),
            "updated": data.get("time_last_update_utc", ""),
        }
        _cache_set(cache_key, out, ttl=3600)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/finance/convert", methods=["GET"])
def finance_convert():
    """Currency conversion."""
    amount = float(request.args.get("amount", 1))
    from_cur = request.args.get("from", "USD").strip().upper()
    to_cur = request.args.get("to", "EUR").strip().upper()
    try:
        r = _requests.get(f"https://open.er-api.com/v6/latest/{from_cur}", timeout=10)
        rates = r.json().get("rates", {})
        if to_cur not in rates:
            return jsonify({"error": f"Unknown currency: {to_cur}"}), 400
        result = round(amount * rates[to_cur], 4)
        return jsonify({
            "from": from_cur, "to": to_cur, "amount": amount,
            "result": result, "rate": rates[to_cur],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ─────────────────────────────────────────────────────────────────────────────
# NLP
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/entities", methods=["POST"])
def entity_extraction():
    """Named entity extraction (emails, URLs, dates, crypto addresses, phone numbers)."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text field required"}), 400
    entities = {
        "emails": re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text),
        "urls": re.findall(r'https?://[^\s<>"\']+', text),
        "ipv4": re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', text),
        "eth_addresses": re.findall(r'0x[a-fA-F0-9]{40}', text),
        "btc_addresses": re.findall(r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b', text),
        "phone_numbers": re.findall(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}', text),
        "dates": re.findall(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', text),
        "hashtags": re.findall(r'#\w+', text),
        "mentions": re.findall(r'@\w+', text),
    }
    total = sum(len(v) for v in entities.values())
    return jsonify({"total_entities": total, "entities": entities})


@utility_bp.route("/data/similarity", methods=["POST"])
def text_similarity():
    """Text similarity scoring (Jaccard + cosine-like)."""
    data = request.get_json(silent=True) or {}
    text1 = data.get("text1", "").strip()
    text2 = data.get("text2", "").strip()
    if not text1 or not text2:
        return jsonify({"error": "text1 and text2 fields required"}), 400
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    intersection = words1 & words2
    union = words1 | words2
    jaccard = len(intersection) / len(union) if union else 0
    all_words = list(union)
    vec1 = [1 if w in words1 else 0 for w in all_words]
    vec2 = [1 if w in words2 else 0 for w in all_words]
    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))
    cosine = dot / (mag1 * mag2) if mag1 and mag2 else 0
    return jsonify({
        "jaccard_similarity": round(jaccard, 4),
        "cosine_similarity": round(cosine, 4),
        "common_words": len(intersection),
        "unique_words_1": len(words1 - words2),
        "unique_words_2": len(words2 - words1),
    })


# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORM
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/transform/json-to-csv", methods=["POST"])
def json_to_csv():
    """JSON array to CSV conversion."""
    data = request.get_json(silent=True) or {}
    items = data.get("data", [])
    if not items or not isinstance(items, list):
        return jsonify({"error": "data field must be a JSON array"}), 400
    headers = list(items[0].keys()) if items else []
    lines = [",".join(headers)]
    for item in items:
        row = [str(item.get(h, "")).replace(",", ";").replace("\n", " ") for h in headers]
        lines.append(",".join(row))
    csv_text = "\n".join(lines)
    return jsonify({"csv": csv_text, "rows": len(items), "columns": len(headers)})


@utility_bp.route("/data/transform/xml", methods=["POST"])
def xml_to_json():
    """XML to JSON conversion."""
    data = request.get_json(silent=True) or {}
    xml_str = data.get("xml", "").strip()
    if not xml_str:
        return jsonify({"error": "xml field required"}), 400
    try:
        root = ElementTree.fromstring(xml_str)
        def elem_to_dict(elem):
            result = {}
            for child in elem:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if len(child):
                    result[tag] = elem_to_dict(child)
                else:
                    result[tag] = child.text
            if elem.attrib:
                result["@attributes"] = dict(elem.attrib)
            if not result and elem.text:
                return elem.text
            return result
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        return jsonify({"json": {tag: elem_to_dict(root)}})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@utility_bp.route("/data/transform/yaml", methods=["POST"])
def yaml_to_json():
    """YAML to JSON conversion."""
    data = request.get_json(silent=True) or {}
    yaml_str = data.get("yaml", "").strip()
    if not yaml_str:
        return jsonify({"error": "yaml field required"}), 400
    try:
        result = yaml.safe_load(yaml_str)
        return jsonify({"json": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# DATE & TIME
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/datetime/between", methods=["GET"])
def datetime_between():
    """Duration between two dates."""
    from_date = request.args.get("from", "").strip()
    to_date = request.args.get("to", "").strip()
    if not from_date or not to_date:
        return jsonify({"error": "from and to parameters required (YYYY-MM-DD)"}), 400
    try:
        d1 = datetime.strptime(from_date, "%Y-%m-%d")
        d2 = datetime.strptime(to_date, "%Y-%m-%d")
        delta = d2 - d1
        total_seconds = abs(delta.total_seconds())
        return jsonify({
            "from": from_date, "to": to_date,
            "days": abs(delta.days),
            "weeks": abs(delta.days) // 7,
            "months": abs(delta.days) // 30,
            "years": abs(delta.days) // 365,
            "hours": int(total_seconds // 3600),
            "minutes": int(total_seconds // 60),
            "seconds": int(total_seconds),
        })
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400


@utility_bp.route("/data/datetime/business-days", methods=["GET"])
def business_days():
    """Business days calculator."""
    from_date = request.args.get("from", "").strip()
    to_date = request.args.get("to", "").strip()
    if not from_date or not to_date:
        return jsonify({"error": "from and to parameters required (YYYY-MM-DD)"}), 400
    try:
        d1 = datetime.strptime(from_date, "%Y-%m-%d")
        d2 = datetime.strptime(to_date, "%Y-%m-%d")
        if d1 > d2:
            d1, d2 = d2, d1
        bdays = 0
        current = d1
        while current <= d2:
            if current.weekday() < 5:
                bdays += 1
            current += timedelta(days=1)
        return jsonify({
            "from": from_date, "to": to_date,
            "business_days": bdays,
            "calendar_days": (d2 - d1).days,
            "weekend_days": (d2 - d1).days - bdays + 1,
        })
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400


@utility_bp.route("/data/datetime/unix", methods=["GET"])
def unix_timestamp():
    """Unix timestamp converter."""
    ts = request.args.get("timestamp", "").strip()
    if ts:
        try:
            ts_float = float(ts)
            if ts_float > 1e12:
                ts_float /= 1000
            dt = datetime.utcfromtimestamp(ts_float)
            return jsonify({
                "timestamp": int(ts_float),
                "iso": dt.isoformat() + "Z",
                "human": dt.strftime("%B %d, %Y %H:%M:%S UTC"),
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M:%S"),
            })
        except Exception:
            return jsonify({"error": "Invalid timestamp"}), 400
    now = datetime.utcnow()
    return jsonify({
        "timestamp": int(now.timestamp()),
        "timestamp_ms": int(now.timestamp() * 1000),
        "iso": now.isoformat() + "Z",
        "human": now.strftime("%B %d, %Y %H:%M:%S UTC"),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/security/headers", methods=["GET"])
def security_headers_audit():
    """Security headers audit (A+ to F grade)."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"},
                          allow_redirects=True)
        headers = {k.lower(): v for k, v in r.headers.items()}
        checks = {
            "Strict-Transport-Security": "strict-transport-security" in headers,
            "Content-Security-Policy": "content-security-policy" in headers,
            "X-Content-Type-Options": headers.get("x-content-type-options", "").lower() == "nosniff",
            "X-Frame-Options": "x-frame-options" in headers,
            "X-XSS-Protection": "x-xss-protection" in headers,
            "Referrer-Policy": "referrer-policy" in headers,
            "Permissions-Policy": "permissions-policy" in headers,
        }
        score = sum(checks.values())
        grades = {7: "A+", 6: "A", 5: "B", 4: "C", 3: "D", 2: "E"}
        grade = grades.get(score, "F")
        return jsonify({
            "url": url,
            "grade": grade,
            "score": f"{score}/7",
            "checks": checks,
            "present_headers": {k: v for k, v in headers.items()
                               if k in [h.lower() for h in checks]},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/security/techstack", methods=["GET"])
def techstack_detect():
    """Technology stack detection from URL."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        r = _requests.get(url, timeout=10, headers={"User-Agent": "AiPayGen/1.0"})
        html = r.text[:100000]
        headers_dict = {k.lower(): v for k, v in r.headers.items()}
        detected = []
        patterns = {
            "React": [r'react', r'__react', r'_reactRoot'],
            "Vue.js": [r'vue\.', r'__vue__', r'v-cloak'],
            "Angular": [r'ng-version', r'angular'],
            "Next.js": [r'_next/', r'__NEXT_DATA__'],
            "Nuxt.js": [r'__nuxt', r'nuxt'],
            "Svelte": [r'svelte', r'__svelte'],
            "jQuery": [r'jquery', r'jQuery'],
            "WordPress": [r'wp-content', r'wp-includes'],
            "Shopify": [r'cdn\.shopify', r'Shopify\.'],
            "Wix": [r'wix\.com', r'X-Wix'],
            "Squarespace": [r'squarespace'],
            "Tailwind CSS": [r'tailwind'],
            "Bootstrap": [r'bootstrap'],
            "Font Awesome": [r'font-awesome|fontawesome'],
            "Google Analytics": [r'google-analytics|gtag|GA_MEASUREMENT'],
            "Google Tag Manager": [r'googletagmanager'],
            "Stripe": [r'stripe\.com/v|js\.stripe'],
            "Cloudflare": [r'cloudflare', r'cf-ray'],
            "Vercel": [r'vercel', r'x-vercel'],
            "Netlify": [r'netlify'],
            "AWS": [r'amazonaws'],
            "Nginx": [r'nginx'],
            "Apache": [r'apache'],
            "Node.js/Express": [r'x-powered-by.*express'],
            "PHP": [r'x-powered-by.*php'],
            "Python": [r'x-powered-by.*python|gunicorn|wsgi'],
        }
        search_text = html + "\n" + str(headers_dict)
        for tech, pats in patterns.items():
            for pat in pats:
                if re.search(pat, search_text, re.I):
                    detected.append(tech)
                    break
        return jsonify({
            "url": url,
            "technologies": detected,
            "server": headers_dict.get("server", "Unknown"),
            "powered_by": headers_dict.get("x-powered-by", "Unknown"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@utility_bp.route("/data/security/uptime", methods=["GET"])
def uptime_check():
    """URL uptime check with response time."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400
    try:
        start = time.time()
        r = _requests.get(url, timeout=15, headers={"User-Agent": "AiPayGen/1.0"},
                          allow_redirects=True)
        elapsed = round((time.time() - start) * 1000, 2)
        return jsonify({
            "url": url,
            "status": "up" if r.status_code < 500 else "down",
            "status_code": r.status_code,
            "response_time_ms": elapsed,
            "content_length": len(r.content),
            "ssl": url.startswith("https"),
        })
    except _requests.exceptions.Timeout:
        return jsonify({"url": url, "status": "timeout", "response_time_ms": 15000})
    except Exception as e:
        return jsonify({"url": url, "status": "down", "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# MATH — Safe AST-based expression evaluator (no eval)
# ─────────────────────────────────────────────────────────────────────────────

_SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}

_SAFE_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "abs": abs, "ceil": math.ceil, "floor": math.floor, "round": round,
}

_SAFE_CONSTS = {"pi": math.pi, "e": math.e}


def _safe_eval_node(node):
    """Recursively evaluate an AST node with only safe operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value}")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(_safe_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCS:
            args = [_safe_eval_node(a) for a in node.args]
            return _SAFE_FUNCS[node.func.id](*args)
        raise ValueError(f"Unsupported function: {ast.dump(node.func)}")
    if isinstance(node, ast.Name):
        if node.id in _SAFE_CONSTS:
            return _SAFE_CONSTS[node.id]
        raise ValueError(f"Unknown variable: {node.id}")
    raise ValueError(f"Unsupported expression: {type(node).__name__}")


@utility_bp.route("/data/math/eval", methods=["POST"])
def math_eval_endpoint():
    """Safe math expression evaluator using AST parsing."""
    data = request.get_json(silent=True) or {}
    expr = data.get("expression", "").strip()
    if not expr:
        return jsonify({"error": "expression field required"}), 400
    safe_expr = expr.replace("^", "**")
    try:
        tree = ast.parse(safe_expr, mode="eval")
        result = _safe_eval_node(tree)
        return jsonify({"expression": expr, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


_UNIT_CONVERSIONS = {
    "length": {
        "m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "mi": 1609.344,
        "yd": 0.9144, "ft": 0.3048, "in": 0.0254, "nm": 1852,
    },
    "weight": {
        "kg": 1, "g": 0.001, "mg": 0.000001, "lb": 0.453592,
        "oz": 0.0283495, "ton": 1000, "st": 6.35029,
    },
    "volume": {
        "l": 1, "ml": 0.001, "gal": 3.78541, "qt": 0.946353,
        "pt": 0.473176, "cup": 0.236588, "floz": 0.0295735,
    },
    "speed": {
        "m/s": 1, "km/h": 0.277778, "mph": 0.44704, "kn": 0.514444,
    },
    "data": {
        "b": 1, "kb": 1024, "mb": 1048576, "gb": 1073741824,
        "tb": 1099511627776,
    },
}

@utility_bp.route("/data/math/convert", methods=["GET"])
def unit_convert():
    """Unit converter (length, weight, volume, speed, data, temperature)."""
    value = float(request.args.get("value", 0))
    from_unit = request.args.get("from", "").strip().lower()
    to_unit = request.args.get("to", "").strip().lower()
    if not from_unit or not to_unit:
        return jsonify({"error": "from and to parameters required"}), 400
    if from_unit in ("c", "f", "k") and to_unit in ("c", "f", "k"):
        if from_unit == "c":
            celsius = value
        elif from_unit == "f":
            celsius = (value - 32) * 5 / 9
        else:
            celsius = value - 273.15
        if to_unit == "c":
            result = celsius
        elif to_unit == "f":
            result = celsius * 9 / 5 + 32
        else:
            result = celsius + 273.15
        return jsonify({"value": value, "from": from_unit, "to": to_unit,
                        "result": round(result, 4), "category": "temperature"})
    for category, units in _UNIT_CONVERSIONS.items():
        if from_unit in units and to_unit in units:
            base = value * units[from_unit]
            result = base / units[to_unit]
            return jsonify({"value": value, "from": from_unit, "to": to_unit,
                            "result": round(result, 6), "category": category})
    return jsonify({"error": f"Cannot convert {from_unit} to {to_unit}. "
                    "Supported: length, weight, volume, speed, data, temperature"}), 400


@utility_bp.route("/data/math/stats", methods=["POST"])
def math_stats():
    """Statistical analysis (mean, median, std dev, etc)."""
    data = request.get_json(silent=True) or {}
    numbers = data.get("numbers", [])
    if not numbers or not isinstance(numbers, list):
        return jsonify({"error": "numbers field must be a list of numbers"}), 400
    try:
        nums = [float(n) for n in numbers]
        result = {
            "count": len(nums),
            "sum": round(sum(nums), 6),
            "mean": round(statistics.mean(nums), 6),
            "median": round(statistics.median(nums), 6),
            "min": min(nums),
            "max": max(nums),
            "range": round(max(nums) - min(nums), 6),
        }
        if len(nums) >= 2:
            result["stdev"] = round(statistics.stdev(nums), 6)
            result["variance"] = round(statistics.variance(nums), 6)
        if len(nums) >= 3:
            try:
                result["mode"] = statistics.mode(nums)
            except statistics.StatisticsError:
                result["mode"] = None
        q = sorted(nums)
        mid = len(q) // 2
        result["q1"] = round(statistics.median(q[:mid]), 6) if len(q) > 1 else nums[0]
        result["q3"] = round(statistics.median(q[mid + (len(q) % 2):]), 6) if len(q) > 1 else nums[0]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# CRYPTO TRENDING
# ─────────────────────────────────────────────────────────────────────────────

@utility_bp.route("/data/crypto/trending", methods=["GET"])
def crypto_trending():
    """Trending tokens & DeFi data from CoinGecko."""
    cache_key = "crypto_trending"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        r = _requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
        data = r.json()
        coins = [{"name": c["item"]["name"], "symbol": c["item"]["symbol"],
                   "market_cap_rank": c["item"].get("market_cap_rank"),
                   "thumb": c["item"].get("thumb")}
                 for c in data.get("coins", [])[:10]]
        out = {"trending_coins": coins, "source": "coingecko"}
        _cache_set(cache_key, out, ttl=300)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
