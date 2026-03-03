# tests/test_metered_pricing.py
import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api_keys import init_keys_db, generate_key, deduct, deduct_metered, get_key_status


def setup_module():
    import api_keys
    api_keys.DB_PATH = "/tmp/test_api_keys.db"
    try:
        os.unlink("/tmp/test_api_keys.db")
    except FileNotFoundError:
        pass
    init_keys_db()


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
