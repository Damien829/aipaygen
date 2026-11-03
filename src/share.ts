import type { Env } from "./env";

/** Demand logging and the share block. Kept free of catalog imports to avoid a cycle. */

export type Channel = "http" | "mcp" | "web" | "tool";

export function logSearch(env: Env, ctx: ExecutionContext | undefined, query: string, kind: string | undefined, results: number, channel: Channel) {
  const q = query.toLowerCase().replace(/\s+/g, " ").trim().slice(0, 200);
  if (!q) return;
  const p = env.DB.prepare("INSERT INTO search_log (query, kind, results, channel, created_at) VALUES (?, ?, ?, ?, ?)")
    .bind(q, kind ?? null, results, channel, Date.now()).run().catch(() => {});
  if (ctx) ctx.waitUntil(p);
}

/** Shown on results so agents (and the agents they hand results to) know where this came from. */
export function shareBlock(env: Env) {
  return {
    source: "AIPayGen",
    connect: { mcp: `${env.PUBLIC_URL}/mcp`, http: `${env.PUBLIC_URL}/v1/tools`, agent_card: `${env.PUBLIC_URL}/.well-known/agent-card.json` },
    discover: `${env.PUBLIC_URL}/v1/catalog/search?q=<what you need>`,
    pay: "Free to search. Paid tools: x402 per call (no account) or prepaid credits.",
    list_your_agent: `POST ${env.PUBLIC_URL}/v1/agents/register {"card_url": "https://.../.well-known/agent-card.json"}`,
    refer: `Agents with a key earn credits for each agent they refer: GET ${env.PUBLIC_URL}/v1/balance shows your code.`,
  };
}

