# Crypto Micropayments Design — 2026-03-10

## Goal
Enable API key funding via direct crypto deposits (no Stripe) and provide demo paying agents so developers can see x402 payments in action.

## Part A: Direct USDC Top-Up

### Supported Networks
- **Base Mainnet** (chain 8453) — USDC contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- **Solana Mainnet** — USDC-SPL mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

### Three Deposit Methods

#### 1. Manual Claim (MVP)
- User calls `POST /crypto/deposit` with API key → returns wallet address, USDC contract, QR code
- User sends USDC on Base or Solana
- User calls `POST /crypto/claim` with `{"api_key": "apk_...", "tx_hash": "0x...", "network": "base"}`
- Server verifies onchain: correct recipient, USDC contract, amount, block confirmations, not already claimed
- Credits `balance_usd` via existing `topup_key()`

#### 2. Background Polling (Auto-Detect)
- Background thread polls Base RPC every ~15s for USDC Transfer events to wallet
- Second thread polls Solana RPC for USDC-SPL transfers
- Matches deposits to API keys via pending_deposits table (user registers intent via `/crypto/deposit`)
- Auto-credits balance, sends email notification via Resend

#### 3. Unique Deposit Addresses (HD Wallet)
- Derive per-user EVM addresses using HD wallet (BIP-44) from master key
- Each API key gets a unique deposit address — no ambiguity
- Sweep funds to main wallet periodically via background task
- For Solana: derive unique addresses from master Solana keypair

### Endpoints
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /crypto/deposit | API key | Get deposit address + QR code |
| POST | /crypto/claim | API key | Claim deposit via tx hash |
| GET | /crypto/deposits | API key | Deposit history for key |
| GET | /crypto/address | API key | Get/generate unique deposit address |
| GET | /admin/crypto/deposits | Admin | All deposits (admin view) |
| GET | /crypto | Public | HTML landing page with instructions |
| WS | /crypto/ws/status/<key> | API key | Real-time deposit status |

### Data Model — crypto_deposits.db
```sql
CREATE TABLE deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL,
    tx_hash TEXT UNIQUE NOT NULL,
    network TEXT NOT NULL,  -- 'base' or 'solana'
    amount_token REAL NOT NULL,  -- raw USDC amount
    amount_usd REAL NOT NULL,  -- credited USD (after fee)
    fee_usd REAL DEFAULT 0.0,
    sender_address TEXT NOT NULL,
    deposit_address TEXT NOT NULL,  -- our receiving address
    block_number INTEGER,
    confirmations INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- pending, confirmed, credited, rejected
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    credited_at TEXT
);

CREATE TABLE deposit_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT UNIQUE NOT NULL,
    evm_address TEXT NOT NULL,
    evm_derivation_index INTEGER NOT NULL,
    solana_address TEXT,
    solana_derivation_index INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE pending_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL,
    network TEXT NOT NULL,
    expected_amount REAL,  -- optional hint
    deposit_address TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL  -- 24h TTL
);
```

### Security
- Double-claim prevention: tx_hash UNIQUE constraint
- Block confirmations: Base 5 blocks (~10s), Solana finalized status
- Amount sanity: reject deposits > $10,000 (flag for manual review)
- Rate limit: /crypto/claim rate-limited (10/min per IP)
- Min deposit: configurable via `CRYPTO_MIN_DEPOSIT_USD` (default $0.50)
- Fee: configurable via `CRYPTO_FEE_PERCENT` (default 0%)

### Observability
- Wall notifications on deposit (same as Stripe checkout)
- Funnel events: deposit_requested, deposit_detected, deposit_credited
- Email via Resend: deposit confirmed + balance updated

### Config (env vars)
```
CRYPTO_MIN_DEPOSIT_USD=0.50
CRYPTO_FEE_PERCENT=0
CRYPTO_MAX_DEPOSIT_USD=10000
CRYPTO_POLL_INTERVAL=15
CRYPTO_BASE_RPC=https://mainnet.base.org
CRYPTO_SOLANA_RPC=https://api.mainnet-beta.solana.com
CRYPTO_HD_MNEMONIC=  # for HD wallet derivation
WALLET_ADDRESS=0x366D488a48de1B2773F3a21F1A6972715056Cb30
```

## Part B: Demo Paying Agent

### Format 1: Standalone Script (`examples/demo_paying_agent.py`)
- Single file, ~150 lines
- Calls 3 AiPayGen endpoints via x402: research, summarize, translate
- Chains them into a multi-tool workflow
- Prints cost per call and running total
- Shows error recovery (402 handling, insufficient funds, retries)
- Requires: `pip install x402 eth-account requests`

### Format 2: Jupyter Notebook (`examples/demo_paying_agent.ipynb`)
- Step-by-step walkthrough with markdown explanations
- Cell 1: Setup and wallet config
- Cell 2: Single x402 call with payment
- Cell 3: Multi-tool chain with cost tracking
- Cell 4: Error handling patterns
- Cell 5: Spending stats and summary

### Format 3: CLI Tool (`examples/aipaygen-agent-cli/`)
- `pip install aipaygen-agent`
- `aipaygen-agent ask "summarize the latest AI news"`
- `aipaygen-agent research "x402 protocol adoption"`
- `aipaygen-agent translate "Hello world" --to french`
- `aipaygen-agent balance` — show x402 spend stats
- Uses x402_client.py patterns, wraps requests session with auto-payment

### Shared: `examples/README.md`
- Explains all three formats
- Links to docs, x402.org, wallet setup guide
- Prerequisites and quick-start

## Part C: Landing Page & Navigation

### `/crypto` HTML Page
- Explains crypto top-up flow
- Shows wallet address with copy button
- QR code for wallet address
- Supported networks (Base, Solana) with logos
- Step-by-step guide
- Link to claim endpoint docs

### Navigation Update
- Add "Crypto Top-Up" to nav bar (green highlight, next to "Buy Credits")

## New Files
| File | Purpose |
|------|---------|
| crypto_deposits.py | Deposit DB, onchain verification, HD derivation, sweep |
| crypto_poller.py | Background threads polling Base + Solana RPCs |
| routes/crypto.py | All /crypto/* endpoints |
| templates/crypto.html | Landing page |
| examples/demo_paying_agent.py | Standalone demo script |
| examples/demo_paying_agent.ipynb | Jupyter notebook demo |
| examples/aipaygen-agent-cli/setup.py | CLI package setup |
| examples/aipaygen-agent-cli/cli.py | CLI entry point |
| examples/README.md | Examples documentation |

## Dependencies
- Already installed: web3, eth-account, solana, solders, qrcode, pillow
- May need: `mnemonic` or `bip_utils` for HD wallet derivation (check if eth-account covers it)
