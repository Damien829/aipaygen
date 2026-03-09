# Platform Acceleration Design — 2026-03-09

## Goal
Get ahead of x402 adoption by maximizing revenue capture, discovery, platform moat, and retention.

## Wave 1 — Revenue Capture (highest priority, compounds everything)

### Resend Email Integration
- Add `resend` Python SDK
- Send API key + usage guide on Stripe purchase
- Send nudge email when free tier exhausted
- Free tier: 100 emails/day, no credit card needed

### Key Lookup Page (`/my-key`)
- Retrieve key by Stripe session ID or email
- No login required — simple form

### Magic Link Accounts
- Email-based, no password
- POST `/auth/magic-link` sends login link via Resend
- Token stored as signed JWT cookie (24h expiry)
- Keys tied to email address

### Dashboard (`/dashboard`)
- Balance, usage history, calls by endpoint, top-up button
- Burn rate projection
- Requires magic link login

### Stripe Webhook Race Condition Fix
- Success page polls `/auth/key-status?session_id=xxx` instead of reading metadata immediately
- Webhook creates key first, success page retrieves it async

### Free Tier Exhaustion Nudge
- Personalized 402 body: "You used 10 free calls today across N tools. Unlock unlimited for $5."
- `X-Upgrade-Hint` header when remaining <= 3

## Wave 2 — Discovery & SEO

### OpenAPI Spec (`/openapi.json`)
- Auto-generated at startup from `routes` dict
- Includes tool descriptions, pricing, auth methods
- Picked up by Glama, Smithery, agent frameworks

### AI Plugin Manifest (`/.well-known/ai-plugin.json`)
- ChatGPT/OpenAI plugin format
- Points to OpenAPI spec, describes auth flow

### Enhanced `/llms.txt`
- Add tool descriptions, pricing tiers, example curl calls
- LLMs can recommend AiPayGen without visiting the site

### `sitemap.xml` + `robots.txt`
- Proper sitemap for Google crawling
- robots.txt allowing crawlers on key pages

### 402 Link Headers
- `Link: </openapi.json>; rel="service-desc"` on all 402 responses
- Agents self-discover capabilities when hitting paywall

## Wave 3 — Platform Moat

### Multi-Step Workflows (`/workflow/run`)
- Chain tools in single call: `["research", "summarize", "translate"]`
- Each step output feeds next step input
- 15% discount vs individual calls
- Charged per step with metered billing

### Persistent Agent Sessions
- `POST /session/start` — creates session with context
- `POST /session/call` — makes call within session, shares context
- `GET /session/resume` — resume session by ID
- Context stored in SQLite, TTL 24h

### Webhook Registration
- Key holders register webhooks: `POST /webhooks/register`
- Events: `balance_low`, `free_tier_exhausted`, `new_tools`, `session_expired`
- Retry with exponential backoff (3 attempts)

### Marketplace Revenue Sharing
- Tool creators set custom pricing
- Platform takes 20% fee
- Creators earn from every call to their tools
- Payout tracking in dashboard

## Wave 4 — Retention

### Expanded `/try` Page
- 15 tools (add: research, scrape, workflow, vision, code, compare, extract)
- Live response with timing display
- "Copy as curl" button per result
- Rate limit: 10 demos/10min

### Usage Dashboard Charts
- Daily usage sparkline (last 30 days)
- Top endpoints pie chart
- Burn rate: "At current usage, balance lasts N days"

### Weekly Digest Email
- For account holders with activity
- Stats: calls made, tools used, money spent/saved
- New tools announcement
- Sent via Resend, unsubscribe link

### Upgrade Hint Headers
- `X-Free-Calls-Remaining: N` (already implemented)
- `X-Upgrade-Hint: true` when remaining <= 3
- 402 body includes usage stats when free tier exhausted

## Tech Stack Additions
- `resend` — email (free 100/day)
- Magic links over passwords (simpler, more secure)
- SQLite for sessions/accounts (consistent with existing arch)
- OpenAPI spec generated at startup from routes dict

## Dependencies
- Resend API key (sign up at resend.com)
- Domain verification for sending from @aipaygen.com

## Success Criteria
- First paid API key from organic user (not test)
- >50 accounts created in first week
- >5 workflow chain calls per day
- Dashboard page views > 10/day
