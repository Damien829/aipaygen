# r/SideProject Post

**Title:** Solo dev, $0 marketing budget, running production off a Raspberry Pi 5 — here's my AI tools platform after 4 months

**Body:**

I want to be honest about this from the start: I have no idea if this will work as a business. But I've learned more building it than anything else I've done, so I figured I'd share the journey.

**What I built:** AiPayGen — an MCP server with 65+ AI tools that plugs into Claude Code, Cursor, and other AI coding assistants. Research, summarize, translate, web scraping, agent memory, workflows. You install it with `pip install aipaygen-mcp` and your AI assistant gets access to everything.

**The setup that would make any investor run:**

My entire production infrastructure is a Raspberry Pi 5 sitting on my desk, overclocked to 2.7GHz, with an NVMe SSD, running behind a Cloudflare tunnel. Flask app. SQLite database. That's it.

When I tell people this, the first question is always "but can it handle traffic?" Honestly? The Pi doesn't do the heavy lifting — AI calls get routed to upstream providers (OpenAI, Anthropic, Google, etc.), so the Pi just handles routing, auth, billing, and serving the MCP endpoints. It works. The bottleneck is never the Pi.

Total infrastructure cost: ~$120 for the Pi + case + NVMe. Monthly: electricity and Cloudflare (free tier).

**What the last 4 months looked like:**

- Month 1: Got the basic Flask app running, first 10 tools, figured out MCP protocol
- Month 2: Added billing (Stripe + x402 crypto payments), scraping tools, published to PyPI
- Month 3: Agent memory, agent networking, skills marketplace, workflow engine. Rewrote the MCP server twice.
- Month 4: 1382 tests. Security hardening. OAuth. Published to MCP Registry, Smithery, Glama. Wrote docs.

I've done zero paid marketing. The only distribution I have is PyPI, a few MCP directories, and a Dev.to post.

**Revenue so far:** Enough to cover my upstream API costs. Not enough to quit anything. I charge $0.006 per AI call with no subscription, which means I need a lot of volume to make this work. The math is tight.

**Things I got wrong:**

- Spent way too long on the marketplace before anyone was using the core tools. Classic premature feature.
- The scraping tools break regularly because platforms change their markup. I should have set expectations better.
- Underestimated how much time documentation takes. The tools are only useful if people can figure out how to use them.

**Things that surprised me:**

- The Raspberry Pi 5 is genuinely capable as a production server for this kind of workload.
- x402 crypto micropayments work well in theory but adoption is still early. Most users just use Stripe.
- MCP as a distribution channel is interesting — people discover tools through their IDE, not through a website.

**The honest pitch:** If you use Claude Code, Cursor, or Cline, you can try it in 30 seconds. Two commands, $0.10 free credits, no card needed. If it's useful, great. If not, I'd still love to hear why.

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

https://aipaygen.com

Happy to answer any questions about the technical side, the economics, or what it's like running production on a Pi 5.
