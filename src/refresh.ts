import { OWNER_HIDDEN, upsertCatalogItem } from "./catalog";
import type { Env } from "./env";
import { facilitatorAlert } from "./facilitator";
import { registerAgent } from "./growth";
import { skillsFromDemand } from "./skills";

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
        env.DB.prepare(`UPDATE catalog SET fail_count = ? WHERE id = ? AND fail_count < ${OWNER_HIDDEN}`).bind(fails, r.catalog_id),
      ]);
    }
  }
  return { checked: results.length, refreshed: ok };
}

interface Probe { alive: boolean; verified: boolean; ms: number }

/** One test call. MCP servers must answer tools/list; x402 APIs must return a payment quote. */
async function probe(kind: string, url: string, x402: boolean): Promise<Probe> {
  const t0 = Date.now();
  const timeout = AbortSignal.timeout(6000);
  if (kind === "mcp") {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18", "user-agent": UA },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
      redirect: "follow", signal: timeout,
    });
    const text = res.status < 500 ? (await res.text()).slice(0, 200_000) : "";
    return { alive: res.status < 500, verified: res.ok && /"tools"\s*:/.test(text), ms: Date.now() - t0 };
  }
  if (x402) {
    const res = await fetch(url, { method: "GET", headers: { accept: "application/json", "user-agent": UA }, redirect: "follow", signal: timeout });
    let quoted = res.status === 402 && !!(res.headers.get("payment-required") || res.headers.get("x-payment-required"));
    if (res.status === 402 && !quoted) quoted = /"accepts"\s*:/.test((await res.text()).slice(0, 50_000));
    return { alive: res.status < 500, verified: quoted, ms: Date.now() - t0 };
  }
  const res = await fetch(url, { method: "HEAD", headers: { "user-agent": UA }, redirect: "follow", signal: timeout });
  return { alive: res.status < 500, verified: false, ms: Date.now() - t0 };
}

// 34 probes leaves room under the free plan's 50 outbound requests per invocation for agent refreshes, both feeds and the alert.
export async function healthCheck(env: Env, limit = 34) {
  // One indexed query per kind (idx_catalog_health), least recently checked first.
  // MCP servers and APIs get most of the budget: they are what agents call.
  type HealthRow = { id: string; kind: string; url: string; x402: number; fail_count: number; latency_ms: number | null };
  const share: [string, number][] = [["mcp", 0.375], ["api", 0.375], ["agent", 0.125], ["service", 0.125]];
  const batches = await env.DB.batch(share.map(([kind, part]) => env.DB.prepare(
    `SELECT id, kind, url, x402, fail_count, latency_ms FROM catalog WHERE kind = ? AND url LIKE 'https://%' AND fail_count < ${OWNER_HIDDEN} ORDER BY checked_at LIMIT ?`,
  ).bind(kind, Math.max(1, Math.round(limit * part)))));
  const results = batches.flatMap((b) => b.results as HealthRow[]);
  if (!results.length) return { checked: 0, alive: 0, verified: 0 };
  const probes = await Promise.allSettled(results.map((r) => probe(r.kind, r.url, !!r.x402)));
  const now = Date.now();
  let alive = 0;
  let verified = 0;
  await env.DB.batch(results.map((r, i) => {
    const p = probes[i]!.status === "fulfilled" ? (probes[i] as PromiseFulfilledResult<Probe>).value : null;
    const up = !!p?.alive;
    if (up) alive++;
    if (p?.verified) verified++;
    const latency = p ? (r.latency_ms == null ? p.ms : Math.round(r.latency_ms * 0.7 + p.ms * 0.3)) : r.latency_ms;
    return env.DB.prepare(
      "UPDATE catalog SET checked_at = ?, fail_count = ?, checks_total = checks_total + 1, checks_ok = checks_ok + ?, latency_ms = ?, verified = ?, verified_at = CASE WHEN ? THEN ? ELSE verified_at END WHERE id = ?",
    ).bind(now, up ? 0 : r.fail_count + 1, up ? 1 : 0, latency, p?.verified ? 1 : 0, p?.verified ? 1 : 0, now, r.id);
  }));
  return { checked: results.length, alive, verified };
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

export async function ingestBazaar(env: Env, limit = 10) {
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
      meta: { network: a?.network, scheme: a?.scheme, pay_to: a?.payTo, method: it.extensions?.bazaar?.info?.input?.method },
    })) === "inserted") added++;
  }
  const total = d.pagination?.total ?? 0;
  await setState(env, "bazaar_offset", String(offset + limit >= total ? 0 : offset + limit));
  return { seen: d.items?.length ?? 0, added, offset, total };
}

/**
 * New catalog items cost about 6 D1 rows written each (row, indexes, search index),
 * and the free plan allows 100k rows written a day. The x402 Bazaar alone lists
 * 35k+ resources, so ingestion adds at most this many new items per UTC day.
 */
const DAILY_NEW_ITEMS = 1000;

async function withNewItemCap<T extends { added?: number }>(env: Env, job: () => Promise<T>): Promise<T | { skipped: string }> {
  const day = new Date().toISOString().slice(0, 10);
  let used = 0;
  try {
    const s = JSON.parse((await getState(env, "ingest_day")) || "{}") as { day?: string; added?: number };
    if (s.day === day) used = s.added ?? 0;
  } catch {
    // start the day fresh
  }
  if (used >= DAILY_NEW_ITEMS) return { skipped: `daily cap of ${DAILY_NEW_ITEMS} new items reached` };
  const out = await job();
  if (out.added) await setState(env, "ingest_day", JSON.stringify({ day, added: used + out.added }));
  return out;
}

export async function runFreshness(env: Env) {
  const out: Record<string, unknown> = {};
  for (const [name, job] of [
    ["agents", () => refreshAgents(env)],
    ["health", () => healthCheck(env)],
    ["mcp_registry", () => withNewItemCap(env, () => ingestMcpRegistry(env))],
    ["x402_bazaar", () => withNewItemCap(env, () => ingestBazaar(env))],
    ["skills_from_demand", () => skillsFromDemand(env)],
    ["facilitator_alert", () => facilitatorAlert(env)],
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
