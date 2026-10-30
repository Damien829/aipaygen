"""Logs must not hold usable API keys or reversible IP addresses."""
import hashlib

from security import hash_ip, mask_secret


def test_mask_secret():
    assert mask_secret("apk_abcdefghijklmnop1234") == "apk_ab…1234"
    assert mask_secret("short") == "***"
    assert mask_secret("") == "***"


def test_hash_ip_is_keyed_when_secret_set(monkeypatch):
    monkeypatch.setenv("AIPAYGEN_IP_HASH_SECRET", "s3cret")
    keyed = hash_ip("203.0.113.9")
    assert keyed != hashlib.sha256(b"203.0.113.9").hexdigest()[:16]
    assert keyed == hash_ip("203.0.113.9") and len(keyed) == 16
    assert len(hash_ip("203.0.113.9", 32)) == 32
    monkeypatch.setenv("AIPAYGEN_IP_HASH_SECRET", "other")
    assert hash_ip("203.0.113.9") != keyed


def test_hash_ip_falls_back_to_v1_hash_without_secret(monkeypatch):
    monkeypatch.delenv("AIPAYGEN_IP_HASH_SECRET", raising=False)
    assert hash_ip("203.0.113.9", 32) == hashlib.sha256(b"203.0.113.9").hexdigest()[:32]
