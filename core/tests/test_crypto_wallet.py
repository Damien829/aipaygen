"""Tests for HD wallet derivation."""

import pytest
from crypto_wallet import derive_evm_address, get_main_wallet

TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


def test_derive_evm_address_deterministic():
    addr1 = derive_evm_address(TEST_MNEMONIC, 0)
    addr2 = derive_evm_address(TEST_MNEMONIC, 0)
    assert addr1 == addr2
    assert addr1.startswith("0x")
    assert len(addr1) == 42


def test_derive_different_indices():
    addr0 = derive_evm_address(TEST_MNEMONIC, 0)
    addr1 = derive_evm_address(TEST_MNEMONIC, 1)
    assert addr0 != addr1


def test_get_main_wallet():
    assert get_main_wallet() == "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
