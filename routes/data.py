"""Blueprint for all free data endpoints."""

import io
import base64
import colorsys
import hashlib as _hashlib
from datetime import datetime

from flask import Blueprint, request, jsonify
import requests as _requests
import qrcode
import feedparser
from youtube_transcript_api import YouTubeTranscriptApi

from helpers import cache_get as _cache_get, cache_set as _cache_set, get_client_ip as _get_client_ip

data_bp = Blueprint("data", __name__)


# ── Data: Wikipedia ───────────────────────────────────────────────────────────

@data_bp.route("/data/wikipedia", methods=["GET"])
def data_wikipedia():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q required (search term or article title)"}), 400
    ck = f"wiki:{_hashlib.md5(q.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        # Search for article
        search_resp = _requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + _requests.utils.quote(q),
            headers={"User-Agent": "AiPayGen/2.0 (https://api.aipaygen.com)"},
            timeout=8,
        )
        if search_resp.status_code == 404:
            # Try search API
            s = _requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": q, "limit": 1, "format": "json"},
                headers={"User-Agent": "AiPayGen/2.0"},
                timeout=8,
            ).json()
            if s[1]:
                title = s[1][0]
                search_resp = _requests.get(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/" + _requests.utils.quote(title),
                    headers={"User-Agent": "AiPayGen/2.0"},
                    timeout=8,
                )
            else:
                return jsonify({"error": "article not found", "query": q}), 404
        d = search_resp.json()
        result = {
            "title": d.get("title", ""),
            "summary": d.get("extract", ""),
            "url": d.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "thumbnail": d.get("thumbnail", {}).get("source", "") if d.get("thumbnail") else "",
            "description": d.get("description", ""),
            "query": q,
        }
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "wikipedia_failed", "message": str(e)}), 502


# ── Data: arXiv ───────────────────────────────────────────────────────────────

@data_bp.route("/data/arxiv", methods=["GET"])
def data_arxiv():
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 5)), 20)
    if not q:
        return jsonify({"error": "q required"}), 400
    ck = f"arxiv:{_hashlib.md5(f'{q}{limit}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{q}", "max_results": limit, "sortBy": "relevance"},
            timeout=12,
        )
        feed = feedparser.parse(resp.text)
        papers = []
        for entry in feed.entries[:limit]:
            papers.append({
                "title": entry.get("title", "").replace("\n", " "),
                "summary": (entry.get("summary", "")[:500] + "...").replace("\n", " "),
                "authors": [a.get("name", "") for a in entry.get("authors", [])],
                "published": entry.get("published", ""),
                "url": entry.get("link", ""),
                "arxiv_id": entry.get("id", "").split("/abs/")[-1],
            })
        result = {"query": q, "papers": papers, "count": len(papers)}
        _cache_set(ck, result, 1800)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "arxiv_failed", "message": str(e)}), 502


# ── Data: GitHub Trending ─────────────────────────────────────────────────────

@data_bp.route("/data/github/trending", methods=["GET"])
def data_github_trending():
    lang = request.args.get("lang", "").lower()
    since = request.args.get("since", "daily")
    ck = f"gh_trend:{lang}:{since}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        url = "https://github.com/trending"
        if lang:
            url += f"/{lang}"
        resp = _requests.get(url, params={"since": since},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []
        for article in soup.select("article.Box-row")[:25]:
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            desc_el = article.select_one("p")
            stars_el = article.select_one("a[href*='/stargazers']")
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            repos.append({
                "repo": h2.get("href", "").lstrip("/"),
                "url": "https://github.com" + h2.get("href", ""),
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "stars": stars_el.get_text(strip=True) if stars_el else "",
                "language": lang_el.get_text(strip=True) if lang_el else "",
            })
        result = {"language": lang or "all", "since": since, "repos": repos, "count": len(repos)}
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "github_trending_failed", "message": str(e)}), 502


# ── Data: Reddit ──────────────────────────────────────────────────────────────

@data_bp.route("/data/reddit", methods=["GET"])
def data_reddit():
    q = request.args.get("q", "").strip()
    sub = request.args.get("sub", "")
    sort = request.args.get("sort", "hot")
    limit = min(int(request.args.get("limit", 10)), 25)
    if not q and not sub:
        return jsonify({"error": "q (search query) or sub (subreddit) required"}), 400
    ck = f"reddit:{_hashlib.md5(f'{q}{sub}{sort}{limit}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        if q:
            url = f"https://www.reddit.com/search.json"
            params = {"q": q, "sort": sort, "limit": limit}
            if sub:
                params["restrict_sr"] = "true"
                url = f"https://www.reddit.com/r/{sub}/search.json"
        else:
            url = f"https://www.reddit.com/r/{sub}/{sort}.json"
            params = {"limit": limit}
        resp = _requests.get(url, params=params,
                             headers={"User-Agent": "AiPayGen/2.0 bot"}, timeout=10)
        data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", [])[:limit]:
            p = child.get("data", {})
            posts.append({
                "title": p.get("title", ""),
                "subreddit": p.get("subreddit", ""),
                "url": "https://reddit.com" + p.get("permalink", ""),
                "external_url": p.get("url", ""),
                "score": p.get("score", 0),
                "comments": p.get("num_comments", 0),
                "author": p.get("author", ""),
                "created": p.get("created_utc", 0),
            })
        result = {"query": q, "subreddit": sub, "posts": posts, "count": len(posts)}
        _cache_set(ck, result, 600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "reddit_failed", "message": str(e)}), 502


# ── Data: YouTube Transcript ──────────────────────────────────────────────────

@data_bp.route("/data/youtube/transcript", methods=["GET"])
def data_youtube_transcript():
    video_id = request.args.get("video_id", "").strip()
    lang = request.args.get("lang", "en")
    if not video_id:
        return jsonify({"error": "video_id required (e.g. dQw4w9WgXcQ)"}), 400
    ck = f"yt_transcript:{video_id}:{lang}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang, "en"])
        full_text = " ".join(t["text"] for t in transcript_list)
        result = {
            "video_id": video_id,
            "language": lang,
            "transcript": transcript_list[:200],  # first 200 segments
            "full_text": full_text[:10000],
            "word_count": len(full_text.split()),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
        _cache_set(ck, result, 86400)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "transcript_failed", "message": str(e),
                       "hint": "Video may have no captions or be age-restricted"}), 502


# ── Data: QR Code ─────────────────────────────────────────────────────────────

@data_bp.route("/data/qr", methods=["GET"])
def data_qr():
    text = request.args.get("text", "").strip()
    size = min(int(request.args.get("size", 200)), 600)
    if not text:
        return jsonify({"error": "text required"}), 400
    ck = f"qr:{_hashlib.md5(f'{text}{size}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        qr = qrcode.QRCode(box_size=max(1, size // 33), border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result = {
            "text": text,
            "size": size,
            "format": "PNG",
            "base64": b64,
            "data_url": f"data:image/png;base64,{b64}",
        }
        _cache_set(ck, result, 86400)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "qr_failed", "message": str(e)}), 500


# ── Data: DNS Lookup ──────────────────────────────────────────────────────────

@data_bp.route("/data/dns", methods=["GET"])
def data_dns():
    domain = request.args.get("domain", "").strip().rstrip("/")
    if not domain:
        return jsonify({"error": "domain required"}), 400
    ck = f"dns:{domain}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        import socket as _sock
        records = {}
        # A / IPv4
        try:
            ipv4 = [r[4][0] for r in _sock.getaddrinfo(domain, None, _sock.AF_INET)]
            records["A"] = list(set(ipv4))
        except Exception:
            records["A"] = []
        # AAAA / IPv6
        try:
            ipv6 = [r[4][0] for r in _sock.getaddrinfo(domain, None, _sock.AF_INET6)]
            records["AAAA"] = list(set(ipv6))
        except Exception:
            records["AAAA"] = []
        # Reverse lookup for first A record
        reverse = ""
        if records["A"]:
            try:
                reverse = _sock.gethostbyaddr(records["A"][0])[0]
            except Exception:
                pass
        result = {
            "domain": domain,
            "records": records,
            "reverse_hostname": reverse,
        }
        _cache_set(ck, result, 300)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "dns_failed", "message": str(e)}), 502


# ── Data: Validate Email ──────────────────────────────────────────────────────

@data_bp.route("/data/validate/email", methods=["GET"])
def data_validate_email():
    email = request.args.get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    import re as _email_re
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    fmt_valid = bool(_email_re.match(pattern, email))
    domain = email.split("@")[-1] if "@" in email else ""
    mx_valid = False
    if fmt_valid and domain:
        try:
            import socket as _s
            _s.getaddrinfo(domain, None)
            mx_valid = True
        except Exception:
            pass
    disposable_domains = {"mailinator.com", "guerrillamail.com", "tempmail.com",
                          "throwaway.email", "yopmail.com", "trashmail.com"}
    result = {
        "email": email,
        "format_valid": fmt_valid,
        "domain_reachable": mx_valid,
        "possibly_disposable": domain in disposable_domains,
        "domain": domain,
    }
    return jsonify(result)


# ── Data: Validate URL ───────────────────────────────────────────────────────

@data_bp.route("/data/validate/url", methods=["GET"])
def data_validate_url():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # SSRF protection
    from security import validate_url, SSRFError
    try:
        validate_url(url, allow_http=True)
    except SSRFError as e:
        return jsonify({"error": f"Blocked: {e}", "url": url, "reachable": False}), 403
    try:
        resp = _requests.head(url, timeout=8, allow_redirects=True,
                              headers={"User-Agent": "AiPayGen/2.0"})
        result = {
            "url": url,
            "reachable": True,
            "status_code": resp.status_code,
            "final_url": resp.url,
            "redirected": resp.url != url,
            "content_type": resp.headers.get("Content-Type", ""),
        }
    except Exception as e:
        result = {"url": url, "reachable": False, "error": str(e)}
    return jsonify(result)


# ── Data: Random Name ────────────────────────────────────────────────────────

@data_bp.route("/data/random/name", methods=["GET"])
def data_random_name():
    count = min(int(request.args.get("count", 1)), 20)
    nat = request.args.get("nationality", "us")
    try:
        resp = _requests.get(
            "https://randomuser.me/api/",
            params={"results": count, "nat": nat, "inc": "name,email,location,phone"},
            timeout=8,
        )
        people = []
        for u in resp.json().get("results", []):
            n = u.get("name", {})
            loc = u.get("location", {})
            people.append({
                "name": f"{n.get('first', '')} {n.get('last', '')}".strip(),
                "email": u.get("email", ""),
                "phone": u.get("phone", ""),
                "city": loc.get("city", ""),
                "country": loc.get("country", ""),
            })
        return jsonify({"people": people, "count": len(people)})
    except Exception as e:
        return jsonify({"error": "random_name_failed", "message": str(e)}), 502


# ── Data: Color Info ─────────────────────────────────────────────────────────

@data_bp.route("/data/color", methods=["GET"])
def data_color():
    hex_str = request.args.get("hex", "").lstrip("#").strip()
    if not hex_str or len(hex_str) not in (3, 6):
        return jsonify({"error": "hex required (e.g. ?hex=ff5733 or ?hex=f53)"}), 400
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    try:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        comp_h = (h + 0.5) % 1.0
        cr, cg, cb = colorsys.hls_to_rgb(comp_h, l, s)
        comp_hex = "{:02x}{:02x}{:02x}".format(int(cr * 255), int(cg * 255), int(cb * 255))
        # Brightness
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        result = {
            "hex": f"#{hex_str.upper()}",
            "rgb": {"r": r, "g": g, "b": b},
            "hsl": {"h": round(h * 360), "s": round(s * 100), "l": round(l * 100)},
            "complementary": f"#{comp_hex.upper()}",
            "brightness": round(brightness),
            "is_dark": brightness < 128,
            "css": f"rgb({r}, {g}, {b})",
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "color_failed", "message": str(e)}), 400


# ── Data: Screenshot ─────────────────────────────────────────────────────────

@data_bp.route("/data/screenshot", methods=["GET"])
def data_screenshot():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ck = f"screenshot:{_hashlib.md5(url.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        # Use thum.io free screenshot API (no key needed)
        screenshot_url = f"https://image.thum.io/get/width/1280/crop/800/{url}"
        result = {
            "url": url,
            "screenshot_url": screenshot_url,
            "note": "Visit screenshot_url directly to render. Cached 24h by thum.io.",
        }
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "screenshot_failed", "message": str(e)}), 502


# ── Free: Time ────────────────────────────────────────────────────────────────

@data_bp.route("/free/time", methods=["GET"])
def free_time():
    """Free endpoint: current UTC time + timezone conversions. No payment needed."""
    from datetime import timezone
    now_utc = datetime.utcnow()
    return jsonify({
        "utc": now_utc.isoformat() + "Z",
        "unix": int(now_utc.replace(tzinfo=timezone.utc).timestamp()),
        "date": now_utc.strftime("%Y-%m-%d"),
        "time": now_utc.strftime("%H:%M:%S"),
        "day_of_week": now_utc.strftime("%A"),
        "week_number": int(now_utc.strftime("%W")),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── Free: UUID ────────────────────────────────────────────────────────────────

@data_bp.route("/free/uuid", methods=["GET"])
def free_uuid():
    """Free endpoint: generate UUIDs. No payment needed."""
    import uuid
    return jsonify({
        "uuid4": str(uuid.uuid4()),
        "uuid4_list": [str(uuid.uuid4()) for _ in range(5)],
        "uuid1": str(uuid.uuid1()),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── Free: IP ──────────────────────────────────────────────────────────────────

@data_bp.route("/free/ip", methods=["GET"])
def free_ip():
    """Free endpoint: caller's IP info. No payment needed."""
    ip = _get_client_ip()
    return jsonify({
        "ip": ip,
        "user_agent": request.headers.get("User-Agent"),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── Free: Hash ────────────────────────────────────────────────────────────────

@data_bp.route("/free/hash", methods=["GET", "POST"])
def free_hash():
    """Free endpoint: hash a string. No payment needed."""
    import hashlib
    text = ""
    if request.method == "POST":
        data = request.get_json() or {}
        text = data.get("text", "")
    else:
        text = request.args.get("text", "hello world")
    text_bytes = text.encode("utf-8")
    return jsonify({
        "input": text,
        "md5": hashlib.md5(text_bytes).hexdigest(),
        "sha1": hashlib.sha1(text_bytes).hexdigest(),
        "sha256": hashlib.sha256(text_bytes).hexdigest(),
        "sha512": hashlib.sha512(text_bytes).hexdigest(),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── Free: Base64 ──────────────────────────────────────────────────────────────

@data_bp.route("/free/base64", methods=["GET", "POST"])
def free_base64():
    """Free endpoint: encode/decode base64. No payment needed."""
    import base64 as _b64
    data = request.get_json() or {} if request.method == "POST" else {}
    text = data.get("text") or request.args.get("text", "")
    decode_text = data.get("decode") or request.args.get("decode", "")
    result = {}
    if text:
        result["encoded"] = _b64.b64encode(text.encode()).decode()
    if decode_text:
        try:
            result["decoded"] = _b64.b64decode(decode_text).decode()
        except Exception:
            result["decode_error"] = "invalid base64"
    result["_meta"] = {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    return jsonify(result)


# ── Free: Random ──────────────────────────────────────────────────────────────

@data_bp.route("/free/random", methods=["GET"])
def free_random():
    """Free endpoint: random numbers, choices, and samples."""
    import random
    import string
    n = min(int(request.args.get("n", 5)), 100)
    min_val = int(request.args.get("min", 1))
    max_val = int(request.args.get("max", 100))
    return jsonify({
        "integers": [random.randint(min_val, max_val) for _ in range(n)],
        "float": random.random(),
        "bool": random.choice([True, False]),
        "shuffle_example": random.sample(list(range(1, 11)), 10),
        "random_string": "".join(random.choices(string.ascii_letters + string.digits, k=16)),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── Data: Weather ─────────────────────────────────────────────────────────────

@data_bp.route("/data/weather", methods=["GET"])
def data_weather():
    city = request.args.get("city", "London")
    ck = f"weather:{city.lower()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        geo = _requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=8,
        ).json()
        results = geo.get("results", [])
        if not results:
            return jsonify({"error": "city_not_found", "city": city}), 404
        loc = results[0]
        weather = _requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current_weather": "true",
                "hourly": "temperature_2m,precipitation_probability",
                "forecast_days": 1,
            },
            timeout=8,
        ).json()
        cw = weather.get("current_weather", {})
        result = {
            "city": loc.get("name"),
            "country": loc.get("country"),
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "temperature_c": cw.get("temperature"),
            "windspeed_kmh": cw.get("windspeed"),
            "weather_code": cw.get("weathercode"),
            "is_day": cw.get("is_day"),
            "time": cw.get("time"),
            "_meta": {"free": True, "source": "open-meteo.com"},
        }
        _cache_set(ck, result, 600)  # 10 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "weather_fetch_failed", "message": str(e)}), 502


# ── Data: Crypto ──────────────────────────────────────────────────────────────

@data_bp.route("/data/crypto", methods=["GET"])
def data_crypto():
    symbol = request.args.get("symbol", "bitcoin,ethereum")
    ck = f"crypto:{symbol}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": symbol,
                "vs_currencies": "usd,eur,gbp",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            },
            timeout=8,
        )
        data = resp.json()
        result = {"prices": data, "symbols": symbol.split(","), "_meta": {"free": True, "source": "coingecko.com"}}
        _cache_set(ck, result, 120)  # 2 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "crypto_fetch_failed", "message": str(e)}), 502


# ── Data: Exchange Rates ──────────────────────────────────────────────────────

@data_bp.route("/data/exchange-rates", methods=["GET"])
def data_exchange_rates():
    base = request.args.get("base", "USD").upper()
    ck = f"fx:{base}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{base}",
            timeout=8,
        )
        data = resp.json()
        result = {
            "base": base,
            "date": data.get("date"),
            "rates": data.get("rates", {}),
            "_meta": {"free": True, "source": "exchangerate-api.com"},
        }
        _cache_set(ck, result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "exchange_rate_fetch_failed", "message": str(e)}), 502


# ── Data: Country ─────────────────────────────────────────────────────────────

@data_bp.route("/data/country", methods=["GET"])
def data_country():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "name required (e.g. ?name=France)"}), 400
    ck = f"country:{name.lower()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://restcountries.com/v3.1/name/{name}",
            params={"fields": "name,capital,currencies,languages,population,flags,region,subregion"},
            timeout=8,
        )
        if resp.status_code == 404:
            return jsonify({"error": "country_not_found", "name": name}), 404
        countries = resp.json()
        result = {"results": countries, "count": len(countries), "_meta": {"free": True, "source": "restcountries.com"}}
        _cache_set(ck, result, 86400)  # 24 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "country_fetch_failed", "message": str(e)}), 502


# ── Data: IP Lookup ───────────────────────────────────────────────────────────

@data_bp.route("/data/ip", methods=["GET"])
def data_ip():
    ip = request.args.get("ip", "")
    target = ip if ip else request.remote_addr
    try:
        resp = _requests.get(f"http://ip-api.com/json/{target}", params={"fields": "status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"}, timeout=8)
        data = resp.json()
        data["_meta"] = {"free": True, "source": "ip-api.com"}
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "ip_fetch_failed", "message": str(e)}), 502


# ── Data: News (Hacker News) ─────────────────────────────────────────────────

@data_bp.route("/data/news", methods=["GET"])
def data_news():
    cached = _cache_get("hn_news")
    if cached:
        return jsonify(cached)
    try:
        top_ids = _requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=8,
        ).json()[:10]
        stories = []
        for sid in top_ids:
            item = _requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=5,
            ).json()
            if item:
                stories.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "score": item.get("score"),
                    "by": item.get("by"),
                    "comments": item.get("descendants", 0),
                })
        result = {"stories": stories, "count": len(stories), "_meta": {"free": True, "source": "hacker-news.firebaseio.com"}}
        _cache_set("hn_news", result, 900)  # 15 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "news_fetch_failed", "message": str(e)}), 502


# ── Data: Stocks ──────────────────────────────────────────────────────────────

@data_bp.route("/data/stocks", methods=["GET"])
def data_stocks():
    symbol = request.args.get("symbol", "AAPL").upper()
    ck = f"stock:{symbol}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return jsonify({"error": "symbol_not_found", "symbol": symbol}), 404
        meta = result[0].get("meta", {})
        stock_result = {
            "symbol": symbol,
            "currency": meta.get("currency"),
            "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("previousClose"),
            "market_state": meta.get("marketState"),
            "exchange": meta.get("exchangeName"),
            "_meta": {"free": True, "source": "yahoo finance"},
        }
        _cache_set(ck, stock_result, 300)  # 5 min
        return jsonify(stock_result)
    except Exception as e:
        return jsonify({"error": "stock_fetch_failed", "message": str(e)}), 502


# ── Data: Joke ────────────────────────────────────────────────────────────────

@data_bp.route("/data/joke", methods=["GET"])
def data_joke():
    cached = _cache_get("joke")
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "https://official-joke-api.appspot.com/random_joke",
            timeout=5,
        )
        d = resp.json()
        result = {
            "setup": d.get("setup"),
            "punchline": d.get("punchline"),
            "type": d.get("type"),
            "_meta": {"free": True, "source": "official-joke-api.appspot.com"},
        }
        _cache_set("joke", result, 3600)  # 1 hr
        return jsonify(result)
    except Exception:
        return jsonify({
            "setup": "Why don't scientists trust atoms?",
            "punchline": "Because they make up everything.",
            "type": "general",
            "_meta": {"free": True, "source": "fallback"},
        })


# ── Data: Quote ───────────────────────────────────────────────────────────────

@data_bp.route("/data/quote", methods=["GET"])
def data_quote():
    category = request.args.get("category", "")
    cached = _cache_get("quote")
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get("https://zenquotes.io/api/random", timeout=5)
        d = resp.json()[0] if resp.ok else {}
        result = {
            "quote": d.get("q"),
            "author": d.get("a"),
            "tags": [category] if category else [],
            "_meta": {"free": True, "source": "zenquotes.io"},
        }
        _cache_set("quote", result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "quote_fetch_failed", "message": str(e)}), 502


# ── Data: Timezone ────────────────────────────────────────────────────────────

@data_bp.route("/data/timezone", methods=["GET"])
def data_timezone():
    tz = request.args.get("tz", "America/New_York")
    ck = f"tz:{tz}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://worldtimeapi.org/api/timezone/{tz}",
            timeout=5,
        )
        d = resp.json()
        result = {
            "timezone": tz,
            "datetime": d.get("datetime"),
            "utc_offset": d.get("utc_offset"),
            "day_of_week": d.get("day_of_week"),
            "week_number": d.get("week_number"),
            "_meta": {"free": True, "source": "worldtimeapi.org"},
        }
        _cache_set(ck, result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "timezone_fetch_failed", "message": str(e)}), 502


# ── Data: Holidays ────────────────────────────────────────────────────────────

@data_bp.route("/data/holidays", methods=["GET"])
def data_holidays():
    country = request.args.get("country", "US").upper()
    year = request.args.get("year", str(datetime.utcnow().year))
    ck = f"holidays:{country}:{year}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}",
            timeout=6,
        )
        holidays = resp.json()
        if isinstance(holidays, list):
            result = {
                "country": country,
                "year": year,
                "holidays": holidays[:20],
                "count": len(holidays),
                "_meta": {"free": True, "source": "date.nager.at"},
            }
            _cache_set(ck, result, 86400)  # 24 hr
            return jsonify(result)
        return jsonify({"error": "no_data", "country": country, "year": year}), 404
    except Exception as e:
        return jsonify({"error": "holidays_fetch_failed", "message": str(e)}), 502
