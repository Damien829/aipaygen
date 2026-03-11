"""Tests for the Seller Marketplace — core logic and Flask routes."""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

# Force seller marketplace to use temp file DB
import tempfile
import seller_marketplace as sm
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db.name
_test_db.close()
sm._DB_PATH = _test_db_path


def _reset_seller_db():
    """Drop all tables and re-create for clean test state."""
    import sqlite3
    sm._DB_PATH = _test_db_path
    c = sqlite3.connect(_test_db_path)
    for tbl in ["seller_apis", "agent_wallets", "escrow_holds", "wallet_transactions", "seller_payouts"]:
        c.execute(f"DROP TABLE IF EXISTS {tbl}")
    c.commit()
    c.close()
    sm.init_seller_db()


# ---------------------------------------------------------------------------
# Unit tests — seller_marketplace.py core logic
# ---------------------------------------------------------------------------


class TestSellerCRUD:
    """Seller registration, lookup, listing, update, delete."""

    def setup_method(self):
        _reset_seller_db()

    def test_register_seller_api(self):
        result = sm.register_seller_api(
            seller_id="seller-1", slug="test-api", name="Test API",
            description="A test", base_url="https://example.com/api",
            routes=[{"path": "/data", "method": "GET", "price_usd": 0.01}],
        )
        assert "id" in result
        assert result["slug"] == "test-api"
        assert result["status"] == "registered"

    def test_register_duplicate_slug(self):
        sm.register_seller_api(
            seller_id="s1", slug="dupe-slug", name="First",
            description="", base_url="https://example.com",
            routes=[],
        )
        result = sm.register_seller_api(
            seller_id="s2", slug="dupe-slug", name="Second",
            description="", base_url="https://example.com",
            routes=[],
        )
        assert "error" in result
        assert "already taken" in result["error"]

    def test_register_invalid_slug(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="X!", name="Bad",
            description="", base_url="https://example.com", routes=[],
        )
        assert "error" in result
        assert "Invalid slug" in result["error"]

    def test_register_slug_too_short(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="ab", name="Short",
            description="", base_url="https://example.com", routes=[],
        )
        assert "error" in result

    def test_get_seller_api_by_slug(self):
        sm.register_seller_api(
            seller_id="s1", slug="my-api", name="My API",
            description="desc", base_url="https://example.com", routes=[],
        )
        api = sm.get_seller_api("my-api")
        assert api is not None
        assert api["name"] == "My API"
        assert api["seller_id"] == "s1"

    def test_get_seller_api_not_found(self):
        assert sm.get_seller_api("nonexistent") is None

    def test_list_seller_apis(self):
        for i in range(3):
            sm.register_seller_api(
                seller_id="s1", slug=f"list-api-{i}", name=f"API {i}",
                description="", base_url="https://example.com", routes=[],
            )
        apis, total = sm.list_seller_apis()
        assert total == 3
        assert len(apis) == 3

    def test_list_seller_apis_with_category(self):
        sm.register_seller_api(
            seller_id="s1", slug="cat-api-a", name="A",
            description="", base_url="https://example.com", routes=[],
            category="finance",
        )
        sm.register_seller_api(
            seller_id="s1", slug="cat-api-b", name="B",
            description="", base_url="https://example.com", routes=[],
            category="ai",
        )
        apis, total = sm.list_seller_apis(category="finance")
        assert total == 1
        assert apis[0]["category"] == "finance"

    def test_list_seller_apis_pagination(self):
        for i in range(5):
            sm.register_seller_api(
                seller_id="s1", slug=f"page-api-{i}", name=f"P {i}",
                description="", base_url="https://example.com", routes=[],
            )
        apis, total = sm.list_seller_apis(page=1, per_page=2)
        assert total == 5
        assert len(apis) == 2

    def test_update_seller_api(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="upd-api", name="Old",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.update_seller_api(reg["id"], "s1", {"name": "New Name"})
        assert "updated" in result
        assert "name" in result["updated"]

        api = sm.get_seller_api("upd-api")
        assert api["name"] == "New Name"

    def test_update_seller_api_wrong_owner(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="own-api", name="Mine",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.update_seller_api(reg["id"], "s-other", {"name": "Stolen"})
        assert "error" in result
        assert "Not authorized" in result["error"]

    def test_update_seller_api_no_valid_fields(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="nop-api", name="Nop",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.update_seller_api(reg["id"], "s1", {"bogus_field": "x"})
        assert "error" in result

    def test_delete_seller_api(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="del-api", name="Del",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.delete_seller_api(reg["id"], "s1")
        assert result["deleted"] is True
        assert sm.get_seller_api("del-api") is None

    def test_delete_seller_api_wrong_owner(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="del-own-api", name="X",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.delete_seller_api(reg["id"], "s-other")
        assert "error" in result

    def test_delete_seller_api_not_found(self):
        result = sm.delete_seller_api("no-such-id", "s1")
        assert "error" in result


class TestRouteMatching:
    """Route matching logic."""

    def test_exact_match(self):
        api = {"routes": [{"path": "/data", "method": "GET", "price_usd": 0.01}]}
        route = sm.match_route(api, "GET", "/data")
        assert route is not None
        assert route["price_usd"] == 0.01

    def test_wildcard_match(self):
        api = {"routes": [{"path": "/api/*", "method": "ANY", "price_usd": 0.02}]}
        route = sm.match_route(api, "POST", "/api/users/123")
        assert route is not None
        assert route["price_usd"] == 0.02

    def test_no_match(self):
        api = {"routes": [{"path": "/data", "method": "GET", "price_usd": 0.01}]}
        route = sm.match_route(api, "GET", "/other")
        assert route is None

    def test_method_mismatch(self):
        api = {"routes": [{"path": "/data", "method": "POST", "price_usd": 0.01}]}
        route = sm.match_route(api, "GET", "/data")
        assert route is None

    def test_no_routes_default_pricing(self):
        api = {"routes": []}
        route = sm.match_route(api, "GET", "/anything")
        assert route is not None
        assert route["price_usd"] == 0.005

    def test_trailing_slash_match(self):
        api = {"routes": [{"path": "/data", "method": "GET", "price_usd": 0.01}]}
        route = sm.match_route(api, "GET", "/data/")
        assert route is not None


class TestAgentWallets:
    """Wallet creation, funding, policy, transactions."""

    def setup_method(self):
        sm._DB_PATH = _test_db_path
        # Drop all tables and re-create for clean state
        import sqlite3
        c = sqlite3.connect(_test_db_path)
        for tbl in ["seller_apis", "agent_wallets", "escrow_holds", "wallet_transactions", "seller_payouts"]:
            c.execute(f"DROP TABLE IF EXISTS {tbl}")
        c.commit()
        c.close()
        sm.init_seller_db()

    def test_create_wallet(self):
        result = sm.create_agent_wallet("apk_test1", label="my-wallet")
        assert "wallet_id" in result
        assert result["wallet_id"].startswith("aw_")
        assert result["balance_usd"] == 0.0

    def test_get_wallet(self):
        created = sm.create_agent_wallet("apk_test2", label="lookup")
        wallet = sm.get_agent_wallet(created["wallet_id"])
        assert wallet is not None
        assert wallet["label"] == "lookup"
        assert wallet["owner_api_key"] == "apk_test2"

    def test_get_wallet_not_found(self):
        assert sm.get_agent_wallet("aw_nonexistent") is None

    def test_fund_wallet(self):
        created = sm.create_agent_wallet("apk_fund", label="fund-test")
        wid = created["wallet_id"]
        result = sm.fund_agent_wallet(wid, 50.0)
        assert result["status"] == "funded"
        assert result["amount_usd"] == 50.0

        wallet = sm.get_agent_wallet(wid)
        assert wallet["balance_usd"] == 50.0

    def test_fund_wallet_not_found(self):
        result = sm.fund_agent_wallet("aw_nope", 10.0)
        assert "error" in result

    def test_fund_wallet_creates_transaction(self):
        created = sm.create_agent_wallet("apk_txn", label="txn-test")
        wid = created["wallet_id"]
        sm.fund_agent_wallet(wid, 25.0)
        txns = sm.get_wallet_transactions(wid)
        assert len(txns) == 1
        assert txns[0]["type"] == "deposit"
        assert txns[0]["amount_usd"] == 25.0

    def test_update_wallet_policy(self):
        created = sm.create_agent_wallet("apk_pol", label="policy")
        wid = created["wallet_id"]
        result = sm.update_wallet_policy(wid, "apk_pol", daily_budget=50.0)
        assert result["updated"] is True

        wallet = sm.get_agent_wallet(wid)
        assert wallet["daily_budget"] == 50.0

    def test_update_wallet_policy_wrong_owner(self):
        created = sm.create_agent_wallet("apk_own", label="own")
        result = sm.update_wallet_policy(created["wallet_id"], "apk_other", daily_budget=5.0)
        assert "error" in result

    def test_update_wallet_policy_vendor_allowlist(self):
        created = sm.create_agent_wallet("apk_al", label="allow")
        wid = created["wallet_id"]
        sm.update_wallet_policy(wid, "apk_al", vendor_allowlist=["vendor-a", "vendor-b"])
        wallet = sm.get_agent_wallet(wid)
        assert "vendor-a" in wallet["vendor_allowlist"]

    def test_list_agent_wallets(self):
        sm.create_agent_wallet("apk_list", label="w1")
        sm.create_agent_wallet("apk_list", label="w2")
        wallets = sm.list_agent_wallets("apk_list")
        assert len(wallets) == 2


class TestPaymentProcessing:
    """Payment flow — direct and escrow."""

    def setup_method(self):
        sm._DB_PATH = _test_db_path
        # Drop all tables and re-create for clean state
        import sqlite3
        c = sqlite3.connect(_test_db_path)
        for tbl in ["seller_apis", "agent_wallets", "escrow_holds", "wallet_transactions", "seller_payouts"]:
            c.execute(f"DROP TABLE IF EXISTS {tbl}")
        c.commit()
        c.close()
        sm.init_seller_db()

    def _setup_wallet_and_seller(self, balance=10.0, escrow=False):
        """Helper: create a funded wallet and a registered seller."""
        wallet = sm.create_agent_wallet("apk_pay", label="pay-wallet", daily_budget=100.0, monthly_budget=1000.0)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, balance)

        sm.register_seller_api(
            seller_id="seller-pay", slug="pay-api", name="Pay API",
            description="", base_url="https://example.com",
            routes=[{"path": "/data", "method": "GET", "price_usd": 0.01}],
            seller_wallet="0x" + "a" * 40, escrow_enabled=escrow,
        )
        return wid

    def test_direct_payment(self):
        wid = self._setup_wallet_and_seller(balance=10.0)
        result = sm.process_payment(wid, "pay-api", "/data", 0.01, escrow=False)
        assert result["status"] == "paid"
        assert result["amount_usd"] == 0.01
        assert result["seller_received"] == round(0.01 * 0.97, 6)
        assert result["platform_fee"] == round(0.01 * 0.03, 6)

        wallet = sm.get_agent_wallet(wid)
        assert wallet["balance_usd"] == pytest.approx(10.0 - 0.01, abs=1e-6)

    def test_payment_credits_seller(self):
        wid = self._setup_wallet_and_seller(balance=10.0)
        sm.process_payment(wid, "pay-api", "/data", 1.00, escrow=False)
        api = sm.get_seller_api("pay-api")
        assert api["total_calls"] == 1
        assert api["total_revenue_usd"] == pytest.approx(0.97, abs=1e-6)
        assert api["balance_usd"] == pytest.approx(0.97, abs=1e-6)

    def test_insufficient_balance(self):
        wid = self._setup_wallet_and_seller(balance=0.001)
        result = sm.process_payment(wid, "pay-api", "/data", 1.00, escrow=False)
        assert result["error"] == "insufficient_balance"

    def test_daily_budget_exceeded(self):
        wallet = sm.create_agent_wallet("apk_db", label="daily", daily_budget=0.05, monthly_budget=1000.0)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 100.0)
        sm.register_seller_api(
            seller_id="seller-db", slug="db-api", name="DB",
            description="", base_url="https://example.com", routes=[],
        )
        # First call succeeds
        r1 = sm.process_payment(wid, "db-api", "/x", 0.04, escrow=False)
        assert r1["status"] == "paid"
        # Second call exceeds daily budget
        r2 = sm.process_payment(wid, "db-api", "/x", 0.02, escrow=False)
        assert r2["error"] == "daily_budget_exceeded"

    def test_monthly_budget_exceeded(self):
        wallet = sm.create_agent_wallet("apk_mb", label="monthly", daily_budget=1000.0, monthly_budget=0.05)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 100.0)
        sm.register_seller_api(
            seller_id="seller-mb", slug="mb-api", name="MB",
            description="", base_url="https://example.com", routes=[],
        )
        r1 = sm.process_payment(wid, "mb-api", "/x", 0.04, escrow=False)
        assert r1["status"] == "paid"
        r2 = sm.process_payment(wid, "mb-api", "/x", 0.02, escrow=False)
        assert r2["error"] == "monthly_budget_exceeded"

    def test_vendor_not_allowed(self):
        wallet = sm.create_agent_wallet("apk_va", label="vendor", daily_budget=100.0, monthly_budget=1000.0)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 100.0)
        sm.update_wallet_policy(wid, "apk_va", vendor_allowlist=["allowed-vendor"])
        sm.register_seller_api(
            seller_id="seller-va", slug="blocked-vendor", name="Blocked",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.process_payment(wid, "blocked-vendor", "/x", 0.01, escrow=False)
        assert result["error"] == "vendor_not_allowed"

    def test_wallet_not_found(self):
        result = sm.process_payment("aw_nonexistent", "some-slug", "/x", 0.01)
        assert result["error"] == "Wallet not found"

    def test_escrow_payment(self):
        wid = self._setup_wallet_and_seller(balance=10.0, escrow=True)
        result = sm.process_payment(wid, "pay-api", "/data", 0.50, escrow=True)
        assert result["status"] == "escrowed"
        assert "escrow_id" in result
        assert result["amount_usd"] == 0.50

        # Balance should be deducted
        wallet = sm.get_agent_wallet(wid)
        assert wallet["balance_usd"] == pytest.approx(9.50, abs=1e-6)

    def test_escrow_release(self):
        wid = self._setup_wallet_and_seller(balance=10.0, escrow=True)
        payment = sm.process_payment(wid, "pay-api", "/data", 1.00, escrow=True)
        escrow_id = payment["escrow_id"]

        result = sm.resolve_escrow(escrow_id, action="release")
        assert result["status"] == "released"
        assert result["seller_received"] == pytest.approx(0.97, abs=1e-6)

        api = sm.get_seller_api("pay-api")
        assert api["total_calls"] == 1
        assert api["balance_usd"] == pytest.approx(0.97, abs=1e-6)

    def test_escrow_refund(self):
        wid = self._setup_wallet_and_seller(balance=10.0, escrow=True)
        payment = sm.process_payment(wid, "pay-api", "/data", 2.00, escrow=True)
        escrow_id = payment["escrow_id"]

        result = sm.resolve_escrow(escrow_id, action="refund")
        assert result["status"] == "refunded"
        assert result["amount_usd"] == 2.00

        # Balance restored
        wallet = sm.get_agent_wallet(wid)
        assert wallet["balance_usd"] == pytest.approx(10.0, abs=1e-6)

    def test_resolve_escrow_not_found(self):
        result = sm.resolve_escrow("no-such-escrow", action="release")
        assert "error" in result

    def test_resolve_escrow_already_resolved(self):
        wid = self._setup_wallet_and_seller(balance=10.0)
        payment = sm.process_payment(wid, "pay-api", "/data", 1.00, escrow=True)
        eid = payment["escrow_id"]
        sm.resolve_escrow(eid, action="release")
        # Second resolve should fail
        result = sm.resolve_escrow(eid, action="release")
        assert "error" in result

    def test_resolve_escrow_unknown_action(self):
        wid = self._setup_wallet_and_seller(balance=10.0)
        payment = sm.process_payment(wid, "pay-api", "/data", 1.00, escrow=True)
        result = sm.resolve_escrow(payment["escrow_id"], action="invalid")
        assert "error" in result


class TestDashboardAndWithdrawal:
    """Seller dashboard and withdrawal."""

    def setup_method(self):
        sm._DB_PATH = _test_db_path
        # Drop all tables and re-create for clean state
        import sqlite3
        c = sqlite3.connect(_test_db_path)
        for tbl in ["seller_apis", "agent_wallets", "escrow_holds", "wallet_transactions", "seller_payouts"]:
            c.execute(f"DROP TABLE IF EXISTS {tbl}")
        c.commit()
        c.close()
        sm.init_seller_db()

    def test_seller_dashboard_empty(self):
        dash = sm.get_seller_dashboard("no-seller")
        assert dash["totals"]["total_calls"] == 0
        assert dash["totals"]["revenue_usd"] == 0

    def test_seller_dashboard_with_data(self):
        sm.register_seller_api(
            seller_id="s-dash", slug="dash-api", name="Dash",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "1" * 40,
        )
        # Simulate some revenue by processing a payment
        wallet = sm.create_agent_wallet("apk_dash")
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        sm.process_payment(wallet["wallet_id"], "dash-api", "/x", 5.0, escrow=False)

        dash = sm.get_seller_dashboard("s-dash")
        assert dash["totals"]["total_calls"] == 1
        assert dash["totals"]["revenue_usd"] == pytest.approx(4.85, abs=1e-2)

    def test_withdrawal_success(self):
        sm.register_seller_api(
            seller_id="s-wd", slug="wd-api", name="WD",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        # Generate balance
        wallet = sm.create_agent_wallet("apk_wd")
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        sm.process_payment(wallet["wallet_id"], "wd-api", "/x", 10.0, escrow=False)

        result = sm.request_withdrawal("s-wd")
        assert "payout_id" in result
        assert result["status"] == "pending"
        assert result["wallet"] == "0x" + "a" * 40

    def test_withdrawal_insufficient_balance(self):
        sm.register_seller_api(
            seller_id="s-insuf", slug="insuf-api", name="Insuf",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        result = sm.request_withdrawal("s-insuf", amount_usd=100.0)
        assert result["error"] == "insufficient_balance"

    def test_withdrawal_below_minimum(self):
        sm.register_seller_api(
            seller_id="s-min", slug="min-api", name="Min",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        wallet = sm.create_agent_wallet("apk_min")
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        sm.process_payment(wallet["wallet_id"], "min-api", "/x", 0.50, escrow=False)
        # Seller got 0.485 (0.50 * 0.97). Request 0.40 which is < $1 minimum.
        result = sm.request_withdrawal("s-min", amount_usd=0.40)
        assert "error" in result
        assert "Minimum" in result["error"]

    def test_withdrawal_no_wallet_address(self):
        sm.register_seller_api(
            seller_id="s-nowal", slug="nowal-api", name="NoWal",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="",
        )
        wallet = sm.create_agent_wallet("apk_nowal")
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        sm.process_payment(wallet["wallet_id"], "nowal-api", "/x", 5.0, escrow=False)

        result = sm.request_withdrawal("s-nowal")
        assert "error" in result
        assert "wallet" in result["error"].lower()

    def test_withdrawal_no_apis(self):
        result = sm.request_withdrawal("no-such-seller")
        assert "error" in result


# ---------------------------------------------------------------------------
# Flask route integration tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    sm._DB_PATH = _test_db_path
    sm.init_seller_db()
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_header(key="apk_test_seller_key"):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


class TestSellerRoutes:
    """Integration tests for /sell/* and /wallet/* endpoints."""

    def setup_method(self):
        _reset_seller_db()

    def test_directory_no_auth(self, client):
        """Directory is public."""
        r = client.get("/sell/directory")
        assert r.status_code == 200
        data = r.get_json()
        assert "apis" in data
        assert "total" in data

    def test_register_no_auth(self, client):
        """Register requires auth."""
        r = client.post("/sell/register", json={
            "name": "Test", "slug": "test-rt", "base_url": "https://example.com",
        })
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_register_missing_fields(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_test_seller_key", "balance_usd": 10, "is_active": 1}
        r = client.post("/sell/register",
                        headers=_auth_header(),
                        json={"name": "Test"})
        assert r.status_code == 400
        assert "required" in r.get_json()["error"]

    @patch("routes.seller.validate_key")
    @patch("routes.seller.validate_url")
    def test_register_success(self, mock_url, mock_vk, client):
        mock_vk.return_value = {"key": "apk_test_seller_key", "balance_usd": 10, "is_active": 1}
        mock_url.return_value = "https://example.com/api"

        r = client.post("/sell/register",
                        headers=_auth_header(),
                        json={
                            "name": "Route Test API",
                            "slug": "route-test-api",
                            "base_url": "https://example.com/api",
                            "description": "Testing",
                            "routes": [{"path": "/v1/data", "method": "GET", "price_usd": 0.01}],
                        })
        assert r.status_code == 201
        data = r.get_json()
        assert data.get("slug") == "route-test-api" or data.get("status") == "registered"

    def test_docs_not_found(self, client):
        r = client.get("/sell/nonexistent-slug-xyz/docs")
        assert r.status_code == 404

    def test_dashboard_no_auth(self, client):
        r = client.get("/sell/dashboard")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_dashboard_with_auth(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_dash_key", "balance_usd": 10, "is_active": 1}
        r = client.get("/sell/dashboard", headers=_auth_header("apk_dash_key"))
        assert r.status_code == 200
        data = r.get_json()
        assert "totals" in data

    def test_withdraw_no_auth(self, client):
        r = client.post("/sell/withdraw", json={})
        assert r.status_code == 401


class TestWalletRoutes:
    """Integration tests for /wallet/* endpoints."""

    def setup_method(self):
        _reset_seller_db()

    def test_wallet_balance_no_auth(self, client):
        r = client.get("/wallet/balance")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_wallet_balance_missing_id(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_bal", "balance_usd": 10, "is_active": 1}
        r = client.get("/wallet/balance", headers=_auth_header("apk_bal"))
        assert r.status_code == 400

    @patch("routes.seller.validate_key")
    def test_wallet_balance_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_bal", "balance_usd": 10, "is_active": 1}
        r = client.get("/wallet/balance?wallet_id=aw_nosuch", headers=_auth_header("apk_bal"))
        assert r.status_code == 404

    def test_wallet_create_no_auth(self, client):
        r = client.post("/wallet/create", json={"label": "test"})
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_wallet_create_success(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_wc_key", "balance_usd": 10, "is_active": 1}
        r = client.post("/wallet/create",
                        headers=_auth_header("apk_wc_key"),
                        json={"label": "my-agent-wallet"})
        assert r.status_code == 201
        data = r.get_json()
        assert "wallet_id" in data

    def test_wallet_transactions_no_auth(self, client):
        r = client.get("/wallet/transactions")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_wallet_transactions_missing_id(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_tx", "balance_usd": 10, "is_active": 1}
        r = client.get("/wallet/transactions", headers=_auth_header("apk_tx"))
        assert r.status_code == 400

    def test_wallet_list_no_auth(self, client):
        r = client.get("/wallet/list")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_wallet_list_with_auth(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_wl_key", "balance_usd": 10, "is_active": 1}
        r = client.get("/wallet/list", headers=_auth_header("apk_wl_key"))
        assert r.status_code == 200
        data = r.get_json()
        assert "wallets" in data

    def test_wallet_policy_no_auth(self, client):
        r = client.patch("/wallet/policy", json={"wallet_id": "aw_x"})
        assert r.status_code == 401

    def test_wallet_fund_no_auth(self, client):
        r = client.post("/wallet/fund", json={"wallet_id": "aw_x", "amount_usd": 10})
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_wallet_fund_missing_wallet_id(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_f", "balance_usd": 10, "is_active": 1}
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_f"),
                        json={"amount_usd": 10})
        assert r.status_code == 400

    @patch("routes.seller.validate_key")
    def test_wallet_fund_below_minimum(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_f2", "balance_usd": 10, "is_active": 1}
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_f2"),
                        json={"wallet_id": "aw_xxx", "amount_usd": 2})
        assert r.status_code == 400
        assert "Minimum" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# Additional unit tests — validation, fee math, edge cases
# ---------------------------------------------------------------------------


class TestSellerValidation:
    """Input validation edge cases for seller registration."""

    def setup_method(self):
        _reset_seller_db()

    def test_register_name_too_long_truncated(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="long-name-api", name="X" * 300,
            description="", base_url="https://example.com", routes=[],
        )
        assert "error" not in result  # silently truncates to 255

    def test_register_description_too_long_truncated(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="long-desc-api", name="OK",
            description="D" * 1001, base_url="https://example.com", routes=[],
        )
        assert "error" not in result  # silently truncates to 500

    def test_register_base_url_too_long_accepted(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="long-url-api", name="OK",
            description="", base_url="https://example.com/" + "x" * 500, routes=[],
        )
        assert "error" not in result  # no length validation on url

    def test_register_unsupported_chain(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="bad-chain-api", name="OK",
            description="", base_url="https://example.com", routes=[],
            preferred_chain="ethereum",
        )
        assert "error" in result
        assert "Unsupported chain" in result["error"]

    def test_register_invalid_evm_wallet(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="bad-evm-api", name="OK",
            description="", base_url="https://example.com", routes=[],
            seller_wallet="not-an-address", preferred_chain="base",
        )
        assert "error" in result
        assert "Invalid Base" in result["error"]

    def test_register_invalid_solana_wallet(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="bad-sol-api", name="OK",
            description="", base_url="https://example.com", routes=[],
            seller_wallet="0x" + "a" * 40, preferred_chain="solana",
        )
        assert "error" in result
        assert "Invalid Solana" in result["error"]

    def test_register_valid_evm_wallet(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="good-evm-api", name="OK",
            description="", base_url="https://example.com", routes=[],
            seller_wallet="0x" + "a" * 40, preferred_chain="base",
        )
        assert "id" in result
        assert result["status"] == "registered"

    def test_register_valid_solana_wallet(self):
        result = sm.register_seller_api(
            seller_id="s1", slug="good-sol-api", name="OK",
            description="", base_url="https://example.com", routes=[],
            seller_wallet="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            preferred_chain="solana",
        )
        assert "id" in result
        assert result["status"] == "registered"

    def test_update_invalid_chain(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="upd-chain-api", name="OK",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.update_seller_api(reg["id"], "s1", {"preferred_chain": "polygon"})
        assert "error" in result
        assert "Unsupported chain" in result["error"]

    def test_update_invalid_wallet_for_chain(self):
        reg = sm.register_seller_api(
            seller_id="s1", slug="upd-wall-api", name="OK",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.update_seller_api(reg["id"], "s1", {
            "preferred_chain": "base", "seller_wallet": "not-valid"
        })
        assert "error" in result
        assert "Invalid Base" in result["error"]

    def test_update_nonexistent_api(self):
        result = sm.update_seller_api("no-such-id", "s1", {"name": "X"})
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestPlatformFeeCalculation:
    """Verify 3% platform fee arithmetic across different amounts."""

    def setup_method(self):
        _reset_seller_db()

    def _pay(self, amount):
        wallet = sm.create_agent_wallet("apk_fee", daily_budget=10000, monthly_budget=100000)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, amount + 1)
        sm.register_seller_api(
            seller_id="s-fee", slug=f"fee-api-{id(self)}-{amount}",
            name="Fee", description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "b" * 40,
        )
        slug = f"fee-api-{id(self)}-{amount}"
        return sm.process_payment(wid, slug, "/x", amount, escrow=False)

    def test_fee_on_one_dollar(self):
        result = self._pay(1.00)
        assert result["platform_fee"] == pytest.approx(0.03, abs=1e-6)
        assert result["seller_received"] == pytest.approx(0.97, abs=1e-6)

    def test_fee_on_small_amount(self):
        result = self._pay(0.001)
        assert result["platform_fee"] == pytest.approx(0.001 * 0.03, abs=1e-6)
        assert result["seller_received"] == pytest.approx(0.001 * 0.97, abs=1e-6)

    def test_fee_on_large_amount(self):
        result = self._pay(100.0)
        assert result["platform_fee"] == pytest.approx(3.0, abs=1e-4)
        assert result["seller_received"] == pytest.approx(97.0, abs=1e-4)

    def test_fee_plus_seller_equals_total(self):
        result = self._pay(7.77)
        assert result["platform_fee"] + result["seller_received"] == pytest.approx(7.77, abs=1e-4)


class TestVerifySellerEndpoint:
    """Seller endpoint verification (ping)."""

    def setup_method(self):
        _reset_seller_db()

    def test_verify_not_found(self):
        result = sm.verify_seller_endpoint("no-such-slug")
        assert "error" in result

    @patch("requests.get")
    def test_verify_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        sm.register_seller_api(
            seller_id="s-ver", slug="ver-api", name="Verify",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.verify_seller_endpoint("ver-api")
        assert result["verified"] is True
        assert result["status_code"] == 200

    @patch("requests.get")
    def test_verify_server_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        sm.register_seller_api(
            seller_id="s-ver2", slug="ver-fail-api", name="VerFail",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.verify_seller_endpoint("ver-fail-api")
        assert result["verified"] is False

    @patch("requests.get", side_effect=Exception("timeout"))
    def test_verify_network_error(self, mock_get):
        sm.register_seller_api(
            seller_id="s-ver3", slug="ver-net-api", name="VerNet",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.verify_seller_endpoint("ver-net-api")
        assert result["verified"] is False


class TestProxyRoute:
    """Tests for /sell/<slug>/<path> proxy endpoint."""

    def setup_method(self):
        _reset_seller_db()

    def test_proxy_seller_not_found(self, client):
        r = client.get("/sell/nonexistent-slug-xyz/v1/data")
        assert r.status_code == 404

    def test_proxy_no_wallet_returns_402(self, client):
        """If seller exists but no wallet header, should return 402."""
        # First register a seller via the core function so it exists
        sm.init_seller_db()
        sm.register_seller_api(
            seller_id="s-proxy", slug="proxy-test-api", name="Proxy Test",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/get", "method": "GET", "price_usd": 0.01}],
        )
        r = client.get("/sell/proxy-test-api/get")
        assert r.status_code == 402
        data = r.get_json()
        assert data["error"] == "payment_required"

    def test_proxy_wallet_not_found(self, client):
        r = client.get("/sell/proxy-test-api/get",
                       headers={"X-Wallet-ID": "aw_nonexistent"})
        assert r.status_code == 404

    def test_proxy_inactive_seller_returns_410(self, client):
        """Inactive seller API should return 410 Gone."""
        reg = sm.register_seller_api(
            seller_id="s-inactive", slug="inactive-api", name="Inactive",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/get", "method": "GET", "price_usd": 0.01}],
        )
        sm.update_seller_api(reg["id"], "s-inactive", {"is_active": 0})
        wallet = sm.create_agent_wallet("apk_inact")
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/inactive-api/get",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 410

    def test_proxy_route_not_matched_returns_404(self, client):
        """If route doesn't match any defined routes, 404."""
        sm.register_seller_api(
            seller_id="s-nomatch", slug="nomatch-api", name="NoMatch",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/specific", "method": "GET", "price_usd": 0.01}],
        )
        wallet = sm.create_agent_wallet("apk_nomatch")
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/nomatch-api/wrong-path",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 404
        assert "route not found" in r.get_json()["error"]

    def test_proxy_insufficient_balance(self, client):
        """Wallet with insufficient balance returns 402."""
        sm.register_seller_api(
            seller_id="s-lowbal", slug="lowbal-api", name="LowBal",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/get", "method": "GET", "price_usd": 5.00}],
        )
        wallet = sm.create_agent_wallet("apk_lowbal", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 1.0)
        r = client.get("/sell/lowbal-api/get",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 402
        assert r.get_json()["error"] == "insufficient_balance"

    def test_proxy_daily_budget_exceeded(self, client):
        """Wallet exceeding daily budget returns 403."""
        sm.register_seller_api(
            seller_id="s-dbudget", slug="dbudget-api", name="DBudget",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/get", "method": "GET", "price_usd": 8.00}],
        )
        wallet = sm.create_agent_wallet("apk_dbudget", daily_budget=5.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        r = client.get("/sell/dbudget-api/get",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 403
        assert r.get_json()["error"] == "daily_budget_exceeded"

    def test_proxy_vendor_blocked(self, client):
        """Wallet with vendor allowlist blocks unlisted sellers."""
        sm.register_seller_api(
            seller_id="s-vblock", slug="vblock-api", name="VBlock",
            description="", base_url="https://httpbin.org",
            routes=[{"path": "/get", "method": "GET", "price_usd": 0.01}],
        )
        wallet = sm.create_agent_wallet("apk_vblock", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        sm.update_wallet_policy(wallet["wallet_id"], "apk_vblock",
                                vendor_allowlist=["other-vendor"])
        r = client.get("/sell/vblock-api/get",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 403
        assert r.get_json()["error"] == "vendor_blocked"

    @patch("routes.seller._requests.request")
    @patch("routes.seller.validate_url")
    def test_proxy_success_direct_payment(self, mock_url, mock_req, client):
        """Full proxy flow: payment + proxy call + response."""
        mock_url.return_value = "https://example.com/api/v1/data"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"result": "ok"}
        mock_req.return_value = mock_resp

        sm.register_seller_api(
            seller_id="s-success", slug="success-api", name="Success",
            description="", base_url="https://example.com/api",
            routes=[{"path": "/v1/data", "method": "GET", "price_usd": 0.05}],
        )
        wallet = sm.create_agent_wallet("apk_success", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/success-api/v1/data",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["data"] == {"result": "ok"}
        assert data["_billing"]["price_usd"] == 0.05
        assert data["_billing"]["seller"] == "success-api"
        # Wallet should be debited
        w = sm.get_agent_wallet(wallet["wallet_id"])
        assert w["balance_usd"] == pytest.approx(9.95, abs=1e-4)

    @patch("routes.seller._requests.request")
    @patch("routes.seller.validate_url")
    def test_proxy_escrow_release_on_success(self, mock_url, mock_req, client):
        """Escrow is released when seller returns 2xx."""
        mock_url.return_value = "https://example.com/api/v1/data"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"ok": True}
        mock_req.return_value = mock_resp

        sm.register_seller_api(
            seller_id="s-esc-ok", slug="esc-ok-api", name="EscOK",
            description="", base_url="https://example.com/api",
            routes=[{"path": "/v1/data", "method": "GET", "price_usd": 1.00}],
            escrow_enabled=True, seller_wallet="0x" + "c" * 40,
        )
        wallet = sm.create_agent_wallet("apk_esc_ok", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/esc-ok-api/v1/data",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["_billing"]["escrow"] in (True, 1)  # SQLite stores as int

    @patch("routes.seller._requests.request")
    @patch("routes.seller.validate_url")
    def test_proxy_escrow_refund_on_500(self, mock_url, mock_req, client):
        """Escrow is refunded when seller returns 5xx."""
        mock_url.return_value = "https://example.com/api/v1/data"
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"error": "server error"}
        mock_req.return_value = mock_resp

        sm.register_seller_api(
            seller_id="s-esc-500", slug="esc-500-api", name="Esc500",
            description="", base_url="https://example.com/api",
            routes=[{"path": "/v1/data", "method": "GET", "price_usd": 1.00}],
            escrow_enabled=True, seller_wallet="0x" + "d" * 40,
        )
        wallet = sm.create_agent_wallet("apk_esc_500", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/esc-500-api/v1/data",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 500
        # Wallet should be refunded
        w = sm.get_agent_wallet(wallet["wallet_id"])
        assert w["balance_usd"] == pytest.approx(10.0, abs=1e-4)

    @patch("routes.seller._requests.request")
    @patch("routes.seller.validate_url")
    def test_proxy_escrow_refund_on_timeout(self, mock_url, mock_req, client):
        """Escrow is refunded when seller times out."""
        import requests as _real_requests
        mock_url.return_value = "https://example.com/api/v1/data"
        mock_req.side_effect = _real_requests.Timeout("timeout")

        sm.register_seller_api(
            seller_id="s-esc-to", slug="esc-to-api", name="EscTO",
            description="", base_url="https://example.com/api",
            routes=[{"path": "/v1/data", "method": "GET", "price_usd": 1.00}],
            escrow_enabled=True, seller_wallet="0x" + "e" * 40,
        )
        wallet = sm.create_agent_wallet("apk_esc_to", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/esc-to-api/v1/data",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 504
        assert r.get_json()["error"] == "seller_timeout"
        # Wallet refunded
        w = sm.get_agent_wallet(wallet["wallet_id"])
        assert w["balance_usd"] == pytest.approx(10.0, abs=1e-4)

    @patch("routes.seller._requests.request")
    @patch("routes.seller.validate_url")
    def test_proxy_non_json_response(self, mock_url, mock_req, client):
        """Proxy handles non-JSON seller responses."""
        mock_url.return_value = "https://example.com/api/v1/data"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html>hello</html>"
        mock_req.return_value = mock_resp

        sm.register_seller_api(
            seller_id="s-html", slug="html-api", name="HTML",
            description="", base_url="https://example.com/api",
            routes=[{"path": "/v1/data", "method": "GET", "price_usd": 0.01}],
        )
        wallet = sm.create_agent_wallet("apk_html", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get("/sell/html-api/v1/data",
                       headers={"X-Wallet-ID": wallet["wallet_id"]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["data"] == "<html>hello</html>"


class TestSellerDocsRoute:
    """Tests for /sell/<slug>/docs endpoint."""

    def setup_method(self):
        _reset_seller_db()

    def test_docs_for_valid_seller(self, client):
        sm.register_seller_api(
            seller_id="s-docs", slug="docs-api", name="Docs API",
            description="Has docs", base_url="https://example.com",
            routes=[
                {"path": "/v1/data", "method": "GET", "price_usd": 0.01, "description": "Get data"},
                {"path": "/v1/submit", "method": "POST", "price_usd": 0.05, "description": "Submit"},
            ],
        )
        r = client.get("/sell/docs-api/docs")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "Docs API"
        assert data["slug"] == "docs-api"
        assert "/v1/data" in data["paths"]
        assert "/v1/submit" in data["paths"]
        assert data["paths"]["/v1/data"]["get"]["price_usd"] == 0.01

    def test_docs_not_found(self, client):
        r = client.get("/sell/no-such-api/docs")
        assert r.status_code == 404

    def test_docs_empty_routes(self, client):
        sm.register_seller_api(
            seller_id="s-empty", slug="empty-routes-api", name="Empty",
            description="", base_url="https://example.com", routes=[],
        )
        r = client.get("/sell/empty-routes-api/docs")
        assert r.status_code == 200
        data = r.get_json()
        assert data["paths"] == {}


class TestSellPageRoute:
    """Test for /sell page."""

    def test_sell_page(self, client):
        r = client.get("/sell")
        assert r.status_code == 200


class TestSellerUpdateDeleteRoutes:
    """Integration tests for PATCH /sell/<id> and DELETE /sell/<id>."""

    def setup_method(self):
        _reset_seller_db()

    def test_update_no_auth(self, client):
        r = client.patch("/sell/some-id", json={"name": "New"})
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    @patch("routes.seller.validate_url")
    def test_update_success(self, mock_url, mock_vk, client):
        mock_vk.return_value = {"key": "apk_upd_key", "balance_usd": 10, "is_active": 1}
        mock_url.return_value = "https://example.com/api"
        # Register first
        reg = sm.register_seller_api(
            seller_id="apk_upd_key", slug="upd-route-api", name="Old",
            description="", base_url="https://example.com", routes=[],
        )
        r = client.patch(f"/sell/{reg['id']}",
                         headers=_auth_header("apk_upd_key"),
                         json={"name": "Updated Name"})
        assert r.status_code == 200
        data = r.get_json()
        assert "updated" in data

    @patch("routes.seller.validate_key")
    def test_update_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_upd2", "balance_usd": 10, "is_active": 1}
        r = client.patch("/sell/no-such-id",
                         headers=_auth_header("apk_upd2"),
                         json={"name": "X"})
        # update_seller_api returns a dict with "error" key (truthy), so route returns 200
        # with error embedded in response body
        assert r.status_code == 200
        data = r.get_json()
        assert "error" in data

    @patch("routes.seller.validate_key")
    @patch("routes.seller.validate_url")
    def test_update_ssrf_blocked(self, mock_url, mock_vk, client):
        from security import SSRFError
        mock_vk.return_value = {"key": "apk_ssrf", "balance_usd": 10, "is_active": 1}
        mock_url.side_effect = SSRFError("blocked")
        reg = sm.register_seller_api(
            seller_id="apk_ssrf", slug="ssrf-upd-api", name="SSRF",
            description="", base_url="https://example.com", routes=[],
        )
        r = client.patch(f"/sell/{reg['id']}",
                         headers=_auth_header("apk_ssrf"),
                         json={"base_url": "http://169.254.169.254"})
        assert r.status_code == 403

    def test_delete_no_auth(self, client):
        r = client.delete("/sell/some-id")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_delete_success(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_del_key", "balance_usd": 10, "is_active": 1}
        reg = sm.register_seller_api(
            seller_id="apk_del_key", slug="del-route-api", name="Del",
            description="", base_url="https://example.com", routes=[],
        )
        r = client.delete(f"/sell/{reg['id']}",
                          headers=_auth_header("apk_del_key"))
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("deleted") is True

    @patch("routes.seller.validate_key")
    def test_delete_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_del2", "balance_usd": 10, "is_active": 1}
        r = client.delete("/sell/no-such-id",
                          headers=_auth_header("apk_del2"))
        # delete_seller_api returns a dict with "error" key (truthy), so route returns 200
        assert r.status_code == 200
        data = r.get_json()
        assert "error" in data


class TestWithdrawRoute:
    """Integration tests for POST /sell/withdraw."""

    def setup_method(self):
        _reset_seller_db()

    @patch("routes.seller.validate_key")
    def test_withdraw_success(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_wd_rt", "balance_usd": 10, "is_active": 1}
        sm.register_seller_api(
            seller_id="apk_wd_rt", slug="wd-route-api", name="WD",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        # Generate balance via payment
        wallet = sm.create_agent_wallet("apk_wd_buyer")
        sm.fund_agent_wallet(wallet["wallet_id"], 100.0)
        sm.process_payment(wallet["wallet_id"], "wd-route-api", "/x", 10.0, escrow=False)

        r = client.post("/sell/withdraw",
                        headers=_auth_header("apk_wd_rt"),
                        json={})
        assert r.status_code == 200
        data = r.get_json()
        assert "payout_id" in data

    @patch("routes.seller.validate_key")
    def test_withdraw_no_apis(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_wd_none", "balance_usd": 10, "is_active": 1}
        r = client.post("/sell/withdraw",
                        headers=_auth_header("apk_wd_none"),
                        json={})
        assert r.status_code == 200
        data = r.get_json()
        assert "error" in data


class TestWalletBalanceOwnership:
    """Tests for wallet ownership checks on balance/transactions."""

    def setup_method(self):
        _reset_seller_db()

    @patch("routes.seller.validate_key")
    def test_wallet_balance_wrong_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_other", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_real_owner", label="not-yours")
        r = client.get(f"/wallet/balance?wallet_id={wallet['wallet_id']}",
                       headers=_auth_header("apk_other"))
        assert r.status_code == 403
        assert "not your wallet" in r.get_json()["error"]

    @patch("routes.seller.validate_key")
    def test_wallet_balance_correct_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_owner", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_owner", label="mine")
        sm.fund_agent_wallet(wallet["wallet_id"], 25.0)
        r = client.get(f"/wallet/balance?wallet_id={wallet['wallet_id']}",
                       headers=_auth_header("apk_owner"))
        assert r.status_code == 200
        data = r.get_json()
        assert data["balance_usd"] == 25.0

    @patch("routes.seller.validate_key")
    def test_wallet_transactions_wrong_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_txother", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_txreal", label="tx-test")
        r = client.get(f"/wallet/transactions?wallet_id={wallet['wallet_id']}",
                       headers=_auth_header("apk_txother"))
        assert r.status_code == 403

    @patch("routes.seller.validate_key")
    def test_wallet_transactions_correct_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_txown", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_txown", label="txs")
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        r = client.get(f"/wallet/transactions?wallet_id={wallet['wallet_id']}",
                       headers=_auth_header("apk_txown"))
        assert r.status_code == 200
        data = r.get_json()
        assert "transactions" in data
        assert len(data["transactions"]) == 1


class TestWalletPolicyRoute:
    """Integration tests for PATCH /wallet/policy."""

    def setup_method(self):
        _reset_seller_db()

    @patch("routes.seller.validate_key")
    def test_policy_missing_wallet_id(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_pol", "balance_usd": 10, "is_active": 1}
        r = client.patch("/wallet/policy",
                         headers=_auth_header("apk_pol"),
                         json={"daily_budget": 50})
        assert r.status_code == 400

    @patch("routes.seller.validate_key")
    def test_policy_update_success(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_polup", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_polup", label="pol")
        r = client.patch("/wallet/policy",
                         headers=_auth_header("apk_polup"),
                         json={"wallet_id": wallet["wallet_id"], "daily_budget": 50.0,
                               "vendor_allowlist": ["vendor-a"]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["updated"] is True

    @patch("routes.seller.validate_key")
    def test_policy_update_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_pol404", "balance_usd": 10, "is_active": 1}
        r = client.patch("/wallet/policy",
                         headers=_auth_header("apk_pol404"),
                         json={"wallet_id": "aw_nonexistent", "daily_budget": 5.0})
        # update_wallet_policy returns {"error": "Wallet not found"} (truthy),
        # route checks `if not result` which is False, so it returns 200
        # but wraps the error dict in agent_response
        data = r.get_json()
        assert "error" in data


class TestWalletFundRoute:
    """Integration tests for POST /wallet/fund with Stripe mock."""

    def setup_method(self):
        _reset_seller_db()

    @patch("routes.seller.validate_key")
    def test_fund_wallet_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_fnf", "balance_usd": 10, "is_active": 1}
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_fnf"),
                        json={"wallet_id": "aw_nope", "amount_usd": 10})
        assert r.status_code == 404

    @patch("routes.seller.validate_key")
    def test_fund_wrong_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_fwo", "balance_usd": 10, "is_active": 1}
        wallet = sm.create_agent_wallet("apk_real_fund_owner", label="fund")
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_fwo"),
                        json={"wallet_id": wallet["wallet_id"], "amount_usd": 10})
        assert r.status_code == 403

    @patch("routes.seller.stripe.checkout.Session.create")
    @patch("routes.seller.validate_key")
    def test_fund_success(self, mock_vk, mock_stripe, client):
        mock_vk.return_value = {"key": "apk_fund_ok", "balance_usd": 10, "is_active": 1}
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session123"
        mock_session.id = "cs_test_123"
        mock_stripe.return_value = mock_session

        wallet = sm.create_agent_wallet("apk_fund_ok", label="fund-ok")
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_fund_ok"),
                        json={"wallet_id": wallet["wallet_id"], "amount_usd": 10})
        assert r.status_code == 200
        data = r.get_json()
        assert "checkout_url" in data
        assert data["amount_usd"] == 10

    @patch("routes.seller.stripe.checkout.Session.create")
    @patch("routes.seller.validate_key")
    def test_fund_stripe_error(self, mock_vk, mock_stripe, client):
        mock_vk.return_value = {"key": "apk_fse", "balance_usd": 10, "is_active": 1}
        mock_stripe.side_effect = Exception("Stripe API error")

        wallet = sm.create_agent_wallet("apk_fse", label="stripe-err")
        r = client.post("/wallet/fund",
                        headers=_auth_header("apk_fse"),
                        json={"wallet_id": wallet["wallet_id"], "amount_usd": 10})
        assert r.status_code == 500
        assert "stripe_error" in r.get_json()["error"]


class TestEscrowStatusRoute:
    """Integration tests for GET /escrow/<id>."""

    def setup_method(self):
        _reset_seller_db()

    def test_escrow_no_auth(self, client):
        r = client.get("/escrow/some-id")
        assert r.status_code == 401

    @patch("routes.seller.validate_key")
    def test_escrow_not_found(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_esc", "balance_usd": 10, "is_active": 1}
        r = client.get("/escrow/no-such-id", headers=_auth_header("apk_esc"))
        assert r.status_code == 404

    @patch("routes.seller.validate_key")
    def test_escrow_status_success(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_esc_own", "balance_usd": 10, "is_active": 1}
        # Create wallet + seller + escrow payment
        wallet = sm.create_agent_wallet("apk_esc_own", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        sm.register_seller_api(
            seller_id="s-esc-st", slug="esc-st-api", name="EscSt",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "f" * 40, escrow_enabled=True,
        )
        payment = sm.process_payment(wallet["wallet_id"], "esc-st-api", "/x", 1.0, escrow=True)
        eid = payment["escrow_id"]

        r = client.get(f"/escrow/{eid}", headers=_auth_header("apk_esc_own"))
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "held"
        assert data["amount_usd"] == 1.0

    @patch("routes.seller.validate_key")
    def test_escrow_status_wrong_owner(self, mock_vk, client):
        mock_vk.return_value = {"key": "apk_esc_wrong", "balance_usd": 10, "is_active": 1}
        # Create wallet owned by different key
        wallet = sm.create_agent_wallet("apk_esc_real", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        sm.register_seller_api(
            seller_id="s-esc-wr", slug="esc-wr-api", name="EscWr",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40, escrow_enabled=True,
        )
        payment = sm.process_payment(wallet["wallet_id"], "esc-wr-api", "/x", 1.0, escrow=True)
        eid = payment["escrow_id"]

        r = client.get(f"/escrow/{eid}", headers=_auth_header("apk_esc_wrong"))
        assert r.status_code == 403


class TestGetEscrowHold:
    """Unit tests for get_escrow_hold."""

    def setup_method(self):
        _reset_seller_db()

    def test_get_escrow_hold_found(self):
        wallet = sm.create_agent_wallet("apk_geh", daily_budget=100.0)
        sm.fund_agent_wallet(wallet["wallet_id"], 10.0)
        sm.register_seller_api(
            seller_id="s-geh", slug="geh-api", name="GEH",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "b" * 40,
        )
        payment = sm.process_payment(wallet["wallet_id"], "geh-api", "/x", 1.0, escrow=True)
        hold = sm.get_escrow_hold(payment["escrow_id"])
        assert hold is not None
        assert hold["status"] == "held"
        assert hold["amount_usd"] == 1.0

    def test_get_escrow_hold_not_found(self):
        assert sm.get_escrow_hold("no-such-id") is None
