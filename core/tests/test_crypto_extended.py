"""Extended crypto tests — Solana claim route, fee calculations, address creation
flow, unsupported networks, deposit history edge cases, and verify edge cases."""

import sys, os, types, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest import mock
from unittest.mock import patch, MagicMock

import crypto_verify


# ---------------------------------------------------------------------------
# crypto_verify — additional edge cases
# ---------------------------------------------------------------------------

RECIPIENT = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
SENDER = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
TX_HASH = "0x" + "bb" * 32


def _make_receipt(status=1, block_number=100):
    r = types.SimpleNamespace()
    r.status = status
    r.blockNumber = block_number
    r.logs = []
    return r


def _make_transfer_event(sender, recipient, value):
    evt = types.SimpleNamespace()
    evt.args = {"from": sender, "to": recipient, "value": value}
    return evt


class TestVerifyBaseTxZeroAmount:
    """Transfer with 0 USDC."""

    def test_returns_valid_but_zero(self):
        receipt = _make_receipt(status=1, block_number=100)
        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 110
            contract = mock.MagicMock()
            w3.eth.contract.return_value = contract
            transfer_event = _make_transfer_event(SENDER, RECIPIENT, 0)
            contract.events.Transfer.return_value.process_receipt.return_value = [
                transfer_event
            ]
            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)
        assert result["valid"] is True
        assert result["amount_usdc"] == 0.0


class TestVerifyBaseTxMultipleTransfers:
    """Multiple Transfer events — should use the one matching recipient."""

    def test_picks_matching_recipient(self):
        receipt = _make_receipt(status=1, block_number=100)
        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 110
            contract = mock.MagicMock()
            w3.eth.contract.return_value = contract
            # Two transfers: one to wrong address, one to correct
            wrong_event = _make_transfer_event(SENDER, "0x0000000000000000000000000000000000000001", 1_000_000)
            right_event = _make_transfer_event(SENDER, RECIPIENT, 7_500_000)
            contract.events.Transfer.return_value.process_receipt.return_value = [
                wrong_event, right_event
            ]
            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)
        assert result["valid"] is True
        assert result["amount_usdc"] == 7.5


class TestVerifyBaseTxNoTransferEvents:
    """No Transfer events found in receipt."""

    def test_returns_invalid(self):
        receipt = _make_receipt(status=1, block_number=100)
        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 110
            contract = mock.MagicMock()
            w3.eth.contract.return_value = contract
            contract.events.Transfer.return_value.process_receipt.return_value = []
            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)
        assert result["valid"] is False


class TestVerifyBaseTxReceiptNone:
    """get_transaction_receipt returns None (tx not found)."""

    def test_returns_invalid(self):
        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = None
            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)
        assert result["valid"] is False


class TestVerifyBaseTxExceptionHandling:
    """Web3 connection or RPC errors."""

    def test_returns_invalid_on_exception(self):
        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.side_effect = Exception("RPC error")
            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)
        assert result["valid"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Solana — additional edge cases
# ---------------------------------------------------------------------------

SOL_RECIPIENT = "RecipientPubkey111111111111111111111111111"
SOL_SENDER = "SenderPubkey2222222222222222222222222222222"
SOL_SIG = "5" * 88


def _make_token_balance(owner, mint, ui_amount):
    tb = types.SimpleNamespace()
    tb.owner = owner
    tb.mint = mint
    tb.ui_token_amount = types.SimpleNamespace()
    tb.ui_token_amount.ui_amount = ui_amount
    return tb


class TestVerifySolanaTxFailedTx:
    """Transaction with meta.err set."""

    def test_returns_invalid(self):
        meta = types.SimpleNamespace()
        meta.err = {"InstructionError": [0, "Custom error"]}
        meta.pre_token_balances = []
        meta.post_token_balances = []

        tx_inner = types.SimpleNamespace()
        tx_inner.meta = meta
        tx_data = types.SimpleNamespace()
        tx_data.transaction = tx_inner
        tx_data.slot = 100

        resp = types.SimpleNamespace()
        resp.value = tx_data

        with mock.patch.object(crypto_verify, "_get_solana_client") as mock_fn:
            client = mock.MagicMock()
            mock_fn.return_value = client
            client.get_transaction.return_value = resp
            result = crypto_verify.verify_solana_tx(SOL_SIG, SOL_RECIPIENT)

        assert result["valid"] is False


class TestVerifySolanaTxNotFound:
    """Transaction not found on chain."""

    def test_returns_invalid(self):
        resp = types.SimpleNamespace()
        resp.value = None

        with mock.patch.object(crypto_verify, "_get_solana_client") as mock_fn:
            client = mock.MagicMock()
            mock_fn.return_value = client
            client.get_transaction.return_value = resp
            result = crypto_verify.verify_solana_tx(SOL_SIG, SOL_RECIPIENT)

        assert result["valid"] is False


class TestVerifySolanaTxNoRecipientBalance:
    """Recipient not found in post_token_balances."""

    def test_returns_invalid(self):
        pre_sender = _make_token_balance(SOL_SENDER, crypto_verify.USDC_SOL_MINT, 100.0)
        post_sender = _make_token_balance(SOL_SENDER, crypto_verify.USDC_SOL_MINT, 90.0)

        meta = types.SimpleNamespace()
        meta.err = None
        meta.pre_token_balances = [pre_sender]
        meta.post_token_balances = [post_sender]

        tx_inner = types.SimpleNamespace()
        tx_inner.meta = meta
        tx_data = types.SimpleNamespace()
        tx_data.transaction = tx_inner
        tx_data.slot = 200

        resp = types.SimpleNamespace()
        resp.value = tx_data

        with mock.patch.object(crypto_verify, "_get_solana_client") as mock_fn:
            client = mock.MagicMock()
            mock_fn.return_value = client
            client.get_transaction.return_value = resp
            result = crypto_verify.verify_solana_tx(SOL_SIG, SOL_RECIPIENT)

        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Crypto routes — additional tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_rate_limiters():
    """Clear rate limiters before each test to prevent order-dependent failures."""
    from helpers import _identity_rate, _ip_rate
    _identity_rate.clear()
    _ip_rate.clear()


@pytest.fixture
def flask_client(tmp_path):
    import api_keys
    # Use a fresh temp DB to avoid pollution from other test modules
    _orig = api_keys.DB_PATH
    api_keys.DB_PATH = str(tmp_path / "api_keys.db")
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        api_keys.init_keys_db()
        yield c
    api_keys.DB_PATH = _orig


_FAKE_KEY = "apk_test_crypto_ext_fake_key_000"


def _generate_key():
    """Return a fake API key — validate_key is mocked in each test."""
    return _FAKE_KEY


class TestCryptoRouteValidation:

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    def test_claim_unsupported_network(self, mock_validate, flask_client):
        api_key = _generate_key()
        resp = flask_client.post("/crypto/claim", json={
            "api_key": api_key,
            "tx_hash": "0x" + "ab" * 32,
            "network": "ethereum",
        })
        assert resp.status_code == 400
        assert "unsupported" in resp.get_json()["error"].lower()

    def test_claim_missing_tx_hash(self, flask_client):
        api_key = _generate_key()
        resp = flask_client.post("/crypto/claim", json={
            "api_key": api_key,
            "network": "base",
        })
        assert resp.status_code == 400

    def test_claim_missing_api_key(self, flask_client):
        resp = flask_client.post("/crypto/claim", json={
            "tx_hash": "0xabc",
            "network": "base",
        })
        assert resp.status_code == 400

    @patch("routes.crypto.validate_key", return_value=None)
    def test_claim_invalid_api_key(self, mock_validate, flask_client):
        resp = flask_client.post("/crypto/claim", json={
            "api_key": "apk_totally_invalid_key_xyz",
            "tx_hash": "0x" + "ab" * 32,
            "network": "base",
        })
        assert resp.status_code == 401

    def test_deposit_post_missing_api_key(self, flask_client):
        resp = flask_client.post("/crypto/deposit", json={
            "network": "base",
            "amount": 5.0,
        })
        assert resp.status_code == 400

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    def test_deposit_post_unsupported_network(self, mock_validate, flask_client):
        api_key = _generate_key()
        resp = flask_client.post("/crypto/deposit", json={
            "api_key": api_key,
            "network": "polygon",
        })
        assert resp.status_code == 400

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    def test_deposit_post_invalid_amount(self, mock_validate, flask_client):
        api_key = _generate_key()
        resp = flask_client.post("/crypto/deposit", json={
            "api_key": api_key,
            "network": "base",
            "amount": "not-a-number",
        })
        assert resp.status_code == 400

    def test_deposits_history_missing_key(self, flask_client):
        # Route returns 400 (missing api_key param) since it's not behind @require_api_key
        resp = flask_client.get("/crypto/deposits")
        assert resp.status_code == 400

    def test_deposits_history_invalid_key(self, flask_client):
        resp = flask_client.get("/crypto/deposits?api_key=apk_invalid_xyz",
                                headers={"Authorization": "Bearer apk_invalid_xyz"})
        assert resp.status_code == 401

    def test_address_missing_key(self, flask_client):
        resp = flask_client.get("/crypto/address")
        assert resp.status_code == 400

    def test_address_invalid_key(self, flask_client):
        resp = flask_client.get("/crypto/address?api_key=apk_invalid_xyz")
        assert resp.status_code == 401


class TestCryptoClaimFeeCalculation:
    """Verify fee calculation on claim endpoint."""

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    @patch("routes.crypto.CRYPTO_FEE_PERCENT", 1.0)
    @patch("routes.crypto.topup_key")
    @patch("routes.crypto.verify_base_tx")
    def test_fee_deducted_from_credit(self, mock_verify, mock_topup, mock_validate, flask_client):
        tx_hash = f"0x{uuid.uuid4().hex}{uuid.uuid4().hex}"
        mock_verify.return_value = {
            "valid": True,
            "amount_usdc": 100.0,
            "sender": "0xSENDER",
            "recipient": "0xRECIPIENT",
            "block_number": 500,
            "confirmations": 10,
            "network": "base",
        }
        mock_topup.return_value = {"key": "test", "balance_usd": 99.0, "topped_up": 99.0}
        api_key = _generate_key()
        resp = flask_client.post("/crypto/claim", json={
            "api_key": api_key,
            "tx_hash": tx_hash,
            "network": "base",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["fee_usd"] > 0
        assert data["amount_usd"] + data["fee_usd"] == pytest.approx(100.0, abs=1e-4)

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    @patch("routes.crypto.topup_key")
    @patch("routes.crypto.is_tx_claimed", return_value=False)
    @patch("routes.crypto.record_deposit", return_value={"status": "credited", "id": 1})
    @patch("routes.crypto.mark_deposit_credited")
    @patch("routes.crypto.verify_solana_tx")
    def test_solana_claim_success(self, mock_verify, mock_mark, mock_record, mock_claimed, mock_topup, mock_validate, flask_client):
        """Solana claim flow through the route."""
        tx_sig = "5" * 88  # valid base58 Solana signature
        mock_verify.return_value = {
            "valid": True,
            "amount_usdc": 50.0,
            "sender": "SolSender",
            "recipient": "SolRecipient",
            "slot": 12345,
            "network": "solana",
        }
        mock_topup.return_value = {"key": "test", "balance_usd": 49.5, "topped_up": 49.5}
        api_key = _generate_key()
        resp = flask_client.post("/crypto/claim", json={
            "api_key": api_key,
            "tx_hash": tx_sig,
            "network": "solana",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "credited"
        assert data["network"] == "solana"
        assert data["amount_usd"] > 0


class TestCryptoDoubleClaim:
    """Claiming the same tx_hash twice."""

    @patch("routes.crypto.validate_key", return_value={"key": _FAKE_KEY, "balance_usd": 0.0, "is_active": 1})
    @patch("routes.crypto.topup_key")
    @patch("routes.crypto.verify_base_tx")
    def test_double_claim_rejected(self, mock_verify, mock_topup, mock_validate, flask_client):
        tx_hash = f"0x{uuid.uuid4().hex}{uuid.uuid4().hex}"
        mock_verify.return_value = {
            "valid": True, "amount_usdc": 10.0, "sender": "0xS",
            "recipient": "0xR", "block_number": 100, "confirmations": 10,
            "network": "base",
        }
        mock_topup.return_value = {"key": "test", "balance_usd": 10.0, "topped_up": 10.0}
        api_key = _generate_key()

        # First claim
        resp1 = flask_client.post("/crypto/claim", json={
            "api_key": api_key, "tx_hash": tx_hash, "network": "base",
        })
        assert resp1.status_code == 200

        # Second claim — same tx_hash
        resp2 = flask_client.post("/crypto/claim", json={
            "api_key": api_key, "tx_hash": tx_hash, "network": "base",
        })
        assert resp2.status_code == 409
        assert "already claimed" in resp2.get_json()["error"]


class TestCryptoLandingPage:

    def test_landing_has_usdc_info(self, flask_client):
        resp = flask_client.get("/crypto")
        assert resp.status_code == 200
        assert b"USDC" in resp.data
        assert b"Base" in resp.data
        assert b"Solana" in resp.data

    def test_landing_has_claim_example(self, flask_client):
        resp = flask_client.get("/crypto")
        assert resp.status_code == 200
        assert b"/crypto/claim" in resp.data

    def test_deposit_info_has_qr(self, flask_client):
        resp = flask_client.get("/crypto/deposit")
        data = resp.get_json()
        assert data["qr_code"].startswith("iVBOR") or len(data["qr_code"]) > 100
