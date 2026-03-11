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
# State (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_state = {
    "base_last_block": None,
    "solana_last_slot": None,
    "running": False,
}

# Cached Web3 instance (reused across poll cycles)
_w3_instance = None


def _get_w3():
    global _w3_instance
    if _w3_instance is None:
        from web3 import Web3
        _w3_instance = Web3(Web3.HTTPProvider(BASE_RPC))
    return _w3_instance


# ---------------------------------------------------------------------------
# Unified transfer processor
# ---------------------------------------------------------------------------
def _process_transfers(transfers: list, wallet_address: str, network: str):
    """Process parsed transfer events and credit matching pending deposits."""
    # Fetch pending once for all transfers (avoid N+1)
    pending = get_pending_for_address(wallet_address, network)
    if not pending:
        return

    for tx in transfers:
        tx_hash = tx["tx_hash"]
        if is_tx_claimed(tx_hash):
            continue

        entry = pending[0]
        api_key = entry["api_key"]
        amount_usd = tx["amount_usd"]

        result = record_deposit(
            api_key=api_key,
            tx_hash=tx_hash,
            network=network,
            amount_token=tx["amount_token"],
            amount_usd=amount_usd,
            sender_address=tx.get("sender"),
            deposit_address=wallet_address,
            block_number=tx.get("block_number", tx.get("slot", 0)),
        )

        if result.get("status") != "recorded":
            continue

        topup_key(api_key, amount_usd)
        mark_deposit_credited(tx_hash)
        log.info("Credited $%.2f to %s from %s tx %s", amount_usd, api_key, network, tx_hash)

        try:
            from email_service import send_deposit_confirmation
            send_deposit_confirmation(api_key, amount_usd, network, tx_hash)
        except Exception:
            log.debug("Email notification failed for %s", tx_hash)


# Public aliases for backwards compat with tests
def process_base_transfers(transfers: list, wallet_address: str):
    _process_transfers(transfers, wallet_address, "base")


def process_solana_transfers(transfers: list, wallet_address: str):
    _process_transfers(transfers, wallet_address, "solana")


# ---------------------------------------------------------------------------
# Polling functions
# ---------------------------------------------------------------------------
def _batch_rpc(from_block: int, wallet_address: str, usdc_address: str) -> tuple:
    """Batch eth_blockNumber + eth_getLogs into a single JSON-RPC request.

    Returns (current_block, logs_list) or raises on failure.
    """
    import requests as _req

    wallet_topic = "0x" + wallet_address.lower().replace("0x", "").zfill(64)
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
        {
            "jsonrpc": "2.0", "id": 2, "method": "eth_getLogs",
            "params": [{
                "fromBlock": hex(from_block + 1),
                "toBlock": "latest",
                "address": usdc_address,
                "topics": [_ERC20_TRANSFER_TOPIC, None, wallet_topic],
            }],
        },
    ]
    resp = _req.post(BASE_RPC, json=batch, timeout=15)
    resp.raise_for_status()
    results = {r["id"]: r for r in resp.json()}

    if "error" in results.get(1, {}):
        raise RuntimeError(f"eth_blockNumber error: {results[1]['error']}")
    if "error" in results.get(2, {}):
        raise RuntimeError(f"eth_getLogs error: {results[2]['error']}")

    current_block = int(results[1]["result"], 16)
    raw_logs = results[2]["result"]
    return current_block, raw_logs


def _poll_base(wallet_address: str):
    """Poll Base chain for USDC Transfer events to wallet_address.

    Uses a single batched JSON-RPC request for eth_blockNumber + eth_getLogs.
    """
    try:
        from web3 import Web3
        usdc_addr = Web3.to_checksum_address(USDC_BASE)

        with _lock:
            from_block = _state["base_last_block"]

        if from_block is None:
            # First run: just set current block, don't scan history
            w3 = _get_w3()
            current_block = w3.eth.block_number
            with _lock:
                _state["base_last_block"] = current_block
            return

        current_block, raw_logs = _batch_rpc(from_block, wallet_address, usdc_addr)

        if current_block <= from_block:
            return

        transfers = []
        for entry in raw_logs:
            data_hex = entry["data"]
            if data_hex.startswith("0x"):
                data_hex = data_hex[2:]
            amount_raw = int(data_hex, 16)
            amount_token = amount_raw / 1e6
            sender_topic = entry["topics"][1]
            sender = "0x" + sender_topic[-40:] if isinstance(sender_topic, str) else "0x" + sender_topic.hex()[-40:]
            tx_hash = entry["transactionHash"]
            if isinstance(tx_hash, bytes):
                tx_hash = tx_hash.hex()
            elif tx_hash.startswith("0x"):
                tx_hash = tx_hash[2:]
            transfers.append({
                "tx_hash": tx_hash,
                "sender": sender,
                "amount_token": amount_token,
                "amount_usd": amount_token,
                "block_number": int(entry["blockNumber"], 16) if isinstance(entry["blockNumber"], str) else entry["blockNumber"],
            })

        with _lock:
            _state["base_last_block"] = current_block

        if transfers:
            process_base_transfers(transfers, wallet_address)

    except ImportError:
        log.warning("web3 not installed — Base polling disabled")
    except Exception as exc:
        log.error("Base poll error: %s", exc)


def _poll_solana(wallet_address: str):
    """Poll Solana for USDC token transfers. Not yet implemented."""
    pass


# ---------------------------------------------------------------------------
# Main loop + start/stop
# ---------------------------------------------------------------------------
def _poller_loop(wallet_address: str):
    while _state["running"]:
        _poll_base(wallet_address)
        _poll_solana(wallet_address)
        time.sleep(POLL_INTERVAL)


def start_poller(wallet_address: str):
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True
    t = threading.Thread(target=_poller_loop, args=(wallet_address,), daemon=True)
    t.start()
    log.info("Crypto deposit poller started for %s (interval=%ds)", wallet_address, POLL_INTERVAL)


def stop_poller():
    with _lock:
        _state["running"] = False
    log.info("Crypto deposit poller stopped")
