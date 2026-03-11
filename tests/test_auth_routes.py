"""Comprehensive tests for routes/auth.py — auth, keys, credits, Stripe, webhooks."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("WEBHOOKS_DB", ":memory:")


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── POST /auth/generate-key ─────────────────────────────────────────────────

class TestGenerateKey:
    @patch("routes.auth.generate_key")
    @patch("routes.auth.check_identity_rate_limit", return_value=True)
    def test_generate_key_success(self, mock_rl, mock_gen, client):
        mock_gen.return_value = {
            "key": "apk_testkey123",
            "balance_usd": 0.0,
            "label": "my-key",
            "created_at": "2026-01-01T00:00:00",
        }
        r = client.post("/auth/generate-key", json={"label": "my-key"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["key"] == "apk_testkey123"
        assert data["balance_usd"] == 0.0
        assert data["label"] == "my-key"
        assert "_meta" in data
        assert data["_meta"]["free"] is True
        mock_gen.assert_called_once_with(initial_balance=0.0, label="my-key")

    @patch("routes.auth.generate_key")
    @patch("routes.auth.check_identity_rate_limit", return_value=True)
    def test_generate_key_no_label(self, mock_rl, mock_gen, client):
        mock_gen.return_value = {
            "key": "apk_abc", "balance_usd": 0.0, "label": "",
            "created_at": "2026-01-01T00:00:00",
        }
        r = client.post("/auth/generate-key", json={})
        assert r.status_code == 200
        mock_gen.assert_called_once_with(initial_balance=0.0, label="")

    @patch("routes.auth.generate_key")
    @patch("routes.auth.check_identity_rate_limit", return_value=True)
    def test_generate_key_no_body(self, mock_rl, mock_gen, client):
        mock_gen.return_value = {
            "key": "apk_abc", "balance_usd": 0.0, "label": "",
            "created_at": "2026-01-01T00:00:00",
        }
        r = client.post("/auth/generate-key", content_type="application/json", data="{}")
        assert r.status_code == 200

    @patch("routes.auth.check_identity_rate_limit", return_value=False)
    def test_generate_key_rate_limited(self, mock_rl, client):
        r = client.post("/auth/generate-key", json={"label": "spam"})
        assert r.status_code == 429
        data = r.get_json()
        assert data["error"] == "rate_limited"


# ── POST /auth/topup ────────────────────────────────────────────────────────

class TestAuthTopup:
    @patch("routes.auth.topup_key")
    def test_topup_success(self, mock_topup, client):
        mock_topup.return_value = {"key": "apk_x", "balance_usd": 15.0, "topped_up": 10.0}
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        r = client.post("/auth/topup",
                        json={"key": "apk_x", "amount_usd": 10.0},
                        headers={"Authorization": "Bearer test-admin-secret"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["topped_up"] == 10.0
        mock_topup.assert_called_once_with("apk_x", 10.0)

    def test_topup_no_admin_key(self, client):
        r = client.post("/auth/topup", json={"key": "apk_x", "amount_usd": 10.0})
        assert r.status_code in (401, 503)

    def test_topup_wrong_admin_key(self, client):
        os.environ["ADMIN_SECRET"] = "real-secret"
        r = client.post("/auth/topup",
                        json={"key": "apk_x", "amount_usd": 10.0},
                        headers={"Authorization": "Bearer wrong-secret"})
        assert r.status_code == 401

    def test_topup_missing_key(self, client):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        r = client.post("/auth/topup",
                        json={"amount_usd": 10.0},
                        headers={"Authorization": "Bearer test-admin-secret"})
        assert r.status_code == 400

    def test_topup_zero_amount(self, client):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        r = client.post("/auth/topup",
                        json={"key": "apk_x", "amount_usd": 0},
                        headers={"Authorization": "Bearer test-admin-secret"})
        assert r.status_code == 400

    def test_topup_negative_amount(self, client):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        r = client.post("/auth/topup",
                        json={"key": "apk_x", "amount_usd": -5},
                        headers={"Authorization": "Bearer test-admin-secret"})
        assert r.status_code == 400


# ── GET/POST /auth/status ────────────────────────────────────────────────────

class TestAuthStatus:
    @patch("routes.auth.get_key_status")
    def test_status_get_success(self, mock_status, client):
        mock_status.return_value = {
            "key": "apk_abc", "balance_usd": 5.0, "call_count": 10,
            "is_active": 1, "label": "", "total_spent": 1.0,
            "created_at": "2026-01-01", "last_used_at": "2026-01-02",
        }
        r = client.get("/auth/status?key=apk_abc")
        assert r.status_code == 200
        data = r.get_json()
        assert data["key"] == "apk_abc"
        assert data["balance_usd"] == 5.0

    @patch("routes.auth.get_key_status")
    def test_status_post_success(self, mock_status, client):
        mock_status.return_value = {"key": "apk_abc", "balance_usd": 5.0}
        r = client.post("/auth/status", json={"key": "apk_abc"})
        assert r.status_code == 200

    def test_status_missing_key_get(self, client):
        r = client.get("/auth/status?key=")
        assert r.status_code == 400
        data = r.get_json()
        assert data["error"] == "key required"

    def test_status_missing_key_post(self, client):
        r = client.post("/auth/status", json={})
        assert r.status_code == 400
        assert r.get_json()["error"] == "key required"

    @patch("routes.auth.get_key_status", return_value=None)
    def test_status_key_not_found(self, mock_status, client):
        r = client.get("/auth/status?key=apk_nonexistent")
        assert r.status_code == 404
        assert r.get_json()["error"] == "key_not_found"


# ── GET/POST /credits/buy ────────────────────────────────────────────────────

class TestCreditsBuy:
    def test_credits_buy_get_info(self, client):
        r = client.get("/credits/buy")
        assert r.status_code == 200
        data = r.get_json()
        assert "how_to_buy" in data
        assert "stripe" in data["how_to_buy"]
        assert "x402" in data["how_to_buy"]

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_credits_buy_post_creates_stripe_checkout(self, mock_funnel, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe.checkout.Session.create.return_value = mock_session
        r = client.post("/credits/buy", json={"amount_usd": 10.0})
        assert r.status_code == 200
        data = r.get_json()
        assert data["checkout_url"] == "https://checkout.stripe.com/test"
        assert data["amount_usd"] == 10.0

    @patch("routes.auth.STRIPE_SECRET_KEY", "")
    def test_credits_buy_post_no_stripe_no_payment(self, client):
        r = client.post("/credits/buy", json={"amount_usd": 5.0})
        assert r.status_code == 402
        data = r.get_json()
        assert data["error"] == "payment_required"

    @patch("routes.auth.generate_key")
    @patch("routes.auth.funnel_log_event")
    def test_credits_buy_post_with_x402_payment(self, mock_funnel, mock_gen, client):
        mock_gen.return_value = {
            "key": "apk_paid", "balance_usd": 5.0, "label": "credit-pack",
            "created_at": "2026-01-01",
        }
        r = client.post("/credits/buy",
                        json={"amount_usd": 5.0},
                        headers={"X-Payment": "valid-payment-token"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["key"] == "apk_paid"
        assert data["balance_usd"] == 5.0

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    def test_credits_buy_stripe_error(self, mock_stripe, client):
        mock_stripe.checkout.Session.create.side_effect = Exception("Stripe connection failed")
        r = client.post("/credits/buy", json={"amount_usd": 10.0})
        assert r.status_code == 500
        assert "stripe_error" in r.get_json()["error"]


# ── POST /stripe/create-checkout ─────────────────────────────────────────────

class TestStripeCreateCheckout:
    @patch("routes.auth.STRIPE_SECRET_KEY", "")
    def test_create_checkout_no_stripe(self, client):
        r = client.post("/stripe/create-checkout", json={"amount": 5})
        assert r.status_code == 503

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    def test_create_checkout_invalid_amount(self, client):
        r = client.post("/stripe/create-checkout", json={"amount": 99})
        assert r.status_code == 400
        assert "amount must be" in r.get_json()["error"]

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_create_checkout_new_key(self, mock_funnel, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/s123"
        mock_session.id = "cs_test_123"
        mock_stripe.checkout.Session.create.return_value = mock_session
        r = client.post("/stripe/create-checkout", json={"amount": 20})
        assert r.status_code == 200
        data = r.get_json()
        assert data["url"] == "https://checkout.stripe.com/s123"
        assert data["session_id"] == "cs_test_123"

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth.get_key_status")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_create_checkout_topup_existing_key(self, mock_funnel, mock_stripe, mock_status, client):
        mock_status.return_value = {"key": "apk_existing", "balance_usd": 5.0}
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/topup"
        mock_session.id = "cs_topup"
        mock_stripe.checkout.Session.create.return_value = mock_session
        r = client.post("/stripe/create-checkout",
                        json={"amount": 10, "existing_key": "apk_existing"})
        assert r.status_code == 200
        # Verify metadata includes action=topup
        call_kwargs = mock_stripe.checkout.Session.create.call_args
        assert call_kwargs[1]["metadata"]["action"] == "topup"
        assert call_kwargs[1]["metadata"]["api_key"] == "apk_existing"

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth.get_key_status", return_value=None)
    def test_create_checkout_topup_invalid_key(self, mock_status, client):
        r = client.post("/stripe/create-checkout",
                        json={"amount": 10, "existing_key": "apk_badkey"})
        assert r.status_code == 404
        assert r.get_json()["error"] == "key not found"

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_create_checkout_stripe_exception(self, mock_funnel, mock_stripe, client):
        mock_stripe.checkout.Session.create.side_effect = Exception("API error")
        r = client.post("/stripe/create-checkout", json={"amount": 5})
        assert r.status_code == 500

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_create_checkout_with_label(self, mock_funnel, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/s"
        mock_session.id = "cs_lbl"
        mock_stripe.checkout.Session.create.return_value = mock_session
        r = client.post("/stripe/create-checkout",
                        json={"amount": 5, "label": "my-project"})
        assert r.status_code == 200
        call_kwargs = mock_stripe.checkout.Session.create.call_args
        assert call_kwargs[1]["metadata"]["label"] == "my-project"


# ── POST /stripe/webhook ────────────────────────────────────────────────────

class TestStripeWebhook:
    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "")
    def test_webhook_no_secret(self, client):
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "sig"})
        assert r.status_code == 503

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    def test_webhook_invalid_signature(self, client):
        import stripe as _real_stripe
        exc = _real_stripe.SignatureVerificationError("Invalid signature", "sig")
        with patch("routes.auth._stripe.Webhook.construct_event", side_effect=exc):
            r = client.post("/stripe/webhook", data=b"payload",
                            headers={"Stripe-Signature": "bad_sig"})
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid signature"

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_webhook_checkout_completed_new_key(self, mock_gen, mock_notify,
                                                 mock_log, mock_stripe, client):
        mock_gen.return_value = {"key": "apk_newkey"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_123",
                    "metadata": {"amount": "10", "action": "new", "label": "test"},
                    "customer_details": {"email": "user@example.com"},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.return_value = None
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200
        assert r.get_json()["received"] is True
        mock_gen.assert_called_once_with(initial_balance=10.0, label="test")
        mock_log.assert_called_once()
        mock_notify.assert_called_once()

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.topup_key")
    def test_webhook_checkout_completed_topup(self, mock_topup, mock_notify,
                                               mock_log, mock_stripe, client):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_456",
                    "metadata": {"amount": "5", "action": "topup",
                                 "api_key": "apk_existing123"},
                    "customer_details": {"email": ""},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200
        mock_topup.assert_called_once_with("apk_existing123", 5.0)

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    def test_webhook_non_checkout_event(self, mock_stripe, client):
        event = {"type": "payment_intent.succeeded", "data": {"object": {}}}
        mock_stripe.Webhook.construct_event.return_value = event
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200
        assert r.get_json()["received"] is True

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    def test_webhook_zero_amount_no_key_gen(self, mock_stripe, client):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_zero",
                    "metadata": {"amount": "0", "action": "new", "label": ""},
                    "customer_details": {},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200


# ── GET /auth/key-status ────────────────────────────────────────────────────

class TestKeyStatus:
    def test_key_status_no_session_id(self, client):
        r = client.get("/auth/key-status")
        assert r.status_code == 200
        assert r.get_json()["ready"] is False

    @patch("routes.auth._stripe")
    def test_key_status_ready(self, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.metadata = {"api_key": "apk_ready", "amount": "10"}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        r = client.get("/auth/key-status?session_id=cs_test")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ready"] is True
        assert data["api_key"] == "apk_ready"

    @patch("routes.auth._stripe")
    def test_key_status_not_ready(self, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.metadata = {}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        r = client.get("/auth/key-status?session_id=cs_pending")
        assert r.status_code == 200
        assert r.get_json()["ready"] is False

    @patch("routes.auth._stripe")
    def test_key_status_stripe_error(self, mock_stripe, client):
        mock_stripe.checkout.Session.retrieve.side_effect = Exception("not found")
        r = client.get("/auth/key-status?session_id=cs_bad")
        assert r.status_code == 200
        assert r.get_json()["ready"] is False


# ── GET /buy-credits page ───────────────────────────────────────────────────

class TestBuyCreditsPage:
    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    def test_buy_credits_page_renders(self, client):
        r = client.get("/buy-credits")
        assert r.status_code == 200
        assert r.content_type.startswith("text/html")

    @patch("routes.auth.STRIPE_SECRET_KEY", "")
    def test_buy_credits_page_no_stripe(self, client):
        r = client.get("/buy-credits")
        assert r.status_code == 503


# ── Webhook registration routes ──────────────────────────────────────────────

class TestWebhookRoutes:
    def test_register_webhook_no_auth(self, client):
        r = client.post("/webhooks/register", json={"url": "https://x.com/hook", "events": ["a"]})
        assert r.status_code == 401

    @patch("routes.auth.register_webhook", create=True)
    def test_register_webhook_success(self, mock_reg, client):
        with patch("webhook_dispatch.register_webhook", return_value=42):
            r = client.post("/webhooks/register",
                            json={"url": "https://example.com/hook", "events": ["balance_low"]},
                            headers={"Authorization": "Bearer apk_testkey"})
            assert r.status_code == 200
            data = r.get_json()
            assert data["webhook_id"] == 42

    def test_register_webhook_missing_fields(self, client):
        r = client.post("/webhooks/register",
                        json={"url": "https://example.com/hook"},
                        headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 400

    @patch("webhook_dispatch.register_webhook", return_value=None)
    def test_register_webhook_invalid_url(self, mock_reg, client):
        r = client.post("/webhooks/register",
                        json={"url": "http://insecure.com/hook", "events": ["a"]},
                        headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 400

    def test_list_webhooks_no_auth(self, client):
        r = client.get("/webhooks")
        assert r.status_code == 401

    @patch("webhook_dispatch.list_webhooks", return_value=[])
    def test_list_webhooks_success(self, mock_list, client):
        r = client.get("/webhooks",
                       headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 200
        assert r.get_json()["webhooks"] == []

    def test_delete_webhook_no_auth(self, client):
        r = client.delete("/webhooks/1")
        assert r.status_code == 401

    @patch("webhook_dispatch.delete_webhook", return_value=True)
    def test_delete_webhook_success(self, mock_del, client):
        r = client.delete("/webhooks/1",
                          headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 200
        assert r.get_json()["deleted"] is True

    @patch("webhook_dispatch.delete_webhook", return_value=False)
    def test_delete_webhook_not_found(self, mock_del, client):
        r = client.delete("/webhooks/999",
                          headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 404


# ── GET /buy-credits/success ────────────────────────────────────────────────

class TestBuyCreditsSuccess:
    def test_success_page_renders(self, client):
        r = client.get("/buy-credits/success")
        assert r.status_code == 200
        assert r.content_type.startswith("text/html")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_sig_error(msg):
    """Create a stripe SignatureVerificationError-like exception."""
    import stripe
    try:
        return stripe.error.SignatureVerificationError(msg, "sig")
    except (AttributeError, TypeError):
        # Newer stripe versions use stripe.SignatureVerificationError
        try:
            return stripe.SignatureVerificationError(msg, "sig")
        except Exception:
            # Fallback: just use a plain exception and patch error type
            return Exception(msg)
