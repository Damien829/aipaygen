"""Background poller for auto-detecting USDC deposits on Base and Solana."""

import logging
import os
import threading
import time

from crypto_deposits import (
    USDC_BASE,
    is_tx_claimed,
    get_pending_for_address,
    record_deposit,
    mark_deposit_credited,
)
from api_keys import topup_key

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
POLL_INTERVAL = int(os.environ.get("CRYPTO_POLL_INTERVAL", "15"))
BASE_RPC = os.environ.get("CRYPTO_BASE_RPC", "https://mainnet.base.org")
SOLANA_RPC = os.environ.get("CRYPTO_SOLANA_RPC", "https://api.mainnet-beta.solana.com")

# ERC-20 Transfer(address,address,uint256) event topic
_ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_state = {
    "base_last_block": None,
    "solana_last_slot": None,
    "running": False,
}


# ---------------------------------------------------------------------------
# Processing helpers
# ---------------------------------------------------------------------------
def process_base_transfers(transfers: list, wallet_address: str):
    """Process parsed Base ERC-20 transfer events and credit matching pending deposits."""
    for tx in transfers:
        tx_hash = tx["tx_hash"]
        if is_tx_claimed(tx_hash):
            continue

        pending = get_pending_for_address(wallet_address, "base")
        if not pending:
            continue

        entry = pending[0]
        api_key = entry["api_key"]
        amount_usd = tx["amount_usd"]

        result = record_deposit(
            api_key=api_key,
            tx_hash=tx_hash,
            network="base",
            amount_token=tx["amount_token"],
            amount_usd=amount_usd,
            sender_address=tx.get("sender"),
            deposit_address=wallet_address,
            block_number=tx.get("block_number", 0),
        )

        if result.get("status") != "recorded":
            continue

        topup_key(api_key, amount_usd)
        mark_deposit_credited(tx_hash)
        log.info("Credited $%.2f to %s from Base tx %s", amount_usd, api_key, tx_hash)

        # Best-effort email notification
        try:
            from email_service import send_topup_confirmation
            send_topup_confirmation(api_key, amount_usd, tx_hash, "base")
        except Exception:
            pass


def process_solana_transfers(transfers: list, wallet_address: str):
    """Process parsed Solana token transfer events and credit matching pending deposits."""
    for tx in transfers:
        tx_hash = tx["tx_hash"]
        if is_tx_claimed(tx_hash):
            continue

        pending = get_pending_for_address(wallet_address, "solana")
        if not pending:
            continue

        entry = pending[0]
        api_key = entry["api_key"]
        amount_usd = tx["amount_usd"]

        result = record_deposit(
            api_key=api_key,
            tx_hash=tx_hash,
            network="solana",
            amount_token=tx["amount_token"],
            amount_usd=amount_usd,
            sender_address=tx.get("sender"),
            deposit_address=wallet_address,
            block_number=tx.get("slot", 0),
        )

        if result.get("status") != "recorded":
            continue

        topup_key(api_key, amount_usd)
        mark_deposit_credited(tx_hash)
        log.info("Credited $%.2f to %s from Solana tx %s", amount_usd, api_key, tx_hash)

        try:
            from email_service import send_topup_confirmation
            send_topup_confirmation(api_key, amount_usd, tx_hash, "solana")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Polling functions
# ---------------------------------------------------------------------------
def _poll_base(wallet_address: str):
    """Poll Base chain for USDC Transfer events to wallet_address."""
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        current_block = w3.eth.block_number

        from_block = _state["base_last_block"]
        if from_block is None:
            # Start from current block on first run
            _state["base_last_block"] = current_block
            return

        if current_block <= from_block:
            return

        # Pad the wallet address to 32 bytes for topic matching
        wallet_topic = "0x" + wallet_address.lower().replace("0x", "").zfill(64)

        logs = w3.eth.get_logs({
            "fromBlock": from_block + 1,
            "toBlock": current_block,
            "address": Web3.to_checksum_address(USDC_BASE),
            "topics": [
                _ERC20_TRANSFER_TOPIC,
                None,           # from (any sender)
                wallet_topic,   # to (our wallet)
            ],
        })

        transfers = []
        for entry in logs:
            amount_raw = int(entry["data"].hex(), 16) if isinstance(entry["data"], bytes) else int(entry["data"], 16)
            # USDC has 6 decimals
            amount_token = amount_raw / 1e6
            sender = "0x" + entry["topics"][1].hex()[-40:]
            transfers.append({
                "tx_hash": entry["transactionHash"].hex(),
                "sender": sender,
                "amount_token": amount_token,
                "amount_usd": amount_token,  # USDC = 1:1 USD
                "block_number": entry["blockNumber"],
            })

        _state["base_last_block"] = current_block

        if transfers:
            process_base_transfers(transfers, wallet_address)

    except ImportError:
        log.warning("web3 not installed — Base polling disabled")
    except Exception as exc:
        log.error("Base poll error: %s", exc)


def _poll_solana(wallet_address: str):
    """Poll Solana for USDC token transfers. Placeholder — Solana polling is more complex."""
    pass


# ---------------------------------------------------------------------------
# Main loop + start/stop
# ---------------------------------------------------------------------------
def _poller_loop(wallet_address: str):
    """Infinite loop calling _poll_base and _poll_solana with sleep."""
    while _state["running"]:
        _poll_base(wallet_address)
        _poll_solana(wallet_address)
        time.sleep(POLL_INTERVAL)


def start_poller(wallet_address: str):
    """Start the background deposit poller as a daemon thread. No-op if already running."""
    if _state["running"]:
        return
    _state["running"] = True
    t = threading.Thread(target=_poller_loop, args=(wallet_address,), daemon=True)
    t.start()
    log.info("Crypto deposit poller started for %s (interval=%ds)", wallet_address, POLL_INTERVAL)


def stop_poller():
    """Signal the poller loop to stop."""
    _state["running"] = False
    log.info("Crypto deposit poller stopped")
