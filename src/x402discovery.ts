import type { Env } from "./env";
import { TOOLS } from "./tools";
import { catalogCounts } from "./catalog";
import { buildRequirements, discoveryExtension, x402Enabled } from "./billing/x402";

/**
 * x402 discovery API in the same shape as the Bazaar's
 * (GET /discovery/resources -> { x402Version, items, pagination }), so any
 * client built for the Bazaar can point at AIPayGen instead and get:
 *   - AIPayGen's own tools, with full payment requirements, first;
 *   - every x402 resource we index (Coinbase's Bazaar and more), with dead
 *     listings (3+ failed health checks) left out and proven-callable ones first;
 *   - our health data on each item (metadata.trust).
 * Read-only. Each page reads about as many catalog rows as it returns.
 */

const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
// Must match TRUST_SQL in catalog.ts and idx_catalog_browse_kind (migration 0012), or SQLite scans the table.
const TRUST_SQL = "(c.verified * 2.0 + CASE WHEN c.checks_total > 0 THEN 1.0 * c.checks_ok / c.checks_total ELSE 0.5 END)";
const MAX_LIMIT = 100;
const MAX_OFFSET = 5000;

interface Row {
  id: string; name: string; description: string; url: string; price_micro: number | null; meta: string;
  checks_total: number; checks_ok: number; latency_ms: number | null; verified: number; checked_at: number; source: string;
}

export interface DiscoveryItem {
  resource: string;
  type: "http";
  x402Version: 2;
  accepts: Record<string, unknown>[];
  lastUpdated: string;
  metadata: Record<string, unknown>;
  extensions?: Record<string, unknown>;
}

/** One catalog row as a Bazaar-shaped item. Payment terms only when we know them. */
export function rowToDiscovery(r: Row): DiscoveryItem {
  let meta: Record<string, unknown> = {};
  try {
    meta = JSON.parse(r.meta) as Record<string, unknown>;
  } catch {
    // keep empty
  }
  const accepts: Record<string, unknown>[] = [];
  if (r.price_micro != null && typeof meta.pay_to === "string") {
    accepts.push({
      scheme: (meta.scheme as string) ?? "exact",
      network: (meta.network as string) ?? "eip155:8453",
      amount: String(r.price_micro),
      maxAmountRequired: String(r.price_micro),
      asset: BASE_USDC,
      payTo: meta.pay_to,
      resource: r.url,
      description: r.description.slice(0, 500),
      mimeType: "application/json",
      maxTimeoutSeconds: 60,
    });
  }
  return {
    resource: r.url,
    type: "http",
    x402Version: 2,
    accepts,
    lastUpdated: new Date(r.checked_at || Date.now()).toISOString(),
    metadata: {
      name: r.name,
      description: r.description,
      method: typeof meta.method === "string" ? meta.method : "GET",
      source: r.source,
      trust: r.checks_total > 0
        ? { verified: !!r.verified, uptime_pct: Math.round((100 * r.checks_ok) / r.checks_total), latency_ms: r.latency_ms, checks: r.checks_total }
        : { verified: !!r.verified, uptime_pct: null, latency_ms: null, checks: 0 },
    },
  };
}

/** AIPayGen's own paid tools as Bazaar-shaped items, with exact payment requirements. */
async function ownItems(env: Env): Promise<DiscoveryItem[]> {
  const paid = TOOLS.filter((t) => t.priceMicro > 0);
  const now = new Date().toISOString();
  return Promise.all(
    paid.map(async (t) => {
      const url = `${env.PUBLIC_URL}/v1/${t.name}`;
      const reqs = x402Enabled(env) ? await buildRequirements(env, t.priceMicro).catch(() => []) : [];
      return {
        resource: url,
        type: "http" as const,
        x402Version: 2 as const,
        accepts: reqs.map((r) => ({ ...r, resource: url, description: t.description, mimeType: "application/json" })),
        lastUpdated: now,
        metadata: {
          name: `${t.title} (AIPayGen)`,
          description: t.description,
          method: t.httpMethod ?? "GET",
          source: "aipaygen",
          example: t.example,
          trust: { verified: true, uptime_pct: null, latency_ms: null, checks: null, first_party: true },
        },
        extensions: discoveryExtension(t, "http"),
      };
    }),
  );
}

export async function discoveryResources(env: Env, params: URLSearchParams) {
  const limit = Math.min(Math.max(Number(params.get("limit")) || 20, 1), MAX_LIMIT);
  const offset = Math.min(Math.max(Number(params.get("offset")) || 0, 0), MAX_OFFSET);
  const verifiedOnly = params.get("verified") === "true";
  const own = params.get("include_aipaygen") === "false" ? [] : await ownItems(env);

  // Our tools fill the first slots; catalog rows continue after them.
  const ownPage = own.slice(offset, offset + limit);
  const rowOffset = Math.max(0, offset - own.length);
  const rowLimit = limit - ownPage.length;

  // Only payable endpoints with known terms (Bazaar imports); seed rows tagged x402 are often repos or docs pages.
  const where = ["c.kind = 'api'", "c.x402 = 1", "c.fail_count < 3", "c.url IS NOT NULL", "c.price_micro IS NOT NULL"];
  if (verifiedOnly) where.push("c.verified = 1");
  let rows: Row[] = [];
  if (rowLimit > 0) {
    const page = await env.DB.prepare(
      `SELECT c.id, c.name, c.description, c.url, c.price_micro, c.meta, c.checks_total, c.checks_ok, c.latency_ms, c.verified, c.checked_at, c.source
       FROM catalog c WHERE ${where.join(" AND ")} ORDER BY ${TRUST_SQL} DESC, c.name LIMIT ? OFFSET ?`,
    ).bind(rowLimit, rowOffset).all<Row>();
    rows = page.results;
  }
  // Exact totals would read every row; use the stored counts (refreshed every 6 hours).
  const counts = await catalogCounts(env).catch(() => null);
  const x402 = counts?.top_categories.find((c) => c.kind === "api" && c.category === "x402")?.n ?? 0;
  const total = own.length + x402;
  return {
    x402Version: 2,
    items: [...ownPage, ...rows.map(rowToDiscovery)],
    pagination: { limit, offset, total: total || null },
    about: {
      provider: "AIPayGen",
      what: "Bazaar-compatible x402 discovery: our tools plus indexed x402 resources, with dead listings removed and health data in metadata.trust.",
      params: "limit (max 100), offset (max 5000), verified=true (only proven-callable), include_aipaygen=false",
      search: `${env.PUBLIC_URL}/v1/catalog/search?q=<words>&kind=api`,
      best_option_for_a_task: `${env.PUBLIC_URL}/v1/find_tool?need=<what you need>`,
    },
  };
}
