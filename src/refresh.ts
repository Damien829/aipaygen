import { upsertCatalogItem } from "./catalog";
import type { Env } from "./env";
import { registerAgent } from "./growth";

/**
 * Runs on the Worker's cron trigger (wrangler.jsonc). Each run does a small,
 * bounded slice of work (well under the free plan's 50 outbound requests):
 * - re-fetch registered agents' cards about daily, so listings update themselves
 * - health-check listings in rotation; 3 failures in a row hides one from search
 * - pull new and updated servers from the official MCP Registry
 * - pull payable services from the x402 Bazaar discovery feed
 */

const UA = "AIPayGenBot/2.1 (+https://aipaygen.com/bot)";
const MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers";
const BAZAAR = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources";
const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

async function getState(env: Env, key: string): Promise<string> {
  return (await env.DB.prepare("SELECT value FROM sync_state WHERE key = ?").bind(key).first<{ value: string }>())?.value ?? "";
}

async function setState(env: Env, key: string, value: string) {
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(key, value, Date.now()).run();
}

async function sha16(s: string) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function refreshAgents(env: Env, limit = 5) {
  const { results } = await env.DB.prepare(
    "SELECT card_url, catalog_id, fail_count FROM agent_registrations WHERE status = 'listed' AND refreshed_at < ? ORDER BY refreshed_at LIMIT ?",
  ).bind(Date.now() - 20 * 3_600_000, limit).all<{ card_url: string; catalog_id: string; fail_count: number }>();
  let ok = 0;
  for (const r of results) {
    try {
      await registerAgent(env, r.card_url);
      ok++;
    } catch {
      const fails = r.fail_count + 1;
      await env.DB.batch([
        env.DB.prepare("UPDATE agent_registrations SET fail_count = ?, refreshed_at = ?, status = ? WHERE card_url = ?").bind(fails, Date.now(), fails >= 3 ? "stale" : "listed", r.card_url),
        env.DB.prepare("UPDATE catalog SET fail_count = ? WHERE id = ?").bind(fails, r.catalog_id),
      ]);
    }
  }
  return { checked: results.length, refreshed: ok };
}

export async function healthCheck(env: Env, limit = 20) {
  const { results } = await env.DB.prepare(
    "SELECT id, url, fail_count FROM catalog WHERE kind IN ('api', 'agent', 'service', 'mcp') AND url LIKE 'https://%' ORDER BY checked_at LIMIT ?",
  ).bind(limit).all<{ id: string; url: string; fail_count: number }>();
  const checks = await Promise.allSettled(results.map(async (r) => {
    const res = await fetch(r.url, { method: "HEAD", headers: { "user-agent": UA }, redirect: "follow", signal: AbortSignal.timeout(5000) });
    return res.status < 500; // any answer short of a server error means it's alive
  }));
  const now = Date.now();
  let alive = 0;
  await env.DB.batch(results.map((r, i) => {
    const up = checks[i]!.status === "fulfilled" && (checks[i] as PromiseFulfilledResult<boolean>).value;
    if (up) alive++;
    return env.DB.prepare("UPDATE catalog SET checked_at = ?, fail_count = ? WHERE id = ?").bind(now, up ? 0 : r.fail_count + 1, r.id);
  }));
  return { checked: results.length, alive };
}

interface McpEntry {
  server: { name: string; title?: string; description?: string; version?: string; websiteUrl?: string; repository?: { url?: string }; remotes?: { type: string; url: string }[] };
  _meta?: Record<string, { status?: string; isLatest?: boolean }>;
}

export async function ingestMcpRegistry(env: Env, limit = 30) {
  const cursor = await getState(env, "mcp_registry_cursor");
  const url = `${MCP_REGISTRY}?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
  const res = await fetch(url, { headers: { accept: "application/json", "user-agent": UA }, signal: AbortSignal.timeout(10000) });
  if (!res.ok) return { error: `registry ${res.status}` };
  const d = (await res.json()) as { servers?: McpEntry[]; metadata?: { nextCursor?: string } };
  let added = 0;
  for (const e of d.servers ?? []) {
    const off = e._meta?.["io.modelcontextprotocol.registry/official"];
    if (off && (off.isLatest === false || (off.status && off.status !== "active"))) continue;
    const s = e.server;
    const endpoint = s.remotes?.[0]?.url ?? null;
    if ((await upsertCatalogItem(env, {
      id: `mcp:${s.name}`, kind: "mcp", name: s.title || s.name, description: s.description ?? "", category: "mcp",
      url: endpoint ?? s.websiteUrl ?? s.repository?.url ?? null, priceMicro: null, x402: false, source: "mcp-registry",
      meta: { registry_name: s.name, version: s.version, remote: endpoint, transports: (s.remotes ?? []).map((r) => r.type), website: s.websiteUrl, repository: s.repository?.url },
    })) === "inserted") added++;
  }
  // At the end of the list, start over so updated servers are picked up again.
  await setState(env, "mcp_registry_cursor", d.metadata?.nextCursor ?? "");
  return { seen: d.servers?.length ?? 0, added };
}

interface BazaarItem {
  resource: string;
  description?: string;
  type?: string;
  lastUpdated?: string;
  accepts?: { amount?: string; asset?: string; network?: string; payTo?: string; scheme?: string }[];
  extensions?: { bazaar?: { info?: { input?: { method?: string } } } };
}

export async function ingestBazaar(env: Env, limit = 40) {
  const offset = Number(await getState(env, "bazaar_offset")) || 0;
  const res = await fetch(`${BAZAAR}?limit=${limit}&offset=${offset}`, { headers: { accept: "application/json", "user-agent": UA }, signal: AbortSignal.timeout(10000) });
  if (!res.ok) return { error: `bazaar ${res.status}` };
  const d = (await res.json()) as { items?: BazaarItem[]; pagination?: { total?: number } };
  let added = 0;
  for (const it of d.items ?? []) {
    let u: URL;
    try {
      u = new URL(it.resource);
    } catch {
      continue;
    }
    if (u.protocol !== "https:") continue;
    const a = it.accepts?.[0];
    const usdc = a?.asset?.toLowerCase() === BASE_USDC && a.network === "eip155:8453";
    if ((await upsertCatalogItem(env, {
      id: `api:x402-${await sha16(it.resource)}`, kind: "api", name: `${u.hostname}${u.pathname === "/" ? "" : u.pathname}`.slice(0, 120),
      description: it.description ?? "", category: "x402", url: it.resource,
      priceMicro: usdc && a?.amount && /^\d+$/.test(a.amount) ? Number(a.amount) : null, x402: true, source: "x402-bazaar",
      meta: { network: a?.network, scheme: a?.scheme, pay_to: a?.payTo, method: it.extensions?.bazaar?.info?.input?.method, last_updated: it.lastUpdated },
    })) === "inserted") added++;
  }
  const total = d.pagination?.total ?? 0;
  await setState(env, "bazaar_offset", String(offset + limit >= total ? 0 : offset + limit));
  return { seen: d.items?.length ?? 0, added, offset, total };
}

export async function runFreshness(env: Env) {
  const out: Record<string, unknown> = {};
  for (const [name, job] of [
    ["agents", () => refreshAgents(env)],
    ["health", () => healthCheck(env)],
    ["mcp_registry", () => ingestMcpRegistry(env)],
    ["x402_bazaar", () => ingestBazaar(env)],
  ] as const) {
    try {
      out[name] = await job();
    } catch (err) {
      out[name] = { error: err instanceof Error ? err.message : String(err) };
    }
  }
  await setState(env, "last_freshness_run", JSON.stringify({ at: new Date().toISOString(), ...out })).catch(() => {});
  return out;
}
