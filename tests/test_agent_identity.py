import pytest
import time
from agent_identity import (
    generate_challenge, verify_evm_signature, verify_solana_signature,
    issue_jwt, verify_jwt, ChallengeExpiredError, InvalidSignatureError,
    verify_challenge,
)
from eth_account import Account
from eth_account.messages import encode_defunct


def test_generate_challenge():
    ch = generate_challenge("0xABCDEF1234567890abcdef1234567890abcdef12")
    assert "nonce" in ch
    assert "message" in ch
    assert "expires_at" in ch
    assert "0xABCDEF" in ch["message"]


def test_verify_evm_signature():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    msg = encode_defunct(text=ch["message"])
    sig = acct.sign_message(msg)
    result = verify_evm_signature(ch["message"], sig.signature.hex(), acct.address)
    assert result is True


def test_verify_evm_bad_signature():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    with pytest.raises(InvalidSignatureError):
        verify_evm_signature(ch["message"], "0x" + "00" * 65, acct.address)


def test_jwt_roundtrip():
    token = issue_jwt(agent_id="0xABC123", wallet="0xABC123", chain="evm")
    payload = verify_jwt(token)
    assert payload["agent_id"] == "0xABC123"
    assert payload["chain"] == "evm"


def test_jwt_expired():
    token = issue_jwt(agent_id="0xABC123", wallet="0xABC123", chain="evm", ttl_seconds=0)
    time.sleep(1)
    with pytest.raises(Exception):
        verify_jwt(token)


def test_full_evm_verify_flow():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    msg = encode_defunct(text=ch["message"])
    sig = acct.sign_message(msg)
    result = verify_challenge(ch["nonce"], sig.signature.hex(), chain="evm")
    assert result["agent_id"] == acct.address.lower()
    assert "token" in result
    assert result["chain"] == "evm"
    # Verify the token works
    payload = verify_jwt(result["token"])
    assert payload["agent_id"] == acct.address.lower()


def test_challenge_reuse_fails():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    msg = encode_defunct(text=ch["message"])
    sig = acct.sign_message(msg)
    # First use succeeds
    verify_challenge(ch["nonce"], sig.signature.hex(), chain="evm")
    # Second use fails (nonce consumed)
    with pytest.raises(ChallengeExpiredError):
        verify_challenge(ch["nonce"], sig.signature.hex(), chain="evm")
