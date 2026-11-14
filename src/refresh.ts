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

type Accept = { scheme?: string; network?: string; payTo?: string; asset?: string; amount?: string; maxAmountRequired?: string };

/**
 * A usable x402 quote: at least one accepts entry with a scheme, a CAIP-2 or v1
 * network name, a payTo and an amount. Reads the v2 PAYMENT-REQUIRED header
 * (base64 JSON) or a JSON body ({ accepts: [...] }, v1 and v2).
 */
export function parseQuote(header: string | null, body: string): boolean {
  const docs: unknown[] = [];
  if (header) {
    try {
      docs.push(JSON.parse(atob(header.trim())));
    } catch {
      try {
        docs.push(JSON.parse(header));
      } catch {
        // not JSON
      }
    }
  }
  try {
    docs.push(JSON.parse(body));
  } catch {
    // not JSON
  }
  return docs.some((d) => {
    const accepts = (d as { accepts?: Accept[] } | null)?.accepts;
    return Array.isArray(accepts) && accepts.some((a) =>
      !!a && typeof a.scheme === "string" && typeof a.network === "string" && a.network.length > 2 &&
      typeof a.payTo === "string" && a.payTo.length >= 20 && /^\d+$/.test(String(a.amount ?? a.maxAmountRequired ?? "")));
  });
}

/** One test call. MCP servers must answer tools/list; x402 APIs must return a usable payment quote. */
async function probe(kind: string, url: string, x402: boolean, method = "GET"): Promise<Probe> {
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
    const post = method.toUpperCase() === "POST";
    const res = await fetch(url, {
      method: post ? "POST" : "GET",
      headers: { accept: "application/json", "user-agent": UA, ...(post ? { "content-type": "application/json" } : {}) },
      ...(post ? { body: "{}" } : {}),
      redirect: "follow", signal: timeout,
    });
    const quoted = res.status === 402 && parseQuote(res.headers.get("payment-required") ?? res.headers.get("x-payment-required"), (await res.text()).slice(0, 50_000));
    // Up: 402, success, or a refusal that means a server is there (bad input, wrong method, bot shield,
    // rate limit). Gone or broken: 404, 410 and 5xx, so dead listings drop out after 3 checks.
    return { alive: res.ok || [400, 401, 402, 403, 405, 429].includes(res.status), verified: quoted, ms: Date.now() - t0 };
  }
  const res = await fetch(url, { method: "HEAD", headers: { "user-agent": UA }, redirect: "follow", signal: timeout });
  return { alive: res.status < 500, verified: false, ms: Date.now() - t0 };
}

// 34 probes leaves room under the free plan's 50 outbound requests per invocation for agent refreshes, both feeds and the alert.
export async function healthCheck(env: Env, limit = 34) {
  // One indexed query per kind (idx_catalog_health), least recently checked first.
  // MCP servers and APIs get most of the budget: they are what agents call.
  type HealthRow = { id: string; kind: string; url: string; x402: number; fail_count: number; latency_ms: number | null; method: string | null };
  // APIs get half: the x402 feeds add thousands of them and about a quarter are dead.
  const share: [string, number][] = [["mcp", 0.25], ["api", 0.5], ["agent", 0.125], ["service", 0.125]];
  const batches = await env.DB.batch(share.map(([kind, part]) => env.DB.prepare(
    `SELECT id, kind, url, x402, fail_count, latency_ms, json_extract(meta, '$.method') AS method FROM catalog WHERE kind = ? AND url LIKE 'https://%' AND fail_count < ${OWNER_HIDDEN} ORDER BY checked_at LIMIT ?`,
  ).bind(kind, Math.max(1, Math.round(limit * part)))));
  const results = batches.flatMap((b) => b.results as HealthRow[]);
  if (!results.length) return { checked: 0, alive: 0, verified: 0 };
  const probes = await Promise.allSettled(results.map((r) => probe(r.kind, r.url, !!r.x402, r.method ?? "GET")));
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
  metadata?: { description?: string };
  accepts?: { amount?: string; asset?: string; network?: string; payTo?: string; scheme?: string; description?: string }[];
  extensions?: { bazaar?: { info?: { input?: { method?: string } } } };
}

/** x402 discovery feeds (same /discovery/resources shape). Each keeps its own offset. */
export const X402_FEEDS = [
  { name: "cdp", url: BAZAAR, offsetKey: "bazaar_offset", source: "x402-bazaar" },
  { name: "payai", url: "https://facilitator.payai.network/discovery/resources", offsetKey: "payai_offset", source: "x402-payai" },
] as const;

/** Lowercased words only, so trivially different copies of one description match. */
export function normalizeDescription(d: string): string {
  return d.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().slice(0, 200);
}

/**
 * Catalog id for an x402 resource. Sellers often list many paths with one shared
 * description; those collapse into one item per host (the first URL seen is kept).
 * Short or missing descriptions can't be told apart, so those stay one item per URL.
 */
export async function x402ItemId(resource: string, description: string): Promise<{ id: string; grouped: boolean }> {
  const norm = normalizeDescription(description);
  if (norm.length < 40) return { id: `api:x402-${await sha16(resource)}`, grouped: false };
  return { id: `api:x402g-${await sha16(`${new URL(resource).hostname}|${norm}`)}`, grouped: true };
}

export async function ingestX402Feed(env: Env, feed: (typeof X402_FEEDS)[number], limit = 10) {
  const offset = Number(await getState(env, feed.offsetKey)) || 0;
  const res = await fetch(`${feed.url}?limit=${limit}&offset=${offset}`, { headers: { accept: "application/json", "user-agent": UA }, signal: AbortSignal.timeout(10000) });
  if (!res.ok) return { error: `${feed.name} ${res.status}` };
  const d = (await res.json()) as { items?: BazaarItem[]; pagination?: { total?: number } };
  let added = 0;
  let duplicates = 0;
  for (const it of d.items ?? []) {
    let u: URL;
    try {
      u = new URL(it.resource);
    } catch {
      continue;
    }
    if (u.protocol !== "https:") continue;
    // Prefer USDC on Base: it's what our price and payment info describe.
    const a = it.accepts?.find((x) => x.network === "eip155:8453" && x.asset?.toLowerCase() === BASE_USDC) ?? it.accepts?.[0];
    const usdc = a?.asset?.toLowerCase() === BASE_USDC && a.network === "eip155:8453";
    const description = (it.description || it.metadata?.description || a?.description || "").trim();
    // Items stored before grouping keep their per-URL id, so they aren't added twice.
    const legacy = `api:x402-${await sha16(it.resource)}`;
    const old = await env.DB.prepare("SELECT 1 AS x FROM catalog WHERE id = ?").bind(legacy).first();
    const { id, grouped } = old ? { id: legacy, grouped: false } : await x402ItemId(it.resource, description);
    if (grouped) {
      const kept = await env.DB.prepare("SELECT url FROM catalog WHERE id = ?").bind(id).first<{ url: string }>();
      if (kept && kept.url !== it.resource) {
        duplicates++;
        continue;
      }
    }
    if ((await upsertCatalogItem(env, {
      id, kind: "api", name: `${u.hostname}${u.pathname === "/" ? "" : u.pathname}`.slice(0, 120),
      description, category: "x402", url: it.resource,
      priceMicro: usdc && a?.amount && /^\d+$/.test(a.amount) && a.amount !== "0" ? Number(a.amount) : null, x402: true, source: feed.source,
      meta: { network: a?.network, scheme: a?.scheme, pay_to: a?.payTo, method: it.extensions?.bazaar?.info?.input?.method },
    })) === "inserted") added++;
  }
  const total = d.pagination?.total ?? 0;
  await setState(env, feed.offsetKey, String(offset + limit >= total ? 0 : offset + limit));
  return { seen: d.items?.length ?? 0, added, duplicates, offset, total };
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

/**
 * Retention: once a day (the 03:00 UTC run) delete what we no longer need.
 * Search text 90 days (demand reports read 30), free-call counters 2 days,
 * payment replay guards 7 days. Matches /privacy.
 */
export async function pruneLogs(env: Env, now = new Date()) {
  if (now.getUTCHours() !== 3 || now.getUTCMinutes() >= 10) return { skipped: "runs daily at 03:00 UTC" };
  const day = (ms: number) => new Date(now.getTime() - ms).toISOString().slice(0, 10);
  const r = await env.DB.batch([
    env.DB.prepare("DELETE FROM search_log WHERE created_at < ?").bind(now.getTime() - 90 * 86_400_000),
    env.DB.prepare("DELETE FROM free_calls WHERE day < ?").bind(day(2 * 86_400_000)),
    env.DB.prepare("DELETE FROM payment_claims WHERE created_at < ?").bind(now.getTime() - 7 * 86_400_000),
  ]);
  return { search_log: r[0]?.meta.changes ?? 0, free_calls: r[1]?.meta.changes ?? 0, payment_claims: r[2]?.meta.changes ?? 0 };
}

export async function runFreshness(env: Env) {
  const out: Record<string, unknown> = {};
  for (const [name, job] of [
    ["agents", () => refreshAgents(env)],
    ["health", () => healthCheck(env)],
    ["mcp_registry", () => withNewItemCap(env, () => ingestMcpRegistry(env))],
    ["x402_bazaar", () => withNewItemCap(env, () => ingestX402Feed(env, X402_FEEDS[0]))],
    ["x402_payai", () => withNewItemCap(env, () => ingestX402Feed(env, X402_FEEDS[1]))],
    ["skills_from_demand", () => skillsFromDemand(env)],
    ["facilitator_alert", () => facilitatorAlert(env)],
    ["prune", () => pruneLogs(env)],
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
