# tests/test_metered_pricing.py
import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api_keys
from api_keys import init_keys_db, generate_key, deduct, deduct_metered, get_key_status

_TEST_DB = "/tmp/test_metered_pricing.db"


@pytest.fixture(autouse=True)
def _use_test_db():
    """Override DB_PATH for every test, after conftest restores it."""
    api_keys.DB_PATH = _TEST_DB
    try:
        os.unlink(_TEST_DB)
    except FileNotFoundError:
        pass
    init_keys_db()
    yield
    try:
        os.unlink(_TEST_DB)
    except FileNotFoundError:
        pass


def test_deduct_metered():
    key_data = generate_key(initial_balance=1.00)
    key = key_data["key"]
    result = deduct_metered(key, input_tokens=1000, output_tokens=500,
                           input_rate=0.80, output_rate=4.00)
    assert result is not None
    assert result["cost"] == pytest.approx((1000*0.80 + 500*4.00) / 1_000_000, abs=0.0001)
    assert result["balance_remaining"] == pytest.approx(1.00 - result["cost"], abs=0.0001)


def test_deduct_metered_insufficient():
    key_data = generate_key(initial_balance=0.000001)
    key = key_data["key"]
    result = deduct_metered(key, input_tokens=1000000, output_tokens=1000000,
                           input_rate=15.0, output_rate=75.0)
    assert result is None


def test_deduct_metered_negative_cost():
    """Negative token counts should not credit the account."""
    key_data = generate_key(initial_balance=1.00)
    result = deduct_metered(key_data["key"], input_tokens=-1000, output_tokens=-500,
                           input_rate=0.80, output_rate=4.00)
    assert result is None
    status = get_key_status(key_data["key"])
    assert status["balance_usd"] == pytest.approx(1.00)
