# r/LocalLLaMA Post

**Title:** I built 65+ AI tools as an MCP server you can pip install into Claude Code — runs on my Pi 5

**Body:**

Hey everyone. I've been working on this for a few months and figured it's far enough along to share.

**What it is:** An MCP server called AiPayGen that exposes 65+ tools — research, summarize, translate, code generation, web scraping (Twitter, YouTube, Google Maps, Instagram, TikTok), RAG, vision, agent memory, workflow orchestration, and a bunch of utility stuff. You install it and your LLM client gets access to all of them.

**Setup is two commands:**

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

After that, Claude Code can call any of the 65+ tools directly. There's also a remote MCP endpoint if you don't want to install anything: `https://mcp.aipaygen.com/mcp`

**For Cursor/Cline users**, add this to your MCP config:

```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "aipaygen-mcp"
    }
  }
}
```

**What the tools actually do:**

- **AI tools (40+):** research, write, summarize, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, outline, keywords, etc. These route to 15 models across 7 providers (Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama) depending on the task.
- **Web scraping:** Google Maps, Twitter/X, Instagram, TikTok, YouTube, generic websites
- **Agent infra:** persistent memory (store/recall/search), agent-to-agent messaging, task boards, knowledge base, a catalog of 4100+ APIs you can invoke
- **Free data feeds:** weather, crypto prices, exchange rates, holidays — no key needed

**The Pi 5 part:** The whole backend runs on a Raspberry Pi 5 overclocked to 2.7GHz with an NVMe SSD, behind a Cloudflare tunnel. Flask app, SQLite for metadata, Redis for caching. It handles production traffic fine — the AI calls are proxied to upstream providers, so the Pi just needs to manage routing and billing.

**Pricing:** $0.006 per AI call. No subscription. You get $0.10 free credits when you generate a key (about 16 calls). There are also free tools that need no key at all:

```bash
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=Tokyo"
curl "https://api.aipaygen.com/data/crypto?symbols=bitcoin"
```

**REST API works too** if you're not using MCP:

```bash
curl -X POST https://api.aipaygen.com/summarize \
  -H "Authorization: Bearer apk_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your long text here", "length": "short"}'
```

**One thing I'm genuinely curious about:** x402 micropayments. I integrated the x402 protocol so you can pay per API call with USDC on Base, Solana, or Stellar. No signup, no API key — the payment happens in the HTTP headers. It works, but adoption is still early. Anyone here experimented with x402 or crypto micropayments for API billing?

**Limitations I'll be upfront about:**
- The AI tools call upstream APIs (OpenAI, Anthropic, etc.) — this isn't running models locally on the Pi
- Scraping tools use Apify under the hood, so they break when platforms change their markup
- It's a solo project so support is basically me responding on GitHub

Would love feedback, especially on the tool selection and pricing. What tools would you actually use? What's missing?

GitHub: https://github.com/Damien829/aipaygen
Docs: https://aipaygen.com/docs
PyPI: https://pypi.org/project/aipaygen-mcp/
