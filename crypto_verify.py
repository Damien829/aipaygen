"""Onchain USDC transaction verification for Base (EVM) and Solana."""

import os
import logging

from web3 import Web3
from solana.rpc.api import Client as SolanaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
CRYPTO_BASE_RPC = os.getenv("CRYPTO_BASE_RPC", "https://mainnet.base.org")
CRYPTO_SOLANA_RPC = os.getenv("CRYPTO_SOLANA_RPC", "https://api.mainnet-beta.solana.com")
BASE_CONFIRMATIONS = int(os.getenv("CRYPTO_BASE_CONFIRMATIONS", "5"))

# ---------------------------------------------------------------------------
# USDC contract addresses
# ---------------------------------------------------------------------------
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Minimal ABI: only the Transfer event
_ERC20_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    }
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_base_w3() -> Web3:
    """Return a Web3 instance connected to Base."""
    return Web3(Web3.HTTPProvider(CRYPTO_BASE_RPC))


def _get_solana_client() -> SolanaClient:
    """Return a Solana RPC client."""
    return SolanaClient(CRYPTO_SOLANA_RPC)


# ---------------------------------------------------------------------------
# Base (EVM) verification
# ---------------------------------------------------------------------------

def verify_base_tx(tx_hash: str, expected_recipient: str) -> dict:
    """Verify an onchain Base USDC transfer.

    Returns a dict with ``valid=True`` and transfer details on success,
    or ``valid=False`` with an ``error`` message on failure.
    """
    try:
        w3 = _get_base_w3()
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        # 1. Check tx succeeded
        if receipt.status != 1:
            return {"valid": False, "error": "Transaction failed (status=0)"}

        # 2. Check confirmations
        current_block = w3.eth.block_number
        confirmations = current_block - receipt.blockNumber
        if confirmations < BASE_CONFIRMATIONS:
            return {
                "valid": False,
                "error": f"Insufficient confirmations: {confirmations}/{BASE_CONFIRMATIONS}",
            }

        # 3. Decode Transfer events from USDC contract
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_BASE), abi=_ERC20_ABI
        )
        transfers = usdc.events.Transfer().process_receipt(receipt)

        if not transfers:
            return {"valid": False, "error": "No USDC Transfer events in transaction"}

        # Find a transfer to the expected recipient
        expected = expected_recipient.lower()
        for evt in transfers:
            args = evt.args
            if args["to"].lower() == expected:
                # USDC has 6 decimals
                amount_usdc = args["value"] / 1_000_000
                return {
                    "valid": True,
                    "amount_usdc": amount_usdc,
                    "sender": args["from"],
                    "recipient": args["to"],
                    "block_number": receipt.blockNumber,
                    "confirmations": confirmations,
                    "network": "base",
                }

        return {"valid": False, "error": "No Transfer to expected recipient"}

    except Exception as exc:
        logger.exception("verify_base_tx failed")
        return {"valid": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Solana verification
# ---------------------------------------------------------------------------

def verify_solana_tx(signature: str, expected_recipient: str) -> dict:
    """Verify an onchain Solana USDC-SPL transfer.

    Uses pre/post token balance diffs to determine transfer amount and
    direction.  Returns a dict with ``valid=True`` on success.
    """
    try:
        client = _get_solana_client()
        resp = client.get_transaction(
            signature,
            encoding="jsonParsed",
            max_supported_transaction_version=0,
        )

        tx_data = resp.value
        if tx_data is None:
            return {"valid": False, "error": "Transaction not found"}

        meta = tx_data.transaction.meta
        if meta is None:
            return {"valid": False, "error": "Transaction meta unavailable"}

        if meta.err is not None:
            return {"valid": False, "error": f"Transaction failed: {meta.err}"}

        # Walk pre/post token balances looking for USDC mint
        pre_balances = {
            b.owner: float(b.ui_token_amount.ui_amount or 0)
            for b in (meta.pre_token_balances or [])
            if b.mint == USDC_SOL_MINT
        }
        post_balances = {
            b.owner: float(b.ui_token_amount.ui_amount or 0)
            for b in (meta.post_token_balances or [])
            if b.mint == USDC_SOL_MINT
        }

        # Find recipient with increased balance
        expected = expected_recipient
        pre_amt = pre_balances.get(expected, 0.0)
        post_amt = post_balances.get(expected, 0.0)
        diff = post_amt - pre_amt

        if diff <= 0:
            return {"valid": False, "error": "No USDC credit to expected recipient"}

        # Identify sender (account whose balance decreased)
        sender = None
        for owner in pre_balances:
            if owner == expected:
                continue
            owner_diff = post_balances.get(owner, 0.0) - pre_balances.get(owner, 0.0)
            if owner_diff < 0:
                sender = owner
                break

        return {
            "valid": True,
            "amount_usdc": round(diff, 6),
            "sender": sender,
            "recipient": expected,
            "slot": tx_data.slot,
            "network": "solana",
        }

    except Exception as exc:
        logger.exception("verify_solana_tx failed")
        return {"valid": False, "error": str(exc)}
