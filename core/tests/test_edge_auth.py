"""Edge-only mode: only Worker-signed requests reach the core, and they skip v1 billing."""
import io
import json

from edge_auth import edge_only_wsgi, sign

SECRET = "test-secret"
NOW = 1_700_000_000


def test_signature_matches_worker_vector():
    # Same vector is asserted in test/core-proxy.test.ts.
    assert sign(SECRET, "1700000000", "post", "/research?x=1%20y", b'{"topic":"agents"}', "x402", "203.0.113.9") == \
        "cf3fea3b5a1df7ce59cc7bf4841cfa4bdb265bc05dd2b5e60e88ca699fff22e5"


def _call(path="/research", method="POST", body=b'{"topic":"x"}', ts=NOW, paid="x402", ip="203.0.113.9", sig=None, tamper=None):
    seen = {}

    def inner(environ, start_response):
        seen.update(environ, body=environ["wsgi.input"].read())
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"ok":true}']

    sent_body = tamper if tamper is not None else body
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path.split("?")[0], "RAW_URI": path,
        "QUERY_STRING": path.split("?")[1] if "?" in path else "",
        "CONTENT_LENGTH": str(len(sent_body)), "wsgi.input": io.BytesIO(sent_body),
        "HTTP_X_AIPAYGEN_EDGE_TS": str(ts), "HTTP_X_AIPAYGEN_PAID": paid, "HTTP_X_AIPAYGEN_CLIENT_IP": ip,
        "HTTP_X_AIPAYGEN_EDGE_SIG": sig if sig is not None else sign(SECRET, str(ts), method, path, body, paid, ip),
        "HTTP_X_FORWARDED_FOR": "6.6.6.6",
    }
    status = {}
    out = edge_only_wsgi(inner, SECRET, now=lambda: NOW)(environ, lambda s, h: status.update(code=s))
    return status["code"], b"".join(out), seen


def test_signed_request_passes_with_body_and_trusted_ip():
    code, _, seen = _call()
    assert code.startswith("200")
    assert seen["body"] == b'{"topic":"x"}'
    assert seen["aipaygen.paid"] == "x402"
    assert seen["HTTP_CF_CONNECTING_IP"] == "203.0.113.9"
    assert "HTTP_X_FORWARDED_FOR" not in seen


def test_rejects_unsigned_tampered_stale_and_wrong_secret():
    assert _call(sig="")[0].startswith("401")
    assert _call(tamper=b'{"topic":"y"}')[0].startswith("401")
    assert _call(ts=NOW - 301)[0].startswith("401")
    assert _call(ts="nope")[0].startswith("401")
    assert _call(sig=sign("other", str(NOW), "POST", "/research", b'{"topic":"x"}', "x402", "203.0.113.9"))[0].startswith("401")
    code, body, _ = _call(paid="free", sig=sign(SECRET, str(NOW), "POST", "/research", b'{"topic":"x"}', "x402", "203.0.113.9"))
    assert code.startswith("401") and json.loads(body)["error"] == "edge_signature_invalid"


def test_health_stays_open_for_the_container_check():
    def inner(environ, start_response):
        start_response("200 OK", [])
        return [b"ok"]
    status = {}
    out = edge_only_wsgi(inner, SECRET)({"REQUEST_METHOD": "GET", "PATH_INFO": "/health"}, lambda s, h: status.update(code=s))
    assert status["code"].startswith("200") and b"".join(out) == b"ok"
