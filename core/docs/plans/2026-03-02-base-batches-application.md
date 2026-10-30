# Base Batches 003 — Startup Track Application

**Applicant:** AiPayGen
**URL:** https://api.aipaygen.com
**Deadline:** March 9, 2026
**Apply:** https://base-batches-startup-track-3.devfolio.co/

---

## One-liner

AiPayGen is pay-per-use AI infrastructure for Base — 172 Claude-powered API endpoints that any agent can access instantly via x402 micropayments in USDC.

## Problem

AI agents are increasingly autonomous but lack a frictionless way to pay for services. Traditional APIs require accounts, API keys, and billing agreements — none of which autonomous agents can set up on their own. This bottleneck prevents agents from composing services across providers, limiting what they can accomplish independently.

## Solution

AiPayGen uses the x402 payment protocol on Base to let any AI agent pay for AI services with a single HTTP request — no accounts, no API keys, no billing setup. An agent sends a request, gets a 402 payment challenge, pays in USDC on Base, and receives its result. The entire flow is one HTTP round-trip.

We offer 172 endpoints spanning AI processing (research, write, code, analyze, translate), web intelligence (scrape, search, extract), data feeds (weather, crypto, news), and agent infrastructure (messaging, memory, task brokering). Published SDKs for LangChain, LlamaIndex, and npm make integration trivial. Our MCP server (79 tools) lets any Claude-compatible agent use AiPayGen natively.

## Why Base

Base handles 86% of all x402 transactions. We chose Base for its low fees (sub-cent per transaction), fast finality, and the growing x402 ecosystem. Our pricing starts at $0.01 per call — only viable on a chain where gas doesn't eat the payment. Base is where agent-to-agent commerce will happen.

## What's Built (live on mainnet)

- **Live API:** api.aipaygen.com — 172 endpoints, real USDC payments on Base
- **MCP Server:** 79 tools, published on PyPI (aipaygen-mcp)
- **SDKs:** npm (aipaygen), PyPI (aipaygen-langchain, aipaygen-llamaindex)
- **Web Intelligence:** /scrape, /search, /extract, /research — agents can browse the web
- **Agent Infrastructure:** messaging, persistent memory, task brokering, knowledge base
- **Stripe Integration:** credit purchase for non-crypto users
- **Auto-Discovery:** .well-known/x402.json for Bazaar indexing by CDP agents

## What We'd Do With the Program

Use the 8-week program to land our first 10 paying agent integrations, ship dynamic pricing, and build volume tier discounts to drive repeat usage. The advisor network and Demo Day would help connect with agent framework teams (LangChain, CrewAI, AutoGPT) to become their default paid tool provider on Base.

## 500-Word Paper (for interview stage)

### AiPayGen: AI Infrastructure for the Agent Economy on Base

The next wave of AI isn't chatbots — it's autonomous agents that take actions, use tools, and pay for services on behalf of users. But today's agents hit a wall the moment they need to use a paid service. They can't sign up for accounts, manage API keys, or negotiate billing terms. Every integration requires a human in the loop.

AiPayGen removes that bottleneck by building AI infrastructure on the x402 payment protocol on Base. Any agent with a USDC balance can call any of our 172 endpoints with a single HTTP request. The agent sends a request, receives a 402 payment challenge specifying the price in USDC, authorizes the payment on Base, and gets its result — all in one round-trip. No accounts. No API keys. No billing setup.

Our endpoints span four categories. AI Processing includes research, writing, code generation, analysis, translation, sentiment analysis, and 25+ more Claude-powered tools. Web Intelligence gives sandboxed agents the ability to browse the internet — scrape URLs, run web searches, extract structured data from pages, and conduct multi-source research with citations. Data Feeds provide free access to weather, crypto prices, news, stocks, and other real-time information. Agent Infrastructure offers persistent memory, inter-agent messaging, a task broker, knowledge bases, and a reputation system — the building blocks of multi-agent workflows.

We chose Base because it dominates the x402 ecosystem, handling 86% of all x402 transaction volume. Base's sub-cent transaction fees are essential for our model — when an API call costs $0.01, the gas fee can't cost more than the service. Base's fast finality means agents don't wait for payment confirmation. And the CDP facilitator provides reliable, low-cost payment settlement.

Our go-to-market is SDK-driven. We've published packages for the three dominant agent frameworks: LangChain (PyPI), LlamaIndex (PyPI), and a JavaScript SDK (npm). We also ship an MCP server with 79 tools that works natively with Claude Desktop and any MCP-compatible agent. Integration is a one-liner — import the package, point it at our API, and every tool is available.

The x402 ecosystem is early but growing fast — 251+ live services, $42.96M in volume, 406,700 unique buyers. We're positioned as the largest service provider by endpoint count. Our .well-known/x402.json endpoint means every CDP-powered agent automatically discovers our services via the Bazaar protocol.

What we need from Base Batches is distribution. Our technology works — it's live on mainnet, the SDKs are published, the endpoints respond. What we need is connections to agent framework teams, wallet providers building agent-native experiences, and the broader Base ecosystem. The 8-week program would help us secure our first enterprise integrations and refine our pricing model with real usage data.

The agent economy needs infrastructure. Agents need to discover services, pay for them, and compose them into complex workflows — all without human intervention. AiPayGen is building that infrastructure layer on Base, and we believe Base Batches is the right launchpad to accelerate it.
