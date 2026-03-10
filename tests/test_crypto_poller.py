"""Tests for crypto_poller deposit processing logic."""

import unittest
from unittest.mock import patch, call


class TestProcessBaseTransfers(unittest.TestCase):
    """Test process_base_transfers with mocked DB/key functions."""

    WALLET = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"

    def _make_transfer(self, tx_hash="0xabc123", amount=5.0):
        return {
            "tx_hash": tx_hash,
            "sender": "0xsender",
            "amount_token": amount,
            "amount_usd": amount,
            "block_number": 100,
        }

    @patch("crypto_poller.mark_deposit_credited")
    @patch("crypto_poller.topup_key")
    @patch("crypto_poller.record_deposit")
    @patch("crypto_poller.get_pending_for_address")
    @patch("crypto_poller.is_tx_claimed")
    def test_process_base_transfer_credits_key(
        self, mock_claimed, mock_pending, mock_record, mock_topup, mock_credited
    ):
        mock_claimed.return_value = False
        mock_pending.return_value = [{"api_key": "apk_test", "network": "base"}]
        mock_record.return_value = {"status": "recorded", "tx_hash": "0xabc123", "amount_usd": 5.0}

        from crypto_poller import process_base_transfers

        process_base_transfers([self._make_transfer()], self.WALLET)

        mock_claimed.assert_called_once_with("0xabc123")
        mock_pending.assert_called_once_with(self.WALLET, "base")
        mock_record.assert_called_once()
        mock_topup.assert_called_once_with("apk_test", 5.0)
        mock_credited.assert_called_once_with("0xabc123")

    @patch("crypto_poller.mark_deposit_credited")
    @patch("crypto_poller.topup_key")
    @patch("crypto_poller.record_deposit")
    @patch("crypto_poller.get_pending_for_address")
    @patch("crypto_poller.is_tx_claimed")
    def test_process_base_transfer_skips_claimed(
        self, mock_claimed, mock_pending, mock_record, mock_topup, mock_credited
    ):
        mock_claimed.return_value = True
        mock_pending.return_value = [{"api_key": "apk_test"}]

        from crypto_poller import process_base_transfers

        process_base_transfers([self._make_transfer()], self.WALLET)

        mock_claimed.assert_called_once_with("0xabc123")
        mock_record.assert_not_called()
        mock_topup.assert_not_called()

    @patch("crypto_poller.mark_deposit_credited")
    @patch("crypto_poller.topup_key")
    @patch("crypto_poller.record_deposit")
    @patch("crypto_poller.get_pending_for_address")
    @patch("crypto_poller.is_tx_claimed")
    def test_process_base_transfer_skips_no_pending(
        self, mock_claimed, mock_pending, mock_record, mock_topup, mock_credited
    ):
        mock_pending.return_value = []

        from crypto_poller import process_base_transfers

        process_base_transfers([self._make_transfer()], self.WALLET)

        mock_pending.assert_called_once_with(self.WALLET, "base")
        mock_claimed.assert_not_called()
        mock_record.assert_not_called()
        mock_topup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
