# Funnel Attribution & Onboarding — Design Spec

## Problem

412 API keys exist but only 3 total calls have been made. We can't diagnose why because:
1. No `source` field on API keys — we don't know where users come from
2. Free key generation (`/auth/generate-key`) returns raw JSON with no guidance
3. Website links don't carry `?ref=` params, so launch post traffic will be invisible
4. `/admin/funnel` tracks demo→checkout but not key→first-call conversion

## Changes

### 1. Add `source` and `first_used_at` columns to `api_keys` table

**File:** `api_keys.py`

- Add `source TEXT DEFAULT 'unknown'` column via `ALTER TABLE` migration (run on startup, idempotent)
- Add `first_used_at TEXT` column via `ALTER TABLE` migration (idempotent)
- In `deduct()`: set `first_used_at = NOW` only when `first_used_at IS NULL` (tracks true first-call time)
- Update `generate_key()` to accept optional `source` parameter
- Populate `source` from:
  - `/auth/generate-key` POST body: `data.get("source", "api-direct")`
  - Stripe webhook: `"stripe"` (or `"stripe-{ref}"` if ref cookie was passed via checkout metadata)
  - x402 facilitator: `"x402"`

**Note:** Existing `ref_agent` in Stripe metadata (used for referral commissions in `record_conversion()`) is a separate concept. `source` tracks marketing attribution (where did the user come from). `ref_agent` tracks agent referral payouts. Both are preserved independently.

### 2. Capture `ref` param on website

**File:** `routes/meta.py` (landing page route), `templates/index.html`, `templates/try.html`

- Landing page (`/`): read `?ref=` query param, store in cookie `aipaygen_ref` (30-day expiry, `secure=True`, `httponly=True`, `samesite="Lax"`)
- `/try` page: read cookie, include in funnel log events
- `/buy-credits` page: read cookie, pass as hidden field to checkout form
- Stripe checkout: pass ref cookie value into checkout session metadata as `ref_source` (separate from existing `ref_agent`)
- Key generation routes: read ref cookie and pass as `source` to `generate_key()`

Cookie approach means ref survives navigation across pages.

### 3. Improve free key onboarding

**File:** `routes/auth.py` (generate-key response)

Add `quickstart` field to the JSON response:

```json
{
  "key": "apk_xxx",
  "balance_usd": 0.0,
  "quickstart": {
    "curl_example": "curl -H 'Authorization: Bearer apk_xxx' https://aipaygen.com/sentiment -X POST -d '{\"text\": \"hello world\"}'",
    "mcp_install": "pip install aipaygen-mcp && claude mcp add aipaygen -- aipaygen-mcp",
    "docs": "https://aipaygen.com/docs",
    "free_calls": 10,
    "note": "You get 10 free calls/day. No payment needed to start."
  }
}
```

### 4. Add key-to-first-call tracking on `/admin/funnel`

**File:** `routes/admin.py`

**Pre-req:** There are two `/admin/funnel` routes (line ~169 HTML dashboard, line ~875 JSON API). Consolidate: keep the HTML dashboard at `/admin/funnel`, rename the JSON one to `/admin/funnel-data`. Then extend the HTML dashboard with:

- Total keys created (by source, last 7d/30d)
- Keys with 0 calls vs 1+ calls (by source)
- Median time from key creation to first call (using `first_used_at - created_at`)
- These are simple SQL queries against `api_keys` table (created_at, call_count, first_used_at, source)

## Files Changed

| File | Change |
|------|--------|
| `api_keys.py` | Add `source` + `first_used_at` columns, update `generate_key()` + `deduct()` |
| `routes/auth.py` | Pass source to `generate_key()`, add quickstart to response |
| `routes/meta.py` | Read/set `ref` cookie on landing + try pages |
| `routes/admin.py` | Add key attribution stats to funnel dashboard |
| `templates/index.html` | JS to read `?ref=` and set cookie |
| `templates/try.html` | Read ref cookie, pass to demo events |

## Out of Scope

- Email drip campaigns / re-engagement (future)
- Full analytics platform (Plausible, PostHog, etc.)
- Changes to Stripe checkout flow beyond metadata
- New templates or pages

## Success Criteria

- After launch posts go live, we can see exactly how many keys came from HN vs Reddit vs organic
- We can query "how many keys have 0 calls" broken down by source
- New free-tier key holders get a working curl example they can copy-paste immediately
