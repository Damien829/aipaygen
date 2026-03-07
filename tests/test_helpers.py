import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import (
    cache_get, cache_set, check_rate_limit,
    check_identity_rate_limit, parse_json_from_claude,
)


def test_cache_roundtrip():
    cache_set("test_key", {"data": 42}, ttl=60)
    assert cache_get("test_key") == {"data": 42}


def test_cache_miss():
    assert cache_get("nonexistent_key") is None


def test_cache_expired():
    cache_set("expired", "old", ttl=-1)  # already expired
    assert cache_get("expired") is None


def test_rate_limit_allows_normal():
    # Fresh IP should be allowed
    assert check_rate_limit("test_helper_ip_1") is True


def test_rate_limit_blocks_excess():
    ip = "test_helper_flood_ip"
    for _ in range(60):
        check_rate_limit(ip)
    assert check_rate_limit(ip) is False


def test_identity_rate_limit():
    ip = "test_helper_identity_ip"
    for _ in range(10):
        check_identity_rate_limit(ip)
    assert check_identity_rate_limit(ip) is False


def test_parse_json_direct():
    result = parse_json_from_claude('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_markdown_wrapped():
    text = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone.'
    result = parse_json_from_claude(text)
    assert result == {"key": "value"}


def test_parse_json_embedded():
    text = 'Some preamble {"key": "value"} some postamble'
    result = parse_json_from_claude(text)
    assert result == {"key": "value"}


def test_parse_json_invalid():
    result = parse_json_from_claude("no json here at all")
    assert result is None
