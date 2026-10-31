"""Edge-only mode: the core accepts only requests signed by the AIPayGen Worker.

When AIPAYGEN_EDGE_SECRET is set, the Worker is the single payment layer: it
charges (credits or x402), then forwards the request here with a signature over

    v1 \n <unix ts> \n <METHOD> \n <raw path?query> \n <sha256(body) hex> \n <paid> \n <client ip>

sent as X-AIPayGen-Edge-Ts / X-AIPayGen-Edge-Sig / X-AIPayGen-Paid /
X-AIPayGen-Client-IP. Anything unsigned, stale (over 5 minutes) or altered gets
401, so nobody can reach the core around the Worker or skip payment. The same
canonical string is built in src/core/proxy.ts; change both together.
"""
import hashlib
import hmac
import io
import json
import time
from urllib.parse import quote

MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 10 * 1024 * 1024
OPEN_PATHS = frozenset({"/health"})  # container healthcheck, from inside the server


def canonical(ts: str, method: str, path: str, body: bytes, paid: str, client_ip: str) -> bytes:
    return "\n".join(["v1", ts, method.upper(), path, hashlib.sha256(body).hexdigest(), paid, client_ip]).encode()


def sign(secret: str, ts: str, method: str, path: str, body: bytes, paid: str, client_ip: str) -> str:
    return hmac.new(secret.encode(), canonical(ts, method, path, body, paid, client_ip), "sha256").hexdigest()


def _raw_path(environ) -> str:
    raw = environ.get("RAW_URI") or environ.get("REQUEST_URI")
    if raw:
        return raw
    qs = environ.get("QUERY_STRING", "")
    return quote(environ.get("PATH_INFO", ""), safe="/:@!$&'()*+,;=-._~%") + (f"?{qs}" if qs else "")


def _deny(start_response, code: str, message: str):
    body = json.dumps({"error": code, "message": message}).encode()
    start_response("401 Unauthorized", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def edge_only_wsgi(inner, secret: str, now=time.time):
    """Wrap the raw Flask WSGI app so only Worker-signed requests reach it."""

    def app(environ, start_response):
        if environ.get("PATH_INFO") in OPEN_PATHS and environ.get("REQUEST_METHOD") in ("GET", "HEAD"):
            return inner(environ, start_response)

        ts = environ.get("HTTP_X_AIPAYGEN_EDGE_TS", "")
        sig = environ.get("HTTP_X_AIPAYGEN_EDGE_SIG", "")
        paid = environ.get("HTTP_X_AIPAYGEN_PAID", "")
        client_ip = environ.get("HTTP_X_AIPAYGEN_CLIENT_IP", "")
        try:
            if abs(now() - int(ts)) > MAX_SKEW_SECONDS:
                return _deny(start_response, "edge_signature_expired", "Request must come through aipaygen.com.")
        except ValueError:
            return _deny(start_response, "edge_signature_required", "Request must come through aipaygen.com.")

        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return _deny(start_response, "body_too_large", "Request body too large.")
        body = environ["wsgi.input"].read(length) if length else b""
        environ["wsgi.input"] = io.BytesIO(body)

        expected = sign(secret, ts, environ.get("REQUEST_METHOD", "GET"), _raw_path(environ), body, paid, client_ip)
        if not hmac.compare_digest(expected, sig):
            return _deny(start_response, "edge_signature_invalid", "Request must come through aipaygen.com.")

        # Trusted from here: the Worker already billed this call.
        environ["aipaygen.paid"] = paid
        environ["HTTP_CF_CONNECTING_IP"] = client_ip
        environ.pop("HTTP_X_FORWARDED_FOR", None)
        environ["wsgi.url_scheme"] = "https"
        return inner(environ, start_response)

    return app
