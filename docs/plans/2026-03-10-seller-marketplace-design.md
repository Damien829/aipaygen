# API Seller Marketplace — Design

**Date**: 2026-03-10
**Status**: Approved
**Competitor ref**: apitoll.com (x402 facilitator, 3% fee, Base+Solana)

## Overview

Third-party API sellers register endpoints with AiPayGen. We proxy agent requests, collect x402 USDC payments, keep 3%, forward 97% to sellers. Full facilitator model with multi-chain settlement, fiat on-ramp, agent wallets with budget policies, and optional escrow.

## Data Model

### seller_apis
- id, seller_id, slug, name, description, base_url
- routes (JSON: [{path, method, price_usd, description}])
- seller_wallet, preferred_chain (base|solana)
- category, is_verified, is_active, escrow_enabled
- total_calls, total_revenue_usd, balance_usd, created_at

### agent_wallets
- id, owner_api_key, label, balance_usd
- daily_budget, monthly_budget, spent_today, spent_month
- vendor_allowlist (JSON), created_at

### escrow_holds
- id, agent_wallet_id, seller_api_id, amount_usd
- status (held|released|refunded), tx_hash, created_at, resolved_at

### seller_payouts
- id, seller_id, amount_usd, chain, tx_hash
- status (pending|sent|confirmed), created_at

## Endpoints

### Seller Management
- POST /sell/register — onboard API (name, base_url, routes, wallet, chain)
- GET /sell/directory — browse all seller APIs (filterable)
- GET /sell/{slug}/docs — auto-generated OpenAPI docs
- GET /sell/dashboard — seller analytics (calls, revenue, latency)
- POST /sell/withdraw — withdraw earnings to wallet
- PATCH /sell/{api_id} — update routes/pricing
- DELETE /sell/{api_id} — remove listing

### Proxied API Calls
- ANY /sell/{slug}/{path} — proxied call with x402 payment
  - Returns 402 with price from route config
  - On payment: proxy to seller base_url, deduct 3%, credit seller
  - Escrow mode: hold payment until 2xx, refund on timeout/5xx

### Agent Wallets
- POST /wallet/create — create agent wallet with budget
- GET /wallet/balance — check balance + spend stats
- POST /wallet/fund — Stripe checkout → USDC credits (fiat on-ramp)
- PATCH /wallet/policy — set daily/monthly budget, vendor allowlist
- GET /wallet/transactions — transaction history

### Escrow
- GET /escrow/{id} — check escrow status

## Payment Flow

```
Agent → GET /sell/weather-api/forecast?city=NYC
  ← 402 Payment Required (price: $0.005, chain: base, payTo: our_wallet)
Agent → pays USDC on Base (or uses internal balance)
Agent → retries with payment proof header
  We → proxy to seller's base_url/forecast?city=NYC
  We → seller returns 200
  We → credit seller balance (97%), keep 3%
  ← 200 OK (seller response + _billing metadata)
```

### Escrow flow
```
Agent → calls escrow-enabled seller API
  We → hold payment in escrow_holds table
  We → proxy to seller
  Seller returns 2xx → release escrow to seller
  Seller returns 5xx/timeout → refund to agent
```

## Multi-chain Settlement
- Base (default): 2s finality, EIP-3009
- Solana: 400ms finality, SPL USDC transfers
- Seller picks preferred chain at registration
- Withdrawals go to seller_wallet on their preferred chain

## Fiat On-ramp
- Stripe Checkout session → agent buys USDC credits
- Credits stored as agent_wallet.balance_usd
- Internal balance used for API calls (no on-chain tx needed per call)
- Minimum purchase: $5

## Agent Swarm Management
- Each agent gets own wallet (POST /wallet/create)
- Per-wallet budget caps (daily + monthly)
- Vendor allowlist: restrict which seller APIs an agent can call
- Anomaly detection: alert if agent exceeds 2x normal daily spend
- Spend tracking: spent_today resets at midnight UTC, spent_month at month start

## Implementation Files
- seller_marketplace.py — core logic (DB, CRUD, proxy, settlement)
- routes/seller.py — Flask blueprint (all /sell/* and /wallet/* endpoints)
- Update mcp_server.py — add MCP tools for seller marketplace
- Update app.py — register blueprint + init

## Platform Fee
- 3% of every transaction
- Competitive with API Toll (3%)
- Sellers keep 97%
- Fee deducted before crediting seller balance
