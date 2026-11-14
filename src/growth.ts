import { z } from "zod";
import { type CatalogItem, ftsQuery, searchCatalog, upsertCatalogItem } from "./catalog";
import type { Env } from "./env";
import { ToolError } from "./lib/errors";
import { defineTool } from "./tools/types";
export { logSearch, shareBlock, type Channel } from "./share";

/**
 * Word of mouth between agents, with no private data:
 * - demand analytics: search words and result counts only (no IP, key or payer)
 * - related suggestions and a "share" block on results, so agents that pass our
 *   output along also pass along how to reach us
 * - agents list themselves by submitting their public agent card URL
 */

export async function relatedTo(env: Env, text: string, excludeId?: string, limit = 3) {
  if (!ftsQuery(text)) return [];
  const r = await searchCatalog(env, { q: text.split(/\s+/).slice(0, 4).join(" "), limit: limit + 1 }).catch(() => ({ items: [] as CatalogItem[] }));
  return r.items.filter((i) => i.id !== excludeId).slice(0, limit).map((i) => {
    const [k, id] = i.id.split(/:(.*)/s);
    return { name: i.name, kind: i.kind, price: i.price, url: `${env.PUBLIC_URL}/market/${k}/${encodeURIComponent(id!)}` };
  });
}

// ── Self-registration ────────────────────────────────────────────────────

const CARD_MAX_BYTES = 64 * 1024;
const cardSchema = z.object({
  name: z.string().min(1).max(120),
  description: z.string().max(1000).optional().default(""),
  url: z.string().url().optional(),
  provider: z.object({ organization: z.string().max(120).optional(), url: z.string().optional() }).optional(),
  skills: z.array(z.object({ name: z.string().max(120).optional(), id: z.string().max(120).optional() }).passthrough()).max(100).optional(),
  protocolVersion: z.string().max(20).optional(),
}).passthrough();

function checkCardUrl(raw: string): URL {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    throw new ToolError("card_url must be a full https URL.", "INVALID_INPUT", 400);
  }
  const host = u.hostname.toLowerCase();
  if (u.protocol !== "https:" || u.username || u.password) throw new ToolError("card_url must be https.", "INVALID_INPUT", 400);
  if (host === "localhost" || host.endsWith(".local") || host.endsWith(".internal") || /^[\d.]+$/.test(host) || host.includes(":")) {
    throw new ToolError("card_url must use a public hostname.", "INVALID_INPUT", 400);
  }
  return u;
}

async function sha16(s: string) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function registerAgent(env: Env, cardUrl: string) {
  const u = checkCardUrl(cardUrl);
  let res: Response;
  try {
    res = await fetch(u, { headers: { accept: "application/json", "user-agent": "AIPayGenBot/2.1 (+https://aipaygen.com/bot)" }, redirect: "manual", signal: AbortSignal.timeout(8000) });
  } catch {
    throw new ToolError("Could not fetch the agent card (8s timeout).", "FETCH_FAILED", 422);
  }
  if (res.status >= 300 && res.status < 400) throw new ToolError("Agent card URL redirects; submit the final URL.", "FETCH_FAILED", 422);
  if (!res.ok) throw new ToolError(`Agent card returned HTTP ${res.status}.`, "FETCH_FAILED", 422);
  const text = await res.text();
  if (text.length > CARD_MAX_BYTES) throw new ToolError("Agent card is larger than 64 KB.", "CARD_TOO_LARGE", 422);
  let parsed;
  try {
    parsed = cardSchema.safeParse(JSON.parse(text));
  } catch {
    throw new ToolError("Agent card is not valid JSON.", "INVALID_CARD", 422);
  }
  if (!parsed.success) throw new ToolError(`Agent card is missing required fields: ${parsed.error.issues.map((i) => i.path.join(".")).join(", ")}`, "INVALID_CARD", 422);
  const card = parsed.data;

  const id = `agent:card-${await sha16(u.href)}`;
  const skills = (card.skills ?? []).map((s) => s.name ?? s.id).filter(Boolean).slice(0, 30) as string[];
  const name = card.name.trim();
  const description = (card.description ?? "").trim();
  const category = "registered";
  const meta = JSON.stringify({ card_url: u.href, skills, provider: card.provider?.organization ?? null, protocol_version: card.protocolVersion ?? null, self_registered: true });
  const now = Date.now();

  const updated = (await upsertCatalogItem(env, {
    id, kind: "agent", name, description, category, url: card.url ?? u.href, priceMicro: null, x402: false, meta: JSON.parse(meta), source: "registered",
  })) === "updated";
  await env.DB.prepare(
    "INSERT INTO agent_registrations (card_url, catalog_id, status, created_at, refreshed_at) VALUES (?, ?, 'listed', ?, ?) ON CONFLICT(card_url) DO UPDATE SET status = 'listed', fail_count = 0, refreshed_at = excluded.refreshed_at",
  ).bind(u.href, id, now, now).run();

  const [, rest] = id.split(/:(.*)/s);
  return { listed: true, id, name, page: `${env.PUBLIC_URL}/market/agent/${rest}`, json: `${env.PUBLIC_URL}/v1/catalog/agent/${rest}`, updated };
}

/** Free tool: an agent lists itself so other agents can find it. */
export const registerAgentTool = defineTool({
  name: "register_agent",
  title: "List your agent in the AIPayGen marketplace",
  description: "Free. Submit your public A2A agent card URL (usually https://<your-domain>/.well-known/agent-card.json) and your agent is listed and searchable in the AIPayGen marketplace, so other agents can find you. Re-submit any time to refresh.",
  priceMicro: 0,
  cacheTtl: 0,
  httpMethod: "POST",
  input: z.object({ card_url: z.string().url().max(500).describe("Public https URL of your agent card JSON") }),
  example: { card_url: "https://example.com/.well-known/agent-card.json" },
  async run(args, { env }) {
    return registerAgent(env, args.card_url);
  },
});

/** Top searches and the ones that found nothing: what to add next. */
export async function demandReport(env: Env, days = 30) {
  const since = Date.now() - days * 86_400_000;
  const [top, empty, byChannel] = await env.DB.batch([
    env.DB.prepare("SELECT query, COUNT(*) AS n, ROUND(AVG(results)) AS avg_results FROM search_log WHERE created_at > ? GROUP BY query ORDER BY n DESC LIMIT 50").bind(since),
    env.DB.prepare("SELECT query, COUNT(*) AS n FROM search_log WHERE created_at > ? AND results = 0 GROUP BY query ORDER BY n DESC LIMIT 50").bind(since),
    env.DB.prepare("SELECT channel, COUNT(*) AS n FROM search_log WHERE created_at > ? GROUP BY channel").bind(since),
  ]);
  return { window_days: days, top_searches: top?.results ?? [], unmet_demand: empty?.results ?? [], by_channel: byChannel?.results ?? [] };
}
