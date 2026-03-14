"""Global test fixtures — reset shared state between test modules."""
import os
import pytest


# Save original DB paths at import time so we can restore after tests that override them
_original_db_paths = {}


def _save_db_paths():
    """Capture original DB_PATH values from key modules."""
    for mod_name in ("api_keys", "crypto_deposits"):
        try:
            mod = __import__(mod_name)
            _original_db_paths[mod_name] = getattr(mod, "DB_PATH", None)
        except ImportError:
            pass


def _restore_db_paths():
    """Restore DB_PATH values that test modules may have overwritten."""
    for mod_name, orig_path in _original_db_paths.items():
        if orig_path is None:
            continue
        try:
            mod = __import__(mod_name)
            if getattr(mod, "DB_PATH", None) != orig_path:
                mod.DB_PATH = orig_path
        except ImportError:
            pass


# Save paths once at conftest import
_save_db_paths()


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Clear all caches and restore DB paths before each test."""
    _restore_db_paths()
    try:
        from helpers import _identity_rate, _ip_rate, _ttl_cache, _key_valid_cache
        _identity_rate.clear()
        _ip_rate.clear()
        _ttl_cache.clear()
        _key_valid_cache.clear()
    except (ImportError, AttributeError):
        pass
    yield
    _restore_db_paths()
    try:
        from helpers import _identity_rate, _ip_rate, _ttl_cache, _key_valid_cache
        _identity_rate.clear()
        _ip_rate.clear()
        _ttl_cache.clear()
        _key_valid_cache.clear()
    except (ImportError, AttributeError):
        pass
