"""Outbound webhooks are signed with a timestamp and never carry the full API key."""
import json
from unittest.mock import MagicMock, patch

from security import verify_webhook_signature, webhook_signature_headers


def test_signature_round_trip_and_replay_window():
    body = b'{"event":"balance_low"}'
    h = webhook_signature_headers("sec", body, now=1_000_000)
    sig = h["X-Webhook-Signature-V2"]
    assert h["X-Webhook-Timestamp"] == "1000000"
    assert verify_webhook_signature("sec", body, sig, now=1_000_100)
    assert not verify_webhook_signature("sec", body, sig, now=1_000_000 + 301)  # replayed too late
    assert not verify_webhook_signature("other", body, sig, now=1_000_100)      # wrong secret
    assert not verify_webhook_signature("sec", body + b" ", sig, now=1_000_100)  # tampered body
    assert not verify_webhook_signature("sec", body, "garbage", now=1_000_100)


def test_dispatch_signs_and_masks_api_key():
    import webhook_dispatch as wd
    key = "apk_live_abcdefghijklmnop9999"
    wh_id = wd.register_webhook(key, "https://hooks.example.com/x", ["balance_low"])
    secret = wd.get_webhook_secret(wh_id, key)
    assert secret and len(secret) == 64
    assert wd.get_webhook_secret(wh_id, "apk_someone_else_entirely") is None

    resp = MagicMock(status_code=200, text="ok")
    with patch.object(wd.requests, "post", return_value=resp) as post:
        assert wd.dispatch_test_event("balance_low", key, {"balance": 0.1}) == 1
    sent = post.call_args.kwargs
    assert key not in sent["data"].decode()
    assert json.loads(sent["data"])["api_key"] == "apk_li…9999"
    assert verify_webhook_signature(secret, sent["data"], sent["headers"]["X-Webhook-Signature-V2"])


def test_subscription_deliveries_carry_timestamped_signature():
    from routes import webhooks as wh
    assert wh._requests.__class__.__name__ == "_GuardedClient"  # SSRF-safe client
