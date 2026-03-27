# HackerNews Show HN — 3 Versions

## RECOMMENDED: Version 1 (Technical/MCP-focused)

**Title:** Show HN: AiPayGen – 65+ AI tools as a single MCP server, one pip install

**First comment:**

Hey HN, I built AiPayGen — an MCP server that bundles 65+ AI tools (research, code, scrape, RAG, vision, diagrams, sentiment analysis, translation, etc.) into a single package. You run `pip install aipaygen`, add it to your MCP config, and every tool is available in Claude Code, Cursor, Cline, or any MCP client.

Quick setup:
```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "uvx",
      "args": ["aipaygen"]
    }
  }
}
```

That's it. No juggling a dozen API keys for different services. One key, one server, 65+ tools.

It also works as a plain REST API if you're not in the MCP ecosystem yet.

Pricing is pay-per-call starting at $0.006. No subscriptions. $0.10 free credits, no card required.

Some backstory HN might appreciate: the entire thing runs on a Raspberry Pi 5 with an NVMe SSD, overclocked to 2.7GHz. I'm a solo developer. The Pi has been the production server from day one. It forces you to write efficient code when your ceiling is 8GB of RAM.

Happy to answer questions about the architecture, MCP protocol, or why I'm running production on an ARM SBC.

Site: https://aipaygen.com

### Follow-up answers:

**Q: "Why not just call the APIs directly?"**
Fair question. You absolutely can. The value is in not having to. If you want web scraping, you need a scraping service. RAG? Vector DB. Vision? Another API. Each has its own auth, billing, rate limits. AiPayGen collapses that into one credential. For agents that dynamically pick from a dozen capabilities, that matters.

**Q: "How does this compare to OpenRouter?"**
Different layer. OpenRouter routes LLM inference. AiPayGen is a tool layer — it gives models tools to call. The difference between "talk to GPT-4" and "give GPT-4 the ability to scrape a website, generate a diagram, and search Google Maps." Complementary, not competing.

**Q: "Running production on a Pi 5? How does that scale?"**
Most heavy compute is offloaded to external services — the Pi orchestrates, not crunches. If traffic outgrows it, I'll move to a VPS. But near-zero infra cost means I can price tools at $0.006/call and sustain it solo.

---

**Posting tips:**
- Tuesday-Thursday, 8-10 AM Pacific
- Post first comment within 5 minutes
- Respond to every comment for 2 hours
- Be technical, honest, humble
- Never ask for upvotes
