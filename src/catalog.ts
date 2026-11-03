import { z } from "zod";
import type { Env } from "./env";
import { ToolError } from "./lib/errors";
import { defineTool } from "./tools/types";
import { logSearch, shareBlock } from "./share";

/** The marketplace catalog in D1 (migrations/0003): listings, APIs, skills, agents, services. */

export const KINDS = ["listing", "api", "skill", "agent", "service"] as const;
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
}

const COLS = "c.id, c.kind, c.name, c.description, c.category, c.url, c.price_micro, c.x402, c.meta";

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
    price: r.price_micro == null ? null : `$${(r.price_micro / 1_000_000).toFixed(r.price_micro < 10_000 ? 3 : 2)}`,
    x402: !!r.x402, meta,
  };
}

/** Turn free text into a safe FTS5 query: each word quoted, prefix-matched, ANDed. */
export function ftsQuery(q: string): string | null {
  const words = q.toLowerCase().match(/[\p{L}\p{N}]+/gu)?.slice(0, 8) ?? [];
  return words.length ? words.map((w) => `"${w}"*`).join(" ") : null;
}

export interface SearchOpts {
  q?: string;
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
  const fts = o.q ? ftsQuery(o.q) : null;
  if (fts) {
    where.push("c.rowid IN (SELECT rowid FROM catalog_fts WHERE catalog_fts MATCH ?)");
    binds.push(fts);
  }
  if (o.kind) {
    where.push("c.kind = ?");
    binds.push(o.kind);
  }
  if (o.category) {
    where.push("c.category = ?");
    binds.push(o.category);
  }
  const w = where.length ? `WHERE ${where.join(" AND ")}` : "";
  // Rank text matches by bm25; otherwise our own listings first, then name.
  const order = fts
    ? "ORDER BY (SELECT bm25(catalog_fts) FROM catalog_fts WHERE catalog_fts.rowid = c.rowid AND catalog_fts MATCH ?)"
    : "ORDER BY (c.kind = 'listing') DESC, c.name";
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
  const r = await env.DB.prepare(`SELECT ${COLS} FROM catalog c WHERE c.id = ?`).bind(id).first<Row>();
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
