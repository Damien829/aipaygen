"""Tests for all 43 utility endpoints in routes/utility.py."""
import sys, os, json, time, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# GEOCODING
# ─────────────────────────────────────────────────────────────────────────────

class TestGeocode:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_geocode_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = [
            {"lat": "40.7128", "lon": "-74.0060", "display_name": "New York", "type": "city"}
        ]
        r = client.get("/data/geocode?q=New+York")
        assert r.status_code == 200
        data = r.get_json()
        assert data["query"] == "New York"
        assert len(data["results"]) == 1
        assert data["results"][0]["lat"] == 40.7128

    def test_geocode_missing_param(self, client):
        r = client.get("/data/geocode")
        assert r.status_code == 400
        assert "q parameter required" in r.get_json()["error"]

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get", side_effect=Exception("timeout"))
    def test_geocode_external_error(self, mock_get, mock_cs, mock_cg, client):
        r = client.get("/data/geocode?q=nowhere")
        assert r.status_code == 502

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_geocode_reverse_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {
            "display_name": "New York, USA",
            "address": {"city": "New York", "country": "USA"},
        }
        r = client.get("/data/geocode/reverse?lat=40.7128&lon=-74.0060")
        assert r.status_code == 200
        data = r.get_json()
        assert data["lat"] == 40.7128
        assert "address" in data

    def test_geocode_reverse_missing_params(self, client):
        r = client.get("/data/geocode/reverse")
        assert r.status_code == 400
        r2 = client.get("/data/geocode/reverse?lat=40")
        assert r2.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY SEARCH
# ─────────────────────────────────────────────────────────────────────────────

class TestCompany:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_company_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {
            "title": "Apple Inc.",
            "extract": "An American tech company",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Apple_Inc."}},
            "thumbnail": {"source": "https://example.com/apple.png"},
        }
        r = client.get("/data/company?q=Apple")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "Apple Inc."
        assert data["domain_guess"] == "apple.com"

    def test_company_missing_param(self, client):
        r = client.get("/data/company")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# WHOIS / DOMAIN
# ─────────────────────────────────────────────────────────────────────────────

class TestWhoisDomain:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_whois_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {
            "status": ["active"],
            "events": [{"eventAction": "registration", "eventDate": "2020-01-01"}],
            "nameservers": [{"ldhName": "ns1.example.com"}],
            "entities": [],
        }
        r = client.get("/data/whois?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["domain"] == "example.com"
        assert data["nameservers"] == ["ns1.example.com"]

    def test_whois_missing_param(self, client):
        r = client.get("/data/whois")
        assert r.status_code == 400

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    @patch("subprocess.run")
    def test_domain_profile_success(self, mock_sub, mock_get, mock_cs, mock_cg, client):
        mock_sub.return_value = MagicMock(stdout="93.184.216.34\n", returncode=0)
        mock_get.return_value.json.return_value = {
            "status": ["active"],
            "nameservers": [{"ldhName": "ns1.example.com"}],
            "events": [],
        }
        r = client.get("/data/domain?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["domain"] == "example.com"

    def test_domain_profile_missing_param(self, client):
        r = client.get("/data/domain")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# TEXT ANALYSIS (pure computation — no mocking needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestReadability:
    def test_readability_success(self, client):
        r = client.post("/data/readability",
                        json={"text": "The quick brown fox jumps over the lazy dog. It was a sunny day."},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert "flesch_reading_ease" in data
        assert "flesch_kincaid_grade" in data
        assert "level" in data
        assert data["words"] > 0

    def test_readability_missing_text(self, client):
        r = client.post("/data/readability", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_readability_single_word(self, client):
        r = client.post("/data/readability", json={"text": "Hello"},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["words"] == 1


class TestLanguageDetect:
    def test_language_detect_english(self, client):
        r = client.get("/data/language?text=Hello+world+this+is+a+test")
        assert r.status_code == 200
        data = r.get_json()
        assert data["detected_language"] == "en"
        assert data["script"] == "LATIN"

    def test_language_detect_cjk(self, client):
        r = client.get("/data/language?text=这是一个测试")
        assert r.status_code == 200
        data = r.get_json()
        assert data["detected_language"] == "zh"

    def test_language_detect_cyrillic(self, client):
        r = client.get("/data/language?text=Привет+мир")
        assert r.status_code == 200
        assert r.get_json()["detected_language"] == "ru"

    def test_language_detect_missing_text(self, client):
        r = client.get("/data/language")
        assert r.status_code == 400


class TestProfanityFilter:
    def test_profanity_detected(self, client):
        r = client.post("/data/profanity",
                        json={"text": "What the hell is going on"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["contains_profanity"] is True
        assert data["profanity_count"] >= 1
        assert "hell" in data["words_found"]
        assert "hell" not in data["cleaned_text"].lower().split()

    def test_profanity_clean(self, client):
        r = client.post("/data/profanity",
                        json={"text": "This is a perfectly clean sentence."},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["contains_profanity"] is False
        assert data["profanity_count"] == 0

    def test_profanity_missing_text(self, client):
        r = client.post("/data/profanity", json={}, content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# WEB & URL TOOLS
# ─────────────────────────────────────────────────────────────────────────────

class TestUrlMeta:
    @patch("routes.utility._requests.get")
    def test_url_meta_success(self, mock_get, client):
        mock_get.return_value.text = '''<html><head>
            <title>Test Page</title>
            <meta property="og:title" content="OG Title"/>
            <meta name="twitter:card" content="summary"/>
        </head></html>'''
        r = client.get("/data/meta?url=https://example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["title"] == "Test Page"
        assert data["og"]["title"] == "OG Title"
        assert data["twitter"]["card"] == "summary"

    def test_url_meta_missing_param(self, client):
        r = client.get("/data/meta")
        assert r.status_code == 400


class TestExtractLinks:
    @patch("routes.utility._requests.get")
    def test_links_success(self, mock_get, client):
        mock_get.return_value.text = '''<html>
            <a href="https://example.com/page1">P1</a>
            <a href="/page2">P2</a>
            <a href="https://other.com">O</a>
        </html>'''
        r = client.get("/data/links?url=https://example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_links"] >= 2
        assert "https://example.com/page1" in data["links"]

    def test_links_missing_param(self, client):
        r = client.get("/data/links")
        assert r.status_code == 400


class TestSitemap:
    @patch("routes.utility._requests.get")
    def test_sitemap_success(self, mock_get, client):
        mock_get.return_value.text = '''<?xml version="1.0"?>
        <urlset><url><loc>https://example.com/page1</loc></url>
        <url><loc>https://example.com/page2</loc></url></urlset>'''
        r = client.get("/data/sitemap?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["url_count"] == 2

    def test_sitemap_missing_param(self, client):
        r = client.get("/data/sitemap")
        assert r.status_code == 400


class TestRobots:
    @patch("routes.utility._requests.get")
    def test_robots_success(self, mock_get, client):
        mock_get.return_value.text = """User-agent: *
Disallow: /admin
Allow: /
Sitemap: https://example.com/sitemap.xml"""
        r = client.get("/data/robots?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["rules"]) >= 2
        assert "https://example.com/sitemap.xml" in data["sitemaps"]

    def test_robots_missing_param(self, client):
        r = client.get("/data/robots")
        assert r.status_code == 400


class TestHttpHeaders:
    @patch("routes.utility._requests.head")
    def test_headers_success(self, mock_head, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html", "Server": "nginx"}
        mock_head.return_value = mock_resp
        r = client.get("/data/headers?url=https://example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status_code"] == 200
        assert "Server" in data["headers"]

    def test_headers_missing_param(self, client):
        r = client.get("/data/headers")
        assert r.status_code == 400

    @patch("routes.utility._requests.head", side_effect=Exception("conn refused"))
    def test_headers_error(self, mock_head, client):
        r = client.get("/data/headers?url=https://down.example.com")
        assert r.status_code == 502


class TestSSLInfo:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("ssl.get_server_certificate")
    def test_ssl_missing_param(self, mock_ssl, mock_cg, client):
        r = client.get("/data/ssl")
        assert r.status_code == 400

    @patch("routes.utility._cache_get", return_value=None)
    @patch("ssl.get_server_certificate", side_effect=Exception("connection refused"))
    def test_ssl_error(self, mock_ssl, mock_cg, client):
        r = client.get("/data/ssl?domain=nonexistent.example")
        assert r.status_code == 502


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE & DEV (pure computation)
# ─────────────────────────────────────────────────────────────────────────────

class TestJwtDecode:
    def test_jwt_decode_success(self, client):
        # Create a real JWT for testing
        import jwt as pyjwt
        token = pyjwt.encode({"sub": "1234", "name": "Test", "exp": 9999999999},
                             "secret", algorithm="HS256")
        r = client.post("/data/jwt/decode", json={"token": token},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["payload"]["sub"] == "1234"
        assert data["header"]["alg"] == "HS256"
        assert data["expired"] is False

    def test_jwt_decode_expired(self, client):
        import jwt as pyjwt
        token = pyjwt.encode({"sub": "1234", "exp": 1000000000},
                             "secret", algorithm="HS256")
        r = client.post("/data/jwt/decode", json={"token": token},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["expired"] is True

    def test_jwt_decode_missing_token(self, client):
        r = client.post("/data/jwt/decode", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_jwt_decode_invalid_token(self, client):
        r = client.post("/data/jwt/decode", json={"token": "not.a.jwt"},
                        content_type="application/json")
        assert r.status_code == 400


class TestMarkdownToHtml:
    def test_markdown_success(self, client):
        r = client.post("/data/markdown",
                        json={"text": "# Hello\n\nWorld **bold**"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert "<h1>" in data["html"]
        assert "<strong>bold</strong>" in data["html"]

    def test_markdown_table(self, client):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        r = client.post("/data/markdown", json={"text": md},
                        content_type="application/json")
        assert r.status_code == 200
        assert "<table>" in r.get_json()["html"]

    def test_markdown_missing_text(self, client):
        r = client.post("/data/markdown", json={}, content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA & VISUAL
# ─────────────────────────────────────────────────────────────────────────────

class TestPlaceholderImage:
    def test_placeholder_default(self, client):
        r = client.get("/data/placeholder")
        assert r.status_code == 200
        assert r.content_type == "image/svg+xml"
        assert b"300x200" in r.data

    def test_placeholder_custom(self, client):
        r = client.get("/data/placeholder?width=500&height=400&bg=ff0000&fg=ffffff&text=Hello")
        assert r.status_code == 200
        assert b"500" in r.data
        assert b"Hello" in r.data

    def test_placeholder_returns_svg(self, client):
        r = client.get("/data/placeholder?width=100&height=100")
        assert b"<svg" in r.data


class TestFavicon:
    @patch("routes.utility._requests.get")
    def test_favicon_success(self, mock_get, client):
        mock_get.return_value.text = '''<html><head>
            <link rel="icon" href="/static/favicon.ico"/>
        </head></html>'''
        r = client.get("/data/favicon?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["icons"]) >= 1

    @patch("routes.utility._requests.get")
    def test_favicon_fallback_to_default(self, mock_get, client):
        mock_get.return_value.text = '<html><head></head></html>'
        r = client.get("/data/favicon?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert any("favicon.ico" in i for i in data["icons"])

    def test_favicon_missing_param(self, client):
        r = client.get("/data/favicon")
        assert r.status_code == 400


class TestIdenticon:
    def test_identicon_success(self, client):
        r = client.get("/data/avatar?input=testuser")
        assert r.status_code == 200
        assert r.content_type == "image/svg+xml"
        assert b"<svg" in r.data

    def test_identicon_deterministic(self, client):
        r1 = client.get("/data/avatar?input=same_seed")
        r2 = client.get("/data/avatar?input=same_seed")
        assert r1.data == r2.data

    def test_identicon_different_inputs(self, client):
        r1 = client.get("/data/avatar?input=user1")
        r2 = client.get("/data/avatar?input=user2")
        assert r1.data != r2.data

    def test_identicon_missing_param(self, client):
        r = client.get("/data/avatar")
        assert r.status_code == 400

    def test_identicon_custom_size(self, client):
        r = client.get("/data/avatar?input=test&size=120")
        assert r.status_code == 200
        assert b'width="120"' in r.data


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKCHAIN
# ─────────────────────────────────────────────────────────────────────────────

class TestENS:
    def test_ens_missing_param(self, client):
        r = client.get("/data/ens")
        assert r.status_code == 400

    def test_ens_invalid_name(self, client):
        r = client.get("/data/ens?name=notanaddress")
        assert r.status_code == 400
        assert "Provide .eth name or 0x address" in r.get_json()["error"]

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    def test_ens_resolve_eth_error(self, mock_cs, mock_cg, client):
        """ENS resolution will fail without real web3 connection."""
        # Just test it doesn't crash the server
        r = client.get("/data/ens?name=vitalik.eth")
        assert r.status_code in (200, 502)


# ─────────────────────────────────────────────────────────────────────────────
# ENRICHMENT
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichDomain:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("subprocess.run")
    @patch("routes.utility._requests.get")
    def test_enrich_domain_success(self, mock_get, mock_sub, mock_cs, mock_cg, client):
        mock_resp = MagicMock()
        mock_resp.text = '<html><script src="https://cdn.shopify.com/s/main.js"></script>' \
                         '<a href="https://twitter.com/testhandle">Twitter</a></html>'
        mock_resp.headers = {"Server": "cloudflare"}
        mock_get.return_value = mock_resp
        mock_sub.return_value = MagicMock(stdout="1.2.3.4\n", returncode=0)
        r = client.get("/data/enrich/domain?domain=example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["domain"] == "example.com"
        assert isinstance(data["tech_stack"], list)
        assert isinstance(data["socials"], list)

    def test_enrich_domain_missing_param(self, client):
        r = client.get("/data/enrich/domain")
        assert r.status_code == 400


class TestEnrichGithub:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_enrich_github_success(self, mock_get, mock_cs, mock_cg, client):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            if "/repos" in url:
                resp.json.return_value = [
                    {"name": "repo1", "stargazers_count": 100, "language": "Python",
                     "description": "A repo", "html_url": "https://github.com/test/repo1"}
                ]
            else:
                resp.json.return_value = {
                    "name": "Test User", "bio": "Developer",
                    "avatar_url": "https://github.com/avatar.png",
                    "public_repos": 10, "followers": 50, "following": 20,
                    "created_at": "2020-01-01T00:00:00Z",
                }
            return resp
        mock_get.side_effect = side_effect
        r = client.get("/data/enrich/github?username=testuser")
        assert r.status_code == 200
        data = r.get_json()
        assert data["username"] == "testuser"
        assert data["name"] == "Test User"
        assert len(data["top_repos"]) == 1

    def test_enrich_github_missing_param(self, client):
        r = client.get("/data/enrich/github")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

class TestEmailSend:
    def test_email_missing_fields(self, client):
        r = client.post("/data/email/send", json={"to": "a@b.com"},
                        content_type="application/json")
        assert r.status_code == 400

    @patch.dict(os.environ, {"RESEND_API_KEY": ""}, clear=False)
    def test_email_no_api_key(self, client):
        r = client.post("/data/email/send",
                        json={"to": "a@b.com", "subject": "Test", "body": "Hello"},
                        content_type="application/json")
        assert r.status_code in (400, 503)

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"}, clear=False)
    @patch("routes.utility._requests.post")
    def test_email_send_success(self, mock_post, client):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"id": "msg_123"}
        r = client.post("/data/email/send",
                        json={"to": "a@b.com", "subject": "Test", "body": "Hello"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["sent"] is True


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractText:
    def test_extract_text_from_html(self, client):
        r = client.post("/data/extract/text",
                        json={"html": "<html><body><h1>Title</h1><p>Content here</p>"
                                      "<script>var x=1;</script></body></html>"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert "Title" in data["text"]
        assert "Content here" in data["text"]
        assert "var x=1" not in data["text"]
        assert data["word_count"] > 0

    @patch("routes.utility._requests.get")
    def test_extract_text_from_url(self, mock_get, client):
        mock_get.return_value.text = "<html><body><p>Hello World</p></body></html>"
        r = client.post("/data/extract/text",
                        json={"url": "https://example.com"},
                        content_type="application/json")
        assert r.status_code == 200
        assert "Hello World" in r.get_json()["text"]

    def test_extract_text_missing_input(self, client):
        r = client.post("/data/extract/text", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_extract_pdf_no_file(self, client):
        r = client.post("/data/extract/pdf")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# FINANCE
# ─────────────────────────────────────────────────────────────────────────────

class TestFinanceHistory:
    def test_finance_history_missing_symbol(self, client):
        r = client.get("/data/finance/history")
        assert r.status_code == 400

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    def test_finance_history_import_error(self, mock_cs, mock_cg, client):
        """If yfinance fails, should return 502."""
        with patch.dict("sys.modules", {"yfinance": None}):
            r = client.get("/data/finance/history?symbol=AAPL")
            assert r.status_code in (200, 502)


class TestFinanceForex:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_forex_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {
            "rates": {"EUR": 0.92, "GBP": 0.79},
            "time_last_update_utc": "2026-01-01 00:00:00",
        }
        r = client.get("/data/finance/forex?base=USD")
        assert r.status_code == 200
        data = r.get_json()
        assert data["base"] == "USD"
        assert "EUR" in data["rates"]

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_forex_default_base(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {"rates": {"EUR": 0.92}, "time_last_update_utc": ""}
        r = client.get("/data/finance/forex")
        assert r.status_code == 200
        assert r.get_json()["base"] == "USD"


class TestFinanceConvert:
    @patch("routes.utility._requests.get")
    def test_convert_success(self, mock_get, client):
        mock_get.return_value.json.return_value = {"rates": {"EUR": 0.92, "GBP": 0.79}}
        r = client.get("/data/finance/convert?amount=100&from=USD&to=EUR")
        assert r.status_code == 200
        data = r.get_json()
        assert data["result"] == 92.0
        assert data["rate"] == 0.92

    @patch("routes.utility._requests.get")
    def test_convert_unknown_currency(self, mock_get, client):
        mock_get.return_value.json.return_value = {"rates": {"EUR": 0.92}}
        r = client.get("/data/finance/convert?amount=100&from=USD&to=XYZ")
        assert r.status_code == 400

    @patch("routes.utility._requests.get", side_effect=Exception("api down"))
    def test_convert_error(self, mock_get, client):
        r = client.get("/data/finance/convert?amount=100&from=USD&to=EUR")
        assert r.status_code == 502


# ─────────────────────────────────────────────────────────────────────────────
# NLP
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityExtraction:
    def test_entities_success(self, client):
        text = ("Contact us at test@example.com or visit https://example.com. "
                "ETH: 0x1234567890abcdef1234567890abcdef12345678 "
                "Date: 2026-01-15 #crypto @user")
        r = client.post("/data/entities", json={"text": text},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_entities"] > 0
        assert "test@example.com" in data["entities"]["emails"]
        assert "https://example.com" in data["entities"]["urls"][0]
        assert len(data["entities"]["eth_addresses"]) == 1
        assert "#crypto" in data["entities"]["hashtags"]
        assert "@user" in data["entities"]["mentions"]

    def test_entities_missing_text(self, client):
        r = client.post("/data/entities", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_entities_empty_result(self, client):
        r = client.post("/data/entities", json={"text": "plain text no entities"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entities"]["emails"] == []


class TestTextSimilarity:
    def test_similarity_identical(self, client):
        r = client.post("/data/similarity",
                        json={"text1": "hello world", "text2": "hello world"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["jaccard_similarity"] == 1.0
        assert data["cosine_similarity"] == 1.0

    def test_similarity_different(self, client):
        r = client.post("/data/similarity",
                        json={"text1": "hello world", "text2": "goodbye universe"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["jaccard_similarity"] == 0.0
        assert data["cosine_similarity"] == 0.0

    def test_similarity_partial(self, client):
        r = client.post("/data/similarity",
                        json={"text1": "the cat sat", "text2": "the dog sat"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert 0 < data["jaccard_similarity"] < 1
        assert data["common_words"] == 2

    def test_similarity_missing_fields(self, client):
        r = client.post("/data/similarity", json={"text1": "hello"},
                        content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORMS (pure computation)
# ─────────────────────────────────────────────────────────────────────────────

class TestJsonToCsv:
    def test_json_to_csv_success(self, client):
        r = client.post("/data/transform/json-to-csv",
                        json={"data": [{"name": "Alice", "age": 30},
                                       {"name": "Bob", "age": 25}]},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["rows"] == 2
        assert data["columns"] == 2
        assert "name" in data["csv"] and "age" in data["csv"]
        assert "Alice" in data["csv"]

    def test_json_to_csv_empty_array(self, client):
        r = client.post("/data/transform/json-to-csv",
                        json={"data": []}, content_type="application/json")
        assert r.status_code == 400

    def test_json_to_csv_not_array(self, client):
        r = client.post("/data/transform/json-to-csv",
                        json={"data": "not an array"}, content_type="application/json")
        assert r.status_code == 400


class TestXmlToJson:
    def test_xml_to_json_success(self, client):
        xml = '<root><name>Alice</name><age>30</age></root>'
        r = client.post("/data/transform/xml", json={"xml": xml},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["json"]["root"]["name"] == "Alice"
        assert data["json"]["root"]["age"] == "30"

    def test_xml_to_json_with_attributes(self, client):
        xml = '<item id="1"><name>Test</name></item>'
        r = client.post("/data/transform/xml", json={"xml": xml},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["json"]["item"]["@attributes"]["id"] == "1"

    def test_xml_to_json_invalid(self, client):
        r = client.post("/data/transform/xml", json={"xml": "not xml"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_xml_to_json_missing(self, client):
        r = client.post("/data/transform/xml", json={}, content_type="application/json")
        assert r.status_code == 400


class TestYamlToJson:
    def test_yaml_to_json_success(self, client):
        r = client.post("/data/transform/yaml",
                        json={"yaml": "name: Alice\nage: 30\ntags:\n  - python\n  - ai"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["json"]["name"] == "Alice"
        assert data["json"]["age"] == 30
        assert "python" in data["json"]["tags"]

    def test_yaml_to_json_missing(self, client):
        r = client.post("/data/transform/yaml", json={}, content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# DATE & TIME (pure computation)
# ─────────────────────────────────────────────────────────────────────────────

class TestDatetimeBetween:
    def test_between_success(self, client):
        r = client.get("/data/datetime/between?from=2026-01-01&to=2026-01-31")
        assert r.status_code == 200
        data = r.get_json()
        assert data["days"] == 30
        assert data["weeks"] == 4

    def test_between_missing_params(self, client):
        r = client.get("/data/datetime/between")
        assert r.status_code == 400
        r2 = client.get("/data/datetime/between?from=2026-01-01")
        assert r2.status_code == 400

    def test_between_invalid_format(self, client):
        r = client.get("/data/datetime/between?from=not-a-date&to=2026-01-01")
        assert r.status_code == 400

    def test_between_reversed_dates(self, client):
        r = client.get("/data/datetime/between?from=2026-12-31&to=2026-01-01")
        assert r.status_code == 200
        assert r.get_json()["days"] == 364


class TestBusinessDays:
    def test_business_days_success(self, client):
        # Mon Jan 5 to Fri Jan 9, 2026
        r = client.get("/data/datetime/business-days?from=2026-01-05&to=2026-01-09")
        assert r.status_code == 200
        data = r.get_json()
        assert data["business_days"] == 5

    def test_business_days_missing_params(self, client):
        r = client.get("/data/datetime/business-days")
        assert r.status_code == 400

    def test_business_days_invalid_format(self, client):
        r = client.get("/data/datetime/business-days?from=abc&to=def")
        assert r.status_code == 400


class TestUnixTimestamp:
    def test_unix_current(self, client):
        r = client.get("/data/datetime/unix")
        assert r.status_code == 200
        data = r.get_json()
        assert "timestamp" in data
        assert "iso" in data

    def test_unix_convert(self, client):
        r = client.get("/data/datetime/unix?timestamp=1704067200")
        assert r.status_code == 200
        data = r.get_json()
        assert "2024-01-01" in data["iso"]

    def test_unix_milliseconds(self, client):
        r = client.get("/data/datetime/unix?timestamp=1704067200000")
        assert r.status_code == 200
        data = r.get_json()
        assert "2024-01-01" in data["iso"]

    def test_unix_invalid(self, client):
        r = client.get("/data/datetime/unix?timestamp=notanumber")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityHeaders:
    @patch("routes.utility._requests.get")
    def test_security_headers_all_present(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Security-Policy": "default-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=()",
        }
        mock_get.return_value = mock_resp
        r = client.get("/data/security/headers?url=https://secure.example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["grade"] == "A+"
        assert data["score"] == "7/7"

    @patch("routes.utility._requests.get")
    def test_security_headers_none_present(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_resp
        r = client.get("/data/security/headers?url=https://insecure.example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["grade"] == "F"

    def test_security_headers_missing_param(self, client):
        r = client.get("/data/security/headers")
        assert r.status_code == 400


class TestTechstackDetect:
    @patch("routes.utility._requests.get")
    def test_techstack_success(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.text = '<html><script src="/_next/static/main.js"></script>' \
                         '<link href="https://cdn.shopify.com/s/style.css"/></html>'
        mock_resp.headers = {"server": "cloudflare", "x-powered-by": "Express"}
        mock_get.return_value = mock_resp
        r = client.get("/data/security/techstack?url=https://example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert "Next.js" in data["technologies"]
        assert "Shopify" in data["technologies"]

    def test_techstack_missing_param(self, client):
        r = client.get("/data/security/techstack")
        assert r.status_code == 400


class TestUptimeCheck:
    @patch("routes.utility._requests.get")
    def test_uptime_success(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"OK"
        mock_get.return_value = mock_resp
        r = client.get("/data/security/uptime?url=https://example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "up"
        assert data["ssl"] is True

    @patch("routes.utility._requests.get")
    def test_uptime_down(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.content = b"Error"
        mock_get.return_value = mock_resp
        r = client.get("/data/security/uptime?url=http://down.example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "down"
        assert data["ssl"] is False

    @patch("routes.utility._requests.get", side_effect=Exception("connection refused"))
    def test_uptime_unreachable(self, mock_get, client):
        r = client.get("/data/security/uptime?url=https://dead.example.com")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "down"

    def test_uptime_missing_param(self, client):
        r = client.get("/data/security/uptime")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# MATH (pure computation)
# ─────────────────────────────────────────────────────────────────────────────

class TestMathEval:
    def test_basic_arithmetic(self, client):
        r = client.post("/data/math/eval", json={"expression": "2 + 3 * 4"},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["result"] == 14

    def test_power(self, client):
        r = client.post("/data/math/eval", json={"expression": "2^10"},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["result"] == 1024

    def test_functions(self, client):
        r = client.post("/data/math/eval", json={"expression": "sqrt(16)"},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["result"] == 4.0

    def test_constants(self, client):
        r = client.post("/data/math/eval", json={"expression": "pi"},
                        content_type="application/json")
        assert r.status_code == 200
        assert abs(r.get_json()["result"] - math.pi) < 0.001

    def test_trig(self, client):
        r = client.post("/data/math/eval", json={"expression": "sin(0)"},
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["result"] == 0.0

    def test_unsafe_expression(self, client):
        r = client.post("/data/math/eval",
                        json={"expression": "__import__('os').system('ls')"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_missing_expression(self, client):
        r = client.post("/data/math/eval", json={}, content_type="application/json")
        assert r.status_code == 400


class TestUnitConvert:
    def test_length_conversion(self, client):
        r = client.get("/data/math/convert?value=1&from=km&to=m")
        assert r.status_code == 200
        assert r.get_json()["result"] == 1000.0

    def test_weight_conversion(self, client):
        r = client.get("/data/math/convert?value=1&from=kg&to=g")
        assert r.status_code == 200
        assert r.get_json()["result"] == 1000.0

    def test_temperature_c_to_f(self, client):
        r = client.get("/data/math/convert?value=100&from=c&to=f")
        assert r.status_code == 200
        assert r.get_json()["result"] == 212.0

    def test_temperature_f_to_c(self, client):
        r = client.get("/data/math/convert?value=32&from=f&to=c")
        assert r.status_code == 200
        assert r.get_json()["result"] == 0.0

    def test_temperature_k(self, client):
        r = client.get("/data/math/convert?value=0&from=c&to=k")
        assert r.status_code == 200
        assert r.get_json()["result"] == 273.15

    def test_data_conversion(self, client):
        r = client.get("/data/math/convert?value=1&from=gb&to=mb")
        assert r.status_code == 200
        assert r.get_json()["result"] == 1024.0

    def test_incompatible_units(self, client):
        r = client.get("/data/math/convert?value=1&from=kg&to=km")
        assert r.status_code == 400

    def test_missing_params(self, client):
        r = client.get("/data/math/convert?value=1")
        assert r.status_code == 400


class TestMathStats:
    def test_stats_success(self, client):
        r = client.post("/data/math/stats",
                        json={"numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 10
        assert data["sum"] == 55
        assert data["mean"] == 5.5
        assert data["median"] == 5.5
        assert data["min"] == 1
        assert data["max"] == 10
        assert "stdev" in data
        assert "q1" in data
        assert "q3" in data

    def test_stats_single_element(self, client):
        r = client.post("/data/math/stats", json={"numbers": [42]},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["mean"] == 42
        assert "stdev" not in data  # needs >= 2

    def test_stats_empty(self, client):
        r = client.post("/data/math/stats", json={"numbers": []},
                        content_type="application/json")
        assert r.status_code == 400

    def test_stats_not_list(self, client):
        r = client.post("/data/math/stats", json={"numbers": "abc"},
                        content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# CRYPTO TRENDING
# ─────────────────────────────────────────────────────────────────────────────

class TestCryptoTrending:
    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get")
    def test_trending_success(self, mock_get, mock_cs, mock_cg, client):
        mock_get.return_value.json.return_value = {
            "coins": [
                {"item": {"name": "Bitcoin", "symbol": "BTC",
                           "market_cap_rank": 1, "thumb": "https://example.com/btc.png"}},
                {"item": {"name": "Ethereum", "symbol": "ETH",
                           "market_cap_rank": 2, "thumb": "https://example.com/eth.png"}},
            ]
        }
        r = client.get("/data/crypto/trending")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["trending_coins"]) == 2
        assert data["trending_coins"][0]["symbol"] == "BTC"
        assert data["source"] == "coingecko"

    @patch("routes.utility._cache_get", return_value=None)
    @patch("routes.utility._cache_set")
    @patch("routes.utility._requests.get", side_effect=Exception("rate limited"))
    def test_trending_error(self, mock_get, mock_cs, mock_cg, client):
        r = client.get("/data/crypto/trending")
        assert r.status_code == 502
