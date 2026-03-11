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
        # Flask returns 415 for GET without content-type when route calls get_json;
        # with explicit content-type header, the route properly returns 400.
        r = client.get("/auth/status?key=",
                       content_type="application/json")
        assert r.status_code == 400
        data = r.get_json()
        assert "error" in data

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

    def test_success_page_with_session_id(self, client):
        """Query params are ignored server-side; page always renders."""
        r = client.get("/buy-credits/success?session_id=cs_test_123")
        assert r.status_code == 200
        assert r.content_type.startswith("text/html")


# ── Free Tier Enforcement ─────────────────────────────────────────────────

class TestFreeTierEnforcement:
    @patch("routes.auth.generate_key")
    @patch("routes.auth.check_identity_rate_limit", return_value=True)
    def test_generate_key_always_zero_balance(self, mock_rl, mock_gen, client):
        """Free tier: keys generated via /auth/generate-key always start at $0."""
        mock_gen.return_value = {
            "key": "apk_free", "balance_usd": 0.0, "label": "",
            "created_at": "2026-01-01T00:00:00",
        }
        r = client.post("/auth/generate-key", json={})
        assert r.status_code == 200
        mock_gen.assert_called_once_with(initial_balance=0.0, label="")

    @patch("routes.auth.check_identity_rate_limit", return_value=False)
    def test_rate_limit_blocks_key_generation(self, mock_rl, client):
        r = client.post("/auth/generate-key", json={"label": "flood"})
        assert r.status_code == 429

    @patch("routes.auth.STRIPE_SECRET_KEY", "")
    def test_credits_buy_post_requires_payment(self, client):
        """Without x402 or API key bypass, POST /credits/buy must return 402."""
        r = client.post("/credits/buy", json={"amount_usd": 5.0})
        assert r.status_code == 402


# ── Credits Buy with API Key Bypass ──────────────────────────────────────

class TestCreditsBuyWithBypass:
    @patch("routes.auth.generate_key")
    @patch("routes.auth.funnel_log_event")
    def test_credits_buy_with_apikey_bypass(self, mock_funnel, mock_gen, client):
        """X_APIKEY_BYPASS environ triggers key generation without Stripe."""
        mock_gen.return_value = {
            "key": "apk_bypass", "balance_usd": 20.0, "label": "credit-pack",
            "created_at": "2026-01-01",
        }
        # Simulate WSGI middleware setting X_APIKEY_BYPASS
        from app import app
        with app.test_request_context():
            with app.test_client() as c:
                # We need to set environ; use a custom approach
                r = c.post("/credits/buy",
                           json={"amount_usd": 20.0, "label": "bypass-test"},
                           environ_base={"X_APIKEY_BYPASS": "1"})
                assert r.status_code == 200
                data = r.get_json()
                assert data["key"] == "apk_bypass"
                assert data["balance_usd"] == 20.0


# ── Stripe Create-Checkout Edge Cases ───────────────────────────────────

class TestStripeCreateCheckoutEdgeCases:
    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_all_valid_amounts(self, mock_funnel, mock_stripe, client):
        """All 7 valid amounts should succeed."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/s"
        mock_session.id = "cs_valid"
        mock_stripe.checkout.Session.create.return_value = mock_session
        for amt in (1, 5, 10, 15, 20, 25, 50):
            r = client.post("/stripe/create-checkout", json={"amount": amt})
            assert r.status_code == 200, f"amount={amt} failed"

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    def test_non_apk_existing_key_treated_as_new(self, client):
        """existing_key that doesn't start with 'apk_' is treated as new."""
        with patch("routes.auth._stripe") as mock_stripe, \
             patch("routes.auth.funnel_log_event"):
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/s"
            mock_session.id = "cs_nonapk"
            mock_stripe.checkout.Session.create.return_value = mock_session
            r = client.post("/stripe/create-checkout",
                            json={"amount": 5, "existing_key": "not_an_apk_key"})
            assert r.status_code == 200
            call_kwargs = mock_stripe.checkout.Session.create.call_args
            assert call_kwargs[1]["client_reference_id"] == "new"
            assert call_kwargs[1]["metadata"]["action"] == "new"

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_label_truncated_at_60_chars(self, mock_funnel, mock_stripe, client):
        """Labels longer than 60 chars should be truncated."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/s"
        mock_session.id = "cs_long"
        mock_stripe.checkout.Session.create.return_value = mock_session
        long_label = "x" * 100
        r = client.post("/stripe/create-checkout",
                        json={"amount": 5, "label": long_label})
        assert r.status_code == 200
        call_kwargs = mock_stripe.checkout.Session.create.call_args
        assert len(call_kwargs[1]["metadata"]["label"]) == 60

    @patch("routes.auth.STRIPE_SECRET_KEY", "sk_test_xxx")
    @patch("routes.auth._stripe")
    @patch("routes.auth.funnel_log_event")
    def test_default_amount_is_20(self, mock_funnel, mock_stripe, client):
        """If no amount is provided, default to 20."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/s"
        mock_session.id = "cs_default"
        mock_stripe.checkout.Session.create.return_value = mock_session
        r = client.post("/stripe/create-checkout", json={})
        assert r.status_code == 200
        call_kwargs = mock_stripe.checkout.Session.create.call_args
        assert call_kwargs[1]["line_items"][0]["price_data"]["unit_amount"] == 2000


# ── Stripe Webhook Extended ──────────────────────────────────────────────

class TestStripeWebhookExtended:
    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_webhook_sends_email_on_new_key(self, mock_gen, mock_notify,
                                             mock_log, mock_stripe, client):
        """When customer_email is present, email and account linking are attempted."""
        mock_gen.return_value = {"key": "apk_emailtest"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_email",
                    "metadata": {"amount": "10", "action": "new", "label": "email-test"},
                    "customer_details": {"email": "buyer@example.com"},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.return_value = None
        with patch("email_service.send_api_key_email") as mock_send_key, \
             patch("email_service.send_welcome_email") as mock_welcome, \
             patch("accounts.create_or_get_account", return_value={"id": "acct_1"}) as mock_acct, \
             patch("accounts.link_key_to_account") as mock_link:
            r = client.post("/stripe/webhook", data=b"payload",
                            headers={"Stripe-Signature": "valid"})
            assert r.status_code == 200
            mock_send_key.assert_called_once_with("buyer@example.com", "apk_emailtest", 10.0)
            mock_welcome.assert_called_once_with("buyer@example.com", "apk_emailtest")
            mock_acct.assert_called_once_with("buyer@example.com")
            mock_link.assert_called_once_with("acct_1", "apk_emailtest")

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_webhook_referral_conversion(self, mock_gen, mock_notify,
                                          mock_log, mock_stripe, client):
        """When ref_agent is in metadata, record_conversion is called."""
        mock_gen.return_value = {"key": "apk_ref"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_ref",
                    "metadata": {"amount": "25", "action": "new", "label": "",
                                 "ref_agent": "agent-abc"},
                    "customer_details": {"email": ""},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.return_value = None
        with patch("routes.auth.record_conversion") as mock_conv:
            r = client.post("/stripe/webhook", data=b"payload",
                            headers={"Stripe-Signature": "valid"})
            assert r.status_code == 200
            mock_conv.assert_called_once_with("agent-abc", "stripe_purchase", 25.0)

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_webhook_email_failure_doesnt_break(self, mock_gen, mock_notify,
                                                  mock_log, mock_stripe, client):
        """If email sending fails, webhook still returns 200."""
        mock_gen.return_value = {"key": "apk_emailfail"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_emailfail",
                    "metadata": {"amount": "5", "action": "new", "label": ""},
                    "customer_details": {"email": "fail@example.com"},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.return_value = None
        with patch("email_service.send_api_key_email", side_effect=Exception("SMTP error")):
            r = client.post("/stripe/webhook", data=b"payload",
                            headers={"Stripe-Signature": "valid"})
            assert r.status_code == 200
            assert r.get_json()["received"] is True

    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_webhook_stripe_metadata_update_failure(self, mock_gen, mock_notify,
                                                      mock_log, mock_stripe, client):
        """If Stripe metadata update fails, webhook still returns 200."""
        mock_gen.return_value = {"key": "apk_metafail"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_metafail",
                    "metadata": {"amount": "10", "action": "new", "label": ""},
                    "customer_details": {"email": ""},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.side_effect = Exception("Stripe API down")
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200


# ── Key Status Extended ──────────────────────────────────────────────────

class TestKeyStatusExtended:
    @patch("routes.auth._stripe")
    def test_key_status_balance_usd_in_metadata(self, mock_stripe, client):
        """When balance_usd is in Stripe metadata, it's returned."""
        mock_session = MagicMock()
        mock_session.metadata = {"api_key": "apk_bal", "balance_usd": "50.0"}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        r = client.get("/auth/key-status?session_id=cs_bal")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ready"] is True
        assert data["balance"] == "50.0"

    @patch("routes.auth._stripe")
    def test_key_status_falls_back_to_amount(self, mock_stripe, client):
        """When balance_usd is missing, falls back to amount field."""
        mock_session = MagicMock()
        mock_session.metadata = {"api_key": "apk_fb", "amount": "20"}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        r = client.get("/auth/key-status?session_id=cs_fb")
        assert r.status_code == 200
        data = r.get_json()
        assert data["balance"] == "20"


# ── Webhook Registration Edge Cases ─────────────────────────────────────

class TestWebhookEdgeCases:
    @patch("webhook_dispatch.register_webhook", return_value=None)
    def test_register_webhook_returns_none(self, mock_reg, client):
        """When register_webhook returns None (e.g., DB error), return 400."""
        r = client.post("/webhooks/register",
                        json={"url": "https://valid.com/hook", "events": ["balance_low"]},
                        headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 400
        assert "Failed" in r.get_json()["error"]

    def test_register_webhook_empty_events(self, client):
        """Empty events list should return 400."""
        r = client.post("/webhooks/register",
                        json={"url": "https://valid.com/hook", "events": []},
                        headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 400

    def test_register_webhook_non_bearer_auth(self, client):
        """Auth header that doesn't start with 'Bearer apk_' is rejected."""
        r = client.post("/webhooks/register",
                        json={"url": "https://valid.com/hook", "events": ["a"]},
                        headers={"Authorization": "Bearer sk_not_apk"})
        assert r.status_code == 401

    def test_register_webhook_no_url(self, client):
        """Missing url should return 400."""
        r = client.post("/webhooks/register",
                        json={"events": ["balance_low"]},
                        headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 400

    @patch("webhook_dispatch.list_webhooks")
    def test_list_webhooks_returns_data(self, mock_list, client):
        """list_webhooks returns non-empty list."""
        mock_list.return_value = [
            {"id": 1, "url": "https://example.com/hook", "events": ["balance_low"]},
        ]
        r = client.get("/webhooks",
                       headers={"Authorization": "Bearer apk_testkey"})
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["webhooks"]) == 1
        assert data["webhooks"][0]["id"] == 1


# ── In-Memory Session Map ────────────────────────────────────────────────

class TestSessionKeyMap:
    @patch("routes.auth.STRIPE_WEBHOOK_SECRET", "whsec_test")
    @patch("routes.auth._stripe")
    @patch("routes.auth.log_payment")
    @patch("routes.auth._notify_checkout")
    @patch("routes.auth.generate_key")
    def test_key_status_from_memory_map(self, mock_gen, mock_notify,
                                         mock_log, mock_stripe, client):
        """After webhook creates key, /auth/key-status finds it via in-memory map."""
        mock_gen.return_value = {"key": "apk_memmap"}
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_memtest",
                    "metadata": {"amount": "10", "action": "new", "label": "map-test"},
                    "customer_details": {"email": ""},
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.checkout.Session.modify.return_value = None
        r = client.post("/stripe/webhook", data=b"payload",
                        headers={"Stripe-Signature": "valid"})
        assert r.status_code == 200

        with patch("routes.auth.get_key_status", return_value={"balance_usd": 10.0}):
            r = client.get("/auth/key-status?session_id=cs_memtest")
            assert r.status_code == 200
            data = r.get_json()
            assert data["ready"] is True
            assert data["api_key"] == "apk_memmap"


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
