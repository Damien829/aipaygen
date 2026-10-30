"""Tests for payment and security improvements — daily spend limits, key rotation,
billing audit, key scoping, Stripe idempotency, trial credit tracking, tiered rate limits."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


@pytest.fixture(scope="module")
def setup_dbs():
    from api_keys import init_keys_db
    from billing_audit import init_audit_db
    init_keys_db()
    init_audit_db()


@pytest.fixture(scope="module")
def client(setup_dbs):
    from app import app
    app.config["TESTING"] = True
    from helpers import _identity_rate, _ip_rate
    _identity_rate.clear()
    _ip_rate.clear()
    with app.test_client() as c:
        yield c


# ── API Key Management ──────────────────────────────────────────────────────

class TestApiKeyFeatures:
    def test_generate_key_with_daily_limit(self, setup_dbs):
        from api_keys import generate_key, get_key_status
        key_data = generate_key(initial_balance=5.0, label="test")
        status = get_key_status(key_data["key"])
        assert status["daily_spend_limit"] == 10.0  # default

    def test_set_daily_spend_limit(self, setup_dbs):
        from api_keys import generate_key, set_daily_spend_limit, get_key_status
        key_data = generate_key(initial_balance=5.0)
        assert set_daily_spend_limit(key_data["key"], 25.0)
        status = get_key_status(key_data["key"])
        assert status["daily_spend_limit"] == 25.0

    def test_daily_spend_limit_max_50(self, setup_dbs):
        from api_keys import generate_key, set_daily_spend_limit, get_key_status
        key_data = generate_key(initial_balance=5.0)
        set_daily_spend_limit(key_data["key"], 100.0)  # should be capped at 50
        status = get_key_status(key_data["key"])
        assert status["daily_spend_limit"] == 50.0

    def test_check_daily_spend(self, setup_dbs):
        from api_keys import generate_key, check_daily_spend, set_daily_spend_limit
        key_data = generate_key(initial_balance=5.0)
        set_daily_spend_limit(key_data["key"], 1.0)
        ok, remaining = check_daily_spend(key_data["key"], 0.50)
        assert ok is True
        assert remaining == 1.0

    def test_daily_spend_limit_blocks(self, setup_dbs):
        from api_keys import generate_key, set_daily_spend_limit, deduct
        key_data = generate_key(initial_balance=5.0)
        set_daily_spend_limit(key_data["key"], 0.01)
        # First deduction should succeed
        assert deduct(key_data["key"], 0.01) is True
        # Second should fail — daily limit reached
        assert deduct(key_data["key"], 0.01) is False


class TestKeyRotation:
    def test_rotate_key(self, setup_dbs):
        from api_keys import generate_key, rotate_key, validate_key
        key_data = generate_key(initial_balance=10.0, label="rotate-test")
        old_key = key_data["key"]
        result = rotate_key(old_key)
        assert result is not None
        assert result["balance_usd"] == 10.0
        assert result["new_key"].startswith("apk_")
        # Old key should be deactivated
        assert validate_key(old_key) is None
        # New key should be active
        new_data = validate_key(result["new_key"])
        assert new_data is not None
        assert new_data["balance_usd"] == 10.0

    def test_rotate_nonexistent_key(self, setup_dbs):
        from api_keys import rotate_key
        assert rotate_key("apk_nonexistent") is None


class TestKeyScoping:
    def test_set_and_get_allowed_tools(self, setup_dbs):
        from api_keys import generate_key, set_allowed_tools, get_allowed_tools
        key_data = generate_key(initial_balance=1.0)
        assert get_allowed_tools(key_data["key"]) is None  # unrestricted
        set_allowed_tools(key_data["key"], ["summarize", "translate"])
        tools = get_allowed_tools(key_data["key"])
        assert "summarize" in tools
        assert "translate" in tools
        assert len(tools) == 2

    def test_clear_allowed_tools(self, setup_dbs):
        from api_keys import generate_key, set_allowed_tools, get_allowed_tools
        key_data = generate_key(initial_balance=1.0)
        set_allowed_tools(key_data["key"], ["summarize"])
        set_allowed_tools(key_data["key"], [])
        assert get_allowed_tools(key_data["key"]) is None


class TestTierDetection:
    def test_tier_free(self, setup_dbs):
        from api_keys import get_key_tier
        assert get_key_tier("apk_nonexistent") == "free"

    def test_tier_starter(self, setup_dbs):
        from api_keys import generate_key, get_key_tier
        key_data = generate_key(initial_balance=1.0)
        assert get_key_tier(key_data["key"]) == "starter"

    def test_tier_pro(self, setup_dbs):
        from api_keys import generate_key, get_key_tier
        key_data = generate_key(initial_balance=5.0)
        assert get_key_tier(key_data["key"]) == "pro"

    def test_tier_enterprise(self, setup_dbs):
        from api_keys import generate_key, get_key_tier
        key_data = generate_key(initial_balance=15.0)
        assert get_key_tier(key_data["key"]) == "enterprise"

    def test_tier_rate_limits(self, setup_dbs):
        from api_keys import get_tier_rate_limit
        assert get_tier_rate_limit("free") == 20
        assert get_tier_rate_limit("starter") == 60
        assert get_tier_rate_limit("pro") == 120
        assert get_tier_rate_limit("enterprise") == 300


# ── Stripe Idempotency ──────────────────────────────────────────────────────

class TestStripeIdempotency:
    def test_event_not_processed(self, setup_dbs):
        from api_keys import is_stripe_event_processed
        assert is_stripe_event_processed("evt_test_123") is False

    def test_mark_event_processed(self, setup_dbs):
        from api_keys import is_stripe_event_processed, mark_stripe_event_processed
        mark_stripe_event_processed("evt_test_456")
        assert is_stripe_event_processed("evt_test_456") is True

    def test_double_mark_is_safe(self, setup_dbs):
        from api_keys import mark_stripe_event_processed
        mark_stripe_event_processed("evt_test_789")
        mark_stripe_event_processed("evt_test_789")  # should not raise


# ── Trial Credits Tracking ──────────────────────────────────────────────────

class TestTrialCredits:
    def test_first_ip_gets_trial(self, setup_dbs):
        import secrets
        from api_keys import has_received_trial_credits, mark_trial_credits_used
        unique_ip = f"192.168.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
        assert has_received_trial_credits(unique_ip) is False
        mark_trial_credits_used(unique_ip)
        assert has_received_trial_credits(unique_ip) is True

    def test_second_ip_no_trial(self, setup_dbs):
        import secrets
        from api_keys import has_received_trial_credits, mark_trial_credits_used
        unique_ip = f"10.{secrets.randbelow(255)}.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
        mark_trial_credits_used(unique_ip)
        assert has_received_trial_credits(unique_ip) is True


# ── Key Gen Rate Limiting ───────────────────────────────────────────────────

class TestKeyGenRate:
    def test_under_limit(self, setup_dbs):
        import secrets
        from api_keys import check_key_gen_rate, record_key_gen
        ip = f"172.16.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
        assert check_key_gen_rate(ip, max_per_day=5) is True
        record_key_gen(ip)
        assert check_key_gen_rate(ip, max_per_day=5) is True

    def test_at_limit(self, setup_dbs):
        import secrets
        from api_keys import check_key_gen_rate, record_key_gen
        ip = f"172.17.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
        for _ in range(5):
            record_key_gen(ip)
        assert check_key_gen_rate(ip, max_per_day=5) is False


# ── Billing Audit ───────────────────────────────────────────────────────────

class TestBillingAudit:
    def test_log_and_query(self, setup_dbs):
        from billing_audit import log_audit, get_audit_log
        log_audit("test_event", api_key="apk_testkey123456", amount_usd=1.0,
                  balance_after=4.0, endpoint="/test", ip="1.2.3.4")
        logs = get_audit_log(api_key_masked="apk_test...3456", event_type="test_event")
        assert len(logs) >= 1
        assert logs[0]["amount_usd"] == 1.0

    def test_deduction_creates_audit(self, setup_dbs):
        from api_keys import generate_key, deduct
        from billing_audit import get_audit_log
        key_data = generate_key(initial_balance=5.0, label="audit-test")
        deduct(key_data["key"], 0.01, endpoint="/test-audit")
        masked = key_data["key"][:8] + "..." + key_data["key"][-4:]
        logs = get_audit_log(api_key_masked=masked, event_type="deduction")
        assert len(logs) >= 1
        assert logs[0]["endpoint"] == "/test-audit"


# ── Route Tests ─────────────────────────────────────────────────────────────

class TestRotateKeyRoute:
    def test_rotate_key_no_auth(self, client):
        r = client.post("/auth/rotate-key")
        assert r.status_code == 401

    def test_rotate_key_success(self, client, setup_dbs):
        from api_keys import generate_key
        key_data = generate_key(initial_balance=5.0, label="rotate-route")
        r = client.post("/auth/rotate-key",
                        headers={"Authorization": f"Bearer {key_data['key']}"})
        assert r.status_code == 200
        data = r.get_json()
        assert "new_key" in data
        assert data["balance_usd"] == 5.0


class TestSetAllowedToolsRoute:
    def test_set_tools(self, client, setup_dbs):
        from api_keys import generate_key
        key_data = generate_key(initial_balance=1.0)
        r = client.post("/auth/set-allowed-tools",
                        json={"tools": ["summarize", "translate"]},
                        headers={"Authorization": f"Bearer {key_data['key']}"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["allowed_tools"] == ["summarize", "translate"]


class TestSetDailyLimitRoute:
    def test_set_limit(self, client, setup_dbs):
        from api_keys import generate_key
        key_data = generate_key(initial_balance=1.0)
        r = client.post("/auth/set-daily-limit",
                        json={"limit_usd": 25.0},
                        headers={"Authorization": f"Bearer {key_data['key']}"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["daily_spend_limit"] == 25.0

    def test_set_limit_out_of_range(self, client, setup_dbs):
        from api_keys import generate_key
        key_data = generate_key(initial_balance=1.0)
        r = client.post("/auth/set-daily-limit",
                        json={"limit_usd": 100.0},
                        headers={"Authorization": f"Bearer {key_data['key']}"})
        assert r.status_code == 400
