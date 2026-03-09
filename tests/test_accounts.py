import pytest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["ACCOUNTS_DB"] = ":memory:"

from accounts import init_accounts_db, create_or_get_account, get_account_by_email, link_key_to_account, get_account_keys

def setup_module():
    init_accounts_db()

def test_create_account():
    acct = create_or_get_account("test@example.com")
    assert acct["email"] == "test@example.com"
    assert acct["id"] is not None

def test_get_existing_account():
    a1 = create_or_get_account("same@example.com")
    a2 = create_or_get_account("same@example.com")
    assert a1["id"] == a2["id"]

def test_get_account_by_email():
    create_or_get_account("lookup@example.com")
    assert get_account_by_email("lookup@example.com") is not None

def test_get_account_not_found():
    assert get_account_by_email("nope@example.com") is None

def test_link_key_to_account():
    acct = create_or_get_account("keys@example.com")
    link_key_to_account(acct["id"], "apk_testkey123")
    keys = get_account_keys(acct["id"])
    assert len(keys) == 1
    assert keys[0]["api_key"] == "apk_testkey123"

def test_link_duplicate_key():
    acct = create_or_get_account("dup@example.com")
    link_key_to_account(acct["id"], "apk_dupkey")
    link_key_to_account(acct["id"], "apk_dupkey")
    assert len(get_account_keys(acct["id"])) == 1
