"""Tests for api_keys.py — key generation, balance, deduction, edge cases."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import tempfile
import sqlite3

# Use a temp DB for each test module run
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["API_KEYS_DB_PATH_OVERRIDE"] = _tmp.name

import api_keys

# Override DB_PATH to use temp file
api_keys.DB_PATH = _tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset DB before each test."""
    conn = sqlite3.connect(api_keys.DB_PATH)
    conn.execute("DROP TABLE IF EXISTS api_keys")
    conn.commit()
    conn.close()
    api_keys.init_keys_db()
    yield
    # cleanup after all tests
    try:
        conn = sqlite3.connect(api_keys.DB_PATH)
        conn.execute("DROP TABLE IF EXISTS api_keys")
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Key Generation ─────────────────────────────────────────────────────────


class TestGenerateKey:
    def test_generate_key_default_balance(self):
        result = api_keys.generate_key()
        assert result["key"].startswith("apk_")
        assert result["balance_usd"] == 0.0
        assert result["label"] == ""
        assert "created_at" in result

    def test_generate_key_with_balance(self):
        result = api_keys.generate_key(initial_balance=25.0)
        assert result["balance_usd"] == 25.0

    def test_generate_key_with_label(self):
        result = api_keys.generate_key(label="my-project")
        assert result["label"] == "my-project"

    def test_generate_key_unique(self):
        k1 = api_keys.generate_key()
        k2 = api_keys.generate_key()
        assert k1["key"] != k2["key"]

    def test_generate_key_persists(self):
        result = api_keys.generate_key(initial_balance=10.0, label="test")
        status = api_keys.get_key_status(result["key"])
        assert status is not None
        assert status["balance_usd"] == 10.0
        assert status["label"] == "test"


# ── Balance Checking ───────────────────────────────────────────────────────


class TestGetKeyStatus:
    def test_status_returns_all_fields(self):
        result = api_keys.generate_key(initial_balance=5.0, label="check")
        status = api_keys.get_key_status(result["key"])
        assert status["key"] == result["key"]
        assert status["balance_usd"] == 5.0
        assert status["label"] == "check"
        assert status["total_spent"] == 0.0
        assert status["call_count"] == 0
        assert status["is_active"] == 1
        assert status["created_at"] is not None
        assert status["last_used_at"] is None

    def test_status_nonexistent_key(self):
        assert api_keys.get_key_status("apk_doesnotexist") is None


class TestValidateKey:
    def test_validate_active_key(self):
        result = api_keys.generate_key(initial_balance=1.0)
        valid = api_keys.validate_key(result["key"])
        assert valid is not None
        assert valid["key"] == result["key"]
        assert valid["is_active"] == 1

    def test_validate_nonexistent_key(self):
        assert api_keys.validate_key("apk_fake") is None

    def test_validate_inactive_key(self):
        result = api_keys.generate_key()
        # Deactivate the key directly
        conn = sqlite3.connect(api_keys.DB_PATH)
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE key = ?", (result["key"],))
        conn.commit()
        conn.close()
        assert api_keys.validate_key(result["key"]) is None


# ── Topup ──────────────────────────────────────────────────────────────────


class TestTopupKey:
    def test_topup_success(self):
        result = api_keys.generate_key(initial_balance=5.0)
        topup = api_keys.topup_key(result["key"], 10.0)
        assert topup["balance_usd"] == 15.0
        assert topup["topped_up"] == 10.0
        assert topup["key"] == result["key"]

    def test_topup_nonexistent_key(self):
        topup = api_keys.topup_key("apk_nonexistent", 10.0)
        assert topup == {"error": "key_not_found"}

    def test_topup_updates_last_used(self):
        result = api_keys.generate_key()
        api_keys.topup_key(result["key"], 1.0)
        status = api_keys.get_key_status(result["key"])
        assert status["last_used_at"] is not None


# ── Deduction ──────────────────────────────────────────────────────────────


class TestDeduct:
    def test_deduct_success(self):
        result = api_keys.generate_key(initial_balance=10.0)
        assert api_keys.deduct(result["key"], 3.0) is True
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == pytest.approx(7.0)
        assert status["total_spent"] == pytest.approx(3.0)
        assert status["call_count"] == 1

    def test_deduct_insufficient_funds(self):
        result = api_keys.generate_key(initial_balance=1.0)
        assert api_keys.deduct(result["key"], 5.0) is False
        # Balance unchanged
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == 1.0
        assert status["call_count"] == 0

    def test_deduct_exact_balance(self):
        result = api_keys.generate_key(initial_balance=5.0)
        assert api_keys.deduct(result["key"], 5.0) is True
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == pytest.approx(0.0)

    def test_deduct_nonexistent_key(self):
        assert api_keys.deduct("apk_fake", 1.0) is False

    def test_deduct_inactive_key(self):
        result = api_keys.generate_key(initial_balance=10.0)
        conn = sqlite3.connect(api_keys.DB_PATH)
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE key = ?", (result["key"],))
        conn.commit()
        conn.close()
        assert api_keys.deduct(result["key"], 1.0) is False

    def test_deduct_multiple_calls_increment_count(self):
        result = api_keys.generate_key(initial_balance=10.0)
        api_keys.deduct(result["key"], 1.0)
        api_keys.deduct(result["key"], 2.0)
        api_keys.deduct(result["key"], 3.0)
        status = api_keys.get_key_status(result["key"])
        assert status["call_count"] == 3
        assert status["total_spent"] == pytest.approx(6.0)
        assert status["balance_usd"] == pytest.approx(4.0)


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_balance_deduct_zero(self):
        result = api_keys.generate_key(initial_balance=0.0)
        # Deducting zero from zero should succeed (balance >= 0)
        assert api_keys.deduct(result["key"], 0.0) is True

    def test_deduct_zero_from_positive_balance(self):
        result = api_keys.generate_key(initial_balance=5.0)
        assert api_keys.deduct(result["key"], 0.0) is True
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == 5.0
        assert status["call_count"] == 1  # still counts as a call

    def test_topup_inactive_key_no_balance_change(self):
        result = api_keys.generate_key(initial_balance=5.0)
        conn = sqlite3.connect(api_keys.DB_PATH)
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE key = ?", (result["key"],))
        conn.commit()
        conn.close()
        topup = api_keys.topup_key(result["key"], 10.0)
        # topup_key updates WHERE is_active=1, so balance stays at 5.0
        # but get_key_status still returns the row
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == 5.0


# ── Metered Deduction ──────────────────────────────────────────────────────


class TestDeductMetered:
    def test_metered_deduct_success(self):
        result = api_keys.generate_key(initial_balance=1.0)
        # 1000 input tokens at $3/M, 500 output tokens at $15/M
        info = api_keys.deduct_metered(result["key"], 1000, 500, 3.0, 15.0)
        assert info is not None
        expected_cost = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert info["cost"] == pytest.approx(expected_cost, abs=1e-6)
        assert info["balance_remaining"] < 1.0

    def test_metered_deduct_insufficient(self):
        result = api_keys.generate_key(initial_balance=0.000001)
        info = api_keys.deduct_metered(result["key"], 1_000_000, 1_000_000, 3.0, 15.0)
        assert info is None
        # Balance unchanged
        status = api_keys.get_key_status(result["key"])
        assert status["balance_usd"] == pytest.approx(0.000001)

    def test_metered_deduct_nonexistent_key(self):
        info = api_keys.deduct_metered("apk_fake", 100, 100, 3.0, 15.0)
        assert info is None

    def test_metered_deduct_zero_tokens(self):
        result = api_keys.generate_key(initial_balance=1.0)
        info = api_keys.deduct_metered(result["key"], 0, 0, 3.0, 15.0)
        assert info is not None
        assert info["cost"] == 0.0
        assert info["balance_remaining"] == pytest.approx(1.0)
