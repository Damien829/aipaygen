"""HD wallet address derivation for per-user deposit addresses."""

import hashlib
import os

_VERIFIED_WALLET = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
HD_MNEMONIC = os.getenv("CRYPTO_HD_MNEMONIC", "")


def get_main_wallet() -> str:
    """Return the verified main wallet address."""
    return _VERIFIED_WALLET


def derive_evm_address(mnemonic: str, index: int) -> str:
    """Derive an EVM address from a mnemonic at the given index."""
    from eth_account import Account

    if not getattr(Account, "_hdwallet_enabled", False):
        Account.enable_unaudited_hdwallet_features()
        Account._hdwallet_enabled = True
    acct = Account.from_mnemonic(mnemonic, account_path=f"m/44'/60'/0'/0/{index}")
    return acct.address


def derive_deposit_address(api_key: str) -> dict:
    """Derive a deterministic deposit address for an API key.

    If no HD mnemonic is configured, falls back to the main wallet.
    """
    if not HD_MNEMONIC:
        return {"address": _VERIFIED_WALLET, "unique": False, "network": "base"}

    idx = int(hashlib.sha256(api_key.encode()).hexdigest()[:4], 16) % (2**31)
    address = derive_evm_address(HD_MNEMONIC, idx)
    return {"address": address, "unique": True, "index": idx, "network": "base"}
