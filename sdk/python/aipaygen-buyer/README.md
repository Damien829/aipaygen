# aipaygen-buyer

Python Buyer SDK for [AiPayGen](https://aipaygen.com) x402 micropayment APIs. Automatically handles 402 Payment Required responses with signed USDC payments on Base Mainnet.

## Install

```bash
pip install aipaygen-buyer
```

## Quick Start

```python
from aipaygen_buyer import AiPayGenBuyer

client = AiPayGenBuyer(
    private_key="0xYOUR_PRIVATE_KEY",  # or set AIPAYGEN_PRIVATE_KEY env var
    max_price=0.05,      # max $0.05 per call
    daily_budget=5.0,    # max $5/day
)

# Call any AiPayGen API — 402s are handled automatically
result = client.call("/ask", prompt="What is the x402 protocol?")
print(result.data)
print(f"Paid: {result.paid}")

# Check spending
print(f"Budget remaining: ${client.budget_remaining:.2f}")
print(f"Total spent: ${client.stats.total_spent_usdc:.4f}")
```

## Features

- **Auto-402 handling** — Detects 402 responses, signs EIP-3009 payments, retries with X-Payment header
- **Policy engine** — Per-call price limits, daily/monthly budgets, vendor allowlists/blocklists
- **Transaction tracking** — Every payment logged with receipts, timestamps, and tx hashes
- **Async support** — `AsyncAiPayGenBuyer` with identical API using `httpx.AsyncClient`
- **Discovery** — Browse API catalog and x402 protocol metadata

## Policy Engine

```python
from aipaygen_buyer import AiPayGenBuyer, SpendingPolicy

policy = SpendingPolicy(
    max_price_per_call=0.02,     # reject calls over $0.02
    daily_budget=2.0,            # $2/day cap
    monthly_budget=50.0,         # $50/month cap
    vendor_allowlist={           # only pay these wallets
        "0x366D488a48de1B2773F3a21F1A6972715056Cb30",
    },
    endpoint_allowlist={"/ask", "/summarize", "/translate"},
)

client = AiPayGenBuyer(private_key="0x...", policy=policy)
```

## Async Usage

```python
import asyncio
from aipaygen_buyer import AsyncAiPayGenBuyer

async def main():
    async with AsyncAiPayGenBuyer(private_key="0x...") as client:
        result = await client.call("/ask", prompt="Hello")
        print(result.data)

asyncio.run(main())
```

## API Key Mode

If you have a prepaid API key, you can skip x402 payments entirely:

```python
client = AiPayGenBuyer(api_key="apk_YOUR_KEY")
result = client.call("/ask", prompt="No crypto needed")
```

## Receipts & Tracking

```python
client = AiPayGenBuyer(private_key="0x...")

client.call("/ask", prompt="First call")
client.call("/summarize", text="Some long text...")

for receipt in client.receipts:
    print(f"{receipt.endpoint}: ${receipt.price_usdc} at {receipt.timestamp}")

stats = client.stats
print(f"Calls today: {stats.calls_today}")
print(f"Spent today: ${stats.spent_today_usdc:.4f}")
```

## Discovery

```python
client = AiPayGenBuyer()

# x402 protocol metadata
info = client.discover()
print(info["chains"])  # Base, Solana

# Browse API catalog
catalog = client.catalog(search="translate", category="ai")
```

## Environment Variables

| Variable | Description |
|---|---|
| `AIPAYGEN_PRIVATE_KEY` | Ethereum private key for signing payments |
| `AIPAYGEN_API_KEY` | Prepaid API key (alternative to x402) |

## How It Works

1. SDK makes an API request to AiPayGen
2. If the endpoint returns **402 Payment Required** with x402 headers:
   - `X-Price-USDC`: Price for the call
   - `X-Pay-To`: Vendor wallet address
   - `X-Network`: Chain (eip155:8453 = Base Mainnet)
   - `X-Facilitator-URL`: Payment processor
3. SDK checks the payment against your **spending policy**
4. If approved, signs an **EIP-3009 TransferWithAuthorization** for USDC
5. Retries the request with the signed `X-Payment` header
6. Server verifies payment via the facilitator and returns the response
7. Receipt is logged for tracking

## License

MIT
