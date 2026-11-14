"""Wallet-based agent identity: challenge-sign-verify for EVM + Solana wallets."""
import os
import uuid
import time
import jwt
from eth_account import Account
from eth_account.messages import encode_defunct

JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    # Generate a random secret if none set — better than a hardcoded default
    import secrets
    JWT_SECRET = secrets.token_hex(32)
    import logging
    logging.getLogger(__name__).warning("JWT_SECRET not set in environment — using random secret (tokens won't persist across restarts)")
JWT_ALGORITHM = "HS256"
CHALLENGE_TTL = 300  # 5 minutes


class InvalidSignatureError(Exception):
    pass


class ChallengeExpiredError(Exception):
    pass


# ── Challenges ────────────────────────────────────────────────────────────────
_pending_challenges: dict = {}  # nonce -> {message, wallet, expires_at}


def _sweep_expired_challenges():
    """Remove challenges older than CHALLENGE_TTL."""
    now = time.time()
    expired = [k for k, v in _pending_challenges.items() if now > v["created"] + CHALLENGE_TTL]
    for k in expired:
        del _pending_challenges[k]


def generate_challenge(wallet_address: str) -> dict:
    """Generate a challenge message for wallet ownership proof."""
    _sweep_expired_challenges()
    nonce = uuid.uuid4().hex
    message = f"AiPayGen identity verification\nWallet: {wallet_address}\nNonce: {nonce}"
    _pending_challenges[nonce] = {
        "wallet": wallet_address,
        "message": message,
        "created": time.time(),
    }
    return {"nonce": nonce, "message": message, "expires_at": int(time.time() + CHALLENGE_TTL)}


def _get_and_validate_challenge(nonce: str) -> dict:
    """Retrieve challenge and check it hasn't expired."""
    ch = _pending_challenges.pop(nonce, None)
    if not ch:
        raise ChallengeExpiredError("Challenge not found or already used")
    if time.time() > ch["created"] + CHALLENGE_TTL:
        raise ChallengeExpiredError("Challenge expired")
    return ch


# ── EVM Verification (EIP-191) ───────────────────────────────────────────────
def verify_evm_signature(message: str, signature: str, expected_address: str) -> bool:
    """Verify an EVM personal_sign signature matches the expected wallet."""
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=signature)
        if recovered.lower() != expected_address.lower():
            raise InvalidSignatureError(
                f"Signature recovered address {recovered} != expected {expected_address}"
            )
        return True
    except InvalidSignatureError:
        raise
    except Exception as e:
        raise InvalidSignatureError(f"EVM signature verification failed: {e}")


# ── Solana Verification (Ed25519) ────────────────────────────────────────────
def verify_solana_signature(message: str, signature_bytes: bytes, pubkey_str: str) -> bool:
    """Verify a Solana Ed25519 signature."""
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        pk = Pubkey.from_string(pubkey_str)
        sig = Signature.from_bytes(signature_bytes)
        if not sig.verify(pk, message.encode()):
            raise InvalidSignatureError("Solana signature verification failed")
        return True
    except InvalidSignatureError:
        raise
    except ImportError:
        raise InvalidSignatureError("solders package not installed — Solana verification unavailable on this platform")
    except Exception as e:
        raise InvalidSignatureError(f"Solana signature verification failed: {e}")


# ── JWT Sessions ─────────────────────────────────────────────────────────────
def issue_jwt(agent_id: str, wallet: str, chain: str, ttl_seconds: int = 86400) -> str:
    """Issue a JWT for a verified agent. Default 24h expiry."""
    payload = {
        "agent_id": agent_id,
        "wallet": wallet,
        "chain": chain,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify and decode a JWT. Raises on expiry or invalid token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── High-Level Verify Flow ───────────────────────────────────────────────────
def verify_challenge(nonce: str, signature: str, chain: str = "evm") -> dict:
    """Full verification flow: validate challenge, verify signature, issue JWT."""
    ch = _get_and_validate_challenge(nonce)
    wallet = ch["wallet"]
    message = ch["message"]

    if chain == "evm":
        verify_evm_signature(message, signature, wallet)
    elif chain == "solana":
        verify_solana_signature(message, bytes.fromhex(signature), wallet)
    else:
        raise InvalidSignatureError(f"Unsupported chain: {chain}")

    token = issue_jwt(agent_id=wallet.lower(), wallet=wallet, chain=chain)
    return {"agent_id": wallet.lower(), "token": token, "chain": chain}
