# AiPayGen Examples

Runnable examples showing how AI agents pay for API calls with crypto (USDC on Base) using the x402 protocol.

## Prerequisites

```bash
pip install x402 eth-account requests
```

You need a wallet private key with USDC on **Base** (chain 8453). Even $2 is enough for hundreds of micro-payment API calls.

```bash
export AGENT_PRIVATE_KEY="0xYOUR_PRIVATE_KEY_HERE"
export AIPAYGEN_API_URL="https://api.aipaygen.com"  # optional, this is the default
```

---

## Format 1: Standalone Script

**File:** `demo_paying_agent.py`

A self-contained Python script that sets up an x402 paying session and calls multiple AiPayGen endpoints, printing costs as it goes.

```bash
python examples/demo_paying_agent.py
```

What it does:
- Creates an x402-wrapped requests session (auto-pays 402 invoices)
- Calls `/research`, `/summarize`, and `/translate` individually
- Runs a chained `/workflow/run` with 3 steps (15% discount)
- Prints per-call cost and grand total in USDC

---

## Format 2: Jupyter Notebook

**File:** `demo_notebook.ipynb` *(coming soon)*

Interactive notebook version of the demo, ideal for exploration:

```bash
jupyter notebook examples/demo_notebook.ipynb
```

Each cell calls one endpoint so you can inspect responses and costs step by step.

---

## Format 3: CLI Tool

**File:** `cli_agent.py` *(coming soon)*

Command-line tool for quick one-off calls:

```bash
# Install
pip install x402 eth-account requests click

# Usage
python examples/cli_agent.py ask "What is x402?"
python examples/cli_agent.py research "AI micropayments 2026"
python examples/cli_agent.py translate "Hello world" --target French
python examples/cli_agent.py balance
```

---

## How x402 Works

1. **Agent calls API** — sends a normal HTTP request to an AiPayGen endpoint.
2. **Server returns 402** — the response includes a payment invoice (amount, token, recipient address) in the `X-Payment` header.
3. **x402 client intercepts** — the wrapped session reads the invoice and signs a USDC transfer on Base using the agent's private key.
4. **Payment settles** — the signed transaction is submitted on-chain. Settlement is near-instant on Base L2.
5. **Server delivers result** — once payment is confirmed, the API returns the actual response. The `X-Payment-Amount` header shows what was charged.

All of this happens automatically inside `wrapRequestsWithPayment` — your code just makes normal HTTP calls.

---

## Links

- **AiPayGen Docs** — https://aipaygen.com/docs
- **x402 Protocol** — https://x402.org
- **Coinbase x402** — https://github.com/coinbase/x402
- **Base Network** — https://base.org
- **USDC on Base** — Bridge at https://bridge.base.org
