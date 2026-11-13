import { z } from "zod";
import type { Env } from "./env";
import { ToolError } from "./lib/errors";
import { defineTool } from "./tools/types";
import { logSearch, shareBlock } from "./share";

/** The marketplace catalog in D1 (migrations/0003): listings, APIs, skills, agents, services. */

/** fail_count value meaning "hidden by the owner" (POST /admin/catalog/hide). Health checks and re-ingests never clear it. */
export const OWNER_HIDDEN = 99;

export const KINDS = ["listing", "api", "skill", "agent", "service", "mcp"] as const;
export type Kind = (typeof KINDS)[number];

export interface CatalogItem {
  id: string;
  kind: Kind;
  name: string;
  description: string;
  category: string;
  url: string | null;
  price: string | null;
  x402: boolean;
  meta: Record<string, unknown>;
  /** From real test calls; null until checked. */
  trust: { verified: boolean; uptime_pct: number | null; latency_ms: number | null; checks: number } | null;
}

interface Row {
  id: string;
  kind: Kind;
  name: string;
  description: string;
  category: string;
  url: string | null;
  price_micro: number | null;
  x402: number;
  meta: string;
  checks_total: number;
  checks_ok: number;
  latency_ms: number | null;
  verified: number;
}

const COLS = "c.id, c.kind, c.name, c.description, c.category, c.url, c.price_micro, c.x402, c.meta, c.checks_total, c.checks_ok, c.latency_ms, c.verified";
// Higher is better: proven callable, then uptime. Unchecked items sit in the middle.
const TRUST_SQL = "(c.verified * 2.0 + CASE WHEN c.checks_total > 0 THEN 1.0 * c.checks_ok / c.checks_total ELSE 0.5 END)";

function toItem(r: Row): CatalogItem {
  let meta: Record<string, unknown> = {};
  try {
    meta = JSON.parse(r.meta) as Record<string, unknown>;
  } catch {
    // keep empty
  }
  for (const k of Object.keys(meta)) if (meta[k] === null || meta[k] === "") delete meta[k];
  return {
    id: r.id, kind: r.kind, name: r.name, description: r.description, category: r.category, url: r.url,
    price: null, // not shown publicly: agents get an exact quote from the 402 reply when they call
    x402: !!r.x402, meta,
    trust: r.checks_total > 0
      ? { verified: !!r.verified, uptime_pct: Math.round((100 * r.checks_ok) / r.checks_total), latency_ms: r.latency_ms, checks: r.checks_total }
      : null,
  };
}

/** Turn free text into a safe FTS5 query: each word quoted, prefix-matched, ANDed. */
export function ftsQuery(q: string, anyWord = false): string | null {
  let words: string[] = [...(q.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [])];
  if (anyWord) words = words.filter((w) => w.length > 2 && !STOPWORDS.has(w));
  words = words.slice(0, 8);
  return words.length ? words.map((w) => `"${w}"*`).join(anyWord ? " OR " : " ") : null;
}

// Dropped from natural-language requests ("I need an API that can...").
const STOPWORDS = new Set("the and for that this with from can you your need want find looking look any some get give show what which who how are was were has have will would could should please help agent agents tool tools api apis service services".split(" "));

export interface SearchOpts {
  q?: string;
  /** Match any significant word (natural-language requests) instead of all words. */
  anyWord?: boolean;
  kind?: Kind;
  category?: string;
  limit?: number;
  offset?: number;
}

export async function searchCatalog(env: Env, o: SearchOpts): Promise<{ total: number; items: CatalogItem[] }> {
  const limit = Math.min(Math.max(o.limit ?? 20, 1), 50);
  const offset = Math.min(Math.max(o.offset ?? 0, 0), 5000);
  const where: string[] = [];
  const binds: unknown[] = [];
  const fts = o.q ? ftsQuery(o.q, o.anyWord) : null;
  if (fts) {
    where.push("c.rowid IN (SELECT rowid FROM catalog_fts WHERE catalog_fts MATCH ?)");
    binds.push(fts);
  }
  if (o.kind) {
    where.push("c.kind = ?");
    binds.push(o.kind);
  }
  where.push("c.fail_count < 3"); // hide listings that failed 3 health checks in a row
  if (o.category) {
    where.push("c.category = ?");
    binds.push(o.category);
  }
  const w = where.length ? `WHERE ${where.join(" AND ")}` : "";
  // Rank text matches by bm25; otherwise our own listings first, then name.
  const order = fts
    ? `ORDER BY (SELECT bm25(catalog_fts) FROM catalog_fts WHERE catalog_fts.rowid = c.rowid AND catalog_fts MATCH ?) - ${TRUST_SQL}`
    : `ORDER BY (c.kind = 'listing') DESC, ${TRUST_SQL} DESC, c.name`;
  const [count, page] = await env.DB.batch([
    env.DB.prepare(`SELECT COUNT(*) AS n FROM catalog c ${w}`).bind(...binds),
    env.DB.prepare(`SELECT ${COLS} FROM catalog c ${w} ${order} LIMIT ? OFFSET ?`).bind(...binds, ...(fts ? [fts] : []), limit, offset),
  ]);
  return {
    total: ((count?.results[0] as { n: number } | undefined)?.n) ?? 0,
    items: ((page?.results ?? []) as unknown as Row[]).map(toItem),
  };
}

export async function getCatalogItem(env: Env, id: string): Promise<CatalogItem | null> {
  const r = await env.DB.prepare(`SELECT ${COLS} FROM catalog c WHERE c.id = ? AND c.fail_count < ${OWNER_HIDDEN}`).bind(id).first<Row>();
  return r ? toItem(r) : null;
}

export async function catalogStats(env: Env) {
  const { results } = await env.DB.prepare("SELECT kind, COUNT(*) AS n FROM catalog GROUP BY kind").all<{ kind: Kind; n: number }>();
  const { results: cats } = await env.DB.prepare(
    "SELECT kind, category, COUNT(*) AS n FROM catalog WHERE category != '' GROUP BY kind, category ORDER BY n DESC LIMIT 60",
  ).all<{ kind: Kind; category: string; n: number }>();
  return { counts: Object.fromEntries(results.map((r) => [r.kind, r.n])), top_categories: cats };
}

/** Free tool: lets agents find APIs, skills, agents and AIPayGen listings. */
export const searchMarketplace = defineTool({
  name: "search_marketplace",
  title: "Search the AIPayGen marketplace",
  description:
    "Search 11,000+ AI-agent resources: AIPayGen's paid tools, 4,300+ third-party APIs (with docs and auth info, some x402-payable), 4,300+ reusable skills, 950+ registered agents and 1,500+ agent services. Free.",
  priceMicro: 0,
  cacheTtl: 300,
  input: z.object({
    query: z.string().min(1).max(200).describe("What you need, e.g. 'weather forecast API' or 'summarize pdf'"),
    kind: z.enum(KINDS).optional().describe("Limit to one kind of result"),
    limit: z.number().int().min(1).max(50).optional().describe("Results to return (default 10)"),
  }),
  example: { query: "translate text", kind: "api", limit: 5 },
  async run(args, { env }) {
    if (!ftsQuery(args.query)) throw new ToolError("Query needs at least one word.", "INVALID_INPUT", 400);
    const r = await searchCatalog(env, { q: args.query, kind: args.kind, limit: args.limit ?? 10 });
    logSearch(env, undefined, args.query, args.kind, r.total, "tool");
    return { query: args.query, total: r.total, results: r.items, share: shareBlock(env) };
  },
});

export interface UpsertItem {
  id: string;
  kind: Kind;
  name: string;
  description: string;
  category: string;
  url: string | null;
  priceMicro: number | null;
  x402: boolean;
  meta: Record<string, unknown>;
  source: string;
}

/** Insert or update one catalog row and keep the external-content FTS index in step. */
export async function upsertCatalogItem(env: Env, it: UpsertItem): Promise<"inserted" | "updated"> {
  const name = it.name.replace(/\*\*/g, "").trim().slice(0, 200);
  const description = (it.description ?? "").trim().slice(0, 2000);
  const category = (it.category ?? "").trim().slice(0, 60);
  const meta = JSON.stringify(it.meta ?? {});
  const now = Date.now();
  const old = await env.DB.prepare("SELECT rowid, name, description, category FROM catalog WHERE id = ?").bind(it.id)
    .first<{ rowid: number; name: string; description: string; category: string }>();
  if (old) {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO catalog_fts (catalog_fts, rowid, name, description, category) VALUES ('delete', ?, ?, ?, ?)").bind(old.rowid, old.name, old.description, old.category),
      env.DB.prepare(`UPDATE catalog SET name = ?, description = ?, category = ?, url = ?, price_micro = ?, x402 = ?, meta = ?, source = ?, updated_at = ?, fail_count = CASE WHEN fail_count >= ${OWNER_HIDDEN} THEN fail_count ELSE 0 END WHERE id = ?`)
        .bind(name, description, category, it.url, it.priceMicro, it.x402 ? 1 : 0, meta, it.source, now, it.id),
      env.DB.prepare("INSERT INTO catalog_fts (rowid, name, description, category) VALUES (?, ?, ?, ?)").bind(old.rowid, name, description, category),
    ]);
    return "updated";
  }
  const ins = await env.DB.prepare("INSERT INTO catalog (id, kind, name, description, category, url, price_micro, x402, meta, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(it.id, it.kind, name, description, category, it.url, it.priceMicro, it.x402 ? 1 : 0, meta, it.source, now).run();
  await env.DB.prepare("INSERT INTO catalog_fts (rowid, name, description, category) VALUES (?, ?, ?, ?)").bind(ins.meta.last_row_id, name, description, category).run();
  return "inserted";
}
