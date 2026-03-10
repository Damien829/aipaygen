"""Meta routes — landing page, docs, discover, health, well-known, openapi, SEO."""
import hashlib as _hashlib
import json
import os
import requests as _requests
import time as _time
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, render_template_string, make_response
from helpers import require_admin, agent_response, get_client_ip, call_llm as _call_llm, cache_get as _cache_get, cache_set as _cache_set
from model_router import call_model, list_models, get_all_perf
from discovery_engine import get_blog_post, list_blog_posts, get_health_history, get_daily_cost
from funnel_tracker import log_event as funnel_log_event

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
EVM_NETWORK = os.getenv("EVM_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")

meta_bp = Blueprint("meta", __name__)

_skills_db_path = None

def init_meta_bp(skills_db_path):
    global _skills_db_path
    _skills_db_path = skills_db_path

NAV_HTML = '''
<nav style="position:fixed;top:0;width:100%;z-index:100;background:rgba(2,4,8,0.95);backdrop-filter:blur(16px) saturate(180%);border-bottom:1px solid rgba(0,255,157,0.1);padding:14px 0">
  <div style="max-width:1200px;margin:0 auto;padding:0 24px;display:flex;align-items:center;justify-content:space-between">
    <a href="/" style="font-family:'IBM Plex Mono',monospace;font-size:1.3rem;font-weight:700;color:#fff;text-decoration:none;display:flex;align-items:center;gap:8px">
      <span style="display:inline-block;width:8px;height:8px;background:#00ff9d;border-radius:50%;box-shadow:0 0 8px #00ff9d,0 0 16px rgba(0,255,157,0.4);animation:pulse-dot 2s ease-in-out infinite"></span>
      Ai<span style="color:#00ff9d">Pay</span>Gen
    </a>
    <div style="display:flex;gap:24px;align-items:center">
      <a href="/builder" style="color:#00d4ff;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;font-weight:600;transition:color .2s">Build Agent</a>
      <a href="/discover" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">Discover</a>
      <a href="/docs" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">Docs</a>
      <a href="/sdk" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">SDK</a>
      <a href="/security" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">Security</a>
      <a href="/try" style="color:#00ff9d;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;font-weight:600">Try Free</a>
      <a href="/buy-credits" style="color:#000;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:0.82rem;font-weight:700;background:linear-gradient(135deg,#00ff9d,#00d4ff);padding:7px 16px;border-radius:4px;margin-left:8px;letter-spacing:0.03em;transition:all .2s;box-shadow:0 0 12px rgba(0,255,157,0.2)">GET API KEY</a>
    </div>
  </div>
</nav>
<style>
@keyframes pulse-dot{0%,100%{opacity:1;box-shadow:0 0 8px #00ff9d,0 0 16px rgba(0,255,157,0.4)}50%{opacity:0.6;box-shadow:0 0 4px #00ff9d,0 0 8px rgba(0,255,157,0.2)}}
</style>
'''

FOOTER_HTML = '''
<footer style="border-top:1px solid rgba(0,255,157,0.08);padding:40px 24px;text-align:center;background:#020408">
  <div style="max-width:1200px;margin:0 auto">
    <div style="margin-bottom:16px">
      <a href="/discover" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Discover</a>
      <a href="/docs" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Docs</a>
      <a href="/llms.txt" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">llms.txt</a>
      <a href="/.well-known/agent.json" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">agent.json</a>
      <a href="/health" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Health</a>
    </div>
    <div style="color:#4a5568;font-size:0.8rem;font-family:'IBM Plex Mono',monospace">
      Powered by x402 &middot; USDC on Base &middot; Built for autonomous agents
    </div>
  </div>
</footer>
'''

LANDING_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen — The Most Powerful AI Toolkit</title>
<link rel="alternate" type="text/plain" href="/llms.txt" title="LLMs.txt">
<meta name="description" content="155 AI tools in one API key. Research, write, code, translate, analyze, scrape — from $0.004/call. Install via pip or use remotely.">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:title" content="AiPayGen — The Most Powerful AI Toolkit">
<meta property="og:description" content="Research, write, code, translate, analyze, scrape — 155 AI tools from $0.004/call. MCP compatible.">
<meta property="og:url" content="https://api.aipaygen.com">
<meta property="og:image" content="https://api.aipaygen.com/og-image.png">
<meta property="og:site_name" content="AiPayGen">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="AiPayGen — The Most Powerful AI Toolkit">
<meta name="twitter:description" content="Research, write, code, translate, analyze, scrape — 155 AI tools from $0.004/call. Try free.">
<meta name="twitter:image" content="https://api.aipaygen.com/og-image.png">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebApplication","name":"AiPayGen","url":"https://api.aipaygen.com","description":"Pay-per-use AI endpoints for autonomous agents via x402 micropayments on Base.","applicationCategory":"DeveloperApplication","operatingSystem":"Any","offers":{"@type":"Offer","price":"0.01","priceCurrency":"USD","description":"Per API call, paid in USDC on Base"},"provider":{"@type":"Organization","name":"AiPayGen","url":"https://api.aipaygen.com"}}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #020408;
    --bg2: #070d14;
    --green: #00ff9d;
    --blue: #0088ff;
    --cyan: #00d4ff;
    --text: #c8d8e8;
    --muted: #4a6070;
    --border: #0d2030;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    overflow-x: hidden;
    padding-top: 70px;
  }

  /* Grid texture */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,136,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,136,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  /* Scanline effect */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 1;
  }

  .noise {
    position: fixed;
    inset: -200%;
    width: 400%;
    height: 400%;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
    opacity: 0.4;
    pointer-events: none;
    z-index: 0;
    animation: noise 0.5s steps(1) infinite;
  }
  @keyframes noise {
    0%,100% { transform: translate(0,0); }
    10% { transform: translate(-2%,-2%); }
    20% { transform: translate(2%,2%); }
    30% { transform: translate(-1%,1%); }
    40% { transform: translate(1%,-1%); }
    50% { transform: translate(-2%,1%); }
    60% { transform: translate(2%,-1%); }
    70% { transform: translate(-1%,2%); }
    80% { transform: translate(1%,1%); }
    90% { transform: translate(-1%,-2%); }
  }

  .content { position: relative; z-index: 2; }

  /* HERO */
  .hero {
    min-height: 80vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 80px 24px;
    max-width: 900px;
    margin: 0 auto;
  }
  .hero h1 {
    font-size: clamp(2.2rem, 5.5vw, 4.2rem);
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
    margin-bottom: 24px;
    color: #fff;
  }
  .hero h1 .accent { color: var(--green); }
  .hero-sub {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 1.15rem;
    color: var(--muted);
    max-width: 600px;
    line-height: 1.7;
    margin-bottom: 40px;
    font-weight: 300;
  }
  .hero-sub code {
    font-family: 'IBM Plex Mono', monospace;
    color: var(--cyan);
    font-size: 0.95rem;
  }
  .btn-cta {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 16px 36px;
    background: var(--green);
    color: #000;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.9rem;
    font-weight: 700;
    text-decoration: none;
    letter-spacing: 0.05em;
    transition: all 0.2s;
  }
  .btn-cta:hover {
    background: #fff;
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,255,157,0.3);
  }

  /* VALUE PROP CARDS */
  .value-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    max-width: 1200px;
    margin: 0 auto 80px;
  }
  .value-card {
    background: var(--bg);
    padding: 40px 32px;
    transition: all 0.25s;
    position: relative;
  }
  .value-card::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 2px;
    background: var(--green);
    transform: scaleX(0);
    transition: transform 0.3s;
  }
  .value-card:hover { background: var(--bg2); }
  .value-card:hover::after { transform: scaleX(1); }
  .value-card h3 {
    font-size: 1rem;
    font-weight: 600;
    color: #fff;
    margin-bottom: 12px;
    letter-spacing: 0.03em;
  }
  .value-card p {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.88rem;
    color: var(--muted);
    line-height: 1.7;
    font-weight: 300;
  }
  .value-icon {
    font-size: 1.6rem;
    margin-bottom: 16px;
    display: block;
    color: var(--green);
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 700;
  }

  /* HOW IT WORKS */
  .how-section {
    max-width: 1200px;
    margin: 0 auto;
    padding: 80px 24px;
  }
  .how-header {
    display: flex;
    align-items: baseline;
    gap: 20px;
    margin-bottom: 48px;
  }
  .how-header span {
    font-size: 0.7rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .how-header-line {
    flex: 1;
    height: 1px;
    background: var(--border);
  }
  .steps-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
  }
  .step-card {
    background: var(--bg);
    padding: 36px 28px;
    position: relative;
  }
  .step-card:hover { background: var(--bg2); }
  .step-num {
    font-size: 2rem;
    font-weight: 700;
    color: var(--green);
    opacity: 0.3;
    margin-bottom: 16px;
    display: block;
  }
  .step-card h3 {
    font-size: 0.95rem;
    font-weight: 600;
    color: #fff;
    margin-bottom: 8px;
    letter-spacing: 0.03em;
  }
  .step-card p {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.85rem;
    color: var(--muted);
    line-height: 1.6;
    font-weight: 300;
  }
  .step-card code {
    font-family: 'IBM Plex Mono', monospace;
    color: var(--cyan);
    font-size: 0.82rem;
  }

  /* Animations */
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .fade-up { animation: fadeUp 0.6s ease both; }
  .delay-1 { animation-delay: 0.1s; }
  .delay-2 { animation-delay: 0.2s; }
  .delay-3 { animation-delay: 0.3s; }

  @media (max-width: 768px) {
    .hero { padding: 60px 20px; min-height: 60vh; }
    .value-grid { grid-template-columns: 1fr; margin: 0 16px 60px; }
    .steps-grid { grid-template-columns: 1fr; }
    .how-section { padding: 60px 16px; }
  }
</style>
</head>
<body>
<div class="noise"></div>
{{ nav|safe }}
<div class="content">

<section class="hero">
  <h1 class="fade-up">
    The Most Powerful AI Toolkit.<br><span class="accent">155 Tools. One API.</span>
  </h1>
  <p class="hero-sub fade-up delay-1">
    Build custom AI agents in minutes. 15 frontier models, 155 tools, scheduling &amp; automation &mdash; from <code>$0.004/call</code>.
  </p>
  <div class="fade-up delay-2" style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
    <a href="/builder" class="btn-cta">Build Your Agent &rarr;</a>
    <a href="/try" class="btn-cta" style="background:transparent;border:1px solid #00ff9d">Try Free</a>
    <a href="/buy-credits" class="btn-cta" style="background:transparent;border:1px solid #4a6070">Get API Key</a>
  </div>
  <p class="fade-up delay-2" style="color:#8b949e;font-size:0.85rem;margin-top:14px;font-family:'IBM Plex Sans',sans-serif">
    <span style="color:#00ff9d;font-weight:600">10 free calls/day</span> &nbsp;&middot;&nbsp; No sign-up required &nbsp;&middot;&nbsp; <code style="color:#00d4ff">pip install aipaygen-mcp</code>
  </p>
</section>

<div class="stats-bar fade-up delay-3" style="display:flex;justify-content:center;gap:40px;flex-wrap:wrap;padding:0 24px 48px;max-width:900px;margin:0 auto">
  <div style="text-align:center">
    <div id="stat-skills" style="font-size:2rem;font-weight:700;color:#00ff9d;font-family:'IBM Plex Mono',monospace">—</div>
    <div style="font-size:0.75rem;color:#4a6070;text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">AI Skills</div>
  </div>
  <div style="text-align:center">
    <div id="stat-apis" style="font-size:2rem;font-weight:700;color:#00ff9d;font-family:'IBM Plex Mono',monospace">—</div>
    <div style="font-size:0.75rem;color:#4a6070;text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">APIs Indexed</div>
  </div>
  <div style="text-align:center">
    <div id="stat-tools" style="font-size:2rem;font-weight:700;color:#00ff9d;font-family:'IBM Plex Mono',monospace">153</div>
    <div style="font-size:0.75rem;color:#4a6070;text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">MCP Tools</div>
  </div>
  <div style="text-align:center">
    <div id="stat-agents" style="font-size:2rem;font-weight:700;color:#00ff9d;font-family:'IBM Plex Mono',monospace">—</div>
    <div style="font-size:0.75rem;color:#4a6070;text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">Agents</div>
  </div>
  <div style="text-align:center">
    <div id="stat-keys" style="font-size:2rem;font-weight:700;color:#00ff9d;font-family:'IBM Plex Mono',monospace">—</div>
    <div style="font-size:0.75rem;color:#4a6070;text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">API Keys</div>
  </div>
</div>

<div class="value-grid">
  <div class="value-card fade-up">
    <span class="value-icon">&gt;_</span>
    <h3>155 AI tools</h3>
    <p>Research, write, code, analyze, translate, scrape &mdash; powered by Claude, GPT-4o, Gemini, DeepSeek.</p>
  </div>
  <div class="value-card fade-up delay-1">
    <span class="value-icon">&#9889;</span>
    <h3>MCP Compatible</h3>
    <p>One install for Claude Code, Cursor, Windsurf. Also available as REST API and remote MCP server.</p>
  </div>
  <div class="value-card fade-up delay-2">
    <span class="value-icon">{&thinsp;}</span>
    <h3>Build Your Own Agent</h3>
    <p>Create custom AI agents with their own tools, personality, memory &amp; scheduling. Use templates or build from scratch.</p>
  </div>
</div>

<section class="how-section">
  <div class="how-header">
    <span>// How It Works</span>
    <div class="how-header-line"></div>
  </div>
  <div class="steps-grid">
    <div class="step-card fade-up">
      <span class="step-num">01</span>
      <h3>Call any endpoint</h3>
      <p><code>POST</code> your request to any AI endpoint. No authentication required.</p>
    </div>
    <div class="step-card fade-up delay-1">
      <span class="step-num">02</span>
      <h3>Receive 402 response</h3>
      <p>Get payment instructions with <code>wallet</code>, <code>amount</code>, <code>network</code>.</p>
    </div>
    <div class="step-card fade-up delay-2">
      <span class="step-num">03</span>
      <h3>Pay &amp; receive results</h3>
      <p>Attach <code>X-Payment</code> header with signed USDC tx. Get your results instantly.</p>
    </div>
  </div>
</section>

</div>
{{ footer|safe }}
<script>
fetch('/api/stats').then(r=>r.json()).then(d=>{
  if(d.skills) document.getElementById('stat-skills').textContent=d.skills.toLocaleString();
  if(d.apis) document.getElementById('stat-apis').textContent=d.apis.toLocaleString();
  if(d.mcp_tools) document.getElementById('stat-tools').textContent=d.mcp_tools.toLocaleString();
  if(d.agents) document.getElementById('stat-agents').textContent=d.agents.toLocaleString();
  if(d.api_keys) document.getElementById('stat-keys').textContent=d.api_keys.toLocaleString();
}).catch(()=>{});
</script>
</body>
</html>'''


def _build_discover_services():
    """Return services organized by category for the /discover endpoint."""
    _all_services = [
        # --- Web Intelligence ---
        {"endpoint": "/scrape", "method": "POST", "price_usd": 0.01, "input": {"url": "string"}, "output": {"url": "string", "text": "string", "word_count": "int"}, "description": "Fetch any URL, return clean markdown text"},
        {"endpoint": "/search", "method": "POST", "price_usd": 0.01, "input": {"query": "string", "n": "int (default 5, max 10)"}, "output": {"query": "string", "results": [{"title": "string", "url": "string", "snippet": "string"}]}, "description": "DuckDuckGo web search, returns top N results"},
        {"endpoint": "/extract", "method": "POST", "price_usd": 0.02, "input": {"url": "string OR text: string", "schema": {"field": "description"}, "fields": ["field1"]}, "description": "Extract structured data from URL or text using a schema"},
        {"endpoint": "/research", "method": "POST", "price_usd": 0.15, "input": {"question": "string"}, "output": {"question": "string", "answer": "string", "sources": [{"title": "string", "url": "string"}]}, "description": "Deep research: search + scrape + AI synthesis with citations"},
        {"endpoint": "/vision", "method": "POST", "price_usd": 0.05, "input": {"url": "image_url", "question": "optional"}, "description": "Analyze any image URL with Claude Vision — describe, extract text, answer questions"},
        {"endpoint": "/web/search", "method": "GET", "price_usd": 0.02, "input": {"q": "query", "n": 10}, "description": "Web search via DuckDuckGo instant answers — returns results with title, URL, snippet."},
        {"endpoint": "/enrich", "method": "POST", "price_usd": 0.05, "input": {"entity": "string", "type": "ip|crypto|country|url|company"}, "description": "Aggregate multiple data sources into a unified enrichment profile for any entity."},
        # --- AI Processing ---
        {"endpoint": "/summarize", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "length": "short|medium|detailed"}, "description": "Summarize long text into key points"},
        {"endpoint": "/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "string"}, "description": "Analyze data or text, returns structured insights"},
        {"endpoint": "/translate", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "language": "string"}, "description": "Translate text to any language"},
        {"endpoint": "/social", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "platforms": ["twitter", "linkedin", "instagram"], "tone": "string"}, "description": "Generate platform-optimized social media posts"},
        {"endpoint": "/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article|post|copy"}, "description": "Write articles, copy, or content to spec"},
        {"endpoint": "/code", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "language": "string"}, "description": "Generate code in any language"},
        {"endpoint": "/qa", "method": "POST", "price_usd": 0.02, "input": {"context": "string", "question": "string"}, "description": "Q&A over a document — answer + confidence + source quote. Core RAG building block."},
        {"endpoint": "/classify", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "categories": ["cat1", "cat2"]}, "description": "Classify text into your defined categories with per-category confidence scores"},
        {"endpoint": "/sentiment", "method": "POST", "price_usd": 0.01, "input": {"text": "string"}, "description": "Deep sentiment — polarity, score, emotions, confidence, key phrases"},
        {"endpoint": "/keywords", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "max_keywords": 10}, "description": "Extract keywords, topics, tags from any text"},
        {"endpoint": "/compare", "method": "POST", "price_usd": 0.02, "input": {"text_a": "string", "text_b": "string", "focus": "optional"}, "description": "Compare two texts — similarities, differences, similarity score, recommendation"},
        {"endpoint": "/transform", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "instruction": "string"}, "description": "Transform text with any instruction — rewrite, reformat, expand, condense, translate style"},
        {"endpoint": "/chat", "method": "POST", "price_usd": 0.03, "input": {"messages": [{"role": "user", "content": "string"}], "system": "optional"}, "description": "Stateless multi-turn chat — send full message history, get Claude reply"},
        {"endpoint": "/plan", "method": "POST", "price_usd": 0.03, "input": {"goal": "string", "context": "optional", "steps": 7}, "description": "Step-by-step action plan with effort estimate and first action"},
        {"endpoint": "/decide", "method": "POST", "price_usd": 0.03, "input": {"decision": "string", "options": ["A", "B"], "criteria": "optional"}, "description": "Decision framework — pros, cons, risks, recommendation, confidence"},
        {"endpoint": "/proofread", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "style": "professional"}, "description": "Grammar/spelling/clarity corrections with tracked issues and writing score"},
        {"endpoint": "/explain", "method": "POST", "price_usd": 0.02, "input": {"concept": "string", "level": "beginner|intermediate|expert", "analogy": True}, "description": "Explain any concept with analogy, key points, common misconceptions"},
        {"endpoint": "/questions", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "type": "faq|interview|quiz|comprehension", "count": 5}, "description": "Generate questions + answers from any content"},
        {"endpoint": "/outline", "method": "POST", "price_usd": 0.02, "input": {"topic": "string", "depth": 2, "sections": 6}, "description": "Hierarchical outline with headings, summaries, and subsections"},
        {"endpoint": "/email", "method": "POST", "price_usd": 0.03, "input": {"purpose": "string", "tone": "professional", "recipient": "optional", "length": "short|medium|long"}, "description": "Compose professional emails with subject and body"},
        {"endpoint": "/sql", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "dialect": "postgresql", "schema": "optional"}, "description": "Natural language to SQL — query + explanation + notes"},
        {"endpoint": "/regex", "method": "POST", "price_usd": 0.02, "input": {"description": "string", "language": "python", "flags": "optional"}, "description": "Regex pattern from description with examples and non-examples"},
        {"endpoint": "/mock", "method": "POST", "price_usd": 0.03, "input": {"description": "string", "count": 5, "format": "json|csv|list"}, "description": "Generate realistic mock data records with schema"},
        {"endpoint": "/preview", "method": "POST", "price_usd": 0.00, "input": {"topic": "string"}, "description": "Free 120-token Claude preview — no payment required"},
        {"endpoint": "/score", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "criteria": ["clarity", "accuracy"], "scale": 10}, "description": "Score content quality on any custom rubric — per-criterion scores + strengths/weaknesses"},
        {"endpoint": "/timeline", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "direction": "chronological"}, "description": "Extract or reconstruct a chronological timeline of events from any text"},
        {"endpoint": "/action", "method": "POST", "price_usd": 0.01, "input": {"text": "string"}, "description": "Extract action items, tasks, owners, and due dates from meeting notes or any text"},
        {"endpoint": "/pitch", "method": "POST", "price_usd": 0.03, "input": {"product": "string", "audience": "string", "length": "15s|30s|60s"}, "description": "Generate elevator pitch — hook, value prop, call to action, full script"},
        {"endpoint": "/debate", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "perspective": "balanced|for|against"}, "description": "Arguments for and against any position with strength ratings and verdict"},
        {"endpoint": "/headline", "method": "POST", "price_usd": 0.01, "input": {"content": "string", "count": 5, "style": "engaging|clickbait|informative"}, "description": "Generate compelling headlines and titles for any content"},
        {"endpoint": "/fact", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "count": 10}, "description": "Extract factual claims from text with verifiability scores and source hints"},
        {"endpoint": "/rewrite", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "audience": "string", "tone": "string"}, "description": "Rewrite text for a specific audience, reading level, or brand voice"},
        {"endpoint": "/tag", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "taxonomy": ["optional", "tags"], "max_tags": 10}, "description": "Auto-tag content using a provided taxonomy or free-form tagging"},
        {"endpoint": "/rag", "method": "POST", "price_usd": 0.05, "input": {"documents": "text (use --- to separate docs)", "query": "string"}, "description": "Grounded Q&A — answer questions using only your provided documents, with citations"},
        {"endpoint": "/diagram", "method": "POST", "price_usd": 0.03, "input": {"description": "string", "type": "flowchart|sequence|erd|gantt|mindmap"}, "description": "Generate Mermaid diagrams from a plain English description"},
        {"endpoint": "/json-schema", "method": "POST", "price_usd": 0.02, "input": {"description": "string", "example": "optional JSON example"}, "description": "Generate JSON Schema (draft-07) from a plain English description of your data"},
        {"endpoint": "/test-cases", "method": "POST", "price_usd": 0.03, "input": {"code": "code or description", "language": "python"}, "description": "Generate comprehensive unit test cases with edge cases for any code or feature"},
        {"endpoint": "/code/run", "method": "POST", "price_usd": 0.05, "input": {"code": "python code string", "timeout": 10}, "description": "Execute Python code in a sandboxed subprocess. Returns stdout, stderr, exit code."},
        # --- Scraping ---
        {"endpoint": "/scrape/google-maps", "method": "POST", "price_usd": 0.10, "input": {"query": "string (e.g. restaurants in NYC)", "max_items": 5}, "description": "Scrape Google Maps — business names, addresses, ratings, reviews, phone numbers"},
        {"endpoint": "/scrape/tweets", "method": "POST", "price_usd": 0.05, "input": {"query": "string or #hashtag", "max_items": 25}, "description": "Scrape Twitter/X — tweet text, author, engagement metrics"},
        {"endpoint": "/scrape/instagram", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape Instagram profile posts and metadata"},
        {"endpoint": "/scrape/linkedin", "method": "POST", "price_usd": 0.15, "input": {"url": "LinkedIn profile URL"}, "description": "Scrape LinkedIn profile — experience, skills, education"},
        {"endpoint": "/scrape/youtube", "method": "POST", "price_usd": 0.05, "input": {"query": "string", "max_items": 5}, "description": "Search YouTube and return video metadata — title, channel, views, URL"},
        {"endpoint": "/scrape/web", "method": "POST", "price_usd": 0.05, "input": {"url": "string", "max_pages": 5}, "description": "Crawl any website and extract structured text content"},
        {"endpoint": "/scrape/tiktok", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape TikTok profile videos and metadata"},
        {"endpoint": "/scrape/facebook-ads", "method": "POST", "price_usd": 0.10, "input": {"url": "Facebook Ad Library URL", "max_items": 10}, "description": "Scrape Facebook Ad Library for competitor ad research"},
        {"endpoint": "/scrape/actor", "method": "POST", "price_usd": 0.10, "input": {"actor_id": "Apify actor ID", "run_input": {}, "max_items": 10}, "description": "Run any Apify actor with custom input — access the full Apify ecosystem"},
        # --- Data & Utilities ---
        {"endpoint": "/data/weather", "method": "GET", "price_usd": 0.01, "input": {"city": "string"}, "description": "Real-time weather — temperature, wind speed, weather code."},
        {"endpoint": "/data/crypto", "method": "GET", "price_usd": 0.01, "input": {"symbol": "bitcoin,ethereum"}, "description": "Live crypto prices in USD/EUR/GBP with 24hr change."},
        {"endpoint": "/data/exchange-rates", "method": "GET", "price_usd": 0.01, "input": {"base": "USD"}, "description": "Exchange rates for any base currency vs 160+ currencies."},
        {"endpoint": "/data/country", "method": "GET", "price_usd": 0.01, "input": {"name": "France"}, "description": "Country info — capital, population, currencies, languages, flag."},
        {"endpoint": "/data/ip", "method": "GET", "price_usd": 0.01, "input": {"ip": "optional"}, "description": "IP geolocation — country, city, ISP, timezone."},
        {"endpoint": "/data/news", "method": "GET", "price_usd": 0.01, "description": "Top 10 Hacker News stories — title, URL, score, comments."},
        {"endpoint": "/data/stocks", "method": "GET", "price_usd": 0.01, "input": {"symbol": "AAPL"}, "description": "Stock price, previous close, market state via Yahoo Finance."},
        {"endpoint": "/data/joke", "method": "GET", "price_usd": 0.01, "description": "Random joke — setup + punchline."},
        {"endpoint": "/data/quote", "method": "GET", "price_usd": 0.01, "input": {"category": "optional"}, "description": "Random inspirational quote with author."},
        {"endpoint": "/data/timezone", "method": "GET", "price_usd": 0.01, "input": {"tz": "America/New_York"}, "description": "Current datetime, UTC offset, week number for any timezone."},
        {"endpoint": "/data/holidays", "method": "GET", "price_usd": 0.01, "input": {"country": "US", "year": "2026"}, "description": "Public holidays for any country and year."},
        {"endpoint": "/data/wikipedia", "method": "GET", "price_usd": 0.01, "input": {"q": "quantum computing"}, "description": "Wikipedia article summary — title, extract, URL, description."},
        {"endpoint": "/data/arxiv", "method": "GET", "price_usd": 0.01, "input": {"q": "LLM agents", "limit": 5}, "description": "Search arXiv academic papers — title, authors, summary, URL."},
        {"endpoint": "/data/github/trending", "method": "GET", "price_usd": 0.01, "input": {"lang": "python", "since": "daily"}, "description": "GitHub trending repositories — repo, stars, description, language."},
        {"endpoint": "/data/reddit", "method": "GET", "price_usd": 0.01, "input": {"q": "AI agents", "sub": "MachineLearning"}, "description": "Reddit search — posts with score, comments, URL."},
        {"endpoint": "/data/youtube/transcript", "method": "GET", "price_usd": 0.01, "input": {"video_id": "dQw4w9WgXcQ"}, "description": "YouTube video transcript/captions — full text and segments."},
        {"endpoint": "/data/qr", "method": "GET", "price_usd": 0.01, "input": {"text": "https://api.aipaygen.com"}, "description": "Generate QR code — returns PNG as base64 and data URL."},
        {"endpoint": "/data/dns", "method": "GET", "price_usd": 0.01, "input": {"domain": "api.aipaygen.com"}, "description": "DNS lookup — A, AAAA records and reverse hostname."},
        {"endpoint": "/data/validate/email", "method": "GET", "price_usd": 0.01, "input": {"email": "test@example.com"}, "description": "Email validation — format check, domain reachability, disposable detection."},
        {"endpoint": "/data/validate/url", "method": "GET", "price_usd": 0.01, "input": {"url": "https://example.com"}, "description": "URL reachability check — status code, final URL, content type."},
        {"endpoint": "/data/random/name", "method": "GET", "price_usd": 0.01, "input": {"count": 5}, "description": "Random person names, emails, phone, location."},
        {"endpoint": "/data/color", "method": "GET", "price_usd": 0.01, "input": {"hex": "ff5733"}, "description": "Color info — RGB, HSL, complementary color, brightness, CSS."},
        {"endpoint": "/data/screenshot", "method": "GET", "price_usd": 0.01, "input": {"url": "https://example.com"}, "description": "Website screenshot URL (1280px wide)."},
        {"endpoint": "/free/time", "method": "GET", "price_usd": 0.00, "description": "Current UTC time, Unix timestamp, date, day of week — completely free"},
        {"endpoint": "/free/uuid", "method": "GET", "price_usd": 0.00, "description": "Generate UUID4 values — completely free"},
        {"endpoint": "/free/ip", "method": "GET", "price_usd": 0.00, "description": "Caller's IP address and user agent info — completely free"},
        {"endpoint": "/free/hash", "method": "GET", "price_usd": 0.00, "input": {"text": "string"}, "description": "Hash text with MD5, SHA1, SHA256, SHA512 — completely free"},
        {"endpoint": "/free/base64", "method": "GET", "price_usd": 0.00, "input": {"text": "string to encode", "decode": "string to decode"}, "description": "Encode/decode base64 — completely free"},
        {"endpoint": "/free/random", "method": "GET", "price_usd": 0.00, "input": {"n": 5, "min": 1, "max": 100}, "description": "Random integers, floats, booleans, and strings — completely free"},
        {"endpoint": "/free-tier/status", "method": "GET", "price_usd": 0.01, "description": "Check how many free AI calls remain today for your IP. 10 free calls/day, resets midnight UTC."},
        {"endpoint": "/sdk/code", "method": "GET", "price_usd": 0.01, "input": {"lang": "python|javascript|curl", "endpoint": "optional"}, "description": "Get copy-paste SDK code in Python, JavaScript, or cURL"},
        {"endpoint": "/sitemap.xml", "method": "GET", "price_usd": 0.01, "description": "XML sitemap of all public endpoints for crawlers and agents"},
        {"endpoint": "/catalog", "method": "GET", "price_usd": 0.01, "input": {"category": "optional", "min_score": 0, "free_only": False, "page": 1}, "description": "Browse 4100+ discovered APIs — the largest autonomous API catalog. Filter by category, quality score, auth requirement"},
        {"endpoint": "/models", "method": "GET", "price_usd": 0.01, "description": "List all supported LLM models (15 models, 7 providers) with pricing and capabilities."},
        {"endpoint": "/api-call", "method": "POST", "price_usd": 0.05, "input": {"api_id": "int from /catalog", "endpoint": "/path", "params": {}, "api_key": "optional", "enrich": False}, "description": "Proxy-call any API in the catalog — optionally enrich results with Claude analysis"},
        # --- Agent Platform ---
        {"endpoint": "/agents/register", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "name": "string", "description": "string", "capabilities": [], "endpoint": "optional URL"}, "description": "Register your agent in the AiPayGen agent registry"},
        {"endpoint": "/agents", "method": "GET", "price_usd": 0.01, "description": "Browse all registered agents in the registry"},
        {"endpoint": "/agents/leaderboard", "method": "GET", "price_usd": 0.01, "description": "Top agents by reputation score. Score = task_completions*3 + knowledge*1.5 + upvotes*0.5"},
        {"endpoint": "/agent/reputation/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "Get reputation score and stats for any agent."},
        {"endpoint": "/agents/challenge", "method": "POST", "price_usd": 0.01, "input": {"wallet_address": "0x...", "chain": "evm|solana"}, "description": "Request a wallet-verification challenge string."},
        {"endpoint": "/agents/verify", "method": "POST", "price_usd": 0.01, "input": {"wallet_address": "0x...", "signature": "0x...", "chain": "evm|solana"}, "description": "Submit signed challenge to verify wallet, get JWT session token."},
        {"endpoint": "/agents/me", "method": "GET", "price_usd": 0.01, "description": "View your verified agent profile (requires JWT)."},
        {"endpoint": "/agents/search", "method": "GET", "price_usd": 0.01, "input": {"q": "query", "capability": "optional"}, "description": "Search wallet-verified agents by name, capability, or address."},
        {"endpoint": "/agents/<agent_id>/portfolio", "method": "GET", "price_usd": 0.01, "description": "View a verified agent's public portfolio and reputation."},
        {"endpoint": "/marketplace", "method": "GET", "price_usd": 0.01, "input": {"category": "optional", "max_price": "optional"}, "description": "Browse the agent marketplace — services listed by other AI agents"},
        {"endpoint": "/marketplace/list", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "name": "string", "endpoint": "URL", "price_usd": 0.05, "description": "string", "category": "string"}, "description": "List your service in the agent marketplace, earn x402 payments"},
        {"endpoint": "/marketplace/call", "method": "POST", "price_usd": 0.05, "input": {"listing_id": "string", "payload": {}}, "description": "Proxy-call any agent marketplace listing — we handle routing and payment"},
        {"endpoint": "/memory/set", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string", "value": "any", "tags": ["optional"]}, "description": "Store persistent memory for any agent — survives across sessions and requests"},
        {"endpoint": "/memory/get", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string"}, "description": "Retrieve a stored memory by agent_id and key"},
        {"endpoint": "/memory/search", "method": "POST", "price_usd": 0.02, "input": {"agent_id": "string", "query": "string"}, "description": "Search all memories for an agent by keyword"},
        {"endpoint": "/memory/clear", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string"}, "description": "Delete all memories for an agent — use before context reset"},
        {"endpoint": "/message/send", "method": "POST", "price_usd": 0.01, "input": {"from_agent": "string", "to_agent": "string", "subject": "string", "body": "string"}, "description": "Send a message from one agent to another. Persistent inbox."},
        {"endpoint": "/message/inbox/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "Read an agent's inbox."},
        {"endpoint": "/message/reply", "method": "POST", "price_usd": 0.01, "input": {"msg_id": "string", "from_agent": "string", "body": "string"}, "description": "Reply to a message in a thread."},
        {"endpoint": "/message/broadcast", "method": "POST", "price_usd": 0.02, "input": {"from_agent": "string", "subject": "string", "body": "string"}, "description": "Broadcast a message to all registered agents."},
        {"endpoint": "/knowledge/add", "method": "POST", "price_usd": 0.01, "input": {"topic": "string", "content": "string", "author_agent": "string", "tags": []}, "description": "Add an entry to the shared knowledge base."},
        {"endpoint": "/knowledge/search", "method": "GET", "price_usd": 0.01, "input": {"q": "query"}, "description": "Search the shared knowledge base."},
        {"endpoint": "/knowledge/trending", "method": "GET", "price_usd": 0.01, "description": "Get trending topics in the knowledge base."},
        {"endpoint": "/knowledge/vote", "method": "POST", "price_usd": 0.01, "input": {"entry_id": "string", "up": True}, "description": "Upvote or downvote a knowledge entry."},
        {"endpoint": "/task/submit", "method": "POST", "price_usd": 0.01, "input": {"posted_by": "string", "title": "string", "description": "string", "skills_needed": [], "reward_usd": 0.10}, "description": "Post a task to the agent task board."},
        {"endpoint": "/task/browse", "method": "GET", "price_usd": 0.01, "input": {"skill": "optional", "status": "open"}, "description": "Browse open tasks."},
        {"endpoint": "/task/claim", "method": "POST", "price_usd": 0.01, "input": {"task_id": "string", "agent_id": "string"}, "description": "Claim a task from the board."},
        {"endpoint": "/task/complete", "method": "POST", "price_usd": 0.01, "input": {"task_id": "string", "agent_id": "string", "result": "string"}, "description": "Mark a task complete with result."},
        {"endpoint": "/task/subscribe", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "callback_url": "https://your-agent/webhook", "skills": ["python", "nlp"]}, "description": "Subscribe to task board notifications. We POST to your callback_url when matching tasks appear."},
        {"endpoint": "/files/upload", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "file": "multipart OR base64_data+filename+content_type"}, "description": "Upload a file (max 10MB). Returns file_id and URL."},
        {"endpoint": "/files/<file_id>", "method": "GET", "price_usd": 0.01, "description": "Download a file by ID. Returns raw file bytes."},
        {"endpoint": "/files/list/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "List all files uploaded by an agent."},
        {"endpoint": "/webhooks/create", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "label": "optional"}, "description": "Get a unique URL to receive webhooks from any external service. Events stored 7 days."},
        {"endpoint": "/webhooks/<id>/receive", "method": "POST", "price_usd": 0.01, "description": "The URL external services POST to. Stores the incoming event for your agent to retrieve."},
        {"endpoint": "/webhooks/<id>/events", "method": "GET", "price_usd": 0.01, "description": "Retrieve stored webhook events. Poll this or set up a task subscription callback."},
        {"endpoint": "/credits/buy", "method": "POST", "price_usd": 5.00, "input": {"amount_usd": 5.0, "label": "optional"}, "description": "Buy a USDC credit pack — returns prepaid API key for metered token-based billing."},
        {"endpoint": "/auth/generate-key", "method": "POST", "price_usd": 0.01, "input": {"label": "optional"}, "description": "Generate a prepaid API key (apk_xxx). Use as Bearer token to bypass x402 per-call."},
        {"endpoint": "/auth/topup", "method": "POST", "price_usd": 0.01, "input": {"key": "apk_xxx", "amount": 1.00}, "description": "Top up balance on a prepaid API key."},
        {"endpoint": "/auth/status", "method": "GET", "price_usd": 0.01, "input": {"key": "apk_xxx"}, "description": "Check balance, usage stats, and last used time for an API key."},
        {"endpoint": "/run-discovery", "method": "POST", "price_usd": 0.01, "description": "Trigger API discovery agents to scan the web for new APIs"},
        {"endpoint": "/async/submit", "method": "POST", "price_usd": 0.01, "input": {"endpoint": "research", "payload": {"topic": "..."}, "callback_url": "optional"}, "description": "Submit an async job. Runs in background, POSTs result to callback_url when done."},
        {"endpoint": "/async/status/<job_id>", "method": "GET", "price_usd": 0.01, "description": "Check status of an async job — pending, running, completed, or failed."},
        # --- Advanced ---
        {"endpoint": "/batch", "method": "POST", "price_usd": 0.10, "input": {"operations": [{"endpoint": "string", "input": {}}]}, "description": "Run up to 5 operations in one payment — best value for multi-step pipelines"},
        {"endpoint": "/pipeline", "method": "POST", "price_usd": 0.15, "input": {"steps": [{"endpoint": "string", "input": {}}]}, "description": "Chain up to 5 operations where each step can use {{prev}} to reference previous output"},
        {"endpoint": "/chain", "method": "POST", "price_usd": 0.25, "input": {"steps": [{"action": "research", "params": {"query": "string"}}, {"action": "summarize", "params": {"text": "{{prev_result}}"}}]}, "description": "Chain up to 5 AI operations in sequence — each step references previous output via {{prev_result}}"},
        {"endpoint": "/workflow", "method": "POST", "price_usd": 0.20, "input": {"goal": "string", "data": "optional context"}, "description": "Multi-step agentic reasoning with Claude Sonnet — breaks down and executes complex goals"},
        {"endpoint": "/stream/research", "method": "POST", "price_usd": 0.01, "input": {"topic": "string"}, "description": "Streaming research — same as /research but tokens stream as text/event-stream SSE"},
        {"endpoint": "/stream/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article"}, "description": "Streaming write — same as /write but content streams as SSE"},
        {"endpoint": "/stream/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "optional"}, "description": "Streaming analysis — same as /analyze but streams as SSE"},
    ]

    # Categorize services by endpoint prefix / type
    categories = {
        "Web Intelligence": [],
        "AI Processing": [],
        "Scraping": [],
        "Data & Utilities": [],
        "Agent Platform": [],
        "Advanced": [],
    }

    _web_intel = {"/scrape", "/search", "/extract", "/research", "/vision", "/web/search", "/enrich"}
    _scraping_prefix = "/scrape/"
    _data_prefixes = ("/data/", "/free/", "/free-tier/", "/sdk/", "/sitemap", "/catalog", "/models", "/api-call")
    _agent_prefixes = ("/agents", "/agent/", "/marketplace", "/memory/", "/message/", "/knowledge/", "/task/",
                       "/files/", "/webhooks/", "/credits/", "/auth/", "/run-discovery", "/async/")
    _advanced = {"/batch", "/pipeline", "/chain", "/workflow", "/stream/research", "/stream/write", "/stream/analyze"}

    for svc in _all_services:
        ep = svc["endpoint"]
        if ep in _advanced:
            categories["Advanced"].append(svc)
        elif ep.startswith(_scraping_prefix):
            categories["Scraping"].append(svc)
        elif ep in _web_intel:
            categories["Web Intelligence"].append(svc)
        elif ep.startswith(_data_prefixes):
            categories["Data & Utilities"].append(svc)
        elif ep.startswith(_agent_prefixes):
            categories["Agent Platform"].append(svc)
        else:
            categories["AI Processing"].append(svc)

    return categories


@meta_bp.route("/")
def landing():
    from flask import make_response, render_template
    try:
        resp = make_response(render_template("index.html"))
    except Exception:
        # Fallback to legacy inline HTML if template fails
        resp = make_response(render_template_string(LANDING_HTML, nav=NAV_HTML, footer=FOOTER_HTML))
    resp.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    return resp


DISCOVER_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Service Catalog — AiPayGen</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#020408;--green:#00ff9d;--card-bg:#0a0e14;--card-border:#111820;--card-hover:#00ff9d22;--text:#e1e4e8;--muted:#6b7280;--blue:#3b82f6;--orange:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'IBM Plex Sans',sans-serif;line-height:1.6;padding-top:70px}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}
.container{max-width:1200px;margin:0 auto;padding:0 24px}
.page-header{text-align:center;padding:48px 24px 32px}
.page-header h1{font-family:'IBM Plex Mono',monospace;font-size:2.2rem;font-weight:700;color:#fff}
.page-header h1 span{color:var(--green)}
.page-header .tagline{font-size:1rem;color:var(--muted);margin-top:8px;max-width:520px;margin-left:auto;margin-right:auto}
.search-wrap{max-width:560px;margin:0 auto 28px;position:relative}
.search-wrap input{width:100%;padding:12px 16px 12px 44px;background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;color:var(--text);font-family:'IBM Plex Sans',sans-serif;font-size:0.95rem;outline:none;transition:border-color .2s}
.search-wrap input:focus{border-color:var(--green)}
.search-wrap input::placeholder{color:var(--muted)}
.search-wrap svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:36px;padding:0 24px}
.tab{padding:6px 18px;border-radius:20px;border:1px solid var(--card-border);background:transparent;color:var(--muted);font-family:'IBM Plex Sans',sans-serif;font-size:0.85rem;font-weight:500;cursor:pointer;transition:all .2s;white-space:nowrap}
.tab:hover{border-color:var(--green);color:var(--text)}
.tab.active{background:var(--green);color:var(--bg);border-color:var(--green);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;margin-bottom:48px}
@media(max-width:420px){.grid{grid-template-columns:1fr}}
.card{background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:18px 20px;transition:border-color .2s,box-shadow .2s}
.card:hover{border-color:rgba(0,255,157,0.35);box-shadow:0 0 20px rgba(0,255,157,0.05)}
.card-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.endpoint{font-family:'IBM Plex Mono',monospace;font-size:0.9rem;color:#fff;font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.5px}
.badge-post{background:var(--blue);color:#fff}
.badge-get{background:#22c55e;color:#fff}
.desc{font-size:0.88rem;color:var(--muted);margin-bottom:10px;line-height:1.5}
.pricing-label{font-size:0.8rem;font-weight:600}
.label-free{color:var(--green)}
.label-x402{color:var(--orange)}
.empty{text-align:center;padding:48px 24px;color:var(--muted);font-size:0.95rem}
.bottom-cta{text-align:center;padding:48px 24px 64px}
.bottom-cta a{display:inline-block;padding:12px 32px;border:1px solid var(--green);color:var(--green);border-radius:8px;font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:0.95rem;transition:all .2s}
.bottom-cta a:hover{background:var(--green);color:var(--bg);text-decoration:none}
</style>
</head>
<body>
{{ nav|safe }}
<div class="page-header">
  <h1>Service <span>Catalog</span></h1>
  <p class="tagline">Browse every endpoint. Pay per call with USDC on Base via the x402 protocol — no accounts, no API keys.</p>
</div>
<div class="container">
  <div class="search-wrap">
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input type="text" id="searchInput" placeholder="Search endpoints..." autocomplete="off">
  </div>
  <div class="tabs" id="categoryTabs">
    <button class="tab active" data-cat="all">All</button>
    {% for cat_name in categories %}
    <button class="tab" data-cat="{{ cat_name }}">{{ cat_name }}</button>
    {% endfor %}
  </div>
  <div class="grid" id="serviceGrid">
    {% for cat_name, services in categories.items() %}
    {% for svc in services %}
    <div class="card" data-category="{{ cat_name }}" data-endpoint="{{ svc.endpoint|lower }}" data-desc="{{ svc.description|lower }}">
      <div class="card-head">
        <span class="badge {{ 'badge-post' if svc.method == 'POST' else 'badge-get' }}">{{ svc.method }}</span>
        <span class="endpoint">{{ svc.endpoint }}</span>
      </div>
      <div class="desc">{{ svc.description }}</div>
      <div class="pricing-label {{ 'label-free' if svc.free else 'label-x402' }}">
        {{ 'FREE' if svc.free else 'x402' }}
      </div>
    </div>
    {% endfor %}
    {% endfor %}
  </div>
  <div class="empty" id="emptyState" style="display:none">No services match your search.</div>
</div>
<div class="bottom-cta">
  <a href="/docs">Read the Docs &rarr;</a>
</div>
{{ footer|safe }}
<script>
(function(){
  var search = document.getElementById('searchInput');
  var tabs = document.querySelectorAll('.tab');
  var cards = document.querySelectorAll('.card');
  var empty = document.getElementById('emptyState');
  var grid = document.getElementById('serviceGrid');
  var activeCat = 'all';
  function filterCards(){
    var q = search.value.toLowerCase().trim();
    var visible = 0;
    cards.forEach(function(c){
      var catMatch = activeCat === 'all' || c.getAttribute('data-category') === activeCat;
      var searchMatch = !q || c.getAttribute('data-endpoint').indexOf(q) !== -1 || c.getAttribute('data-desc').indexOf(q) !== -1;
      if(catMatch && searchMatch){ c.style.display = ''; visible++; } else { c.style.display = 'none'; }
    });
    empty.style.display = visible === 0 ? '' : 'none';
    grid.style.display = visible === 0 ? 'none' : '';
  }
  search.addEventListener('input', filterCards);
  tabs.forEach(function(tab){
    tab.addEventListener('click', function(){
      tabs.forEach(function(t){ t.classList.remove('active'); });
      tab.classList.add('active');
      activeCat = tab.getAttribute('data-cat');
      filterCards();
    });
  });
})();
</script>
</body>
</html>'''


@meta_bp.route("/discover")
def discover():
    try:
        funnel_log_event("discover_hit", endpoint="/discover", ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""))
    except Exception:
        pass
    categories = _build_discover_services()
    base_url = "https://api.aipaygen.com"

    all_services = [s for cat_services in categories.values() for s in cat_services]
    free_count = sum(1 for s in all_services if s.get("price_usd", 0) == 0)

    # Content negotiation: HTML for browsers, JSON for agents
    best = request.accept_mimetypes.best_match(
        ["text/html", "application/json"], default="application/json"
    )

    if best == "text/html":
        display_categories = {}
        for cat_name, services in categories.items():
            display_categories[cat_name] = [
                {
                    "endpoint": s["endpoint"],
                    "method": s["method"],
                    "description": s["description"],
                    "free": s.get("price_usd", 0) == 0,
                }
                for s in services
            ]
        return render_template_string(
            DISCOVER_HTML,
            categories=display_categories,
            nav=NAV_HTML,
            footer=FOOTER_HTML,
        )

    # Strip schemas and exact prices for competitive protection
    stripped_categories = {}
    for cat_name, services in categories.items():
        stripped_categories[cat_name] = [
            {
                "endpoint": s["endpoint"],
                "method": s["method"],
                "description": s["description"],
                "pricing": "free" if s.get("price_usd", 0) == 0 else "x402",
            }
            for s in services
        ]

    return jsonify({
        "meta": {
            "name": "AiPayGen",
            "description": "AI agent API marketplace with 155 tools and 1500+ skills. Three payment paths: API key (recommended), x402 USDC, or MCP (10 free/day).",
            "categories": list(categories.keys()),
        },
        "payment": {
            "recommended": {
                "method": "api_key",
                "description": "Buy a prepaid API key — fastest path to access.",
                "endpoint": f"{base_url}/credits/buy",
                "example": {"amount_usd": 5.0},
                "usage": "Authorization: Bearer apk_xxx",
                "bulk_discount": "20% off when balance >= $2.00",
            },
            "x402": {
                "wallet": WALLET_ADDRESS,
                "network": EVM_NETWORK,
                "payment_scheme": "x402/exact",
                "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            },
            "mcp": {
                "description": "10 free calls/day via MCP, unlimited with API key.",
                "install": "pip install aipaygen-mcp",
                "sse": f"https://mcp.aipaygen.com/mcp",
            },
        },
        "categories": stripped_categories,
        "links": {
            "openapi": f"{base_url}/openapi.json",
            "llms_txt": f"{base_url}/llms.txt",
            "docs": f"{base_url}/docs",
            "buy_credits": f"{base_url}/credits/buy",
        },
    })


_app_start_time = _time.time()
_health_cache = {"data": None, "ts": 0}

@meta_bp.route("/health")
def health():
    now = _time.time()
    # Cache health for 60s to avoid hammering checks on every call
    if _health_cache["data"] and (now - _health_cache["ts"]) < 60:
        cached = _health_cache["data"]
        code = 200 if cached.get("status") == "healthy" else 503
        return jsonify(cached), code

    checks = {}
    degraded = False

    # 1. SQLite DBs writable
    _project_root = os.path.dirname(os.path.dirname(__file__))
    for db_name, db_path in [("skills", _skills_db_path), ("agent_network", os.path.join(_project_root, "agent_network.db"))]:
        try:
            import sqlite3 as _sq
            c = _sq.connect(db_path, timeout=2)
            c.execute("SELECT 1")
            c.close()
            checks[db_name] = "ok"
        except Exception as exc:
            checks[db_name] = f"error: {exc}"
            degraded = True

    # 2. Facilitator reachable (cached via _health_cache TTL)
    try:
        r = _requests.get(FACILITATOR_URL, timeout=5)
        checks["facilitator"] = "ok" if r.status_code < 500 else f"http {r.status_code}"
        if r.status_code >= 500:
            degraded = True
    except Exception as exc:
        checks["facilitator"] = f"unreachable: {exc}"
        degraded = True

    # 3. Disk space
    try:
        st = os.statvfs(os.path.dirname(__file__))
        free_mb = (st.f_bavail * st.f_frsize) / (1024 * 1024)
        checks["disk_free_mb"] = round(free_mb, 1)
        if free_mb < 100:
            degraded = True
    except Exception:
        checks["disk_free_mb"] = "unknown"

    # 4. Daily cost
    try:
        checks["daily_cost_usd"] = round(get_daily_cost(), 4)
    except Exception:
        checks["daily_cost_usd"] = "unknown"

    # 5. Uptime
    checks["uptime_seconds"] = round(now - _app_start_time, 1)

    # 6. Circuit breaker status
    from model_router import _circuit_state, get_all_perf
    if _circuit_state:
        checks["circuit_breakers"] = {k: {"failures": v["failures"], "open": v.get("opened_at") is not None} for k, v in _circuit_state.items() if v["failures"] > 0}

    # 7. Model performance stats
    perf = get_all_perf()
    if perf:
        checks["model_performance"] = perf

    result = {
        "status": "degraded" if degraded else "healthy",
        "wallet": WALLET_ADDRESS,
        "network": EVM_NETWORK,
        "checks": checks,
    }
    _health_cache["data"] = result
    _health_cache["ts"] = now
    code = 200 if not degraded else 503
    return jsonify(result), code


_stats_cache = {"data": None, "ts": 0}


@meta_bp.route("/api/stats")
def live_stats():
    """Public live stats for homepage — cached 5 min."""
    now = _time.time()
    if _stats_cache["data"] and (now - _stats_cache["ts"]) < 300:
        return jsonify(_stats_cache["data"])

    import sqlite3 as _sq
    _root = os.path.dirname(os.path.dirname(__file__))
    # Count MCP tools dynamically from mcp_server.py decorators
    _mcp_file = os.path.join(_root, "mcp_server.py")
    try:
        with open(_mcp_file) as f:
            _mcp_src = f.read()
        mcp_count = _mcp_src.count("@metered_tool") + _mcp_src.count("@mcp.tool()")
    except Exception:
        mcp_count = 155
    stats = {"mcp_tools": mcp_count}

    def _count(db, query):
        c = _sq.connect(os.path.join(_root, db), timeout=2)
        val = c.execute(query).fetchone()[0]
        c.close()
        return val

    # Skills
    try:
        stats["skills"] = _count("skills.db", "SELECT COUNT(*) FROM skills")
    except Exception:
        stats["skills"] = 0

    # Discovered APIs
    try:
        stats["apis"] = _count("api_catalog.db", "SELECT COUNT(*) FROM discovered_apis")
    except Exception:
        stats["apis"] = 0

    # Registered agents
    try:
        stats["agents"] = _count("agent_memory.db", "SELECT COUNT(*) FROM agent_registry")
    except Exception:
        stats["agents"] = 0

    # API keys issued + total calls
    try:
        c = _sq.connect(os.path.join(_root, "api_keys.db"), timeout=2)
        stats["api_keys"] = c.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        stats["total_calls"] = c.execute("SELECT COALESCE(SUM(call_count), 0) FROM api_keys").fetchone()[0]
        c.close()
    except Exception:
        stats["api_keys"] = 0
        stats["total_calls"] = 0

    _stats_cache["data"] = stats
    _stats_cache["ts"] = now
    return jsonify(stats)


@meta_bp.route("/preview", methods=["GET", "POST"])
def preview():
    """Free demo endpoint — no payment required. Returns a short Claude response to prove the service works."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", request.args.get("topic", "x402 payment protocol for AI agents"))
    topic = topic[:200]  # cap input length
    ck = f"preview:{_hashlib.md5(topic.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    llm_result, err = _call_llm(
        [{"role": "user", "content": f"In 2-3 sentences, briefly explain: {topic}"}],
        max_tokens=120, endpoint="/preview",
    )
    if err:
        return jsonify({"error": err}), 400
    result = {
        "result": llm_result["text"],
        "model": llm_result["model"],
        "free": True,
        "note": "This preview is capped at 120 tokens. Full /research returns structured summary + key points + sources for $0.01 USDC.",
        "full_api": "https://api.aipaygen.com/discover",
        "openapi": "https://api.aipaygen.com/openapi.json",
    }
    _cache_set(ck, result, 300)  # 5 min
    return jsonify(result)


@meta_bp.route("/robots.txt")

@meta_bp.route("/robots.txt")
def robots_txt():
    from flask import Response
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /discover\n"
        "Allow: /docs\n"
        "Allow: /llms.txt\n"
        "Allow: /security\n"
        "Allow: /openapi.json\n"
        "Allow: /.well-known/\n"
        "Allow: /.well-known/agent.json\n"
        "Allow: /.well-known/ai-plugin.json\n"
        "Allow: /.well-known/security.txt\n"
        "Disallow: /admin/\n"
        "Disallow: /stats\n"
        "Disallow: /skills/\n"
        "Disallow: /discovery/\n"
        "Disallow: /outbound/\n"
        "Disallow: /harvest/\n"
        "Disallow: /agent\n"
        "Disallow: /credits/\n"
        "Disallow: /free-tier/\n"
        "\n"
        "Sitemap: https://api.aipaygen.com/sitemap.xml\n"
        "\n"
        "# AI Agent Discovery\n"
        "# LLMs.txt: https://api.aipaygen.com/llms.txt\n"
        "# Agent Card: https://api.aipaygen.com/.well-known/agent.json\n"
        "# OpenAPI: https://api.aipaygen.com/openapi.json\n"
    )
    return Response(body, mimetype="text/plain")


DOCS_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen — Documentation</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#020408;--bg2:#070d14;--bg3:#0d1a24;--green:#00ff9d;--cyan:#00d4ff;--dim:#8b949e;--border:#1a2332}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:#e1e4e8;font-family:'IBM Plex Sans',sans-serif;line-height:1.7;padding-top:70px}
.layout{display:flex;max-width:1200px;margin:0 auto;min-height:calc(100vh - 70px)}
.sidebar{width:240px;position:sticky;top:70px;height:calc(100vh - 70px);overflow-y:auto;padding:32px 16px;border-right:1px solid var(--border);flex-shrink:0}
.sidebar a{display:block;color:var(--dim);text-decoration:none;padding:6px 12px;font-size:0.85rem;border-radius:6px;margin-bottom:2px;transition:all .15s}
.sidebar a:hover,.sidebar a.active{color:#fff;background:var(--bg3)}
.sidebar .section-title{color:#4a5568;font-size:0.7rem;text-transform:uppercase;letter-spacing:0.08em;padding:16px 12px 4px;font-weight:600}
.content{flex:1;padding:40px 48px 80px;max-width:860px}
h1{font-family:'IBM Plex Mono',monospace;font-size:2rem;color:#fff;margin-bottom:8px}
.subtitle{color:var(--dim);font-size:1.05rem;margin-bottom:40px}
h2{font-family:'IBM Plex Mono',monospace;font-size:1.3rem;color:var(--green);margin:48px 0 16px;padding-bottom:8px;border-bottom:1px solid var(--border)}
h3{font-size:1rem;color:#fff;margin:24px 0 8px}
p{color:var(--dim);margin-bottom:16px}
code{font-family:'IBM Plex Mono',monospace;background:var(--bg3);padding:2px 6px;border-radius:4px;font-size:0.85em;color:var(--green)}
pre{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:20px;overflow-x:auto;margin:16px 0;font-size:0.85rem;line-height:1.5}
pre code{background:none;padding:0;color:#e1e4e8}
ol,ul{margin:0 0 16px 24px;color:var(--dim)}
li{margin-bottom:8px}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}
.step{display:flex;gap:16px;margin:16px 0;padding:16px;background:var(--bg2);border:1px solid var(--border);border-radius:8px}
.step-num{font-family:'IBM Plex Mono',monospace;font-size:1.5rem;font-weight:700;color:var(--green);min-width:40px}
.step-content{flex:1}
.step-content strong{color:#fff}
.endpoint{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px 20px;margin:12px 0}
.endpoint .method{font-family:'IBM Plex Mono',monospace;font-size:0.8rem;font-weight:600;padding:3px 8px;border-radius:4px;margin-right:8px}
.endpoint .method.post{background:rgba(0,255,157,0.15);color:var(--green)}
.endpoint .method.get{background:rgba(0,212,255,0.15);color:var(--cyan)}
.endpoint .method.put{background:rgba(255,165,0,0.15);color:#ffa500}
.endpoint .method.delete{background:rgba(255,80,80,0.15);color:#ff5050}
.endpoint .path{font-family:'IBM Plex Mono',monospace;font-size:0.9rem;color:#fff}
.endpoint .desc{color:var(--dim);font-size:0.85rem;margin-top:6px}
.pricing-table{width:100%;border-collapse:collapse;margin:16px 0}
.pricing-table th{text-align:left;color:var(--green);font-family:'IBM Plex Mono',monospace;font-size:0.8rem;padding:8px 12px;border-bottom:1px solid var(--border)}
.pricing-table td{padding:8px 12px;color:var(--dim);font-size:0.85rem;border-bottom:1px solid rgba(26,35,50,0.5)}
.pricing-table td:first-child{font-family:'IBM Plex Mono',monospace;color:#fff}
.badge{display:inline-block;font-size:0.7rem;padding:2px 8px;border-radius:10px;font-weight:600;margin-left:8px}
.badge-new{background:rgba(0,212,255,0.2);color:var(--cyan)}
.badge-free{background:rgba(0,255,157,0.2);color:var(--green)}
.cta-box{background:linear-gradient(135deg,rgba(0,255,157,0.08),rgba(0,212,255,0.08));border:1px solid rgba(0,255,157,0.2);border-radius:12px;padding:24px;margin:24px 0;text-align:center}
.cta-box a{display:inline-block;background:linear-gradient(135deg,#00ff9d,#00d4ff);color:#000;font-weight:700;padding:10px 24px;border-radius:6px;margin-top:12px;text-decoration:none;font-family:'IBM Plex Mono',monospace}
@media(max-width:768px){.sidebar{display:none}.content{padding:24px 16px}}
</style>
</head>
<body>
{{ nav|safe }}
<div class="layout">
<nav class="sidebar">
  <div class="section-title">Getting Started</div>
  <a href="#overview">Overview</a>
  <a href="#quickstart">Quick Start</a>
  <a href="#payment">Payment Options</a>
  <div class="section-title">Agent Builder</div>
  <a href="#builder">Build Your Agent</a>
  <a href="#templates">Templates</a>
  <a href="#scheduling">Scheduling</a>
  <div class="section-title">API Reference</div>
  <a href="#ai-tools">AI Tools (40+)</a>
  <a href="#data">Data Lookups</a>
  <a href="#scraping">Web Scraping</a>
  <a href="#agents">Agent System</a>
  <a href="#memory">Agent Memory</a>
  <a href="#skills">Skills Library</a>
  <a href="#catalog">API Catalog</a>
  <div class="section-title">Integration</div>
  <a href="#mcp">MCP Setup</a>
  <a href="#models">Models</a>
  <a href="#discovery">Discovery</a>
  <a href="#free">Free Endpoints</a>
</nav>
<div class="content">

<h1>Documentation</h1>
<p class="subtitle">155 AI tools, custom agent builder, scheduling, and 15 AI models — all in one API.</p>

<h2 id="overview">Overview</h2>
<p>AiPayGen is the most comprehensive AI toolkit for developers and agents. Build custom AI agents, access 155 tools, 1500+ skills, and 4000+ APIs — all through a single API key or MCP connection.</p>

<div class="cta-box">
  <strong style="color:#fff">Start building in 30 seconds</strong><br>
  <span style="color:var(--dim)">Get an API key and start making calls immediately.</span>
  <br><a href="/buy-credits">Get API Key ($1)</a>
</div>

<h2 id="quickstart">Quick Start</h2>

<h3>Option 1: API Key (Recommended)</h3>
<pre><code>import httpx

BASE = "https://api.aipaygen.com"

# 1. Buy an API key
key = httpx.post(f"{BASE}/credits/buy",
    json={"amount_usd": 5.0}).json()["key"]  # apk_xxx

# 2. Use it on any endpoint
result = httpx.post(f"{BASE}/research",
    json={"topic": "quantum computing"},
    headers={"Authorization": f"Bearer {key}"}
).json()
print(result)</code></pre>

<h3>Option 2: MCP (Claude / Cursor)</h3>
<pre><code># Install
pip install aipaygen-mcp

# Add to Claude Code
claude mcp add aipaygen -- aipaygen-mcp

# Or connect remotely (no install needed)
# URL: https://mcp.aipaygen.com/mcp</code></pre>

<h3>Option 3: Free Preview</h3>
<pre><code># No payment or key needed
curl -X POST https://api.aipaygen.com/preview \\
  -H "Content-Type: application/json" \\
  -d '{"topic": "AI agents"}'</code></pre>

<h2 id="payment">Payment Options</h2>
<table class="pricing-table">
<tr><th>Method</th><th>How</th><th>Best For</th></tr>
<tr><td>API Key</td><td>POST /credits/buy with Stripe</td><td>Most users — simple, prepaid credits</td></tr>
<tr><td>x402 USDC</td><td>HTTP 402 + X-Payment header</td><td>Crypto-native agents, no accounts</td></tr>
<tr><td>MCP</td><td>pip install aipaygen-mcp</td><td>Claude/Cursor — 10 free/day, unlimited with key</td></tr>
</table>

<h2 id="builder">Build Your Own Agent <span class="badge badge-new">NEW</span></h2>
<p>Create custom AI agents with their own personality, tools, model, memory, and scheduling — all through the API or the <a href="/builder">visual builder</a>.</p>

<div class="endpoint">
  <span class="method post">POST</span><span class="path">/agents/build</span>
  <div class="desc">Create a custom agent with name, personality, tools, model, memory, and optional schedule.</div>
</div>

<pre><code># Create a crypto monitoring agent
agent = httpx.post(f"{BASE}/agents/build",
    json={
        "name": "Crypto Watcher",
        "system_prompt": "Monitor crypto prices and alert on big moves",
        "tools": ["get_crypto_prices", "analyze", "memory_store"],
        "model": "claude-haiku",
        "schedule": {"type": "loop", "config": {"minutes": 30}}
    },
    headers={"Authorization": f"Bearer {key}"}
).json()

agent_id = agent["agent_id"]

# Run the agent
result = httpx.post(f"{BASE}/agents/custom/{agent_id}/run",
    json={"task": "Check BTC and ETH prices, analyze trends"},
    headers={"Authorization": f"Bearer {key}"}
).json()</code></pre>

<div class="endpoint">
  <span class="method get">GET</span><span class="path">/agents/custom</span>
  <div class="desc">List your custom agents.</div>
</div>
<div class="endpoint">
  <span class="method get">GET</span><span class="path">/agents/custom/{id}</span>
  <div class="desc">Get agent details and config.</div>
</div>
<div class="endpoint">
  <span class="method put">PUT</span><span class="path">/agents/custom/{id}</span>
  <div class="desc">Update agent config (name, tools, prompt, model, schedule, etc.).</div>
</div>
<div class="endpoint">
  <span class="method post">POST</span><span class="path">/agents/custom/{id}/run</span>
  <div class="desc">Execute a task with the agent.</div>
</div>
<div class="endpoint">
  <span class="method delete">DELETE</span><span class="path">/agents/custom/{id}</span>
  <div class="desc">Archive an agent.</div>
</div>

<h2 id="templates">Agent Templates</h2>
<p>Start from a pre-built template and customize. 10 templates available:</p>
<ul>
  <li><strong>Research Agent</strong> — web search + summarize + scraping</li>
  <li><strong>Crypto Tracker</strong> — price monitoring on a 30-min loop</li>
  <li><strong>Content Writer</strong> — blog posts, social media, copywriting</li>
  <li><strong>Customer Support</strong> — Q&amp;A with sentiment detection</li>
  <li><strong>Social Media Manager</strong> — daily posts + platform monitoring</li>
  <li><strong>Code Helper</strong> — code generation + testing</li>
  <li><strong>Data Analyst</strong> — data analysis + SQL + charts</li>
  <li><strong>News Monitor</strong> — hourly news briefings</li>
  <li><strong>Personal Assistant</strong> — planning + email + memory</li>
  <li><strong>Sales Bot</strong> — lead scoring + outreach</li>
</ul>
<div class="endpoint">
  <span class="method get">GET</span><span class="path">/builder/templates</span>
  <div class="desc">List all available templates (JSON).</div>
</div>

<h2 id="scheduling">Scheduling &amp; Automation</h2>
<p>Agents can run automatically on three trigger types:</p>
<h3>Loop (Interval)</h3>
<pre><code>httpx.post(f"{BASE}/agents/custom/{agent_id}/schedule",
    json={"type": "loop", "config": {"minutes": 30}},
    headers={"Authorization": f"Bearer {key}"})</code></pre>
<h3>Cron (Schedule)</h3>
<pre><code>httpx.post(f"{BASE}/agents/custom/{agent_id}/schedule",
    json={"type": "cron", "config": {"hour": 9, "minute": 0, "day_of_week": "mon-fri"}},
    headers={"Authorization": f"Bearer {key}"})</code></pre>
<h3>Event (Trigger)</h3>
<pre><code>httpx.post(f"{BASE}/agents/custom/{agent_id}/schedule",
    json={"type": "event", "config": {"trigger": "message"}},
    headers={"Authorization": f"Bearer {key}"})</code></pre>
<div class="endpoint">
  <span class="method get">GET</span><span class="path">/agents/custom/{id}/runs</span>
  <div class="desc">View execution history for an agent.</div>
</div>

<h2 id="ai-tools">AI Tools</h2>
<p>40+ AI-powered endpoints. All accept an optional <code>model</code> parameter.</p>
<div class="endpoint"><span class="method post">POST</span><span class="path">/research</span><div class="desc">Deep research on any topic with web sources.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/summarize</span><div class="desc">Summarize text into bullets, paragraph, or TL;DR.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/analyze</span><div class="desc">Analyze text with a specific question.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/write</span><div class="desc">Generate written content (blog, email, copy).</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/code</span><div class="desc">Generate, explain, or debug code.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/translate</span><div class="desc">Translate text to any language.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/sentiment</span><div class="desc">Detect sentiment (positive/negative/neutral).</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/classify</span><div class="desc">Classify text into custom categories.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/vision</span><div class="desc">Analyze images with AI.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/rag</span><div class="desc">Retrieval-augmented generation over documents.</div></div>
<p style="margin-top:8px">Plus: <code>/rewrite</code>, <code>/extract</code>, <code>/qa</code>, <code>/compare</code>, <code>/outline</code>, <code>/explain</code>, <code>/proofread</code>, <code>/keywords</code>, <code>/headline</code>, <code>/social</code>, <code>/pitch</code>, <code>/diagram</code>, <code>/json_schema</code>, <code>/workflow</code>, <code>/pipeline</code>, <code>/batch</code>, <code>/chain</code>, <code>/test_cases</code>, <code>/sql</code>, <code>/regex</code>, <code>/mock</code>, <code>/debate</code>, <code>/decide</code>, <code>/plan</code>, <code>/score</code>, <code>/tag</code>, <code>/fact</code>, <code>/questions</code>, <code>/email</code>, <code>/enrich</code></p>

<h2 id="data">Data Lookups</h2>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/weather?city=London</span><div class="desc">Current weather for any city.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/crypto?symbols=BTC,ETH</span><div class="desc">Live crypto prices.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/exchange?from=USD&amp;to=EUR</span><div class="desc">Currency exchange rates.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/holidays?country=US</span><div class="desc">Public holidays by country.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/joke</span><div class="desc">Random joke. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/data/quote</span><div class="desc">Random inspirational quote. <span class="badge badge-free">FREE</span></div></div>

<h2 id="scraping">Web Scraping</h2>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/website</span><div class="desc">Scrape any website URL.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/google-maps</span><div class="desc">Scrape Google Maps business listings.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/tweets</span><div class="desc">Scrape tweets by keyword or user.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/youtube</span><div class="desc">Scrape YouTube video data and transcripts.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/instagram</span><div class="desc">Scrape Instagram profiles and posts.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/scrape/tiktok</span><div class="desc">Scrape TikTok videos and profiles.</div></div>

<h2 id="agents">Agent System</h2>
<div class="endpoint"><span class="method post">POST</span><span class="path">/agent</span><div class="desc">Autonomous ReAct agent — give it a task, it reasons through it using tools.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/agent/stream</span><div class="desc">Streaming agent with SSE events.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/agents/register</span><div class="desc">Register an agent in the network.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/agents</span><div class="desc">List all registered agents.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/agents/search?q=keyword</span><div class="desc">Search agents by capability.</div></div>

<h2 id="memory">Agent Memory</h2>
<p>Persistent key-value memory for agents across conversations.</p>
<div class="endpoint"><span class="method post">POST</span><span class="path">/memory/set</span><div class="desc">Store a value in agent memory.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/memory/get</span><div class="desc">Retrieve a value from agent memory.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/memory/search</span><div class="desc">Search agent memory by keyword.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/memory/list</span><div class="desc">List all memory keys for an agent.</div></div>

<h2 id="skills">Skills Library</h2>
<p>1500+ searchable, executable skills. Create your own or use community skills.</p>
<div class="endpoint"><span class="method get">GET</span><span class="path">/skills/search?q=keyword</span><div class="desc">Search skills by keyword (TF-IDF ranked).</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/skills/execute</span><div class="desc">Execute a skill by name with input.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/skills/create</span><div class="desc">Create a new reusable skill.</div></div>

<h2 id="catalog">API Catalog</h2>
<p>4000+ indexed APIs — search, discover, and invoke third-party APIs through AiPayGen.</p>
<div class="endpoint"><span class="method get">GET</span><span class="path">/catalog</span><div class="desc">Browse the full API catalog.</div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/catalog/{id}</span><div class="desc">Get details for a specific API.</div></div>
<div class="endpoint"><span class="method post">POST</span><span class="path">/catalog/{id}/invoke</span><div class="desc">Invoke a cataloged API through AiPayGen.</div></div>

<h2 id="mcp">MCP Integration</h2>
<p>All 155 tools are available as MCP tools. Three ways to connect:</p>

<h3>1. PyPI Package (Recommended)</h3>
<pre><code># Install
pip install aipaygen-mcp

# Add to Claude Code
claude mcp add aipaygen -- aipaygen-mcp

# Add to Claude Desktop (claude_desktop_config.json)
{
  "mcpServers": {
    "aipaygen": {
      "command": "aipaygen-mcp",
      "env": { "AIPAYGEN_API_KEY": "apk_xxx" }
    }
  }
}</code></pre>

<h3>2. Remote SSE (No Install)</h3>
<pre><code># Connect directly — works in any MCP client
URL: https://mcp.aipaygen.com/mcp</code></pre>

<h3>3. MCP Registry</h3>
<pre><code># Listed on registry.modelcontextprotocol.io
# ID: io.github.Damien829/aipaygen</code></pre>

<h2 id="models">Available Models</h2>
<table class="pricing-table">
<tr><th>Model</th><th>Provider</th><th>Best For</th></tr>
<tr><td>auto</td><td>AiPayGen</td><td>Automatic — picks best model for the task</td></tr>
<tr><td>claude-sonnet</td><td>Anthropic</td><td>Complex reasoning, analysis</td></tr>
<tr><td>claude-haiku</td><td>Anthropic</td><td>Fast, cheap, good enough for most tasks</td></tr>
<tr><td>gpt-4o</td><td>OpenAI</td><td>General purpose, strong coding</td></tr>
<tr><td>gpt-4o-mini</td><td>OpenAI</td><td>Fast and cheap</td></tr>
<tr><td>deepseek-chat</td><td>DeepSeek</td><td>Coding, technical tasks</td></tr>
<tr><td>deepseek-reasoner</td><td>DeepSeek</td><td>Complex reasoning chains</td></tr>
<tr><td>gemini-2.0-flash</td><td>Google</td><td>Fast, multimodal</td></tr>
<tr><td>grok-3-mini</td><td>xAI</td><td>Real-time knowledge</td></tr>
<tr><td>mistral-small</td><td>Mistral</td><td>Efficient, multilingual</td></tr>
<tr><td>llama-4-scout</td><td>Meta</td><td>Open-weight, fast</td></tr>
</table>
<pre><code># Use any model on any endpoint
httpx.post(f"{BASE}/research",
    json={"topic": "AI", "model": "deepseek-chat"},
    headers={"Authorization": f"Bearer {key}"})</code></pre>

<h2 id="discovery">Discovery Endpoints</h2>
<ul>
  <li><a href="/discover"><code>/discover</code></a> — machine-readable service catalog (JSON)</li>
  <li><a href="/.well-known/agent.json"><code>/.well-known/agent.json</code></a> — A2A Agent Card</li>
  <li><a href="/openapi.json"><code>/openapi.json</code></a> — OpenAPI 3.1 spec</li>
  <li><a href="/llms.txt"><code>/llms.txt</code></a> — LLMs.txt format</li>
  <li><a href="/builder/templates"><code>/builder/templates</code></a> — Agent templates</li>
</ul>

<h2 id="free">Free Endpoints</h2>
<p>No payment or API key needed:</p>
<div class="endpoint"><span class="method post">POST</span><span class="path">/preview</span><div class="desc">Free Claude demo — try before you buy. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/time</span><div class="desc">Current UTC time. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/uuid</span><div class="desc">Generate a UUID. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/ip</span><div class="desc">Your IP address info. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/hash</span><div class="desc">Hash text (SHA256, MD5, etc.). <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/base64</span><div class="desc">Base64 encode/decode. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/free/random</span><div class="desc">Random numbers/strings. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/health</span><div class="desc">Service health check. <span class="badge badge-free">FREE</span></div></div>
<div class="endpoint"><span class="method get">GET</span><span class="path">/discover</span><div class="desc">Full service catalog. <span class="badge badge-free">FREE</span></div></div>

<h2>Payment Details</h2>
<ul>
  <li><strong>Protocol:</strong> <a href="https://x402.org">x402</a> (HTTP 402 Payment Required)</li>
  <li><strong>Network:</strong> Base Mainnet (eip155:8453)</li>
  <li><strong>Token:</strong> USDC (6 decimals)</li>
  <li><strong>Wallet:</strong> <code>0x366D488a48de1B2773F3a21F1A6972715056Cb30</code></li>
  <li><strong>Bulk discount:</strong> 20% when balance &gt;= $2.00</li>
</ul>

</div>
</div>
{{ footer|safe }}
</body>
</html>'''


@meta_bp.route("/docs")
def docs_page():
    return render_template_string(DOCS_HTML, nav=NAV_HTML, footer=FOOTER_HTML)


LLMS_TXT = """\
# AiPayGen

> 155 AI tools in one API. Multi-model (Claude, GPT-4o, DeepSeek, Gemini, Grok, Mistral, Llama). Three payment paths: API key (from $1), x402 USDC, or MCP (10 free/day).

## What This Service Does

AiPayGen is a pay-per-use AI platform for autonomous agents. Research, write, code, analyze, scrape, and more. Built for agent pipelines with persistent memory and skill discovery.

## Capabilities

- **AI Processing** — research, write, code, analyze, translate, summarize, classify, sentiment, RAG, vision, diagrams
- **Web Scraping** — Google Maps, Twitter/X, Instagram, LinkedIn, YouTube, TikTok, any website
- **Agent Infrastructure** — persistent memory, messaging, task boards, webhook relay, async jobs, file storage
- **Data & Utilities** — weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending
- **Skills Library** — 1500+ searchable skills via TF-IDF. Search, browse, and execute dynamically.
- **Multi-Model** — Claude, GPT-4o, DeepSeek, Gemini. All AI endpoints accept `model` parameter.

## Authentication (3 Paths)

### 1. Free Tier (No Auth)
- 10 calls/day per IP, no key needed
- Just POST JSON to any endpoint

### 2. API Key (Recommended)
Buy a prepaid API key via Stripe or x402. Use it everywhere with Bearer auth.
- `POST /credits/buy` with `{"amount_usd": 5.0}` → returns `apk_xxx` key
- Use: `Authorization: Bearer apk_xxx` header on any endpoint
- 20% bulk discount when balance >= $2.00
- Token-based metering available: `X-Pricing: metered` header

### 3. x402 USDC (Crypto-Native)
- **Standard**: [x402](https://x402.org) — HTTP 402 Payment Required
- **Network**: Base Mainnet (eip155:8453)
- **Token**: USDC (6 decimals)
- **Flow**: POST endpoint → 402 with payment instructions → retry with `X-Payment` header

## Top 15 Tools — Input/Output & Pricing

| Tool | Endpoint | Price | Input (JSON POST) | Output |
|------|----------|-------|--------------------|--------|
| Research | POST /research | $0.01 | `{"topic": "..."}` | `{"result": "...", "_meta": {...}}` |
| Summarize | POST /summarize | $0.01 | `{"text": "..."}` | `{"summary": "..."}` |
| Translate | POST /translate | $0.02 | `{"text": "...", "target": "es"}` | `{"translation": "..."}` |
| Code | POST /code | $0.05 | `{"task": "...", "language": "python"}` | `{"code": "...", "explanation": "..."}` |
| Write | POST /write | $0.05 | `{"prompt": "...", "tone": "professional"}` | `{"text": "..."}` |
| Analyze | POST /analyze | $0.02 | `{"text": "...", "aspects": [...]}` | `{"analysis": "..."}` |
| Scrape Website | POST /scrape/website | $0.02 | `{"url": "https://..."}` | `{"content": "...", "title": "..."}` |
| Sentiment | POST /sentiment | $0.01 | `{"text": "..."}` | `{"sentiment": "positive", "score": 0.92}` |
| Extract | POST /extract | $0.02 | `{"text": "...", "fields": [...]}` | `{"extracted": {...}}` |
| Compare | POST /compare | $0.02 | `{"items": ["A", "B"]}` | `{"comparison": "..."}` |
| Classify | POST /classify | $0.01 | `{"text": "...", "categories": [...]}` | `{"category": "...", "confidence": 0.95}` |
| Web Search | POST /web-search | $0.02 | `{"query": "..."}` | `{"results": [...]}` |
| Fact Check | POST /fact | $0.02 | `{"claim": "..."}` | `{"verdict": "...", "evidence": "..."}` |
| Batch | POST /batch | $0.10 | `{"operations": [{...}, ...]}` | `{"results": [...]}` |
| Vision | POST /vision | $0.05 | `{"image_url": "...", "question": "..."}` | `{"description": "..."}` |

## Example curl Calls

### Research
```bash
curl -X POST https://api.aipaygen.com/research \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer apk_YOUR_KEY" \\
  -d '{"topic": "quantum computing breakthroughs 2026"}'
```

### Summarize
```bash
curl -X POST https://api.aipaygen.com/summarize \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer apk_YOUR_KEY" \\
  -d '{"text": "Long article text here...", "length": "short"}'
```

### Translate
```bash
curl -X POST https://api.aipaygen.com/translate \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer apk_YOUR_KEY" \\
  -d '{"text": "Hello world", "target": "ja"}'
```

### Code
```bash
curl -X POST https://api.aipaygen.com/code \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer apk_YOUR_KEY" \\
  -d '{"task": "fibonacci sequence generator", "language": "python"}'
```

### Scrape Website
```bash
curl -X POST https://api.aipaygen.com/scrape/website \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer apk_YOUR_KEY" \\
  -d '{"url": "https://example.com"}'
```

## MCP (Model Context Protocol)

- 10 free calls/day, no payment needed
- Unlimited with `AIPAYGEN_API_KEY` env var
- Install: `pip install aipaygen-mcp && claude mcp add aipaygen -- python -m aipaygen_mcp`
- Remote SSE: https://mcp.aipaygen.com/mcp

## Discovery Endpoints

- `GET /discover` — machine-readable service catalog (JSON)
- `GET /.well-known/agent.json` — A2A Agent Card
- `GET /.well-known/ai-plugin.json` — ChatGPT/OpenAI plugin manifest
- `GET /openapi.json` — OpenAPI 3.1 spec
- `GET /llms.txt` — this file
- `GET /health` — service health check
- `POST /preview` — free Claude demo (no payment needed)

## Quick Start (Python)

```python
import httpx
BASE = "https://api.aipaygen.com"

# 1. Get an API key (easiest path)
key_resp = httpx.post(f"{BASE}/credits/buy", json={"amount_usd": 5.0}).json()
API_KEY = key_resp["key"]  # apk_xxx

# 2. Use it on any endpoint
result = httpx.post(f"{BASE}/research",
    json={"topic": "quantum computing"},
    headers={"Authorization": f"Bearer {API_KEY}"}
).json()

# Free preview (no payment needed)
print(httpx.post(f"{BASE}/preview", json={"topic": "AI agents"}).json())
```

## Links

- Documentation: https://aipaygen.com/docs
- OpenAPI Spec: https://api.aipaygen.com/openapi.json
- Buy Credits: https://aipaygen.com/buy-credits
- Security: https://aipaygen.com/security
- MCP Registry: https://registry.modelcontextprotocol.io/servers/io.github.Damien829/aipaygen

## Notes for AI Agents

- All paid responses include `_meta` with endpoint, model, network, timestamp.
- Fetch `/discover` for the service catalog before calling endpoints.
- USDC precision: 6 decimals. Network: Base Mainnet (eip155:8453).
- Agent memory persists indefinitely — use a stable `agent_id`.
- API key is the fastest path — one POST and you're running.
- 402 responses include `Link` headers pointing to /openapi.json and /.well-known/ai-plugin.json.
"""


@meta_bp.route("/openapi.json")
def openapi_spec():
    from openapi_gen import generate_openapi_spec
    return jsonify(generate_openapi_spec())




@meta_bp.route("/llms.txt")

@meta_bp.route("/llms.txt")
def llms_txt():
    try:
        funnel_log_event("llms_txt_hit", endpoint="/llms.txt", ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""))
    except Exception:
        pass
    from flask import Response
    return Response(LLMS_TXT, content_type="text/plain; charset=utf-8")


@meta_bp.route("/.well-known/ai-plugin.json")
def ai_plugin():
    base_url = "https://api.aipaygen.com"
    return jsonify({
        "schema_version": "v1",
        "name_for_human": "AiPayGen",
        "name_for_model": "aipaygen",
        "description_for_human": "155 AI tools — research, write, code, translate, scrape, and more. 10 free calls/day.",
        "description_for_model": (
            "AiPayGen provides 153 AI-powered tools accessible via a single API. "
            "Use for research, writing, code generation, translation, sentiment analysis, "
            "web scraping, data extraction, content comparison, fact-checking, and more. "
            "Free tier: 10 calls/day per IP. Paid: prepaid API key (Bearer apk_xxx) or "
            "x402 USDC micropayment. All tools accept JSON POST requests."
        ),
        "auth": {"type": "service_http", "authorization_type": "bearer"},
        "api": {
            "type": "openapi",
            "url": f"{base_url}/openapi.json",
        },
        "logo_url": "https://aipaygen.com/favicon.ico",
        "contact_email": "hello@aipaygen.com",
        "legal_info_url": f"{base_url}/security",
    })


@meta_bp.route("/.well-known/openapi.json")
def well_known_openapi():
    from flask import redirect
    return redirect("/openapi.json", code=301)




@meta_bp.route("/.well-known/agent.json")
def agent_manifest():
    """Google A2A Agent Card — https://google.github.io/A2A/specification/"""
    base = "https://api.aipaygen.com"
    return jsonify({
        "name": "AiPayGen",
        "description": (
            "AI agent API marketplace with 155 tools and 1500+ searchable skills. "
            "Research, writing, coding, analysis, web scraping, real-time data, agent memory, "
            "and multi-model AI (Claude, GPT-4o, DeepSeek, Gemini). "
            "Three payment paths: API key (recommended), x402 USDC, or MCP (10 free/day)."
        ),
        "url": base,
        "version": "3.1.0",
        "documentationUrl": f"{base}/llms.txt",
        "capabilities": {
            "streaming": True,
            "pushNotifications": True,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["Bearer", "x402"],
            "description": (
                "Recommended: Buy API key via POST /credits/buy or /stripe/create-checkout, "
                "then use 'Authorization: Bearer apk_xxx'. "
                "Alternative: Pay per call with USDC on Base via x402. "
                "MCP: 10 free calls/day, unlimited with API key."
            ),
            "buyCredits": f"{base}/credits/buy",
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "research", "name": "Research",
                "description": "Research any topic — returns summary, key points, sources",
                "tags": ["research", "ai", "claude", "knowledge"],
                "examples": ["Research quantum computing breakthroughs in 2025"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "write", "name": "Write Content",
                "description": "Write articles, blog posts, copy, or any content to spec",
                "tags": ["writing", "content", "copywriting"],
                "examples": ["Write a 500-word article about renewable energy"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "code", "name": "Generate Code",
                "description": "Generate code in any language from a description",
                "tags": ["code", "programming", "development"],
                "examples": ["Write a Python function to parse CSV files"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "analyze", "name": "Analyze",
                "description": "Analyze data or text, return structured insights",
                "tags": ["analysis", "data", "insights"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "scrape", "name": "Web Scraping",
                "description": "Scrape Google Maps, Twitter, LinkedIn, YouTube, TikTok, Instagram, any website",
                "tags": ["scraping", "data-collection", "web"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "data", "name": "Real-Time Data",
                "description": "Real-time weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending, Reddit, YouTube transcripts",
                "tags": ["data", "real-time", "free"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "memory", "name": "Agent Memory",
                "description": "Persistent key-value memory for agents — survives across sessions",
                "tags": ["memory", "persistence", "storage"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "files", "name": "File Storage",
                "description": "Upload and retrieve files up to 10MB. Returns URL.",
                "tags": ["files", "storage", "upload"],
                "inputModes": ["application/json", "multipart/form-data"],
                "outputModes": ["application/json"],
            },
            {
                "id": "webhooks", "name": "Webhook Relay",
                "description": "Get a unique URL to receive webhooks from any external service",
                "tags": ["webhooks", "callbacks", "events"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "async", "name": "Async Jobs",
                "description": "Submit long-running jobs with a callback URL — fire and forget",
                "tags": ["async", "jobs", "background"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "messaging", "name": "Agent Messaging",
                "description": "Send messages between agents with persistent inbox",
                "tags": ["messaging", "communication", "agents"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "tasks", "name": "Task Board",
                "description": "Post tasks for other agents to claim and complete",
                "tags": ["tasks", "collaboration", "marketplace"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
        ],
        "security": {
            "transport": "TLS 1.3 (Cloudflare)",
            "headers": ["HSTS", "X-Content-Type-Options", "X-Frame-Options", "CSP", "Referrer-Policy", "Permissions-Policy"],
            "data_handling": {
                "request_logging": "metadata_only",
                "response_storage": "none",
                "data_retention_days": 0,
                "description": "No request/response payloads are stored. Only billing metadata (timestamp, endpoint, token count) is retained.",
            },
            "code_execution": {
                "sandbox": "AST-validated with blocked imports/builtins",
                "network_access": "none",
                "filesystem_access": "none",
            },
            "ssrf_protection": True,
            "auto_refund_on_5xx": True,
            "security_policy": f"{base}/security",
            "security_txt": f"{base}/.well-known/security.txt",
        },
        "contact": {"email": "hello@aipaygen.com"},
        "openapi": f"{base}/openapi.json",
        "pricing": {
            "method": "x402",
            "currency": "USDC",
            "network": "Base Mainnet (eip155:8453)",
            "discovery": "POST any endpoint — receive 402 with payment instructions",
        },
    })


@meta_bp.route("/.well-known/agents.json")
def agents_json():
    """Wild Card AI / agentsfoundation.org agents.json discovery standard."""
    base = "https://api.aipaygen.com"
    ai_endpoints = [
        "research", "summarize", "analyze", "translate", "social", "write",
        "code", "extract", "qa", "classify", "sentiment", "keywords", "compare",
        "transform", "chat", "plan", "decide", "proofread", "explain", "questions",
        "outline", "email", "sql", "regex", "mock", "score", "timeline", "action",
        "pitch", "debate", "headline", "fact", "rewrite", "tag", "batch", "pipeline",
        "vision", "rag", "diagram", "json-schema", "test-cases", "workflow",
    ]
    scrape_endpoints = [
        "scrape/google-maps", "scrape/tweets", "scrape/instagram", "scrape/linkedin",
        "scrape/youtube", "scrape/web", "scrape/tiktok", "scrape/facebook-ads", "scrape/actor",
    ]
    memory_endpoints = ["memory/set", "memory/get", "memory/search", "memory/clear"]
    identity_endpoints = ["agents/challenge", "agents/verify", "agents/me", "agents/search"]
    free_endpoints = ["preview", "discover", "openapi.json", "catalog", "agents", "agents/register",
                      "api-call", ".well-known/agents.json", "health", "models"]
    return jsonify({
        "$schema": "https://agentsfoundation.org/agents.json/schema/v1",
        "agents": [{
            "name": "AiPayGen",
            "description": (
                "Multi-model AI platform (15 LLMs, 7 providers) with 155 tools and 140+ endpoints + web scrapers + agent memory + "
                "wallet-based identity + metered token pricing + agent economy. "
                "Research, write, code, analyze, vision, RAG, diagrams, test-cases, workflows, "
                "web scraping (Google Maps, Twitter, LinkedIn, TikTok, YouTube), persistent agent memory, "
                "and a searchable catalog of 4100+ discovered APIs. "
                "No API key required — pay in USDC on Base via x402 protocol. "
                "Also available as MCP tools: mcp install aipaygen-mcp"
            ),
            "url": base,
            "version": "2.0.0",
            "capabilities": [
                "research", "writing", "code-generation", "translation",
                "analysis", "summarization", "social-media", "data-extraction",
                "question-answering", "sentiment-analysis", "sql-generation",
                "batch-processing", "pipeline-chaining", "image-analysis",
                "rag", "diagram-generation", "test-generation", "workflow-orchestration",
                "web-scraping", "agent-memory", "api-catalog", "agent-registry",
                "multi-model", "wallet-identity", "metered-pricing", "agent-search",
                "agent-portfolio", "reputation",
            ],
            "endpoints": (
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "ai"} for ep in ai_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "scraping"} for ep in scrape_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "memory"} for ep in memory_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": True, "category": "identity"} for ep in identity_endpoints] +
                [{"path": "/credits/buy", "method": "POST", "free": False, "category": "pricing"}] +
                [{"path": f"/{ep}", "method": "GET", "free": True} for ep in free_endpoints]
            ),
            "authentication": {
                "type": "x402",
                "description": "HTTP 402 payment protocol. No API key required. Also supports prepaid API keys with metered token-based billing.",
                "payment": {
                    "protocol": "x402",
                    "network": EVM_NETWORK,
                    "token": "USDC",
                    "prices_from": "0.01",
                    "prices_to": "0.20",
                    "currency": "USD",
                },
                "prepaid": {
                    "description": "Buy credit pack via /credits/buy, get API key, use X-Pricing: metered header for per-token billing",
                    "pricing_modes": ["flat", "metered"],
                },
                "wallet_identity": {
                    "description": "EVM/Solana wallet verification via /agents/challenge + /agents/verify, returns JWT session",
                    "chains": ["evm", "solana"],
                },
            },
            "mcp": {
                "remote": "https://mcp.aipaygen.com/mcp",
                "package": "aipaygen-mcp",
                "registry": "pypi",
                "install": "mcp install aipaygen-mcp",
            },
            "links": {
                "openapi": f"{base}/openapi.json",
                "discover": f"{base}/discover",
                "sdk": f"{base}/sdk",
                "llms_txt": f"{base}/llms.txt",
                "mcp": "https://mcp.aipaygen.com/mcp",
                "catalog": f"{base}/catalog",
                "agents": f"{base}/agents",
            },
            "contact": "https://aipaygen.com",
        }]
    })


@meta_bp.route("/.well-known/x402.json")
def x402_manifest():
    """x402 payment discovery + Bazaar auto-discovery manifest — tells agents how to pay and indexes this service."""
    base = "https://api.aipaygen.com"
    return jsonify({
        "x402": True,
        "x402Version": 1,
        "version": "1.0",
        "network": EVM_NETWORK,
        "currency": "USDC",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base Mainnet
        "payTo": WALLET_ADDRESS,
        "wallet": WALLET_ADDRESS,
        "facilitator": FACILITATOR_URL,
        "name": "AiPayGen",
        "description": (
            "155 AI tools, 1500+ skills, web scrapers, agent memory, file storage, "
            "webhook relay, async jobs, and an API catalog of 4100+ discovered APIs. "
            "No API key required — pay per call in USDC on Base via x402 protocol."
        ),
        "url": base,
        "openapi": f"{base}/openapi.json",
        "llms_txt": f"{base}/llms.txt",
        "discovery": {
            "catalog": f"{base}/discover",
            "openapi": f"{base}/openapi.json",
            "llms_txt": f"{base}/llms.txt",
            "agent_card": f"{base}/.well-known/agent.json",
        },
        "flow": "POST endpoint -> HTTP 402 with X-Payment-Info -> retry with X-Payment header",
        "categories": ["ai", "scraping", "data", "memory", "workflows", "agent-infrastructure"],
        "endpoints": [
            {"path": "/research", "method": "POST", "price": "$0.01", "description": "AI research on any topic"},
            {"path": "/write", "method": "POST", "price": "$0.05", "description": "Long-form content generation"},
            {"path": "/analyze", "method": "POST", "price": "$0.02", "description": "Data/text analysis"},
            {"path": "/code", "method": "POST", "price": "$0.05", "description": "Code generation in any language"},
            {"path": "/summarize", "method": "POST", "price": "$0.01", "description": "Text summarization"},
            {"path": "/translate", "method": "POST", "price": "$0.01", "description": "Translation between languages"},
            {"path": "/vision", "method": "POST", "price": "$0.05", "description": "Image analysis with Claude"},
            {"path": "/rag", "method": "POST", "price": "$0.05", "description": "RAG over provided documents"},
            {"path": "/workflow", "method": "POST", "price": "$0.20", "description": "Multi-step agentic workflow"},
            {"path": "/chain", "method": "POST", "price": "$0.25", "description": "Pipeline up to 5 AI steps"},
            {"path": "/batch", "method": "POST", "price": "$0.10", "description": "Batch multiple AI calls"},
            {"path": "/scrape/web", "method": "POST", "price": "$0.05", "description": "Web page scraping"},
            {"path": "/scrape/tweets", "method": "POST", "price": "$0.05", "description": "Twitter/X scraping"},
            {"path": "/scrape/linkedin", "method": "POST", "price": "$0.15", "description": "LinkedIn scraping"},
            {"path": "/scrape/google-maps", "method": "POST", "price": "$0.10", "description": "Google Maps data"},
            {"path": "/memory/set", "method": "POST", "price": "$0.01", "description": "Store agent memory"},
            {"path": "/memory/get", "method": "POST", "price": "$0.01", "description": "Retrieve agent memory"},
            {"path": "/web/search", "method": "POST", "price": "$0.02", "description": "Web search"},
            {"path": "/code/run", "method": "POST", "price": "$0.05", "description": "Execute Python code"},
        ],
        "contact": "https://aipaygen.com",
        "mcp": "https://mcp.aipaygen.com/mcp",
    })


# ── Security Policy ──────────────────────────────────────────────────────────

@meta_bp.route("/.well-known/mcp/server-card.json")
def smithery_server_card():
    """Smithery server card — static metadata for MCP directory scanning."""
    return jsonify({
        "serverInfo": {
            "name": "AiPayGen",
            "version": "1.7.0"
        },
        "authentication": {
            "required": False,
            "schemes": ["bearer"],
            "note": "Optional API key for metered access. 10 free calls/day without key."
        },
        "tools": [
            {"name": "research", "description": "Research any topic with web sources and AI synthesis"},
            {"name": "summarize", "description": "Summarize text into key points"},
            {"name": "analyze", "description": "Analyze text and answer questions about it"},
            {"name": "write", "description": "Generate content — articles, emails, code docs"},
            {"name": "code", "description": "Generate, review, convert, and document code"},
            {"name": "translate", "description": "Translate text between 50+ languages"},
            {"name": "web_search", "description": "Search the web and return structured results"},
            {"name": "scrape_website", "description": "Extract content from any URL"},
            {"name": "vision", "description": "Analyze images with AI"},
            {"name": "sentiment", "description": "Detect sentiment and emotion in text"},
            {"name": "classify", "description": "Classify text into categories"},
            {"name": "extract", "description": "Extract structured data from unstructured text"},
            {"name": "compare", "description": "Compare two texts for differences and similarity"},
            {"name": "diagram", "description": "Generate Mermaid diagrams from descriptions"},
            {"name": "chain_operations", "description": "Pipeline multiple AI operations together"},
            {"name": "memory_store", "description": "Persistent agent memory across sessions"},
            {"name": "memory_recall", "description": "Recall stored memories by key"},
            {"name": "create_agent", "description": "Build custom AI agents with selected tools"},
            {"name": "run_agent", "description": "Execute a custom agent"},
            {"name": "browse_catalog", "description": "Browse 4100+ discovered APIs"},
            {"name": "get_weather", "description": "Current weather for any location"},
            {"name": "get_crypto_prices", "description": "Live cryptocurrency prices"},
            {"name": "get_exchange_rates", "description": "Currency exchange rates"},
        ],
        "resources": [],
        "prompts": []
    })


@meta_bp.route("/.well-known/security.txt")
def security_txt():
    """RFC 9116 security.txt — machine-readable security policy."""
    return (
        "Contact: mailto:hello@aipaygen.com\n"
        "Preferred-Languages: en\n"
        "Canonical: https://api.aipaygen.com/.well-known/security.txt\n"
        "Policy: https://api.aipaygen.com/security\n"
        "Hiring: https://api.aipaygen.com/security\n"
    ), 200, {"Content-Type": "text/plain"}


@meta_bp.route("/security")
def security_page():
    """Human-readable security & privacy policy page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Security & Privacy — AiPayGen</title>
<meta name="description" content="AiPayGen security practices: encryption, data handling, sandboxing, refund policy, and privacy guarantees.">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 32px 16px; line-height: 1.7; }
  .wrap { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin-bottom: 6px; }
  .sub { color: #888; font-size: 0.88rem; margin-bottom: 32px; }
  .section { background: #141414; border: 1px solid #2a2a2a; border-radius: 14px; padding: 28px; margin-bottom: 16px; }
  .section h2 { font-size: 1.1rem; margin-bottom: 12px; display: flex; align-items: center; gap: 10px; }
  .section h2 .icon { font-size: 1.3rem; }
  .section p, .section li { font-size: 0.88rem; color: #bbb; }
  .section ul { margin: 8px 0 0 20px; }
  .section li { margin-bottom: 6px; }
  .highlight { color: #34d399; font-weight: 600; }
  .badge-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .badge { background: #1a1a2e; border: 1px solid #2d2d5e; border-radius: 6px; padding: 4px 10px; font-size: 0.75rem; color: #a0a0ff; }
  .machine { background: #1a1a1a; border-radius: 8px; padding: 14px; margin-top: 16px; font-size: 0.8rem; color: #888; }
  .machine code { color: #a78bfa; }
  a { color: #818cf8; }
  .nav { display: flex; gap: 16px; margin-bottom: 24px; font-size: 0.85rem; }
  .nav a { color: #888; text-decoration: none; }
  .nav a:hover { color: #fff; }
</style>
</head>
<body>
<div class="wrap">
  <div class="nav">
    <a href="/">Home</a>
    <a href="/docs">Docs</a>
    <a href="/try">Try Free</a>
    <a href="/buy-credits">Get API Key</a>
  </div>

  <h1>Security & Privacy</h1>
  <p class="sub">How AiPayGen protects your data, your payments, and your agents.</p>

  <div class="section">
    <h2><span class="icon">&#128274;</span> Encryption</h2>
    <ul>
      <li><span class="highlight">TLS 1.3</span> on all connections via Cloudflare — no plaintext traffic accepted</li>
      <li>HSTS enabled with <span class="highlight">preload</span> — browsers always use HTTPS</li>
      <li>API keys and credentials <span class="highlight">encrypted at rest</span> — never stored in plaintext</li>
      <li>Stripe handles all card data — we never see or store card numbers</li>
    </ul>
    <div class="badge-row">
      <span class="badge">HSTS Preload</span>
      <span class="badge">TLS 1.3</span>
      <span class="badge">X-Content-Type-Options: nosniff</span>
      <span class="badge">X-Frame-Options: DENY</span>
      <span class="badge">CSP Enforced</span>
      <span class="badge">Referrer-Policy: strict-origin</span>
    </div>
  </div>

  <div class="section">
    <h2><span class="icon">&#128065;</span> Data Handling — What We Store</h2>
    <p>We follow a <span class="highlight">zero-payload-retention</span> policy:</p>
    <ul>
      <li><span class="highlight">Request bodies</span> — NOT stored. Your prompts, text, and data are processed in memory and discarded.</li>
      <li><span class="highlight">Response bodies</span> — NOT stored. AI outputs are returned to you and not retained.</li>
      <li><span class="highlight">Billing metadata only</span> — we log: timestamp, endpoint called, token count (for metered billing), and API key ID. No content.</li>
      <li><span class="highlight">Agent memory</span> — stored only if you explicitly use /memory endpoints. You control it and can delete it anytime.</li>
      <li><span class="highlight">IP addresses</span> — used only for rate limiting, not sold or shared.</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128737;</span> Code Sandbox</h2>
    <p>When you use the <code>/code/run</code> endpoint, your code runs in a <span class="highlight">restricted sandbox</span>:</p>
    <ul>
      <li>AST-validated before execution — dangerous patterns rejected at parse time</li>
      <li><span class="highlight">No filesystem access</span> — os, sys, pathlib, shutil blocked</li>
      <li><span class="highlight">No network access</span> — socket, requests, urllib, httpx blocked</li>
      <li><span class="highlight">No process spawning</span> — subprocess, multiprocessing, threading blocked</li>
      <li>Blocked builtins: eval, exec, compile, open, __import__, getattr, setattr</li>
      <li>Execution timeout enforced — runaway code is killed</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128737;</span> SSRF Protection</h2>
    <p>All outbound HTTP requests (scraping, webhooks, API catalog) pass through SSRF validation:</p>
    <ul>
      <li>Private IP ranges blocked (10.x, 172.16-31.x, 192.168.x, 127.x, ::1)</li>
      <li>Link-local and metadata endpoints blocked (169.254.x, cloud metadata)</li>
      <li>DNS rebinding protection — resolved IPs checked against block list</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128176;</span> Payment Security</h2>
    <ul>
      <li><span class="highlight">Stripe</span> handles all card payments — PCI DSS compliant, we never touch card data</li>
      <li><span class="highlight">x402 USDC</span> payments verified on-chain via Coinbase facilitator on Base Mainnet</li>
      <li><span class="highlight">Automatic refund credits</span> — if a paid request returns a 5xx error, you get a refund credit automatically (returned in <code>X-Refund-Credit</code> header)</li>
      <li>API keys are <span class="highlight">revocable</span> — contact us to deactivate a compromised key</li>
      <li>Request correlation via <code>X-Request-ID</code> header on every response</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#129302;</span> For AI Agents</h2>
    <p>Machine-readable security signals are embedded in every interaction:</p>
    <ul>
      <li><code>/.well-known/agent.json</code> includes a <code>security</code> object with data handling policies</li>
      <li>Every <code>402</code> response includes <code>security</code> field confirming data retention policy</li>
      <li><code>/.well-known/security.txt</code> follows <a href="https://www.rfc-editor.org/rfc/rfc9116">RFC 9116</a></li>
      <li><code>X-Payment-Receipt</code> header confirms payment was processed</li>
      <li><code>X-Refund-Credit</code> header on 5xx after payment — automatic compensation</li>
    </ul>
    <div class="machine">
      <strong>Verify programmatically:</strong><br>
      <code>GET /.well-known/agent.json</code> → check <code>.security.data_handling.request_logging == "metadata_only"</code><br>
      <code>GET /.well-known/security.txt</code> → RFC 9116 security policy<br>
      <code>GET /security</code> → this page (HTML)
    </div>
  </div>

  <div class="section">
    <h2><span class="icon">&#9993;</span> Reporting Vulnerabilities</h2>
    <p>Found a security issue? Email <a href="mailto:hello@aipaygen.com">hello@aipaygen.com</a> with details. We take all reports seriously and will respond within 24 hours.</p>
  </div>
</div>
</body>
</html>""", 200, {"Content-Type": "text/html"}


@meta_bp.route("/sdk")
def sdk():
    """Copy-paste integration code for Python, JS, curl, and MCP."""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen SDK & Integration</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }
  .header { background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%); border-bottom: 1px solid #30363d; padding: 40px 24px; text-align: center; }
  .header h1 { font-size: 2rem; font-weight: 700; color: #58a6ff; margin-bottom: 8px; }
  .header p { color: #8b949e; font-size: 1.1rem; }
  .container { max-width: 900px; margin: 0 auto; padding: 40px 24px; }
  .section { margin-bottom: 48px; }
  .section h2 { font-size: 1.3rem; font-weight: 600; color: #f0f6fc; margin-bottom: 16px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 0; }
  .tab { padding: 8px 16px; border: 1px solid #30363d; border-bottom: none; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 0.875rem; color: #8b949e; background: #161b22; }
  .tab.active { background: #1a1f2e; color: #58a6ff; border-color: #388bfd; }
  pre { background: #161b22; border: 1px solid #30363d; border-radius: 0 6px 6px 6px; padding: 20px; overflow-x: auto; font-size: 0.85rem; line-height: 1.7; }
  code { font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace; }
  .comment { color: #8b949e; }
  .kw { color: #ff7b72; }
  .str { color: #a5d6ff; }
  .fn { color: #d2a8ff; }
  .num { color: #f2cc60; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-left: 8px; vertical-align: middle; }
  .free-badge { background: #1a4a1a; color: #3fb950; border: 1px solid #238636; }
  .paid-badge { background: #3d1f00; color: #ffa657; border: 1px solid #f0883e; }
  .note { background: #161b22; border: 1px solid #388bfd; border-left: 4px solid #388bfd; border-radius: 0 6px 6px 0; padding: 12px 16px; margin-bottom: 16px; font-size: 0.9rem; color: #79c0ff; }
  .endpoints-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin-top: 16px; }
  .endpoint-pill { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px 12px; font-size: 0.8rem; }
  .endpoint-pill code { color: #79c0ff; }
  .endpoint-pill .price { color: #f2cc60; float: right; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .link-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 24px; font-size: 0.9rem; }
</style>
</head>
<body>
<div style="max-width:900px;margin:0 auto;padding:16px 24px 0;display:flex;gap:16px;font-size:0.85rem"><a href="/" style="color:#8b949e;text-decoration:none">Home</a><a href="/docs" style="color:#8b949e;text-decoration:none">Docs</a><a href="/try" style="color:#8b949e;text-decoration:none">Try Free</a><a href="/buy-credits" style="color:#58a6ff;text-decoration:none;font-weight:600">Get API Key</a></div>
<div class="header">
  <h1>AiPayGen SDK</h1>
  <p>Copy-paste integration code for Python, JavaScript, curl, and MCP</p>
</div>
<div class="container">

  <div class="section">
    <div class="note">
      No API keys, no accounts. POST to any endpoint &rarr; receive HTTP 402 with payment instructions &rarr; retry with signed USDC payment header. Use <a href="/preview">/preview</a> to test free.
    </div>
  </div>

  <div class="section">
    <h2>curl <span class="badge free-badge">FREE — test first</span></h2>
    <pre><code><span class="comment"># Free preview — no payment needed</span>
curl https://api.aipaygen.com/preview?topic=bitcoin

<span class="comment"># Paid endpoint — will return 402 first</span>
curl -X POST https://api.aipaygen.com/research \\
  -H "Content-Type: application/json" \\
  -d \'{"topic": "quantum computing breakthroughs 2025"}\'

<span class="comment"># With x402 payment header (Base Mainnet USDC)</span>
curl -X POST https://api.aipaygen.com/research \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: &lt;signed-x402-tx&gt;" \\
  -d \'{"topic": "quantum computing breakthroughs 2025"}\'</code></pre>
  </div>

  <div class="section">
    <h2>Python <span class="badge paid-badge">x402-python</span></h2>
    <pre><code><span class="kw">pip install</span> x402-python anthropic

<span class="comment"># --- research.py ---</span>
<span class="kw">from</span> x402.client <span class="kw">import</span> <span class="fn">X402Client</span>
<span class="kw">from</span> eth_account <span class="kw">import</span> Account
<span class="kw">import</span> json

<span class="comment"># Your EVM wallet (Base Mainnet)</span>
account = Account.<span class="fn">from_key</span>(<span class="str">"YOUR_PRIVATE_KEY"</span>)
client = <span class="fn">X402Client</span>(account)

<span class="comment"># One call handles the 402 handshake automatically</span>
response = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygen.com/research"</span>,
    json={<span class="str">"topic"</span>: <span class="str">"quantum computing breakthroughs 2025"</span>}
)
data = response.<span class="fn">json</span>()
<span class="fn">print</span>(data[<span class="str">"summary"</span>])
<span class="fn">print</span>(data[<span class="str">"key_points"</span>])

<span class="comment"># --- batch.py (5 tasks, one payment at $0.10) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygen.com/batch"</span>,
    json={<span class="str">"operations"</span>: [
        {<span class="str">"endpoint"</span>: <span class="str">"research"</span>,  <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"AI agents 2025"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"summarize"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>, <span class="str">"length"</span>: <span class="str">"short"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"sentiment"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>}},
    ]}
).<span class="fn">json</span>()

<span class="comment"># --- pipeline.py (chain steps, pass output with {{prev}}) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygen.com/pipeline"</span>,
    json={<span class="str">"steps"</span>: [
        {<span class="str">"endpoint"</span>: <span class="str">"research"</span>,  <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"AI regulation EU 2025"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"summarize"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"{{prev}}"</span>, <span class="str">"length"</span>: <span class="str">"short"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"social"</span>,    <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"{{prev}}"</span>, <span class="str">"platforms"</span>: [<span class="str">"twitter"</span>]}},
    ]}
).<span class="fn">json</span>()</code></pre>
  </div>

  <div class="section">
    <h2>JavaScript / Node.js <span class="badge paid-badge">x402-fetch</span></h2>
    <pre><code><span class="kw">npm install</span> x402-fetch viem

<span class="comment">// research.mjs</span>
<span class="kw">import</span> { wrapFetchWithPayment } <span class="kw">from</span> <span class="str">"x402-fetch"</span>;
<span class="kw">import</span> { privateKeyToAccount } <span class="kw">from</span> <span class="str">"viem/accounts"</span>;
<span class="kw">import</span> { baseSepolia } <span class="kw">from</span> <span class="str">"viem/chains"</span>;

<span class="kw">const</span> account = <span class="fn">privateKeyToAccount</span>(<span class="str">"0xYOUR_PRIVATE_KEY"</span>);
<span class="kw">const</span> fetchWithPayment = <span class="fn">wrapFetchWithPayment</span>(fetch, account, baseSepolia);

<span class="kw">const</span> res = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygen.com/research"</span>, {
  method: <span class="str">"POST"</span>,
  headers: { <span class="str">"Content-Type"</span>: <span class="str">"application/json"</span> },
  body: <span class="fn">JSON.stringify</span>({ topic: <span class="str">"quantum computing 2025"</span> }),
});
<span class="kw">const</span> data = <span class="kw">await</span> res.<span class="fn">json</span>();
console.<span class="fn">log</span>(data.summary);

<span class="comment">// Generate social posts + translate in one pipeline call</span>
<span class="kw">const</span> pipeline = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygen.com/pipeline"</span>, {
  method: <span class="str">"POST"</span>,
  headers: { <span class="str">"Content-Type"</span>: <span class="str">"application/json"</span> },
  body: <span class="fn">JSON.stringify</span>({ steps: [
    { endpoint: <span class="str">"write"</span>,      input: { spec: <span class="str">"blog post about x402"</span>, type: <span class="str">"article"</span> } },
    { endpoint: <span class="str">"headline"</span>,   input: { content: <span class="str">"{{prev}}"</span>, count: <span class="num">5</span> } },
    { endpoint: <span class="str">"translate"</span>,  input: { text: <span class="str">"{{prev}}"</span>, language: <span class="str">"Spanish"</span> } },
  ]}),
});
<span class="kw">const</span> result = <span class="kw">await</span> pipeline.<span class="fn">json</span>();</code></pre>
  </div>

  <div class="section">
    <h2>MCP (Claude Desktop / Cursor / any MCP client)</h2>
    <pre><code><span class="comment"># Option 1 — Remote (no install, no API key needed by client)</span>
<span class="comment"># Add to your MCP client config:</span>
{
  <span class="str">"mcpServers"</span>: {
    <span class="str">"aipaygen"</span>: {
      <span class="str">"type"</span>: <span class="str">"streamable-http"</span>,
      <span class="str">"url"</span>: <span class="str">"https://mcp.aipaygen.com/mcp"</span>
    }
  }
}

<span class="comment"># Option 2 — Local via stdio (requires your own ANTHROPIC_API_KEY)</span>
pip install aipaygen-mcp

{
  <span class="str">"mcpServers"</span>: {
    <span class="str">"aipaygen"</span>: {
      <span class="str">"command"</span>: <span class="str">"aipaygen-mcp"</span>,
      <span class="str">"env"</span>: { <span class="str">"ANTHROPIC_API_KEY"</span>: <span class="str">"sk-ant-..."</span> }
    }
  }
}</code></pre>
  </div>

  <div class="section">
    <h2>Claude Agent (Anthropic SDK) <span class="badge paid-badge">Tool use</span></h2>
    <pre><code><span class="kw">pip install</span> anthropic x402-python

<span class="comment"># Give Claude the ability to call AiPayGen tools</span>
<span class="kw">import</span> anthropic, requests
<span class="kw">from</span> x402.client <span class="kw">import</span> X402Client
<span class="kw">from</span> eth_account <span class="kw">import</span> Account

x402 = X402Client(Account.<span class="fn">from_key</span>(<span class="str">"YOUR_PRIVATE_KEY"</span>))

<span class="kw">def</span> <span class="fn">call_aipaygen</span>(endpoint: str, payload: dict) -> dict:
    <span class="kw">return</span> x402.<span class="fn">post</span>(<span class="str">f"https://api.aipaygen.com/{endpoint}"</span>, json=payload).<span class="fn">json</span>()

client = anthropic.<span class="fn">Anthropic</span>()
tools = [{
    <span class="str">"name"</span>: <span class="str">"research"</span>,
    <span class="str">"description"</span>: <span class="str">"Research any topic. Returns summary, key points, and sources."</span>,
    <span class="str">"input_schema"</span>: {<span class="str">"type"</span>: <span class="str">"object"</span>, <span class="str">"properties"</span>: {<span class="str">"topic"</span>: {<span class="str">"type"</span>: <span class="str">"string"</span>}}, <span class="str">"required"</span>: [<span class="str">"topic"</span>]},
}]

<span class="comment"># Claude will autonomously call /research and use the result</span>
response = client.messages.<span class="fn">create</span>(
    model=<span class="str">"claude-sonnet-4-6"</span>, max_tokens=<span class="num">1024</span>, tools=tools,
    messages=[{<span class="str">"role"</span>: <span class="str">"user"</span>, <span class="str">"content"</span>: <span class="str">"Research the latest in fusion energy"</span>}]
)</code></pre>
  </div>

  <div class="section">
    <h2>Endpoints &amp; Pricing</h2>
    <div class="endpoints-grid">
      <div class="endpoint-pill"><code>/research</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/write</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/code</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/analyze</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/translate</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/summarize</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/social</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/extract</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/qa</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/classify</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/sentiment</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/keywords</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/compare</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/transform</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/chat</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/plan</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/decide</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/proofread</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/explain</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/questions</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/outline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/email</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/sql</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/regex</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/mock</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/score</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/timeline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/action</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/pitch</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/debate</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/headline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/fact</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/rewrite</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/tag</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/batch</code> <span class="price">$0.10</span></div>
      <div class="endpoint-pill"><code>/pipeline</code> <span class="price">$0.15</span></div>
      <div class="endpoint-pill"><code>/preview</code> <span class="price" style="color:#3fb950">FREE</span></div>
    </div>
  </div>

  <div class="link-row">
    <a href="/discover">Full manifest (JSON)</a>
    <a href="/openapi.json">OpenAPI spec</a>
    <a href="/preview">Free preview</a>
    <a href="https://mcp.aipaygen.com/mcp">MCP endpoint</a>
    <a href="https://pypi.org/project/aipaygen-mcp/">PyPI package</a>
    <a href="https://x402.org">x402 protocol</a>
  </div>

</div>
</body>
</html>'''
    from flask import Response, make_response
    resp = make_response(Response(html, mimetype="text/html"))
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ─── New AI Capability Endpoints ─────────────────────────────────────────────

def vision_inner(image_url, question="Describe this image in detail", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "url", "url": image_url}},
            {"type": "text", "text": question},
        ],
    }], max_tokens=1024)
    return {"image_url": image_url, "question": question, "analysis": r["text"], "model": r["model"]}


def rag_inner(documents, query, model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Documents:\n{documents}\n\n"
            f"Query: {query}\n\n"
            f'Return JSON: {{"answer": "str", "confidence": 0.0-1.0, '
            f'"citations": ["relevant quotes"], "cannot_answer": false}}'
        ),
    }], system="Answer using ONLY the provided documents. Never hallucinate. Cite specific document sections.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"answer": r["text"]}
    return {**parsed, "model": r["model"]}


def diagram_inner(description, diagram_type="flowchart", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Create a {diagram_type} Mermaid diagram for: {description}\n"
            f'Return JSON: {{"mermaid": "valid mermaid code block", "title": "str", "description": "str"}}'
        ),
    }], system="You generate valid Mermaid diagram syntax. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"mermaid": r["text"]}
    return {**parsed, "model": r["model"]}


def json_schema_inner(description, example="", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": f"Generate JSON Schema for: {description}\nExample data: {example}\nReturn the complete JSON Schema object.",
    }], system="You are a JSON Schema expert. Generate valid JSON Schema draft-07. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"schema": r["text"]}
    return {**parsed, "model": r["model"]}


def test_cases_inner(code_or_description, language="python", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Generate comprehensive test cases for:\n{code_or_description}\n"
            f'Return JSON: {{"test_cases": [{{"name": "str", "input": "str", "expected": "str", "edge_case": true}}], '
            f'"coverage_notes": "str", "suggested_framework": "str"}}'
        ),
    }], system=f"You are a {language} testing expert. Always respond with valid JSON only.", max_tokens=1500)
    parsed = parse_json_from_claude(r["text"]) or {"test_cases": r["text"]}
    return {**parsed, "model": r["model"]}


def workflow_inner(goal, available_data="", model="claude-sonnet"):
    r = call_model(model, [{"role": "user", "content": f"Goal: {goal}\n\nAvailable data:\n{available_data}"}],
        system="You are an autonomous agent. Break complex goals into sub-tasks, reason through each, and produce a comprehensive final answer. Show your reasoning, then give a clean result.",
        max_tokens=4096)
    return {"goal": goal, "result": r["text"], "model": r["model"]}


@meta_bp.route("/vision", methods=["POST"])

@meta_bp.route("/sdk/code", methods=["GET"])
def sdk_code():
    """Return copy-paste SDK code in Python, JavaScript, or cURL as JSON."""
    lang = request.args.get("lang", "python").lower()
    endpoint = request.args.get("endpoint", "/research")
    base_url = "https://api.aipaygen.com"

    if lang in ("python", "py"):
        code = f'''import requests

# AiPayGen Python SDK — copy-paste ready
# More endpoints: {base_url}/discover

def call_aipaygen(endpoint: str, payload: dict, x402_token: str = None) -> dict:
    """Call any AiPayGen endpoint. x402_token required for paid endpoints."""
    headers = {{"Content-Type": "application/json"}}
    if x402_token:
        headers["X-Payment"] = x402_token
    resp = requests.post(f"{base_url}{{endpoint}}", json=payload, headers=headers)
    if resp.status_code == 402:
        payment_info = resp.json()
        raise ValueError(f"Payment required: {{payment_info}}")
    resp.raise_for_status()
    return resp.json()

# Example: research
result = call_aipaygen("{endpoint}", {{"query": "latest AI agent frameworks 2026"}})
print(result["result"])

# Free endpoints (no payment needed)
import requests
print(requests.get("{base_url}/free/time").json())     # UTC time
print(requests.get("{base_url}/free/uuid").json())     # UUID
print(requests.get("{base_url}/free/ip").json())       # Your IP
print(requests.get("{base_url}/catalog").json())       # API catalog
'''
    elif lang in ("javascript", "js", "typescript", "ts"):
        code = f'''// AiPayGen JavaScript SDK — copy-paste ready
// More endpoints: {base_url}/discover

const BASE = "{base_url}";

async function callAiPayGen(endpoint, payload, x402Token = null) {{
  const headers = {{ "Content-Type": "application/json" }};
  if (x402Token) headers["X-Payment"] = x402Token;
  const res = await fetch(`${{BASE}}${{endpoint}}`, {{
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  }});
  if (res.status === 402) {{
    const info = await res.json();
    throw new Error(`Payment required: ${{JSON.stringify(info)}}`);
  }}
  if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
  return res.json();
}}

// Example: research
const result = await callAiPayGen("{endpoint}", {{ query: "latest AI agent frameworks 2026" }});
console.log(result.result);

// Free endpoints (no payment needed)
const time = await fetch(`${{BASE}}/free/time`).then(r => r.json());
const catalog = await fetch(`${{BASE}}/catalog`).then(r => r.json());
console.log(time, catalog);
'''
    elif lang in ("curl", "bash", "sh"):
        code = f'''#!/bin/bash
# AiPayGen cURL examples — copy-paste ready
BASE="{base_url}"

# Free endpoints
curl "$BASE/free/time"
curl "$BASE/free/uuid"
curl "$BASE/catalog?min_score=7"

# Paid endpoints (replace X_PAYMENT with valid x402 token)
curl -X POST "$BASE{endpoint}" \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: $X_PAYMENT" \\
  -d \'{{"query": "latest AI agent frameworks 2026"}}\'

# List all 153 endpoints
curl "$BASE/discover" | python3 -m json.tool
'''
    else:
        return jsonify({"error": f"Unknown lang '{lang}'. Use: python, javascript, curl"}), 400

    return jsonify({
        "lang": lang,
        "endpoint": endpoint,
        "code": code,
        "base_url": base_url,
        "docs": f"{base_url}/discover",
        "_meta": {"free": True}
    })


@meta_bp.route("/sitemap.xml", methods=["GET"])

@meta_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """XML sitemap — includes static pages AND all blog posts for Google/Bing."""
    base_url = "https://api.aipaygen.com"
    now = datetime.utcnow().strftime("%Y-%m-%d")
    static_pages = [
        ("/", "daily", "1.0"),
        ("/discover", "weekly", "0.9"),
        ("/docs", "weekly", "0.9"),
        ("/security", "monthly", "0.7"),
        ("/preview", "weekly", "0.7"),
        ("/openapi.json", "weekly", "0.6"),
        ("/llms.txt", "weekly", "0.6"),
        ("/health", "hourly", "0.3"),
    ]
    urls_xml = "\n".join(
        f'  <url><loc>{base_url}{p}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority><lastmod>{now}</lastmod></url>'
        for p, freq, pri in static_pages
    )
    # Add all blog posts with their actual generation date
    try:
        for post in list_blog_posts():
            slug = post["slug"]
            date = post.get("generated_at", now)[:10]
            urls_xml += f'\n  <url><loc>{base_url}/blog/{slug}</loc><changefreq>monthly</changefreq><priority>0.8</priority><lastmod>{date}</lastmod></url>'
    except Exception:
        pass
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
{urls_xml}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml"}


# ── Interactive Try Page ─────────────────────────────────────────────────────

_TRY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Try AiPayGen — Free Interactive Demo</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; padding: 32px 16px; }
  .wrap { max-width: 680px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .sub { color: #888; font-size: 0.88rem; margin-bottom: 24px; }
  .sub a { color: #818cf8; }

  .demo-card { background: #141414; border: 1px solid #2a2a2a; border-radius: 14px; padding: 28px; margin-bottom: 16px; }
  .tool-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
  .tool-btn { background: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 8px 14px; color: #aaa; font-size: 0.82rem; cursor: pointer; transition: all 0.15s; }
  .tool-btn:hover, .tool-btn.active { background: #1a1a3e; border-color: #6366f1; color: #c4b5fd; }
  .tool-desc { font-size: 0.8rem; color: #666; margin-bottom: 14px; min-height: 20px; }

  textarea { width: 100%; background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; padding: 14px; color: #e8e8e8; font-size: 0.9rem; resize: vertical; min-height: 80px; outline: none; font-family: inherit; }
  textarea:focus { border-color: #6366f1; }
  textarea::placeholder { color: #444; }

  .run-btn { margin-top: 14px; background: #059669; color: #fff; border: none; border-radius: 10px; padding: 12px 28px; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .run-btn:hover { background: #047857; }
  .run-btn:disabled { background: #333; color: #666; cursor: wait; }

  .result-box { margin-top: 16px; background: #0d0d0d; border: 1px solid #222; border-radius: 10px; padding: 16px; font-size: 0.85rem; line-height: 1.6; white-space: pre-wrap; word-break: break-word; display: none; max-height: 400px; overflow-y: auto; }
  .result-box.show { display: block; }

  .curl-wrap { margin-top: 12px; display: none; }
  .curl-wrap.show { display: block; }
  .curl-box { background: #111; border: 1px solid #2a2a2a; border-radius: 8px; padding: 12px; font-size: 0.75rem; font-family: 'SF Mono', 'Fira Code', monospace; color: #8b8; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto; }
  .copy-curl-btn { margin-top: 6px; background: #1e1e1e; border: 1px solid #333; border-radius: 6px; padding: 6px 14px; color: #aaa; font-size: 0.75rem; cursor: pointer; transition: all 0.15s; }
  .copy-curl-btn:hover { background: #1a1a3e; border-color: #6366f1; color: #c4b5fd; }

  .cta { text-align: center; margin-top: 24px; }
  .cta a { display: inline-block; background: #6366f1; color: #fff; text-decoration: none; padding: 12px 28px; border-radius: 10px; font-weight: 600; font-size: 0.95rem; }
  .cta p { color: #555; font-size: 0.78rem; margin-top: 8px; }

  .free-note { text-align: center; color: #555; font-size: 0.75rem; margin-top: 12px; }

  /* Upsell modal */
  .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.75); z-index: 100; align-items: center; justify-content: center; padding: 16px; }
  .modal-overlay.show { display: flex; }
  .modal { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 32px; max-width: 480px; width: 100%; position: relative; }
  .modal-close { position: absolute; top: 12px; right: 16px; background: none; border: none; color: #666; font-size: 1.4rem; cursor: pointer; }
  .modal-close:hover { color: #fff; }
  .modal h2 { font-size: 1.3rem; margin-bottom: 6px; }
  .modal .modal-sub { color: #888; font-size: 0.85rem; margin-bottom: 20px; }
  .modal-plans { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }
  .modal-plan { display: flex; align-items: center; justify-content: space-between; background: #1a1a1a; border: 2px solid #2a2a2a; border-radius: 10px; padding: 14px 16px; cursor: pointer; transition: all 0.15s; }
  .modal-plan:hover, .modal-plan.selected { border-color: #6366f1; background: #1a1a2e; }
  .modal-plan .mp-left { display: flex; align-items: center; gap: 12px; }
  .modal-plan .mp-amount { font-size: 1.3rem; font-weight: 800; color: #fff; min-width: 40px; }
  .modal-plan .mp-detail { font-size: 0.8rem; color: #888; }
  .modal-plan .mp-tag { font-size: 0.7rem; background: #6366f1; color: #fff; padding: 2px 8px; border-radius: 12px; }
  .modal-plan .mp-tag.gold { background: #f59e0b; }
  .modal-plan .mp-tag.green { background: #059669; }
  .modal-btn { width: 100%; background: #6366f1; color: #fff; border: none; border-radius: 10px; padding: 14px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .modal-btn:hover { background: #4f52d0; }
  .modal-btn:disabled { background: #333; color: #666; cursor: not-allowed; }
  .modal-or { text-align: center; color: #555; font-size: 0.78rem; margin-top: 12px; }
  .modal-or a { color: #818cf8; }
  @media (max-width: 500px) { .modal { padding: 24px 18px; } }
</style>
</head>
<body>
<div class="wrap">
  <div style="display:flex;gap:16px;margin-bottom:20px;font-size:0.85rem"><a href="/" style="color:#888;text-decoration:none">Home</a><a href="/docs" style="color:#888;text-decoration:none">Docs</a><a href="/buy-credits" style="color:#818cf8;text-decoration:none;font-weight:600">Get API Key</a></div>
  <h1>Try AiPayGen</h1>
  <p class="sub">Test any tool below — completely free, no sign-up. <a href="/discover">See all 155 tools &rarr;</a></p>

  <div class="demo-card">
    <div class="tool-row">
      <div class="tool-btn active" data-tool="sentiment" data-placeholder="Type any text to analyze sentiment..." data-desc="Detects polarity, emotions, confidence, and key phrases">Sentiment</div>
      <div class="tool-btn" data-tool="summarize" data-placeholder="Paste text to summarize..." data-desc="Condenses long text into key bullet points">Summarize</div>
      <div class="tool-btn" data-tool="translate" data-placeholder="Text to translate..." data-desc="Translates text to any language (add target language on second line)">Translate</div>
      <div class="tool-btn" data-tool="keywords" data-placeholder="Paste text to extract keywords..." data-desc="Extracts topics, entities, and key phrases">Keywords</div>
      <div class="tool-btn" data-tool="explain" data-placeholder="Enter a concept to explain..." data-desc="Explains any concept in simple terms with analogies">Explain</div>
      <div class="tool-btn" data-tool="code" data-placeholder="Describe what code to generate..." data-desc="Generates code in any language from a description">Code</div>
      <div class="tool-btn" data-tool="research" data-placeholder="Enter a topic to research..." data-desc="Researches any topic with key points and sources">Research</div>
      <div class="tool-btn" data-tool="analyze" data-placeholder="Paste content to analyze (add question on second line)..." data-desc="Analyzes content with findings, sentiment, and confidence">Analyze</div>
      <div class="tool-btn" data-tool="compare" data-placeholder="Enter two items separated by a blank line..." data-desc="Compares two texts with similarities, differences, and scores">Compare</div>
      <div class="tool-btn" data-tool="extract" data-placeholder="Paste text, then what to extract on second line..." data-desc="Extracts structured data, entities, and facts from text">Extract</div>
      <div class="tool-btn" data-tool="questions" data-placeholder="Enter a topic to generate questions about..." data-desc="Generates FAQ, interview, or quiz questions from content">Questions</div>
      <div class="tool-btn" data-tool="decide" data-placeholder="Describe a decision (options on second line, comma-separated)..." data-desc="Analyzes decisions with pros, cons, risks, and recommendations">Decide</div>
      <div class="tool-btn" data-tool="classify" data-placeholder="Text to classify (categories on second line, comma-separated)..." data-desc="Classifies text into custom categories with confidence scores">Classify</div>
      <div class="tool-btn" data-tool="rewrite" data-placeholder="Text to rewrite (style/audience on second line)..." data-desc="Rewrites text for a different audience or tone">Rewrite</div>
      <div class="tool-btn" data-tool="headline" data-placeholder="Enter content to generate headlines for..." data-desc="Generates engaging headlines and titles for any content">Headline</div>
      <div class="tool-btn" data-tool="geocode" data-placeholder="Enter an address or place name..." data-desc="Geocodes addresses to lat/lon coordinates via OpenStreetMap">Geocode</div>
      <div class="tool-btn" data-tool="math-eval" data-placeholder="Enter a math expression (e.g. 2^10 + sqrt(144))..." data-desc="Evaluates math expressions safely using AST parsing">Math Eval</div>
      <div class="tool-btn" data-tool="unit-convert" data-placeholder="Enter: value, from_unit, to_unit (e.g. 100, km, mi)..." data-desc="Converts units — length, weight, volume, speed, data, temperature">Unit Convert</div>
      <div class="tool-btn" data-tool="readability" data-placeholder="Paste text to score readability..." data-desc="Flesch-Kincaid readability score with grade level and difficulty">Readability</div>
      <div class="tool-btn" data-tool="language-detect" data-placeholder="Type or paste text in any language..." data-desc="Detects language and script from text using character analysis">Language</div>
      <div class="tool-btn" data-tool="whois" data-placeholder="Enter a domain name (e.g. example.com)..." data-desc="WHOIS/RDAP lookup — registrar, nameservers, status, dates">WHOIS</div>
      <div class="tool-btn" data-tool="security-headers" data-placeholder="Enter a URL to audit (e.g. https://example.com)..." data-desc="Audits security headers and assigns A+ to F grade">Sec Headers</div>
      <div class="tool-btn" data-tool="currency-convert" data-placeholder="Enter: amount, from, to (e.g. 100, USD, EUR)..." data-desc="Converts currencies using live exchange rates (150+ currencies)">Currency</div>
      <div class="tool-btn" data-tool="stats" data-placeholder="Enter numbers separated by commas (e.g. 10, 20, 30, 40, 50)..." data-desc="Statistical analysis — mean, median, std dev, quartiles">Stats</div>
    </div>
    <p class="tool-desc" id="desc">Detects polarity, emotions, confidence, and key phrases</p>
    <textarea id="input" placeholder="Type any text to analyze sentiment..."></textarea>
    <button class="run-btn" id="run" onclick="runTool()">&#9654; Run</button>
    <div class="result-box" id="result"></div>
    <div class="curl-wrap" id="curl-wrap">
      <div class="curl-box" id="curl-cmd"></div>
      <button class="copy-curl-btn" id="copy-curl" onclick="copyCurl()">Copy as curl</button>
    </div>
  </div>

  <div class="cta">
    <a href="/buy-credits">Get API Key — From $1</a>
    <p>155 tools &middot; 15 AI models &middot; Credits never expire</p>
  </div>
  <p class="free-note">Free demo uses the same AI models as paid API. Limited to 10 demos per session.</p>
</div>

<!-- Upsell modal -->
<div class="modal-overlay" id="upsell-modal">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">&times;</button>
    <h2>You've used all 10 free demos</h2>
    <p class="modal-sub">Pick a plan to unlock unlimited access to all 155 tools.</p>
    <div class="modal-plans">
      <div class="modal-plan" data-amt="1" onclick="selectModalPlan(this)">
        <div class="mp-left"><span class="mp-amount">$1</span><span class="mp-detail">~160 calls</span></div>
        <span class="mp-tag gold">Starter</span>
      </div>
      <div class="modal-plan selected" data-amt="5" onclick="selectModalPlan(this)">
        <div class="mp-left"><span class="mp-amount">$5</span><span class="mp-detail">~830 calls</span></div>
      </div>
      <div class="modal-plan" data-amt="20" onclick="selectModalPlan(this)">
        <div class="mp-left"><span class="mp-amount">$20</span><span class="mp-detail">~4,000 calls</span></div>
        <span class="mp-tag">Popular</span>
      </div>
      <div class="modal-plan" data-amt="50" onclick="selectModalPlan(this)">
        <div class="mp-left"><span class="mp-amount">$50</span><span class="mp-detail">~12,500 calls</span></div>
        <span class="mp-tag green">Best value</span>
      </div>
    </div>
    <button class="modal-btn" id="modal-buy" onclick="modalCheckout()">Get API Key</button>
    <p class="modal-or">or <a href="/buy-credits">view full pricing page</a></p>
  </div>
</div>
<script>
let currentTool = 'sentiment';
let demoCount = 0;
const MAX_DEMOS = 10;
let lastCurl = '';

document.querySelectorAll('.tool-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTool = btn.dataset.tool;
    document.getElementById('input').placeholder = btn.dataset.placeholder;
    document.getElementById('desc').textContent = btn.dataset.desc;
  });
});

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.textContent;
}

let modalAmount = 5;
function selectModalPlan(el) {
  document.querySelectorAll('.modal-plan').forEach(p => p.classList.remove('selected'));
  el.classList.add('selected');
  modalAmount = parseInt(el.dataset.amt);
}
function showModal() { document.getElementById('upsell-modal').classList.add('show'); }
function closeModal() { document.getElementById('upsell-modal').classList.remove('show'); }
async function modalCheckout() {
  const btn = document.getElementById('modal-buy');
  btn.disabled = true; btn.textContent = 'Redirecting to Stripe...';
  try {
    const res = await fetch('/stripe/create-checkout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ amount: modalAmount })
    });
    const data = await res.json();
    if (data.url) { window.location.href = data.url; }
    else { btn.disabled = false; btn.textContent = 'Get API Key'; alert(data.error || 'Something went wrong'); }
  } catch(e) { btn.disabled = false; btn.textContent = 'Get API Key'; alert('Network error — try again'); }
}
document.getElementById('upsell-modal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });

async function runTool() {
  const input = document.getElementById('input').value.trim();
  if (!input) return;
  const box = document.getElementById('result');
  if (demoCount >= MAX_DEMOS) {
    showModal();
    return;
  }
  const btn = document.getElementById('run');
  btn.disabled = true; btn.textContent = 'Running...';
  box.className = 'result-box'; box.textContent = '';
  try {
    const body = {};
    if (currentTool === 'sentiment') body.text = input;
    else if (currentTool === 'summarize') { body.text = input; body.format = 'bullets'; }
    else if (currentTool === 'translate') {
      const lines = input.split('\\n');
      body.text = lines[0]; body.language = lines[1] || 'Spanish';
    }
    else if (currentTool === 'keywords') body.text = input;
    else if (currentTool === 'explain') { body.concept = input; body.level = 'beginner'; }
    else if (currentTool === 'code') { body.description = input; body.language = 'python'; }
    else if (currentTool === 'research') body.topic = input;
    else if (currentTool === 'analyze') {
      const lines = input.split('\\n');
      body.content = lines[0]; body.question = lines.slice(1).join(' ') || 'general analysis';
    }
    else if (currentTool === 'compare') {
      const parts = input.split('\\n\\n');
      body.text_a = parts[0] || ''; body.text_b = parts.slice(1).join('\\n\\n') || '';
    }
    else if (currentTool === 'extract') {
      const lines = input.split('\\n');
      body.text = lines[0]; body.schema_desc = lines.slice(1).join(' ') || '';
    }
    else if (currentTool === 'questions') body.content = input;
    else if (currentTool === 'decide') {
      const lines = input.split('\\n');
      body.decision = lines[0]; if (lines[1]) body.options = lines[1].split(',').map(s => s.trim());
    }
    else if (currentTool === 'classify') {
      const lines = input.split('\\n');
      body.text = lines[0]; body.categories = (lines[1] || 'positive,negative,neutral').split(',').map(s => s.trim());
    }
    else if (currentTool === 'rewrite') {
      const lines = input.split('\\n');
      body.text = lines[0]; body.audience = lines[1] || 'general';
    }
    else if (currentTool === 'headline') body.content = input;
    else if (currentTool === 'geocode') body.q = input;
    else if (currentTool === 'math-eval') body.expression = input;
    else if (currentTool === 'unit-convert') {
      const p = input.split(',').map(s => s.trim());
      body.value = parseFloat(p[0]) || 0; body.from_unit = p[1] || ''; body.to_unit = p[2] || '';
    }
    else if (currentTool === 'readability') body.text = input;
    else if (currentTool === 'language-detect') body.text = input;
    else if (currentTool === 'whois') body.domain = input;
    else if (currentTool === 'security-headers') body.url = input;
    else if (currentTool === 'currency-convert') {
      const p = input.split(',').map(s => s.trim());
      body.amount = parseFloat(p[0]) || 1; body.from = p[1] || 'USD'; body.to = p[2] || 'EUR';
    }
    else if (currentTool === 'stats') body.numbers = input.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n));

    const res = await fetch('/try/' + currentTool, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (res.status === 429) { showModal(); btn.disabled = false; btn.textContent = '\\u25B6 Run'; return; }
    demoCount++;
    const output = typeof data.result === 'string' ? data.result : JSON.stringify(data.result || data, null, 2);
    const remaining = MAX_DEMOS - demoCount;
    if (remaining === 0) {
      box.textContent = output;
      box.className = 'result-box show';
      setTimeout(showModal, 1500);
    } else {
      box.textContent = output + '\\n\\n--- ' + remaining + ' free demo' + (remaining !== 1 ? 's' : '') + ' remaining';
      box.className = 'result-box show';
    }
    // Build curl command
    const curlBody = JSON.stringify(body);
    lastCurl = "curl -X POST https://api.aipaygen.com/" + currentTool + " \\\\\\n  -H 'Content-Type: application/json' \\\\\\n  -H 'Authorization: Bearer YOUR_API_KEY' \\\\\\n  -d '" + curlBody.replace(/'/g, "'\\\\''") + "'";
    const curlEl = document.getElementById('curl-cmd');
    curlEl.textContent = lastCurl;
    document.getElementById('curl-wrap').className = 'curl-wrap show';
    document.getElementById('copy-curl').textContent = 'Copy as curl';
  } catch(e) {
    box.textContent = 'Error: ' + e.message;
    box.className = 'result-box show';
    document.getElementById('curl-wrap').className = 'curl-wrap';
  }
  btn.disabled = false; btn.textContent = '\\u25B6 Run';
}

function copyCurl() {
  navigator.clipboard.writeText(lastCurl).then(() => {
    document.getElementById('copy-curl').textContent = 'Copied!';
    setTimeout(() => { document.getElementById('copy-curl').textContent = 'Copy as curl'; }, 2000);
  });
}
</script>
</body>
</html>"""


@meta_bp.route("/try", methods=["GET"])
def try_page():
    return _TRY_PAGE, 200, {"Content-Type": "text/html"}


# Per-IP demo rate limiter (10 per 10 minutes)
_demo_usage = {}

def _check_demo_limit(ip):
    now = _time.time()
    key = f"demo:{ip}"
    entries = _demo_usage.get(key, [])
    entries = [t for t in entries if now - t < 600]
    if len(entries) >= 10:
        return False
    entries.append(now)
    _demo_usage[key] = entries
    return True


@meta_bp.route("/try/<tool>", methods=["POST"])
def try_tool(tool):
    from routes.ai_tools import (
        sentiment_inner, summarize_inner, translate_inner,
        keywords_inner, explain_inner, code_inner,
        research_inner, analyze_inner, compare_inner,
        extract_inner, questions_inner, decide_inner,
        classify_inner, rewrite_inner, headline_inner,
    )
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown")
    if not _check_demo_limit(ip):
        return jsonify({"error": "Demo limit reached (10 per 10 minutes)", "upgrade": "/buy-credits"}), 429

    data = request.get_json() or {}
    try:
        if tool == "sentiment":
            result = sentiment_inner(data.get("text", "")[:500])
        elif tool == "summarize":
            result = summarize_inner(data.get("text", "")[:2000], data.get("format", "bullets"))
        elif tool == "translate":
            result = translate_inner(data.get("text", "")[:500], data.get("language", "Spanish"))
        elif tool == "keywords":
            result = keywords_inner(data.get("text", "")[:1000])
        elif tool == "explain":
            result = explain_inner(data.get("concept", "")[:200])
        elif tool == "code":
            result = code_inner(data.get("description", "")[:300], data.get("language", "python"))
        elif tool == "research":
            result = research_inner(data.get("topic", "")[:300])
        elif tool == "analyze":
            result = analyze_inner(data.get("content", "")[:2000], data.get("question", "general analysis")[:300])
        elif tool == "compare":
            result = compare_inner(data.get("text_a", "")[:1000], data.get("text_b", "")[:1000])
        elif tool == "extract":
            result = extract_inner(data.get("text", "")[:2000], data.get("schema_desc", ""), data.get("fields", []))
        elif tool == "questions":
            result = questions_inner(data.get("content", "")[:2000])
        elif tool == "decide":
            result = decide_inner(data.get("decision", "")[:500], data.get("options", None))
        elif tool == "classify":
            result = classify_inner(data.get("text", "")[:1000], data.get("categories", []))
        elif tool == "rewrite":
            result = rewrite_inner(data.get("text", "")[:2000], data.get("audience", "general")[:100])
        elif tool == "headline":
            result = headline_inner(data.get("content", "")[:1000])
        elif tool == "geocode":
            r = _requests.get("http://127.0.0.1:5001/data/geocode", params={"q": data.get("q", "")[:200]}, timeout=10)
            result = r.json()
        elif tool == "math-eval":
            r = _requests.post("http://127.0.0.1:5001/data/math/eval", json={"expression": data.get("expression", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "unit-convert":
            r = _requests.get("http://127.0.0.1:5001/data/math/convert", params={"value": data.get("value", 0), "from": data.get("from_unit", ""), "to": data.get("to_unit", "")}, timeout=10)
            result = r.json()
        elif tool == "readability":
            r = _requests.post("http://127.0.0.1:5001/data/readability", json={"text": data.get("text", "")[:2000]}, timeout=10)
            result = r.json()
        elif tool == "language-detect":
            r = _requests.get("http://127.0.0.1:5001/data/language", params={"text": data.get("text", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "whois":
            r = _requests.get("http://127.0.0.1:5001/data/whois", params={"domain": data.get("domain", "")[:100]}, timeout=10)
            result = r.json()
        elif tool == "security-headers":
            r = _requests.get("http://127.0.0.1:5001/data/security/headers", params={"url": data.get("url", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "currency-convert":
            r = _requests.get("http://127.0.0.1:5001/data/finance/convert", params={"amount": data.get("amount", 1), "from": data.get("from", "USD"), "to": data.get("to", "EUR")}, timeout=10)
            result = r.json()
        elif tool == "stats":
            r = _requests.post("http://127.0.0.1:5001/data/math/stats", json={"numbers": data.get("numbers", [])}, timeout=10)
            result = r.json()
        else:
            return jsonify({"error": f"Unknown demo tool: {tool}"}), 400
        funnel_log_event("demo_used", endpoint=f"/try/{tool}", ip=ip)
        return jsonify({"result": result, "tool": tool, "_meta": {"free_demo": True, "upgrade": "/buy-credits"}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

