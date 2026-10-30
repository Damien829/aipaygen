"""Extended seller marketplace tests — escrow edge cases, multi-API withdrawals,
wallet transaction history, concurrent operations, and get_escrow_hold."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import tempfile
import sqlite3
import seller_marketplace as sm

_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db.name
_test_db.close()
sm._DB_PATH = _test_db_path


def _reset():
    sm._DB_PATH = _test_db_path
    c = sqlite3.connect(_test_db_path)
    for tbl in ["seller_apis", "agent_wallets", "escrow_holds", "wallet_transactions", "seller_payouts"]:
        c.execute(f"DROP TABLE IF EXISTS {tbl}")
    c.commit()
    c.close()
    sm.init_seller_db()


# ---------------------------------------------------------------------------
# get_escrow_hold
# ---------------------------------------------------------------------------

class TestGetEscrowHold:

    def setup_method(self):
        _reset()

    def test_get_escrow_hold_exists(self):
        wallet = sm.create_agent_wallet("apk_esc", daily_budget=100, monthly_budget=1000)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 50.0)
        sm.register_seller_api(
            seller_id="s1", slug="esc-api", name="Esc",
            description="", base_url="https://example.com",
            routes=[{"path": "/x", "method": "GET", "price_usd": 1.0}],
            seller_wallet="0x" + "a" * 40,
        )
        payment = sm.process_payment(wid, "esc-api", "/x", 5.0, escrow=True)
        hold = sm.get_escrow_hold(payment["escrow_id"])
        assert hold is not None
        assert hold["status"] == "held"
        assert hold["amount_usd"] == 5.0
        assert hold["agent_wallet_id"] == wid

    def test_get_escrow_hold_not_found(self):
        assert sm.get_escrow_hold("nonexistent-id") is None

    def test_escrow_hold_after_release(self):
        wallet = sm.create_agent_wallet("apk_rel", daily_budget=100, monthly_budget=1000)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 10.0)
        sm.register_seller_api(
            seller_id="s-rel", slug="rel-api", name="Rel",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "b" * 40,
        )
        payment = sm.process_payment(wid, "rel-api", "/x", 2.0, escrow=True)
        sm.resolve_escrow(payment["escrow_id"], action="release")
        hold = sm.get_escrow_hold(payment["escrow_id"])
        assert hold is not None
        assert hold["status"] == "released"

    def test_escrow_hold_after_refund(self):
        wallet = sm.create_agent_wallet("apk_ref", daily_budget=100, monthly_budget=1000)
        wid = wallet["wallet_id"]
        sm.fund_agent_wallet(wid, 10.0)
        sm.register_seller_api(
            seller_id="s-ref", slug="ref-api", name="Ref",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "c" * 40,
        )
        payment = sm.process_payment(wid, "ref-api", "/x", 3.0, escrow=True)
        sm.resolve_escrow(payment["escrow_id"], action="refund")
        hold = sm.get_escrow_hold(payment["escrow_id"])
        assert hold["status"] == "refunded"


# ---------------------------------------------------------------------------
# Multi-API withdrawal math
# ---------------------------------------------------------------------------

class TestMultiAPIWithdrawal:

    def setup_method(self):
        _reset()

    def test_withdrawal_proportional_across_apis(self):
        """Withdrawal deducts proportionally from multiple APIs."""
        sm.register_seller_api(
            seller_id="s-multi", slug="multi-a", name="A",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        sm.register_seller_api(
            seller_id="s-multi", slug="multi-b", name="B",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        # Generate revenue on both APIs
        w = sm.create_agent_wallet("apk_mw", daily_budget=1000, monthly_budget=10000)
        sm.fund_agent_wallet(w["wallet_id"], 200.0)
        sm.process_payment(w["wallet_id"], "multi-a", "/x", 10.0, escrow=False)
        sm.process_payment(w["wallet_id"], "multi-b", "/x", 20.0, escrow=False)

        api_a = sm.get_seller_api("multi-a")
        api_b = sm.get_seller_api("multi-b")
        total_before = api_a["balance_usd"] + api_b["balance_usd"]

        result = sm.request_withdrawal("s-multi", amount_usd=5.0)
        assert result["status"] == "pending"
        assert result["amount_usd"] == 5.0

        # Total balance decreased by 5.0
        api_a_after = sm.get_seller_api("multi-a")
        api_b_after = sm.get_seller_api("multi-b")
        total_after = api_a_after["balance_usd"] + api_b_after["balance_usd"]
        assert total_after == pytest.approx(total_before - 5.0, abs=1e-4)

    def test_withdrawal_all_balance(self):
        """Withdrawing None withdraws all balance."""
        sm.register_seller_api(
            seller_id="s-all", slug="all-api", name="All",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "d" * 40,
        )
        w = sm.create_agent_wallet("apk_all", daily_budget=1000, monthly_budget=10000)
        sm.fund_agent_wallet(w["wallet_id"], 100.0)
        sm.process_payment(w["wallet_id"], "all-api", "/x", 50.0, escrow=False)

        result = sm.request_withdrawal("s-all")  # amount_usd=None -> all
        assert result["status"] == "pending"
        api = sm.get_seller_api("all-api")
        assert api["balance_usd"] == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Wallet transaction history details
# ---------------------------------------------------------------------------

class TestWalletTransactionHistory:

    def setup_method(self):
        _reset()

    def test_multiple_transaction_types(self):
        """Transaction history records deposits, payments, and escrow holds."""
        w = sm.create_agent_wallet("apk_th", daily_budget=1000, monthly_budget=10000)
        wid = w["wallet_id"]
        sm.fund_agent_wallet(wid, 100.0)

        sm.register_seller_api(
            seller_id="s-th", slug="th-api", name="TH",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "e" * 40,
        )

        sm.process_payment(wid, "th-api", "/x", 1.0, escrow=False)
        sm.process_payment(wid, "th-api", "/y", 2.0, escrow=True)

        txns = sm.get_wallet_transactions(wid)
        assert len(txns) == 3  # deposit + payment + escrow_hold
        types = {t["type"] for t in txns}
        assert "deposit" in types
        assert "payment" in types
        assert "escrow_hold" in types

    def test_transaction_history_limit(self):
        """Limit parameter restricts returned rows."""
        w = sm.create_agent_wallet("apk_lim", daily_budget=1000, monthly_budget=10000)
        wid = w["wallet_id"]
        for i in range(5):
            sm.fund_agent_wallet(wid, 1.0)
        txns = sm.get_wallet_transactions(wid, limit=3)
        assert len(txns) == 3

    def test_escrow_refund_transaction_recorded(self):
        """Escrow refund creates a transaction."""
        w = sm.create_agent_wallet("apk_reftxn", daily_budget=1000, monthly_budget=10000)
        wid = w["wallet_id"]
        sm.fund_agent_wallet(wid, 50.0)
        sm.register_seller_api(
            seller_id="s-reftxn", slug="reftxn-api", name="RefTxn",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "f" * 40,
        )
        payment = sm.process_payment(wid, "reftxn-api", "/x", 5.0, escrow=True)
        sm.resolve_escrow(payment["escrow_id"], action="refund")

        txns = sm.get_wallet_transactions(wid)
        types = [t["type"] for t in txns]
        assert "escrow_refund" in types


# ---------------------------------------------------------------------------
# Seller dashboard payout records
# ---------------------------------------------------------------------------

class TestDashboardPayouts:

    def setup_method(self):
        _reset()

    def test_dashboard_includes_payouts(self):
        sm.register_seller_api(
            seller_id="s-po", slug="po-api", name="PO",
            description="", base_url="https://example.com",
            routes=[], seller_wallet="0x" + "a" * 40,
        )
        w = sm.create_agent_wallet("apk_po", daily_budget=1000, monthly_budget=10000)
        sm.fund_agent_wallet(w["wallet_id"], 100.0)
        sm.process_payment(w["wallet_id"], "po-api", "/x", 20.0, escrow=False)
        sm.request_withdrawal("s-po", amount_usd=5.0)

        dash = sm.get_seller_dashboard("s-po")
        assert len(dash["payouts"]) == 1
        assert dash["payouts"][0]["amount_usd"] == 5.0
        assert dash["payouts"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Payment with seller not found
# ---------------------------------------------------------------------------

class TestPaymentSellerNotFound:

    def setup_method(self):
        _reset()

    def test_payment_proceeds_even_if_seller_slug_unregistered(self):
        """process_payment does not check seller existence — it updates by slug."""
        w = sm.create_agent_wallet("apk_ns", daily_budget=1000, monthly_budget=10000)
        wid = w["wallet_id"]
        sm.fund_agent_wallet(wid, 10.0)
        # No seller registered with this slug — payment still succeeds
        # (the seller_apis UPDATE matches 0 rows, but doesn't error)
        result = sm.process_payment(wid, "no-such-seller", "/x", 1.0, escrow=False)
        assert result["status"] == "paid"
        wallet = sm.get_agent_wallet(wid)
        assert wallet["balance_usd"] == pytest.approx(9.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Vendor allowlist with exact match
# ---------------------------------------------------------------------------

class TestVendorAllowlistExact:

    def setup_method(self):
        _reset()

    def test_vendor_allowed_exact_match(self):
        w = sm.create_agent_wallet("apk_va2", daily_budget=100, monthly_budget=1000)
        wid = w["wallet_id"]
        sm.fund_agent_wallet(wid, 10.0)
        sm.update_wallet_policy(wid, "apk_va2", vendor_allowlist=["my-vendor"])
        sm.register_seller_api(
            seller_id="s-va2", slug="my-vendor", name="MyV",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.process_payment(wid, "my-vendor", "/x", 0.01, escrow=False)
        assert result["status"] == "paid"

    def test_empty_allowlist_allows_all(self):
        w = sm.create_agent_wallet("apk_ea", daily_budget=100, monthly_budget=1000)
        wid = w["wallet_id"]
        sm.fund_agent_wallet(wid, 10.0)
        sm.update_wallet_policy(wid, "apk_ea", vendor_allowlist=[])
        sm.register_seller_api(
            seller_id="s-ea", slug="any-vendor", name="Any",
            description="", base_url="https://example.com", routes=[],
        )
        result = sm.process_payment(wid, "any-vendor", "/x", 0.01, escrow=False)
        assert result["status"] == "paid"
