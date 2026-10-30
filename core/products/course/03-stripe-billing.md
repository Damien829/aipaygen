# Lesson 03: Stripe Billing

## What You Will Build

Full Stripe integration: checkout session creation, webhook handling with signature verification, idempotent event processing, credit top-ups, subscription plans with monthly renewals, and anti-fraud protections. This is how you go from "side project" to "business."

## Setting Up Stripe

```python
import os
import stripe as _stripe

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY
```

Start with test mode. Stripe gives you `sk_test_` and `sk_live_` keys. Use test mode until your entire flow works end-to-end. Then flip to live keys and nothing else changes.

## Creating Checkout Sessions

The real production pattern handles top-ups (existing key) and new purchases (generate key after payment):

```python
@auth_bp.route("/stripe/create-checkout", methods=["POST"])
def stripe_create_checkout():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503

    # Rate limit checkout creation to block card-testing bots
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    if _check_checkout_rate(ip):
        return jsonify({"error": "Too many checkout attempts."}), 429

    data = request.get_json() or {}
    amount = float(data.get("amount", 0))
    
    allowed_amounts = (0.50, 1, 5, 10, 20, 25, 29, 50, 99)
    if amount not in allowed_amounts:
        return jsonify({"error": "invalid_amount"}), 400

    existing_key = str(data.get("existing_key", "")).strip()
    email = str(data.get("email", "")).strip().lower()

    # Top-up or new purchase?
    if existing_key and existing_key.startswith("apk_"):
        status = get_key_status(existing_key)
        if not status:
            return jsonify({"error": "key not found"}), 404
        action = "topup"
    else:
        existing_key = ""
        action = "new"

    session = _stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"API Credits — ${amount:.2f}",
                    "description": f"~{int(amount * 100)} API calls.",
                },
                "unit_amount": int(round(amount * 100)),  # cents
            },
            "quantity": 1,
        }],
        mode="payment",
        client_reference_id=existing_key or "new",
        metadata={
            "amount": str(amount),
            "action": action,
            **({"api_key": existing_key} if existing_key else {}),
        },
        success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/buy-credits?abandoned=1",
        billing_address_collection="required",
        expires_at=int(time.time()) + 1800,  # 30 minutes
    )
    return jsonify({"url": session.url, "session_id": session.id})
```

Key decisions in this code:

**Fixed allowed amounts.** Don't let users enter arbitrary amounts. Card testers love $0.01 charges to validate stolen card numbers. Fixed amounts plus `billing_address_collection="required"` makes this much harder.

**30-minute expiry.** Abandoned checkouts are noise. Expire them quickly.

**Metadata on the session.** This is how the webhook knows what to do — top up an existing key or create a new one.

## The Webhook: Where Money Becomes Credits

This is the most important endpoint in your entire application. Stripe calls this endpoint when a payment succeeds. You must handle it correctly — if you crash here, you lose the customer's money.

```python
@auth_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    
    try:
        event = _stripe.Webhook.construct_event(
            payload, sig, STRIPE_WEBHOOK_SECRET
        )
    except _stripe.error.SignatureVerificationError:
        return jsonify({"error": "invalid signature"}), 400

    # Idempotency: never process the same event twice
    event_id = event.get("id", "")
    if event_id and is_stripe_event_processed(event_id):
        return jsonify({"received": True, "duplicate": True})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        amount = float(meta.get("amount", 0))
        action = meta.get("action", "new")
        api_key = meta.get("api_key", "")

        if action == "topup" and api_key:
            topup_key(api_key, amount)
        else:
            # Generate new key with purchased balance
            key_data = generate_key(
                initial_balance=amount,
                label="stripe-checkout",
                source="stripe"
            )
            api_key = key_data["key"]

    # Mark event as processed
    mark_stripe_event_processed(event_id)
    return jsonify({"received": True})
```

## Idempotency Table

Stripe can (and will) send the same webhook event multiple times. Without idempotency protection, you will double-credit customers:

```python
def is_stripe_event_processed(event_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT event_id FROM processed_stripe_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return row is not None

def mark_stripe_event_processed(event_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO processed_stripe_events "
            "(event_id, processed_at) VALUES (?, ?)",
            (event_id, now),
        )
```

Simple. Effective. The `INSERT OR IGNORE` handles the race condition where two webhook deliveries arrive simultaneously.

## Subscription Plans

Subscriptions add recurring revenue. The pattern creates a Stripe subscription checkout and handles the recurring `invoice.paid` event:

```python
SUBSCRIPTION_TIERS = {
    "starter": {"price_usd": 9, "monthly_calls": 2000, "credits_usd": 12},
    "pro":     {"price_usd": 29, "monthly_calls": 7500, "credits_usd": 45},
    "enterprise": {"price_usd": 99, "monthly_calls": 30000, "credits_usd": 180},
}

@auth_bp.route("/stripe/create-subscription", methods=["POST"])
def stripe_create_subscription():
    data = request.get_json() or {}
    plan_id = data.get("plan", "starter")
    plan = SUBSCRIPTION_TIERS[plan_id]

    session = _stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"AiPayGen {plan_id.title()} Plan"},
                "unit_amount": plan["price_usd"] * 100,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        mode="subscription",
        metadata={"action": "subscription", "tier": plan_id},
        success_url=f"{BASE_URL}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/subscribe?abandoned=1",
    )
    return jsonify({"url": session.url})
```

On each monthly renewal, Stripe fires `invoice.paid`. Your webhook resets the customer's monthly call count:

```python
if event["type"] == "invoice.paid":
    invoice = event["data"]["object"]
    sub_id = invoice.get("subscription", "")
    if sub_id:
        # Find the API key linked to this subscription and reset calls
        reset_subscription_calls(key)
```

## Anti-Fraud: Checkout Rate Limiting

Card testers will find your checkout endpoint and hammer it. Rate limit by IP:

```python
_checkout_attempts = {}

def _check_checkout_rate(ip: str) -> bool:
    """Returns True if IP should be blocked (too many checkouts)."""
    now = time.time()
    attempts = _checkout_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < 300]  # 5-min window
    if len(attempts) >= 5:
        _checkout_attempts[ip] = attempts
        return True
    attempts.append(now)
    _checkout_attempts[ip] = attempts
    return False
```

Five checkout attempts per IP in five minutes is generous for real users and aggressive enough to stop bots.

## Exercise

1. Create a Stripe test account and get your `sk_test_` key and webhook signing secret.
2. Implement the `/stripe/create-checkout` endpoint with fixed allowed amounts.
3. Implement the `/stripe/webhook` endpoint with signature verification and idempotency.
4. Use the Stripe CLI to test: `stripe trigger checkout.session.completed`.
5. Verify: after a test payment, a new API key should exist with the purchased balance.

Next lesson: building the marketplace where other developers list their agents.
