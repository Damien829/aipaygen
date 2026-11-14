import type { MiddlewareHandler } from "hono";

/**
 * Edge cache for public, read-only pages that query D1.
 *
 * D1's free plan allows 5 million row reads a day, and one catalog listing can
 * read thousands. Without this, a crawler or a polling client can use up the
 * day's quota and take search down until midnight UTC (it happened: 2026-11-13).
 * A cache hit costs no database reads.
 *
 * Seconds to keep each path. First match wins.
 */
const RULES: [RegExp, number][] = [
  [/^\/v1\/catalog\/summary$/, 1800],
  [/^\/v1\/catalog\//, 300],
  [/^\/(v1\/)?discovery\/resources$/, 300],
  [/^\/market(\/|$)/, 300],
  [/^\/sitemap\.xml$|^\/sitemaps\//, 3600],
  [/^\/llms-full\.txt$/, 600],
  [/^\/facilitator$/, 60],
];

export const edgeCache: MiddlewareHandler = async (c, next) => {
  const cache = (globalThis as { caches?: { default?: Cache } }).caches?.default;
  const url = new URL(c.req.url);
  const rule = RULES.find(([re]) => re.test(url.pathname));
  // Requests with credentials are never cached.
  if (!cache || !rule || c.req.method !== "GET" || c.req.header("authorization") || c.req.header("x-api-key")) return next();

  url.searchParams.sort();
  url.searchParams.set("__variant", /text\/markdown/i.test(c.req.header("accept") ?? "") ? "md" : "default");
  const key = new Request(url.toString());
  const hit = await cache.match(key);
  if (hit) {
    const res = new Response(hit.body, hit);
    res.headers.set("x-edge-cache", "hit");
    // The stored copy can come back with the zone's browser TTL (hours); clients should use ours.
    res.headers.set("cache-control", `public, max-age=${rule[1]}`);
    return res;
  }

  await next();
  if (c.res.status !== 200) return;
  const copy = new Response(c.res.clone().body, c.res);
  copy.headers.set("cache-control", `public, max-age=${rule[1]}`);
  c.executionCtx.waitUntil(cache.put(key, copy));
};
