# Lesson 07: Webhooks and Events

## What You Will Build

Full webhook infrastructure: event subscriptions, HMAC-SHA256 payload signing, delivery tracking with status codes, automatic retry with exponential backoff, auto-disable after repeated failures, and a test endpoint. This is how you let customers build on top of your platform.

## Why Webhooks

Every meaningful action on your platform — a trade opened, a marketplace purchase, a balance deposit — should be observable. Webhooks let your customers automate their workflows: "When a trade closes, log it to my spreadsheet." "When my balance drops below $1, send me a Slack message."

## The Event Types

Define your events explicitly. Every event type maps to something real that happens on the platform:

```python
SUPPORTED_EVENTS = [
    "trade.opened",
    "trade.closed",
    "strategy.activated",
    "strategy.paused",
    "marketplace.purchase",
    "marketplace.review",
    "balance.low",
    "balance.deposit",
]

MAX_RETRIES = 3
DELIVERY_TIMEOUT = 10  # seconds
```

## Subscription Schema

Two tables: one for subscriptions (what the customer wants), one for deliveries (what actually happened):

```python
def _init_webhooks_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '[]',
            secret TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_delivery_at TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            response_code INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            FOREIGN KEY (subscription_id) REFERENCES webhook_subscriptions(id)
        )""")
```

The `failure_count` on subscriptions is key — it enables auto-disable after repeated failures, which prevents your background workers from wasting time on dead endpoints.

## HMAC Signing

Every webhook delivery is signed with HMAC-SHA256. The customer uses their secret to verify the payload hasn't been tampered with:

```python
import hmac
import hashlib

def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
```

The signature is sent in the `X-Webhook-Signature` header as `sha256=<hex>`. This is the same pattern used by GitHub, Stripe, and Shopify. Customers verify it like this:

```python
# Customer's verification code
import hmac, hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

Always use `hmac.compare_digest` for timing-safe comparison. Never use `==` — it leaks timing information that can be exploited to forge signatures.

## Firing Events

When something happens on your platform, call `fire_event`. It finds all matching subscriptions and queues deliveries:

```python
def fire_event(event_type: str, payload: dict):
    """Find all active subscriptions for this event and queue deliveries."""
    now = datetime.now(timezone.utc).isoformat()
    queued = 0
    with _conn() as c:
        rows = c.execute(
            "SELECT id, events FROM webhook_subscriptions WHERE active = 1"
        ).fetchall()
        for row in rows:
            events = json.loads(row["events"])
            if event_type in events or "*" in events:
                delivery_id = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO webhook_deliveries "
                    "(id, subscription_id, event_type, payload, status, attempts, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                    (delivery_id, row["id"], event_type, json.dumps(payload), now),
                )
                queued += 1
    # Kick off async delivery
    if queued > 0:
        threading.Thread(target=process_webhook_queue, daemon=True).start()
    return queued
```

The wildcard `*` subscription lets power users receive all events. The delivery is queued in the database first, then a background thread processes it. This means the event producer never blocks waiting for HTTP deliveries.

## Delivery with Retry

The delivery function implements exponential backoff (1s, 2s, 4s) with a maximum of 3 attempts:

```python
def deliver_webhook(delivery_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT d.id, d.payload, d.attempts, s.url, s.secret, s.id as sub_id "
            "FROM webhook_deliveries d "
            "JOIN webhook_subscriptions s ON d.subscription_id = s.id "
            "WHERE d.id = ?",
            (delivery_id,),
        ).fetchone()
    if not row:
        return False

    payload_bytes = row["payload"].encode()
    signature = _sign_payload(payload_bytes, row["secret"])
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={signature}",
        "X-Webhook-Event": row["event_type"],
        "X-Webhook-Delivery": delivery_id,
        "User-Agent": "AiPayGen-Webhooks/1.0",
    }

    for attempt in range(row["attempts"], MAX_RETRIES):
        wait = 2 ** attempt  # 1s, 2s, 4s
        if attempt > 0:
            time.sleep(wait)

        try:
            resp = requests.post(
                row["url"], data=payload_bytes,
                headers=headers, timeout=DELIVERY_TIMEOUT
            )
            with _conn() as c:
                c.execute(
                    "UPDATE webhook_deliveries SET attempts = ?, response_code = ? "
                    "WHERE id = ?",
                    (attempt + 1, resp.status_code, delivery_id),
                )
                if 200 <= resp.status_code < 300:
                    c.execute(
                        "UPDATE webhook_deliveries SET status = 'delivered', "
                        "delivered_at = ? WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(), delivery_id),
                    )
                    c.execute(
                        "UPDATE webhook_subscriptions SET failure_count = 0 "
                        "WHERE id = ?", (row["sub_id"],),
                    )
                    return True
        except Exception as exc:
            logger.warning("Delivery %s attempt %d failed: %s",
                           delivery_id, attempt + 1, exc)

    # All retries exhausted
    with _conn() as c:
        c.execute("UPDATE webhook_deliveries SET status = 'failed' WHERE id = ?",
                  (delivery_id,))
        c.execute(
            "UPDATE webhook_subscriptions SET failure_count = failure_count + 1 "
            "WHERE id = ?", (row["sub_id"],),
        )
        # Auto-disable after 10 consecutive failures
        c.execute(
            "UPDATE webhook_subscriptions SET active = 0 "
            "WHERE id = ? AND failure_count >= 10",
            (row["sub_id"],),
        )
    return False
```

The auto-disable at 10 failures is essential. Without it, a customer who decommissions their webhook server will cause your background workers to waste time forever.

## The API Endpoints

### Subscribe

```python
@webhooks_bp.route("/webhooks/subscribe", methods=["POST"])
@require_api_key
def webhook_subscribe():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    events = data.get("events", [])

    if not url.startswith("https://"):
        return jsonify({"error": "url must use HTTPS"}), 400

    invalid = [e for e in events if e not in SUPPORTED_EVENTS and e != "*"]
    if invalid:
        return jsonify({"error": f"unsupported events: {invalid}"}), 400

    sub_id = str(uuid.uuid4())
    secret = secrets.token_hex(32)
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM webhook_subscriptions "
            "WHERE user_id = ? AND active = 1", (request.api_key,)
        ).fetchone()[0]
        if count >= 20:
            return jsonify({"error": "maximum 20 active subscriptions"}), 429

        c.execute(
            "INSERT INTO webhook_subscriptions "
            "(id, user_id, url, events, secret, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (sub_id, request.api_key, url, json.dumps(events), secret, now),
        )

    return jsonify({
        "id": sub_id, "url": url, "events": events,
        "secret": secret, "active": True,
        "message": "Store the secret — it won't be shown again.",
    }), 201
```

### Test Delivery

Let customers test their webhook without waiting for a real event:

```python
@webhooks_bp.route("/webhooks/test/<sub_id>", methods=["POST"])
@require_api_key
def webhook_test(sub_id):
    test_payload = {
        "event": "trade.opened",
        "test": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"message": "Test webhook delivery from AiPayGen."},
    }
    # Deliver synchronously so caller gets immediate result
    success = deliver_webhook(delivery_id)
    return jsonify({"success": success, "delivery_id": delivery_id})
```

## Integrating Events Across the Platform

Wire `fire_event` into your existing code wherever something significant happens:

```python
# In trading_engine.py after closing a trade:
from routes.webhooks import fire_event

fire_event("trade.closed", {
    "trade_id": trade_id,
    "pair": pair,
    "pnl": pnl,
    "pnl_pct": pnl_pct,
    "strategy_id": strategy_id,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
```

## Exercise

1. Create the webhook tables (subscriptions and deliveries).
2. Implement the subscribe endpoint with HTTPS validation and secret generation.
3. Implement `fire_event` and `deliver_webhook` with HMAC signing.
4. Add retry logic with exponential backoff and auto-disable.
5. Test: subscribe a webhook to https://webhook.site, fire a test event, verify it arrives with a valid signature.

Next lesson: deploying everything to production on a Raspberry Pi 5.
