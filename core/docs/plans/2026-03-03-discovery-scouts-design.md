# Discovery Scouts Design

**Date**: 2026-03-03
**Goal**: Deploy autonomous discovery agents that find AI agents on the internet and get them to call AiPayGen APIs as their tool provider.

## Architecture: Scout Fleet

6 specialized scouts in `discovery_scouts.py`, each owning a channel, scheduled via APScheduler. Follows existing `specialist_agents.py` pattern.

## Scouts

### 1. GitHubScout (2x/day — 8 AM, 8 PM UTC)
- Search GitHub for agent repos (AutoGPT, CrewAI, LangChain, BabyAGI, MetaGPT, etc.)
- Find repos with `tools/`, `plugins/`, or MCP config files
- Open issues: "Add AiPayGen as tool provider — 646 skills via MCP/REST"
- 30-day cooldown per repo, ~100 repos/run
- Budget: ~$0.50/day (Haiku)

### 2. RegistryScout (daily — 5 AM UTC)
- Monitor agent registries: AgentProtocol, Composio, Relevance AI, agent marketplaces
- Auto-submit AiPayGen listings where registration APIs exist
- Weekly search for new registries/directories
- Budget: ~$0.30/day

### 3. SocialScout (3x/day — 9 AM, 3 PM, 9 PM UTC)
- Reddit: r/AutoGPT, r/LangChain, r/LocalLLaMA, r/artificial
- Craft helpful replies mentioning AiPayGen when relevant (not spam)
- Track comments, avoid double-posting
- Budget: ~$1.00/day (Sonnet for quality)

### 4. A2AScout (hourly)
- Crawl MCP registries (mcp.so, smithery.ai, glama.ai) for live agent endpoints
- Send agent-to-agent introductory messages via MCP/REST
- Propose collaboration: "I provide 646 skills, here's my endpoint"
- Follow up once after 7 days
- Budget: ~$0.50/day

### 5. TwitterScout (4x/day — 6 AM, 12 PM, 6 PM, 12 AM UTC)
- Search X for: "AI agent tools", "MCP server", "agent framework", "looking for API"
- Reply to relevant tweets with helpful mentions
- Post 1-2 original tweets/day: use cases, skill highlights
- Budget: ~$0.50/day (Haiku search, Sonnet crafting)

### 6. FollowUpAgent (every 6 hours)
- Review all outreach from other scouts
- Check responses on GitHub issues, Reddit threads, tweets
- Send follow-ups where engagement exists but no conversion
- Generate weekly report → knowledge base + /discovery/stats
- Budget: ~$0.20/day

**Total daily budget: ~$3.00/day**

## Data Flow

```
APScheduler (6 new jobs)
    │
    ├→ GitHubScout ──┐
    ├→ RegistryScout ─┤
    ├→ SocialScout ───┤
    ├→ A2AScout ──────┤──→ scout_outreach table
    ├→ TwitterScout ──┤
    └→ FollowUpAgent ─┘──→ weekly report + stats endpoint
```

## Database Schema

Extend `discovery_engine.db`:

```sql
CREATE TABLE scout_outreach (
    id INTEGER PRIMARY KEY,
    scout TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    message TEXT,
    response TEXT,
    status TEXT DEFAULT 'sent',
    cost_usd REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    follow_up_at TEXT,
    UNIQUE(scout, target_id, action)
);

CREATE TABLE scout_conversions (
    id INTEGER PRIMARY KEY,
    outreach_id INTEGER REFERENCES scout_outreach(id),
    caller_ip TEXT,
    user_agent TEXT,
    endpoint TEXT,
    ref_code TEXT,
    attribution TEXT DEFAULT 'direct',
    first_call_at TEXT DEFAULT (datetime('now')),
    total_calls INTEGER DEFAULT 1,
    total_spend_usd REAL DEFAULT 0
);
```

## Conversion Tracking

### Funnel
Outreach Sent → Target Engaged → First API Call (CONVERSION) → Repeat Usage

### Detection
1. **Referral codes**: Each outreach includes `?ref=gh_<hash>` or `?ref=tw_<id>` tracking link
2. **Middleware**: Extract `ref` param or `X-Referred-By` header, log alongside API call
3. **Fuzzy attribution**: Match new callers (IP/user-agent) to recent outreach within 48h window

## API Endpoints

- `GET /discovery/scouts/status` — current state of each scout
- `GET /discovery/scouts/stats` — outreach stats (sent, engaged, converted, ROI)
- `POST /discovery/scouts/run/<scout_name>` — manually trigger a scout
- `GET /discovery/scouts/report` — weekly conversion report

## Files

- `discovery_scouts.py` — all 6 scouts (new file)
- `app.py` — add scheduler jobs + referral middleware + 4 new endpoints
- `discovery_engine.db` — 2 new tables

## Constraints

- Max 3 GitHub issues/day (existing rate limit)
- Cooldown: 30 days per target (GitHub), 7 days (A2A follow-up)
- All messages crafted by Claude (Haiku/Sonnet) — never hardcoded templates
- Cost tracking per action via existing `track_cost()` in discovery_engine.py
