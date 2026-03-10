"""Tests for crypto_verify — onchain USDC verification (Base + Solana)."""

import types
from unittest import mock

import pytest

import crypto_verify


# ---------------------------------------------------------------------------
# Helpers to build mock objects
# ---------------------------------------------------------------------------

RECIPIENT = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
SENDER = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
TX_HASH = "0x" + "aa" * 32


def _make_receipt(status=1, block_number=100):
    """Return a mock transaction receipt."""
    r = types.SimpleNamespace()
    r.status = status
    r.blockNumber = block_number
    r.logs = []
    return r


def _make_transfer_event(sender, recipient, value):
    """Return a mock decoded Transfer event."""
    evt = types.SimpleNamespace()
    evt.args = {"from": sender, "to": recipient, "value": value}
    return evt


# ---------------------------------------------------------------------------
# Base tests
# ---------------------------------------------------------------------------


class TestVerifyBaseTxValid:
    """Valid Base USDC transfer."""

    def test_returns_valid_with_correct_amount(self):
        receipt = _make_receipt(status=1, block_number=100)

        with (
            mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn,
        ):
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 110  # 10 confirmations

            # Mock contract + event processing
            contract = mock.MagicMock()
            w3.eth.contract.return_value = contract
            transfer_event = _make_transfer_event(SENDER, RECIPIENT, 5_000_000)  # 5 USDC
            contract.events.Transfer.return_value.process_receipt.return_value = [
                transfer_event
            ]

            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)

        assert result["valid"] is True
        assert result["amount_usdc"] == 5.0
        assert result["sender"] == SENDER
        assert result["recipient"] == RECIPIENT
        assert result["block_number"] == 100
        assert result["confirmations"] == 10
        assert result["network"] == "base"


class TestVerifyBaseTxWrongRecipient:
    """Transfer to wrong address."""

    def test_returns_invalid(self):
        receipt = _make_receipt(status=1, block_number=100)
        wrong_addr = "0x0000000000000000000000000000000000000001"

        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 110

            contract = mock.MagicMock()
            w3.eth.contract.return_value = contract
            transfer_event = _make_transfer_event(SENDER, wrong_addr, 1_000_000)
            contract.events.Transfer.return_value.process_receipt.return_value = [
                transfer_event
            ]

            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)

        assert result["valid"] is False
        assert "expected recipient" in result["error"].lower()


class TestVerifyBaseTxFailedTx:
    """Transaction with status=0."""

    def test_returns_invalid(self):
        receipt = _make_receipt(status=0, block_number=100)

        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt

            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)

        assert result["valid"] is False
        assert "failed" in result["error"].lower()


class TestVerifyBaseTxInsufficientConfirmations:
    """Only 1 confirmation when 5 required."""

    def test_returns_invalid(self):
        receipt = _make_receipt(status=1, block_number=100)

        with mock.patch.object(crypto_verify, "_get_base_w3") as mock_w3_fn:
            w3 = mock.MagicMock()
            mock_w3_fn.return_value = w3
            w3.eth.get_transaction_receipt.return_value = receipt
            w3.eth.block_number = 101  # only 1 confirmation

            result = crypto_verify.verify_base_tx(TX_HASH, RECIPIENT)

        assert result["valid"] is False
        assert "confirmations" in result["error"].lower()


# ---------------------------------------------------------------------------
# Solana tests
# ---------------------------------------------------------------------------

SOL_RECIPIENT = "RecipientPubkey111111111111111111111111111"
SOL_SENDER = "SenderPubkey2222222222222222222222222222222"
SOL_SIG = "5" * 88


def _make_token_balance(owner, mint, ui_amount):
    """Return a mock token balance entry."""
    tb = types.SimpleNamespace()
    tb.owner = owner
    tb.mint = mint
    tb.ui_token_amount = types.SimpleNamespace()
    tb.ui_token_amount.ui_amount = ui_amount
    return tb


class TestVerifySolanaTxValid:
    """Valid Solana USDC-SPL transfer."""

    def test_returns_valid_with_correct_amount(self):
        pre_sender = _make_token_balance(SOL_SENDER, crypto_verify.USDC_SOL_MINT, 100.0)
        pre_recip = _make_token_balance(SOL_RECIPIENT, crypto_verify.USDC_SOL_MINT, 50.0)
        post_sender = _make_token_balance(SOL_SENDER, crypto_verify.USDC_SOL_MINT, 90.0)
        post_recip = _make_token_balance(SOL_RECIPIENT, crypto_verify.USDC_SOL_MINT, 60.0)

        meta = types.SimpleNamespace()
        meta.err = None
        meta.pre_token_balances = [pre_sender, pre_recip]
        meta.post_token_balances = [post_sender, post_recip]

        tx_inner = types.SimpleNamespace()
        tx_inner.meta = meta

        tx_data = types.SimpleNamespace()
        tx_data.transaction = tx_inner
        tx_data.slot = 12345

        resp = types.SimpleNamespace()
        resp.value = tx_data

        with mock.patch.object(crypto_verify, "_get_solana_client") as mock_client_fn:
            client = mock.MagicMock()
            mock_client_fn.return_value = client
            client.get_transaction.return_value = resp

            result = crypto_verify.verify_solana_tx(SOL_SIG, SOL_RECIPIENT)

        assert result["valid"] is True
        assert result["amount_usdc"] == 10.0
        assert result["sender"] == SOL_SENDER
        assert result["recipient"] == SOL_RECIPIENT
        assert result["slot"] == 12345
        assert result["network"] == "solana"
