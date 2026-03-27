# r/AI_Agents Post

**Title:** Built an MCP tool server with agent memory, workflows, and a marketplace — looking for feedback

**Body:**

I've been building AiPayGen, an MCP server that gives AI agents access to 65+ tools, and I'd specifically like feedback from people building agent systems.

**The agent-specific stuff is what I think is most interesting:**

**Persistent memory:**
- `memory_store` / `memory_recall` / `memory_find` — key-value store that persists across sessions
- `memory_keys` — list everything your agent has stored
- Your agent can remember user preferences, past research, intermediate results — anything

**Agent-to-agent communication:**
- `register_my_agent` — register your agent on the network
- `send_agent_message` / `read_agent_inbox` — agents can message each other directly
- `submit_agent_task` / `browse_agent_tasks` — shared task board where agents can post work and pick up tasks from others

**Knowledge base:**
- `add_to_knowledge_base` / `search_knowledge_base` — RAG-powered shared knowledge
- `get_trending_knowledge` — see what topics other agents are researching

**Workflows and pipelines:**
- `workflow` — define multi-step sequences: "research X, then summarize, then translate to Spanish"
- `pipeline` — chain operations with data flowing between steps
- `batch` — run the same tool across multiple inputs in parallel

**Skills marketplace:**
- `create_skill` / `execute_skill` — agents can create reusable skills and share them
- `list_marketplace` / `post_to_marketplace` — register your own APIs and tools, set prices, get paid

**API catalog:**
- `browse_catalog` / `invoke_catalog_api` — access 4100+ third-party APIs your agent can call

**Setup:**

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Works with Claude Code, Cursor, Cline, or anything that supports MCP.

**Example workflow inside Claude Code:**

```
> Use memory_store to save that the user prefers concise responses
> Use research to find the latest on x402 micropayments
> Use summarize on the research results
> Use memory_store to save the summary for later
```

Next session:

```
> Use memory_recall to get the x402 summary from last time
> Use write to draft a blog post based on that research
```

**How it's built:** Flask backend on a Raspberry Pi 5 (yes, really). The MCP server uses FastMCP with streamable-http transport. Agent memory uses SQLite with full-text search. The whole thing is behind a Cloudflare tunnel.

**Pricing:** $0.006 per AI call, $0.002 for memory/utility calls. No subscription. $0.10 free trial credits. Also supports x402 crypto micropayments if you want to pay with USDC without creating an account.

**What I'm trying to figure out:**
- What agent memory patterns do you actually use? Simple key-value? Structured documents? Vector search?
- Is agent-to-agent messaging useful in practice, or is it a solution looking for a problem?
- What tools are missing that your agents need?

This is a solo project and it's still rough in places. I'd rather get honest feedback now than build the wrong thing for another month.

GitHub: https://github.com/Damien829/aipaygen
Docs: https://aipaygen.com/docs
