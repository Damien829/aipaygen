"""Global test fixtures — reset shared state between test modules."""
import atexit
import os
import shutil
import tempfile

# Must run before any app module is imported: every database path is built from
# AIPAYGEN_DATA_DIR at import time. Tests used to write into the live databases
# (the 2026-03-30 snapshot has 4,243 fake "credited" deposits from this).
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="aipaygen-test-data-")
os.environ["AIPAYGEN_DATA_DIR"] = _TEST_DATA_DIR
os.environ.pop("AIPAYGEN_RUN_SCHEDULER", None)
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

import pytest  # noqa: E402


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
