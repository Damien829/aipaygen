"""Admin access needs a valid Cloudflare Access JWT once Access is configured."""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import security

TEAM = "aipaygen.cloudflareaccess.com"
AUD = "test-aud-tag"


@pytest.fixture
def keys():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048), \
        rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def access(monkeypatch, keys):
    good, _ = keys
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    monkeypatch.setenv("ADMIN_SECRET", "admin-secret-for-tests")
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = MagicMock(key=good.public_key())
    security._cf_jwk_clients.clear()
    with patch("jwt.PyJWKClient", return_value=client):
        yield
    security._cf_jwk_clients.clear()


def _token(key, aud=AUD, iss=f"https://{TEAM}", exp_in=300):
    return jwt.encode({"aud": aud, "iss": iss, "exp": int(time.time()) + exp_in, "email": "owner@example.com"},
                      key, algorithm="RS256")


def _req(token=None):
    r = MagicMock()
    r.headers = {"Cf-Access-Jwt-Assertion": token} if token else {}
    r.cookies = {}
    return r


def test_not_configured_allows_unless_required(monkeypatch):
    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    monkeypatch.delenv("ADMIN_REQUIRE_CF_ACCESS", raising=False)
    assert security.admin_access_problem(_req()) is None
    monkeypatch.setenv("ADMIN_REQUIRE_CF_ACCESS", "1")
    assert security.admin_access_problem(_req())[0] == 503


def test_valid_token_passes(access, keys):
    assert security.admin_access_problem(_req(_token(keys[0]))) is None


@pytest.mark.parametrize("kind", ["missing", "wrong_key", "wrong_aud", "wrong_iss", "expired"])
def test_bad_tokens_rejected(access, keys, kind):
    good, other = keys
    token = {
        "missing": None,
        "wrong_key": _token(other),
        "wrong_aud": _token(good, aud="someone-else"),
        "wrong_iss": _token(good, iss="https://evil.cloudflareaccess.com"),
        "expired": _token(good, exp_in=-60),
    }[kind]
    assert security.admin_access_problem(_req(token))[0] == 403


def test_admin_routes_enforce_access(access, keys):
    import app as app_module
    c = app_module.app.test_client()
    secret = {"X-Admin-Key": "admin-secret-for-tests"}
    assert c.get("/admin/login").status_code == 403
    assert c.get("/admin/login", headers={"Cf-Access-Jwt-Assertion": _token(keys[0])}).status_code == 200
    # Admin secret used as a master API key still needs Access.
    assert c.get("/discovery/scouts/status", headers=secret).status_code == 403
    ok = c.get("/discovery/scouts/status", headers={**secret, "Cf-Access-Jwt-Assertion": _token(keys[0])})
    assert ok.status_code == 200
