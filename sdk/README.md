# AiPayGen SDK

Python client for [AiPayGen](https://aipaygen.com) APIs with automatic x402 payment handling.

## Install

```bash
pip install aipaygen-sdk

# With crypto support (auto-pay via USDC)
pip install aipaygen-sdk[crypto]
```

## Quick Start

```python
from aipaygen_sdk import Client

client = Client(api_key="apk_xxx")

# Call tools
result = client.ask("What is quantum computing?")
print(result.result)

result = client.research("AI agent frameworks 2026")
result = client.summarize("Long text here...")
result = client.translate("Hello world", target="es")
result = client.code("def fibonacci(n):", language="python")

# Generic tool call
result = client.call_tool("sentiment", text="I love this product")

# Check balance
balance = client.check_balance()
```

## Auto-Pay (x402)

When your free tier runs out, enable auto-pay to automatically handle 402 responses:

```python
client = Client(
    api_key="apk_xxx",
    auto_pay=True,
    wallet_key="0x...",  # Your Ethereum private key
)

# Automatically pays USDC on Base when 402 is returned
result = client.research("detailed analysis of x402 protocol")
print(result.paid)     # True
print(result.receipt)  # PaymentReceipt(...)
```

## Async

```python
from aipaygen_sdk import AsyncClient

async with AsyncClient(api_key="apk_xxx") as client:
    result = await client.ask("Hello")
    print(result.result)
```

## Streaming

```python
for chunk in client.stream("research", query="MCP servers"):
    print(chunk.data, end="")
```

## Error Handling

```python
from aipaygen_sdk import Client, AuthError, PaymentRequired, RateLimitError

try:
    result = client.ask("Hello")
except AuthError:
    print("Invalid API key")
except PaymentRequired as e:
    print(f"Payment needed: {e.payment_info}")
except RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
```

## Environment Variables

- `AIPAYGEN_API_KEY` — default API key (alternative to passing `api_key=`)

## License

MIT
