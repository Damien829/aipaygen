"""Comprehensive tests for routes/data.py — all 29 data endpoints."""
import sys, os, json, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

# Clear TTL cache between tests to avoid interference
import helpers as _helpers


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clear_cache():
    _helpers._ttl_cache.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_response(json_data=None, status_code=200, text="", headers=None, url="https://example.com", ok=True):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = ok
    resp.url = url
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    resp.headers = headers or {"Content-Type": "application/json"}
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# 1. /data/wikipedia
# ═══════════════════════════════════════════════════════════════════════════

class TestWikipedia:
    def test_missing_q(self, client):
        r = client.get("/data/wikipedia")
        assert r.status_code == 400
        assert "q required" in r.get_json()["error"]

    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "title": "Python",
            "extract": "A programming language",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}},
            "thumbnail": {"source": "https://img.png"},
            "description": "Programming language",
        })
        r = client.get("/data/wikipedia?q=Python")
        assert r.status_code == 200
        d = r.get_json()
        assert d["title"] == "Python"
        assert d["summary"] == "A programming language"

    @patch("routes.data._requests.get")
    def test_404_fallback_search(self, mock_get, client):
        resp_404 = _mock_response(status_code=404, json_data={})
        resp_search = _mock_response(json_data=[None, ["Python (programming language)"], [], []])
        resp_summary = _mock_response(json_data={
            "title": "Python (programming language)",
            "extract": "Found via search",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python_(programming_language)"}},
            "description": "Language",
        })
        mock_get.side_effect = [resp_404, resp_search, resp_summary]
        r = client.get("/data/wikipedia?q=pythonn")
        assert r.status_code == 200
        assert r.get_json()["title"] == "Python (programming language)"

    @patch("routes.data._requests.get")
    def test_404_not_found(self, mock_get, client):
        resp_404 = _mock_response(status_code=404, json_data={})
        resp_search = _mock_response(json_data=[None, [], [], []])
        mock_get.side_effect = [resp_404, resp_search]
        r = client.get("/data/wikipedia?q=xyznonexistent")
        assert r.status_code == 404
        assert "article not found" in r.get_json()["error"]

    @patch("routes.data._requests.get", side_effect=Exception("timeout"))
    def test_error(self, mock_get, client):
        r = client.get("/data/wikipedia?q=test")
        assert r.status_code == 502
        assert "wikipedia_failed" in r.get_json()["error"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. /data/arxiv
# ═══════════════════════════════════════════════════════════════════════════

class TestArxiv:
    def test_missing_q(self, client):
        r = client.get("/data/arxiv")
        assert r.status_code == 400

    @patch("routes.data._requests.get")
    @patch("routes.data.feedparser.parse")
    def test_success(self, mock_parse, mock_get, client):
        mock_get.return_value = _mock_response(text="<xml/>")
        mock_entry = MagicMock()
        mock_entry.get = lambda k, d="": {
            "title": "Deep Learning\nPaper",
            "summary": "A great paper about AI" * 20,
            "authors": [{"name": "Alice"}],
            "published": "2026-01-01",
            "link": "https://arxiv.org/abs/2601.00001",
            "id": "http://arxiv.org/abs/2601.00001",
        }.get(k, d)
        mock_feed = MagicMock()
        mock_feed.entries = [mock_entry]
        mock_parse.return_value = mock_feed
        r = client.get("/data/arxiv?q=deep+learning&limit=1")
        assert r.status_code == 200
        d = r.get_json()
        assert d["count"] == 1
        assert d["papers"][0]["title"] == "Deep Learning Paper"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/arxiv?q=test")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 3. /data/github/trending
# ═══════════════════════════════════════════════════════════════════════════

class TestGithubTrending:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        html = '''<article class="Box-row">
            <h2><a href="/user/repo">repo</a></h2>
            <p>Description</p>
            <a href="/user/repo/stargazers">1234</a>
            <span itemprop="programmingLanguage">Python</span>
        </article>'''
        mock_get.return_value = _mock_response(text=html)
        r = client.get("/data/github/trending?lang=python&since=weekly")
        assert r.status_code == 200
        d = r.get_json()
        assert d["language"] == "python"
        assert d["since"] == "weekly"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/github/trending")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 4. /data/reddit
# ═══════════════════════════════════════════════════════════════════════════

class TestReddit:
    def test_missing_params(self, client):
        r = client.get("/data/reddit")
        assert r.status_code == 400

    @patch("routes.data._requests.get")
    def test_search_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "data": {"children": [{"data": {
                "title": "Test Post",
                "subreddit": "python",
                "permalink": "/r/python/test",
                "url": "https://example.com",
                "score": 100,
                "num_comments": 10,
                "author": "user1",
                "created_utc": 1700000000,
            }}]}
        })
        r = client.get("/data/reddit?q=python")
        assert r.status_code == 200
        d = r.get_json()
        assert d["count"] == 1
        assert d["posts"][0]["title"] == "Test Post"

    @patch("routes.data._requests.get")
    def test_sub_only(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "data": {"children": []}
        })
        r = client.get("/data/reddit?sub=python&sort=new")
        assert r.status_code == 200

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/reddit?q=test")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 5. /data/youtube/transcript
# ═══════════════════════════════════════════════════════════════════════════

class TestYoutubeTranscript:
    def test_missing_video_id(self, client):
        r = client.get("/data/youtube/transcript")
        assert r.status_code == 400

    @patch("routes.data.YouTubeTranscriptApi.get_transcript")
    def test_success(self, mock_yt, client):
        mock_yt.return_value = [
            {"text": "Hello", "start": 0, "duration": 1},
            {"text": "World", "start": 1, "duration": 1},
        ]
        r = client.get("/data/youtube/transcript?video_id=abc123")
        assert r.status_code == 200
        d = r.get_json()
        assert d["video_id"] == "abc123"
        assert "Hello World" in d["full_text"]
        assert d["word_count"] == 2

    @patch("routes.data.YouTubeTranscriptApi.get_transcript", side_effect=Exception("no captions"))
    def test_error(self, mock_yt, client):
        r = client.get("/data/youtube/transcript?video_id=bad")
        assert r.status_code == 502
        assert "hint" in r.get_json()


# ═══════════════════════════════════════════════════════════════════════════
# 6. /data/qr
# ═══════════════════════════════════════════════════════════════════════════

class TestQR:
    def test_missing_text(self, client):
        r = client.get("/data/qr")
        assert r.status_code == 400

    def test_success(self, client):
        r = client.get("/data/qr?text=hello&size=100")
        assert r.status_code == 200
        d = r.get_json()
        assert d["text"] == "hello"
        assert d["format"] == "PNG"
        assert d["base64"]  # non-empty
        assert d["data_url"].startswith("data:image/png;base64,")


# ═══════════════════════════════════════════════════════════════════════════
# 7. /data/dns
# ═══════════════════════════════════════════════════════════════════════════

class TestDNS:
    def test_missing_domain(self, client):
        r = client.get("/data/dns")
        assert r.status_code == 400

    @patch("socket.getaddrinfo")
    def test_success(self, mock_dns, client):
        mock_dns.return_value = [(2, 1, 6, '', ('1.2.3.4', 0))]
        r = client.get("/data/dns?domain=example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert d["domain"] == "example.com"
        assert "records" in d


# ═══════════════════════════════════════════════════════════════════════════
# 8. /data/validate/email
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateEmail:
    def test_missing_email(self, client):
        r = client.get("/data/validate/email")
        assert r.status_code == 400

    def test_valid_format(self, client):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, '', ('1.2.3.4', 0))]):
            r = client.get("/data/validate/email?email=test@example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert d["format_valid"] is True
        assert d["domain"] == "example.com"

    def test_invalid_format(self, client):
        r = client.get("/data/validate/email?email=notanemail")
        assert r.status_code == 200
        d = r.get_json()
        assert d["format_valid"] is False

    def test_disposable(self, client):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, '', ('1.2.3.4', 0))]):
            r = client.get("/data/validate/email?email=test@mailinator.com")
        assert r.status_code == 200
        assert r.get_json()["possibly_disposable"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 9. /data/validate/url
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateUrl:
    def test_missing_url(self, client):
        r = client.get("/data/validate/url")
        assert r.status_code == 400

    @patch("routes.data._requests.head")
    @patch("security.validate_url", return_value="https://example.com")
    def test_reachable(self, mock_val, mock_head, client):
        mock_head.return_value = _mock_response(url="https://example.com")
        r = client.get("/data/validate/url?url=https://example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert d["reachable"] is True

    @patch("routes.data._requests.head", side_effect=Exception("timeout"))
    @patch("security.validate_url", return_value="https://example.com")
    def test_unreachable(self, mock_val, mock_head, client):
        r = client.get("/data/validate/url?url=https://example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert d["reachable"] is False

    def test_ssrf_blocked(self, client):
        from security import SSRFError
        with patch("security.validate_url", side_effect=SSRFError("private IP")):
            r = client.get("/data/validate/url?url=http://127.0.0.1")
        assert r.status_code == 403

    @patch("routes.data._requests.head")
    @patch("security.validate_url", return_value="https://example.com")
    def test_auto_prefix_https(self, mock_val, mock_head, client):
        mock_head.return_value = _mock_response(url="https://example.com")
        r = client.get("/data/validate/url?url=example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert d["url"] == "https://example.com"


# ═══════════════════════════════════════════════════════════════════════════
# 10. /data/random/name
# ═══════════════════════════════════════════════════════════════════════════

class TestRandomName:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "results": [{
                "name": {"first": "John", "last": "Doe"},
                "email": "john@example.com",
                "phone": "555-1234",
                "location": {"city": "Austin", "country": "US"},
            }]
        })
        r = client.get("/data/random/name?count=1")
        assert r.status_code == 200
        d = r.get_json()
        assert d["count"] == 1
        assert d["people"][0]["name"] == "John Doe"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/random/name")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 11. /data/color
# ═══════════════════════════════════════════════════════════════════════════

class TestColor:
    def test_missing_hex(self, client):
        r = client.get("/data/color")
        assert r.status_code == 400

    def test_invalid_hex_length(self, client):
        r = client.get("/data/color?hex=12")
        assert r.status_code == 400

    def test_6_digit_hex(self, client):
        r = client.get("/data/color?hex=ff5733")
        assert r.status_code == 200
        d = r.get_json()
        assert d["hex"] == "#FF5733"
        assert d["rgb"]["r"] == 255
        assert d["rgb"]["g"] == 87
        assert d["rgb"]["b"] == 51
        assert "complementary" in d
        assert "is_dark" in d

    def test_3_digit_hex(self, client):
        r = client.get("/data/color?hex=f00")
        assert r.status_code == 200
        d = r.get_json()
        assert d["rgb"]["r"] == 255
        assert d["rgb"]["g"] == 0
        assert d["rgb"]["b"] == 0

    def test_with_hash_prefix(self, client):
        r = client.get("/data/color?hex=%23ff5733")
        assert r.status_code == 200
        assert r.get_json()["hex"] == "#FF5733"


# ═══════════════════════════════════════════════════════════════════════════
# 12. /data/screenshot
# ═══════════════════════════════════════════════════════════════════════════

class TestScreenshot:
    def test_missing_url(self, client):
        r = client.get("/data/screenshot")
        assert r.status_code == 400

    def test_success(self, client):
        r = client.get("/data/screenshot?url=https://example.com")
        assert r.status_code == 200
        d = r.get_json()
        assert "screenshot_url" in d
        assert "thum.io" in d["screenshot_url"]

    def test_auto_prefix_https(self, client):
        r = client.get("/data/screenshot?url=example.com")
        assert r.status_code == 200
        assert r.get_json()["url"] == "https://example.com"


# ═══════════════════════════════════════════════════════════════════════════
# 13. /free/time
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeTime:
    def test_success(self, client):
        r = client.get("/free/time")
        assert r.status_code == 200
        d = r.get_json()
        assert "utc" in d
        assert "unix" in d
        assert "date" in d
        assert "day_of_week" in d
        assert d["_meta"]["free"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 14. /free/uuid
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeUuid:
    def test_success(self, client):
        r = client.get("/free/uuid")
        assert r.status_code == 200
        d = r.get_json()
        assert "uuid4" in d
        assert len(d["uuid4_list"]) == 5
        assert "uuid1" in d


# ═══════════════════════════════════════════════════════════════════════════
# 15. /free/ip
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeIp:
    def test_success(self, client):
        r = client.get("/free/ip")
        assert r.status_code == 200
        d = r.get_json()
        assert "ip" in d
        assert "user_agent" in d


# ═══════════════════════════════════════════════════════════════════════════
# 16. /free/hash
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeHash:
    def test_get(self, client):
        r = client.get("/free/hash?text=hello")
        assert r.status_code == 200
        d = r.get_json()
        assert d["input"] == "hello"
        assert d["md5"] == hashlib.md5(b"hello").hexdigest()
        assert d["sha256"] == hashlib.sha256(b"hello").hexdigest()

    def test_post(self, client):
        r = client.post("/free/hash", json={"text": "world"})
        assert r.status_code == 200
        assert r.get_json()["input"] == "world"

    def test_default(self, client):
        r = client.get("/free/hash")
        assert r.status_code == 200
        assert r.get_json()["input"] == "hello world"


# ═══════════════════════════════════════════════════════════════════════════
# 17. /free/base64
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeBase64:
    def test_encode_get(self, client):
        r = client.get("/free/base64?text=hello")
        assert r.status_code == 200
        d = r.get_json()
        assert d["encoded"] == "aGVsbG8="

    def test_decode_get(self, client):
        r = client.get("/free/base64?decode=aGVsbG8=")
        assert r.status_code == 200
        assert r.get_json()["decoded"] == "hello"

    def test_encode_post(self, client):
        r = client.post("/free/base64", json={"text": "test"})
        assert r.status_code == 200
        assert r.get_json()["encoded"] == "dGVzdA=="

    def test_invalid_decode(self, client):
        r = client.get("/free/base64?decode=!!!invalid!!!")
        assert r.status_code == 200
        assert "decode_error" in r.get_json()

    def test_empty(self, client):
        r = client.get("/free/base64")
        assert r.status_code == 200
        d = r.get_json()
        assert "_meta" in d


# ═══════════════════════════════════════════════════════════════════════════
# 18. /free/random
# ═══════════════════════════════════════════════════════════════════════════

class TestFreeRandom:
    def test_success(self, client):
        r = client.get("/free/random?n=3&min=10&max=20")
        assert r.status_code == 200
        d = r.get_json()
        assert len(d["integers"]) == 3
        assert all(10 <= i <= 20 for i in d["integers"])
        assert isinstance(d["float"], float)
        assert isinstance(d["bool"], bool)
        assert len(d["random_string"]) == 16

    def test_default(self, client):
        r = client.get("/free/random")
        assert r.status_code == 200
        assert len(r.get_json()["integers"]) == 5


# ═══════════════════════════════════════════════════════════════════════════
# 19. /data/weather
# ═══════════════════════════════════════════════════════════════════════════

class TestWeather:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        geo_resp = _mock_response(json_data={
            "results": [{"name": "London", "country": "UK", "latitude": 51.5, "longitude": -0.1}]
        })
        weather_resp = _mock_response(json_data={
            "current_weather": {"temperature": 15, "windspeed": 10, "weathercode": 1, "is_day": 1, "time": "2026-01-01T12:00"}
        })
        mock_get.side_effect = [geo_resp, weather_resp]
        r = client.get("/data/weather?city=London")
        assert r.status_code == 200
        d = r.get_json()
        assert d["city"] == "London"
        assert d["temperature_c"] == 15

    @patch("routes.data._requests.get")
    def test_city_not_found(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={"results": []})
        r = client.get("/data/weather?city=Xyznonexistent")
        # geo returns empty results array
        assert r.status_code == 404

    @patch("routes.data._requests.get")
    def test_no_results_key(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={})
        r = client.get("/data/weather?city=Nowhere")
        assert r.status_code == 404

    @patch("routes.data._requests.get", side_effect=Exception("timeout"))
    def test_error(self, mock_get, client):
        r = client.get("/data/weather?city=London")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 20. /data/crypto
# ═══════════════════════════════════════════════════════════════════════════

class TestCrypto:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "bitcoin": {"usd": 60000, "eur": 55000, "gbp": 48000}
        })
        r = client.get("/data/crypto?symbol=bitcoin")
        assert r.status_code == 200
        d = r.get_json()
        assert "bitcoin" in d["prices"]
        assert d["symbols"] == ["bitcoin"]

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/crypto?symbol=bitcoin")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 21. /data/exchange-rates
# ═══════════════════════════════════════════════════════════════════════════

class TestExchangeRates:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "date": "2026-01-01",
            "rates": {"EUR": 0.85, "GBP": 0.73},
        })
        r = client.get("/data/exchange-rates?base=USD")
        assert r.status_code == 200
        d = r.get_json()
        assert d["base"] == "USD"
        assert "EUR" in d["rates"]

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/exchange-rates")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 22. /data/country
# ═══════════════════════════════════════════════════════════════════════════

class TestCountry:
    def test_missing_name(self, client):
        r = client.get("/data/country")
        assert r.status_code == 400

    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data=[
            {"name": {"common": "France"}, "capital": ["Paris"], "population": 67000000}
        ])
        r = client.get("/data/country?name=France")
        assert r.status_code == 200
        d = r.get_json()
        assert d["count"] == 1

    @patch("routes.data._requests.get")
    def test_not_found(self, mock_get, client):
        mock_get.return_value = _mock_response(status_code=404)
        r = client.get("/data/country?name=Neverland")
        assert r.status_code == 404

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/country?name=France")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 23. /data/ip
# ═══════════════════════════════════════════════════════════════════════════

class TestIPLookup:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "status": "success",
            "country": "US",
            "city": "Austin",
            "query": "8.8.8.8",
        })
        r = client.get("/data/ip?ip=8.8.8.8")
        assert r.status_code == 200
        d = r.get_json()
        assert d["country"] == "US"

    @patch("routes.data._requests.get")
    def test_default_ip(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={"status": "success", "query": "127.0.0.1"})
        r = client.get("/data/ip")
        assert r.status_code == 200

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/ip?ip=1.1.1.1")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 24. /data/news
# ═══════════════════════════════════════════════════════════════════════════

class TestNews:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        top_resp = _mock_response(json_data=[101, 102])
        item1 = _mock_response(json_data={"id": 101, "title": "Story 1", "url": "https://a.com", "score": 50, "by": "user", "descendants": 3})
        item2 = _mock_response(json_data={"id": 102, "title": "Story 2", "url": "https://b.com", "score": 30, "by": "user2", "descendants": 1})
        mock_get.side_effect = [top_resp, item1, item2]
        r = client.get("/data/news")
        assert r.status_code == 200
        d = r.get_json()
        assert d["count"] == 2
        assert d["stories"][0]["title"] == "Story 1"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/news")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 25. /data/stocks
# ═══════════════════════════════════════════════════════════════════════════

class TestStocks:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "chart": {"result": [{"meta": {
                "currency": "USD",
                "regularMarketPrice": 175.5,
                "previousClose": 174.0,
                "marketState": "REGULAR",
                "exchangeName": "NMS",
            }}]}
        })
        r = client.get("/data/stocks?symbol=AAPL")
        assert r.status_code == 200
        d = r.get_json()
        assert d["symbol"] == "AAPL"
        assert d["price"] == 175.5

    @patch("routes.data._requests.get")
    def test_symbol_not_found(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={"chart": {"result": []}})
        r = client.get("/data/stocks?symbol=XXXXXX")
        assert r.status_code == 404

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/stocks?symbol=AAPL")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 26. /data/joke
# ═══════════════════════════════════════════════════════════════════════════

class TestJoke:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "setup": "Why did the chicken?",
            "punchline": "To get to the other side",
            "type": "general",
        })
        r = client.get("/data/joke")
        assert r.status_code == 200
        d = r.get_json()
        assert d["setup"] == "Why did the chicken?"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_fallback(self, mock_get, client):
        r = client.get("/data/joke")
        assert r.status_code == 200
        d = r.get_json()
        assert d["setup"] == "Why don't scientists trust atoms?"
        assert d["_meta"]["source"] == "fallback"


# ═══════════════════════════════════════════════════════════════════════════
# 27. /data/quote
# ═══════════════════════════════════════════════════════════════════════════

class TestQuote:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        resp = _mock_response(json_data=[{"q": "Be yourself.", "a": "Oscar Wilde"}], ok=True)
        mock_get.return_value = resp
        r = client.get("/data/quote?category=wisdom")
        assert r.status_code == 200
        d = r.get_json()
        assert d["quote"] == "Be yourself."
        assert d["author"] == "Oscar Wilde"
        assert d["tags"] == ["wisdom"]

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/quote")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 28. /data/timezone
# ═══════════════════════════════════════════════════════════════════════════

class TestTimezone:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={
            "datetime": "2026-01-01T12:00:00",
            "utc_offset": "-05:00",
            "day_of_week": 4,
            "week_number": 1,
        })
        r = client.get("/data/timezone?tz=America/New_York")
        assert r.status_code == 200
        d = r.get_json()
        assert d["timezone"] == "America/New_York"
        assert d["utc_offset"] == "-05:00"

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/timezone?tz=Invalid/Zone")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# 29. /data/holidays
# ═══════════════════════════════════════════════════════════════════════════

class TestHolidays:
    @patch("routes.data._requests.get")
    def test_success(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data=[
            {"date": "2026-01-01", "localName": "New Year", "name": "New Year's Day"},
            {"date": "2026-07-04", "localName": "Independence Day", "name": "Independence Day"},
        ])
        r = client.get("/data/holidays?country=US&year=2026")
        assert r.status_code == 200
        d = r.get_json()
        assert d["country"] == "US"
        assert d["year"] == "2026"
        assert d["count"] == 2

    @patch("routes.data._requests.get")
    def test_no_data(self, mock_get, client):
        mock_get.return_value = _mock_response(json_data={"error": "not found"})
        r = client.get("/data/holidays?country=XX")
        assert r.status_code == 404

    @patch("routes.data._requests.get", side_effect=Exception("fail"))
    def test_error(self, mock_get, client):
        r = client.get("/data/holidays?country=US")
        assert r.status_code == 502


# ═══════════════════════════════════════════════════════════════════════════
# Cache tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCaching:
    @patch("routes.data._requests.get")
    def test_weather_uses_cache(self, mock_get, client):
        geo_resp = _mock_response(json_data={
            "results": [{"name": "Paris", "country": "FR", "latitude": 48.8, "longitude": 2.3}]
        })
        weather_resp = _mock_response(json_data={
            "current_weather": {"temperature": 20, "windspeed": 5, "weathercode": 0, "is_day": 1, "time": "2026-01-01T12:00"}
        })
        mock_get.side_effect = [geo_resp, weather_resp]
        r1 = client.get("/data/weather?city=Paris")
        assert r1.status_code == 200
        # Second call should use cache — no more mock_get calls needed
        mock_get.side_effect = Exception("should not be called")
        r2 = client.get("/data/weather?city=Paris")
        assert r2.status_code == 200
        assert r2.get_json()["city"] == "Paris"
