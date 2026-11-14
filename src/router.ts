import { z } from "zod";
import { SIZES } from "./copy";
import { ftsQuery } from "./catalog";
import { ownMatches } from "./owntools";
import type { Env } from "./env";
import { ToolError } from "./lib/errors";
import { logSearch, shareBlock } from "./share";
import { defineTool } from "./tools/types";

/**
 * find_tool: "I need X" -> the best working, cheapest callable option, with
 * exactly how to call it. Recommends only: the agent calls (and pays) the
 * provider directly, so no money passes through AIPayGen.
 *
 * Ranking blends text relevance with what our health checks measured
 * (src/refresh.ts): verified callable, uptime, latency, then price.
 */

interface Candidate {
  id: string;
  kind: "api" | "mcp" | "listing";
  name: string;
  description: string;
  url: string | null;
  price_micro: number | null;
  x402: number;
  meta: string;
  checks_total: number;
  checks_ok: number;
  latency_ms: number | null;
  verified: number;
}

const POOL = 60; // candidates read per call; FTS-bounded, so a call reads a few hundred rows at most

export function scoreCandidate(c: Candidate, rank: number, cheapest: number | null): { score: number; reasons: string[] } {
  const reasons: string[] = [];
  let score = 1 / (1 + rank * 0.15); // relevance from FTS order, gently decaying
  if (c.verified) {
    score += 1;
    reasons.push(c.kind === "mcp" ? "answered tools/list in our last check" : "returned a valid payment quote in our last check");
  }
  if (c.checks_total > 0) {
    const up = c.checks_ok / c.checks_total;
    score += up * 0.8;
    reasons.push(`${Math.round(up * 100)}% uptime over ${c.checks_total} checks`);
    if (c.latency_ms != null) {
      score += c.latency_ms < 500 ? 0.3 : c.latency_ms < 1500 ? 0.15 : 0;
      reasons.push(`about ${c.latency_ms} ms`);
    }
  } else {
    score += 0.3; // unchecked: neither rewarded nor buried
    reasons.push("not health-checked yet");
  }
  if (cheapest != null && c.price_micro != null && c.kind !== "listing") {
    // Cheapest scores +0.5; ten times the cheapest about +0.1.
    score += 0.5 / (1 + Math.log10(Math.max(c.price_micro, 1) / Math.max(cheapest, 1)) * 4);
    if (c.price_micro === cheapest) reasons.push("cheapest published price among matches");
  }
  if (c.kind === "listing") reasons.push("run by AIPayGen");
  return { score, reasons };
}

function howToCall(c: Candidate, meta: Record<string, unknown>) {
  if (c.kind === "mcp") {
    const remote = (meta.remote as string | undefined) ?? c.url;
    return remote
      ? { protocol: "mcp", url: remote, transport: ((meta.transports as string[] | undefined) ?? ["streamable-http"])[0] }
      : { protocol: "mcp", note: "Local server only; see its repository.", repository: meta.repository ?? meta.website ?? null };
  }
  if (c.kind === "listing") {
    return { protocol: "aipaygen", mcp: "https://mcp.aipaygen.com/mcp", http: c.url, note: "Price is quoted in the 402 reply or by the free pricing tool." };
  }
  return {
    protocol: c.x402 ? "x402" : "http",
    method: (meta.method as string | undefined) ?? "GET",
    url: c.url,
    ...(c.x402 ? { network: meta.network ?? null, pay_to: meta.pay_to ?? null, note: "Call it; the 402 reply has the exact payment requirements." } : {}),
    ...(meta.docs_url ? { docs: meta.docs_url } : {}),
  };
}

export const findTool = defineTool({
  name: "find_tool",
  title: "Find the best tool for a job",
  description:
    `Describe what you need ("current weather in Tokyo", "OCR a receipt", "company data from a domain") and get the best working, cheapest options from ${SIZES.apisAndMcp} APIs and MCP servers, ranked by real health checks, with exactly how to call each one. Free. You call the provider directly.`,
  priceMicro: 0,
  cacheTtl: 300,
  input: z.object({
    need: z.string().min(3).max(300).describe("What you want to get done, in plain words"),
    pay_with_x402: z.boolean().optional().describe("Only options payable per call with x402"),
    max_price_usd: z.number().positive().max(100).optional().describe("Skip options whose published price per call is higher"),
    limit: z.number().int().min(1).max(10).optional().describe("How many options to return (default 5)"),
  }),
  example: { need: "current weather for a city", pay_with_x402: true, limit: 3 },
  async run(args, { env }) {
    const fts = ftsQuery(args.need, true);
    if (!fts) throw new ToolError("Describe the need in a few words.", "INVALID_INPUT", 400);
    const where = ["c.kind IN ('api', 'mcp', 'listing')", "c.fail_count < 3", "c.url IS NOT NULL"];
    if (args.pay_with_x402) where.push("c.x402 = 1");
    const { results } = await env.DB.prepare(
      `SELECT c.id, c.kind, c.name, c.description, c.url, c.price_micro, c.x402, c.meta, c.checks_total, c.checks_ok, c.latency_ms, c.verified
       FROM catalog c JOIN catalog_fts f ON f.rowid = c.rowid
       WHERE catalog_fts MATCH ? AND ${where.join(" AND ")}
       ORDER BY bm25(catalog_fts) LIMIT ${POOL}`,
    ).bind(fts).all<Candidate>();

    const maxMicro = args.max_price_usd != null ? Math.round(args.max_price_usd * 1_000_000) : null;
    const pool = results.filter((c) => maxMicro == null || c.price_micro == null || c.kind === "listing" || c.price_micro <= maxMicro);
    const priced = pool.filter((c) => c.price_micro != null && c.kind !== "listing").map((c) => c.price_micro!);
    const cheapest = priced.length ? Math.min(...priced) : null;

    // At most two options per host, so one seller with many listings can't fill the answer.
    const perHost = new Map<string, number>();
    const ranked = pool
      .map((c, i) => ({ c, ...scoreCandidate(c, i, cheapest) }))
      .sort((a, b) => b.score - a.score)
      .filter(({ c }) => {
        let host = c.id;
        try {
          host = new URL(c.url ?? "").hostname;
        } catch {
          // no URL: count by id
        }
        const n = perHost.get(host) ?? 0;
        perHost.set(host, n + 1);
        return n < 2;
      })
      .slice(0, args.limit ?? 5);

    // Our own tools aren't catalog rows; offer the best one or two first when they fit the need.
    const own = ownMatches(env, args.need, 2).map((o) => ({
      id: o.id,
      kind: "aipaygen",
      name: o.name,
      what_it_does: o.description.slice(0, 300),
      price_usd: null, // quoted in the 402 reply or by the free pricing tool
      score: null,
      why: ["AIPayGen tool: maintained and monitored by us", "pay per call with x402, or an API key; failed calls are never charged"],
      call: { protocol: "aipaygen", tool: o.meta.tool, http: o.meta.http, mcp: o.meta.mcp, example_input: o.meta.example, docs: o.meta.docs },
    }));
    const host = new URL(env.PUBLIC_URL).hostname;
    const others = own.length ? ranked.filter(({ c }) => c.kind !== "listing" && !(c.url ?? "").includes(host)) : ranked;

    logSearch(env, undefined, args.need, undefined, own.length + others.length, "tool");
    return {
      need: args.need,
      considered: pool.length + own.length,
      options: [...own, ...others.slice(0, (args.limit ?? 5) - own.length).map(({ c, score, reasons }) => {
        let meta: Record<string, unknown> = {};
        try {
          meta = JSON.parse(c.meta) as Record<string, unknown>;
        } catch {
          // keep empty
        }
        return {
          id: c.id,
          kind: c.kind,
          name: c.name,
          what_it_does: c.description.slice(0, 300),
          // Third-party prices are their own public quotes; AIPayGen's are quoted on request.
          price_usd: c.kind === "listing" || c.price_micro == null ? null : c.price_micro / 1_000_000,
          score: Math.round(score * 100) / 100,
          why: reasons,
          call: howToCall(c, meta),
        };
      })],
      tip: own.length + others.length ? "Options are health-checked every few hours. If one fails, try the next." : "Nothing matched. Try fewer or simpler words; unmet needs are logged and may become new skills.",
      share: shareBlock(env),
    };
  },
});
