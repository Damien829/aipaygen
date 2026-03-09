import pytest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("WEBHOOKS_DB", ":memory:")

from webhook_dispatch import init_webhooks_dispatch_db, register_webhook, list_webhooks, delete_webhook, dispatch_event

def setup_module():
    init_webhooks_dispatch_db()

def test_register_webhook():
    wh_id = register_webhook("apk_test1", "https://example.com/hook", ["balance_low", "free_tier_exhausted"])
    assert wh_id is not None

def test_list_webhooks():
    register_webhook("apk_test2", "https://example.com/hook2", ["balance_low"])
    hooks = list_webhooks("apk_test2")
    assert len(hooks) >= 1
    assert hooks[0]["url"] == "https://example.com/hook2"

def test_delete_webhook():
    wh_id = register_webhook("apk_test3", "https://example.com/hook3", ["balance_low"])
    result = delete_webhook(wh_id, "apk_test3")
    assert result is True
    assert len(list_webhooks("apk_test3")) == 0

def test_delete_wrong_owner():
    wh_id = register_webhook("apk_owner", "https://example.com/hook4", ["balance_low"])
    result = delete_webhook(wh_id, "apk_other")
    assert result is False

def test_dispatch_event_no_webhooks():
    # Should not error even with no matching webhooks
    dispatch_event("nonexistent_event", "apk_nobody", {"test": True})

def test_register_validates_url():
    # Should reject non-https URLs
    wh_id = register_webhook("apk_test5", "http://insecure.com/hook", ["balance_low"])
    assert wh_id is None
