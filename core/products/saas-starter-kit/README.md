# SaaS Starter Kit

A production-ready Flask API backend with Stripe billing, API key auth, rate limiting, and admin dashboard. Deploy your SaaS in minutes, not months.

Built from patterns battle-tested in production handling real payments and thousands of API calls daily.

---

## What's Included

| Feature | Description |
|---------|-------------|
| **Flask API** | Clean REST API with request tracing, CORS, gzip compression, error handling |
| **API Key Auth** | Generate, validate, revoke keys with `apk_` prefix. Per-key balance tracking |
| **Stripe Billing** | One-time credit purchases + recurring subscriptions. Full webhook handling |
| **Rate Limiting** | Per-key rate limiting (configurable requests/minute) |
| **Daily Spend Limits** | Per-key daily caps prevent runaway usage |
| **Admin Dashboard** | Key management, top-ups, revocation, revenue stats via admin API |
| **SQLite + WAL** | Zero-config database with write-ahead logging for concurrent reads |
| **Gzip Compression** | Automatic response compression for payloads > 500 bytes |
| **Idempotent Webhooks** | Stripe events are deduplicated — no double-crediting |
| **Checkout Rate Limiting** | Per-IP checkout throttling blocks card-testing bots |
| **Request IDs** | Every request gets a unique ID for tracing through logs |
| **Email Ready** | Resend integration for transactional emails |

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure your environment
cp env.template .env    # Edit .env with your Stripe keys, etc.

# 3. Run
python app_template.py
```

Your API is live at `http://localhost:5000`. Hit `/health` to verify.

---

## File Structure

```
saas-starter-kit/
├── app_template.py     # Main Flask app — routes, middleware, admin
├── auth.py             # Auth module — keys, billing, rate limits, Stripe
├── env.template        # Environment variable template
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── data/
    └── app.db          # SQLite database (created automatically)
```

---

## Architecture

```
Client Request
    │
    ▼
┌──────────────────┐
│  Flask Middleware │  ← Request ID, timing, CORS, gzip
└────────┬─────────┘
         │
    ┌────▼────┐
    │ Router  │
    └────┬────┘
         │
    ┌────▼──────────────┐
    │ @require_api_key  │  ← Validates key, checks rate limit, deducts cost
    └────┬──────────────┘
         │
    ┌────▼────────────┐
    │ Your API Logic  │
    └────┬────────────┘
         │
    ┌────▼────────┐
    │  Response   │  ← Auto-compressed, traced, timed
    └─────────────┘
```

**Billing flow:**
1. Client calls `POST /api/billing/checkout` with amount
2. Server creates Stripe Checkout session, returns URL
3. Customer pays on Stripe-hosted page
4. Stripe sends webhook to `POST /stripe/webhook`
5. Server generates API key with prepaid balance (or tops up existing key)
6. Customer uses key in `X-API-Key` header for paid endpoints

---

## API Reference

### Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | App info |
| `GET` | `/health` | Health check |
| `POST` | `/api/keys/generate` | Generate a new API key |
| `GET` | `/api/keys/status` | Check key balance (requires `X-API-Key`) |
| `POST` | `/api/keys/revoke` | Deactivate your key (requires `X-API-Key`) |
| `POST` | `/api/billing/checkout` | Create Stripe checkout for credits |
| `POST` | `/api/billing/subscribe` | Create Stripe subscription checkout |
| `POST` | `/stripe/webhook` | Stripe webhook receiver |
| `POST` | `/api/example` | Example paid endpoint ($0.01/call) |

### Admin (requires `X-Admin-Key` header)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/keys` | List all keys with usage stats |
| `POST` | `/admin/keys/<key>/topup` | Add balance to any key |
| `POST` | `/admin/keys/<key>/revoke` | Deactivate any key |
| `GET` | `/admin/stats` | Revenue and usage dashboard |

---

## Configuration

### Stripe Setup

1. Create a Stripe account at [stripe.com](https://stripe.com)
2. Get your API keys from [Dashboard > API Keys](https://dashboard.stripe.com/apikeys)
3. Create subscription products in [Dashboard > Products](https://dashboard.stripe.com/products):
   - Starter ($29/mo) — copy the Price ID to `STRIPE_PRICE_STARTER`
   - Pro ($79/mo) — copy the Price ID to `STRIPE_PRICE_PRO`
   - Business ($199/mo) — copy the Price ID to `STRIPE_PRICE_BUSINESS`
4. Create a webhook endpoint at [Dashboard > Webhooks](https://dashboard.stripe.com/webhooks):
   - URL: `https://yourdomain.com/stripe/webhook`
   - Events: `checkout.session.completed`, `customer.subscription.deleted`, `invoice.paid`
   - Copy the signing secret to `STRIPE_WEBHOOK_SECRET`

### Email Setup (Optional)

1. Create a Resend account at [resend.com](https://resend.com)
2. Verify your domain
3. Set `RESEND_API_KEY` and `EMAIL_FROM` in `.env`

---

## Adding Your API Endpoints

Replace the example endpoint with your business logic:

```python
@app.route("/api/analyze", methods=["POST"])
@require_api_key(cost=0.05)  # $0.05 per call
def analyze():
    data = request.get_json() or {}
    text = data.get("text", "")

    # Your logic here
    result = do_analysis(text)

    return jsonify({"result": result, "cost": 0.05})
```

The `@require_api_key(cost=X)` decorator handles:
- Key validation (401 if invalid)
- Rate limiting (429 if exceeded)
- Balance deduction (402 if insufficient funds)
- Sets `request.api_key` for your handler

Set `cost=0.0` for free endpoints that still require authentication.

---

## Deployment

### Production with Gunicorn

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 "app_template:create_app()"
```

### Systemd Service

Create `/etc/systemd/system/saas-api.service`:

```ini
[Unit]
Description=SaaS API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/saas-api
ExecStart=/opt/saas-api/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 "app_template:create_app()"
Restart=always
RestartSec=5
Environment=PATH=/opt/saas-api/venv/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable saas-api
sudo systemctl start saas-api
```

### Cloudflare Tunnel (Zero-Config HTTPS)

Expose your local server to the internet without opening ports:

```bash
# Install cloudflared
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install cloudflared

# Create tunnel
cloudflared tunnel login
cloudflared tunnel create saas-api
cloudflared tunnel route dns saas-api api.yourdomain.com

# Run tunnel
cloudflared tunnel --url http://localhost:5000 run saas-api
```

Create `/etc/systemd/system/cloudflared.service` for persistent tunnels:

```ini
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=www-data
ExecStart=/usr/bin/cloudflared tunnel run saas-api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Customization Guide

### Change Pricing Tiers

Edit the `allowed_amounts` tuple in `auth.py` → `create_checkout()`:

```python
allowed_amounts = (5, 10, 25, 50, 100, 200)
```

### Change Rate Limits

Set `RATE_LIMIT_PER_MINUTE` in `.env`, or implement per-tier limits:

```python
TIER_LIMITS = {"free": 10, "starter": 60, "pro": 300, "business": 1000}

def check_rate_limit(api_key: str) -> bool:
    record = validate_key(api_key)
    tier = record.get("subscription_tier") or "free"
    limit = TIER_LIMITS.get(tier, 10)
    # ... rest of rate limiting logic with dynamic limit
```

### Add User Accounts

The `users` table is already created. Extend it:

```python
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    # Add password hashing, email verification, etc.
    key = generate_key(label=email, source="registration")
    # Store user + key association
    return jsonify({"api_key": key["key"], "email": email})
```

### Add a Frontend

This kit is API-first. Pair it with any frontend:
- **React/Next.js** — call your API from the client
- **Static HTML** — serve from Flask with `render_template`
- **Mobile** — React Native or Flutter hitting your API

### Database Migration

To switch from SQLite to PostgreSQL:
1. Replace `sqlite3` with `psycopg2` in `auth.py`
2. Update connection logic in `_conn()`
3. Adjust SQL syntax (e.g., `AUTOINCREMENT` → `SERIAL`)

For most SaaS products, SQLite with WAL mode handles thousands of concurrent users without issues.

---

## Testing

```bash
# Generate a key
curl -X POST http://localhost:5000/api/keys/generate

# Check balance
curl -H "X-API-Key: apk_YOUR_KEY" http://localhost:5000/api/keys/status

# Call a paid endpoint
curl -X POST -H "X-API-Key: apk_YOUR_KEY" \
     -H "Content-Type: application/json" \
     -d '{"input": "test"}' \
     http://localhost:5000/api/example

# Admin stats
curl -H "X-Admin-Key: YOUR_ADMIN_SECRET" http://localhost:5000/admin/stats
```

---

## License

This is a purchased product. You may use it for unlimited commercial projects. Do not redistribute the source code.
