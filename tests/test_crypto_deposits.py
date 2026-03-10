"""Tests for crypto_deposits module."""

import os
import pytest

import crypto_deposits as cd


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a temporary directory for every test."""
    db_file = str(tmp_path / "crypto_deposits.db")
    monkeypatch.setattr(cd, "DB_PATH", db_file)
    cd.init_crypto_db()


# ---- deposits ----

def test_record_deposit():
    result = cd.record_deposit(
        api_key="key1", tx_hash="0xabc", network="base",
        amount_token=10.0, amount_usd=10.0,
        sender_address="0xsender", deposit_address="0xdeposit",
        block_number=100, confirmations=3,
    )
    assert result["status"] == "recorded"
    assert result["tx_hash"] == "0xabc"
    assert result["amount_usd"] == 10.0


def test_double_claim_rejected():
    cd.record_deposit(
        api_key="key1", tx_hash="0xdup", network="base",
        amount_token=5.0, amount_usd=5.0,
        sender_address="0xs", deposit_address="0xd",
        block_number=1,
    )
    result = cd.record_deposit(
        api_key="key2", tx_hash="0xdup", network="base",
        amount_token=5.0, amount_usd=5.0,
        sender_address="0xs2", deposit_address="0xd2",
        block_number=2,
    )
    assert result["status"] == "already_claimed"


def test_get_deposit_by_tx():
    cd.record_deposit(
        api_key="key1", tx_hash="0xfind", network="base",
        amount_token=1.0, amount_usd=1.0,
        sender_address="0xs", deposit_address="0xd",
        block_number=10,
    )
    dep = cd.get_deposit_by_tx("0xfind")
    assert dep is not None
    assert dep["api_key"] == "key1"
    assert dep["network"] == "base"

    assert cd.get_deposit_by_tx("0xmissing") is None


def test_get_deposits_for_key():
    for i in range(3):
        cd.record_deposit(
            api_key="keyA", tx_hash=f"0xtx{i}", network="base",
            amount_token=1.0, amount_usd=1.0,
            sender_address="0xs", deposit_address="0xd",
            block_number=i,
        )
    cd.record_deposit(
        api_key="keyB", tx_hash="0xother", network="base",
        amount_token=1.0, amount_usd=1.0,
        sender_address="0xs", deposit_address="0xd",
        block_number=99,
    )
    deps = cd.get_deposits_for_key("keyA")
    assert len(deps) == 3
    assert all(d["api_key"] == "keyA" for d in deps)


def test_is_tx_claimed():
    assert cd.is_tx_claimed("0xnope") is False
    cd.record_deposit(
        api_key="k", tx_hash="0xyes", network="base",
        amount_token=1.0, amount_usd=1.0,
        sender_address="0xs", deposit_address="0xd",
        block_number=1,
    )
    assert cd.is_tx_claimed("0xyes") is True


def test_mark_deposit_credited():
    cd.record_deposit(
        api_key="k", tx_hash="0xcredit", network="base",
        amount_token=2.0, amount_usd=2.0,
        sender_address="0xs", deposit_address="0xd",
        block_number=5,
    )
    dep = cd.get_deposit_by_tx("0xcredit")
    assert dep["credited"] == 0

    assert cd.mark_deposit_credited("0xcredit") is True
    dep = cd.get_deposit_by_tx("0xcredit")
    assert dep["credited"] == 1

    # non-existent tx
    assert cd.mark_deposit_credited("0xghost") is False


# ---- pending deposits ----

def test_create_pending_deposit():
    result = cd.create_pending_deposit(
        api_key="k1", network="base", deposit_address="0xaddr",
        expected_amount=5.0,
    )
    assert result["api_key"] == "k1"
    assert result["network"] == "base"
    assert result["expected_amount"] == 5.0
    assert result["expires_at"] > 0


def test_get_pending_for_address():
    cd.create_pending_deposit("k1", "base", "0xpend", expected_amount=1.0)
    cd.create_pending_deposit("k2", "base", "0xpend", expected_amount=2.0)
    cd.create_pending_deposit("k3", "solana", "0xpend", expected_amount=3.0)

    results = cd.get_pending_for_address("0xpend", "base")
    assert len(results) == 2

    results_sol = cd.get_pending_for_address("0xpend", "solana")
    assert len(results_sol) == 1


def test_get_pending_expired(monkeypatch):
    cd.create_pending_deposit("k1", "base", "0xexp", expected_amount=1.0)
    # Expire it by moving time forward
    import time as _time
    _real_time = _time.time
    monkeypatch.setattr(cd.time, "time", lambda: _real_time() + 90000)
    results = cd.get_pending_for_address("0xexp", "base")
    assert len(results) == 0


# ---- deposit addresses ----

def test_create_deposit_address():
    result = cd.create_deposit_address(
        api_key="k1", evm_address="0xevm", evm_index=0,
        solana_address="SolAddr", solana_index=1,
    )
    assert result["api_key"] == "k1"
    assert result["evm_address"] == "0xevm"
    assert result["solana_address"] == "SolAddr"


def test_get_deposit_address():
    cd.create_deposit_address("k1", "0xevm", 0)
    addr = cd.get_deposit_address("k1")
    assert addr is not None
    assert addr["evm_address"] == "0xevm"
    assert addr["solana_address"] is None


def test_get_deposit_address_not_found():
    assert cd.get_deposit_address("nonexistent") is None


def test_create_deposit_address_replace():
    cd.create_deposit_address("k1", "0xold", 0)
    cd.create_deposit_address("k1", "0xnew", 1, "SolNew", 2)
    addr = cd.get_deposit_address("k1")
    assert addr["evm_address"] == "0xnew"
    assert addr["evm_index"] == 1
    assert addr["solana_address"] == "SolNew"
