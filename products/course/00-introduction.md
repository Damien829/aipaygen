# Build an AI Agent Marketplace from Scratch

## Course Overview

This is the story of how I built AiPayGen — a live AI agent marketplace running at api.aipaygen.com — on a Raspberry Pi 5, deployed through a Cloudflare tunnel, handling real money through Stripe, and serving 65+ AI tools through a single API.

This is not a theoretical tutorial. Every code snippet in this course comes from the actual production codebase. You will see the real patterns, the real trade-offs, and the real mistakes I made along the way.

By the end of this course, you will have built:

- A Flask API backend with SQLite, Gunicorn, and CORS
- A prepaid API key system with the `apk_` prefix convention
- Stripe integration for one-time purchases and subscriptions
- A full agent marketplace with listings, search, reviews, and ratings
- An agent discovery system with OpenAPI specs and MCP compatibility
- A trading engine with strategies, backtesting, and auto-execution
- Webhook infrastructure with HMAC signing and retry logic
- A production deployment on a Raspberry Pi 5 with Cloudflare tunnels

## Who This Course Is For

You are a developer who wants to build a real product, not a demo. You know Python. You know what an API is. You want to see how a solo developer ships a monetized platform without a team, without Kubernetes, and without spending $500/month on infrastructure.

## What You Will Need

- Python 3.11+
- A Stripe account (test mode is fine to start)
- SQLite (comes with Python)
- A domain name (optional but recommended)
- A server or Raspberry Pi (Lesson 08 covers deployment)

## Course Structure

| Lesson | Topic | What You Build |
|--------|-------|----------------|
| 01 | Flask Foundation | App skeleton, health checks, Gunicorn config |
| 02 | API Keys & Auth | Key generation, validation, balance tracking |
| 03 | Stripe Billing | Checkout sessions, webhooks, credit top-ups |
| 04 | Marketplace CRUD | Listings, search, categories, reviews |
| 05 | Agent Discovery | OpenAPI spec, MCP server, SEO |
| 06 | Trading Engine | Strategies, backtesting, signals |
| 07 | Webhooks & Events | Subscriptions, HMAC signing, retries |
| 08 | Deployment | Systemd, Cloudflare tunnel, monitoring |
| 09 | What's Next | Growth strategies, monetization, scaling |

## Philosophy

Three principles guided every decision in this codebase:

**1. SQLite over Postgres.** For a solo-developer product doing <1000 concurrent users, SQLite with WAL mode is fast, reliable, and zero-maintenance. No database server to manage. No connection pools to tune. Just a file.

**2. Ship ugly, then iterate.** The first version of every feature in this codebase was rough. The marketplace started as 50 lines of code. The trading engine was paper-only for weeks. What matters is that it worked, it was live, and it was earning.

**3. Own your infrastructure.** Running on a $80 Raspberry Pi with a Cloudflare tunnel means my monthly cost is ~$0. The only variable cost is the AI model calls, and those are passed through to the customer. This changes the math on what's viable as a solo developer.

Let's build it.
