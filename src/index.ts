import { Hono } from "hono";
import { RECONCILE_CRON, reconcilePayments } from "./reconcile";
import { createMcpHandler } from "agents/mcp/server";
import { APP_VERSION, type Env } from "./env";
import { buildMcpServer } from "./mcp";
import { apiRoutes, catalog } from "./http";
import { billingPage, docsPage, privacyPage, landingPage, llmsTxt, openApi, serverCard } from "./pages";
import { createCheckout, handleStripeWebhook } from "./billing/stripe";
import { x402Enabled } from "./billing/x402";
import { handleCore } from "./core/proxy";
import { KINDS, searchCatalog, type Kind } from "./catalog";
import { demandReport, logSearch, relatedTo } from "./growth";
import { runFreshness } from "./refresh";
import { handleA2A } from "./a2a";
import { facilitatorEnabled, facilitatorNetworks, facilitatorPaused, facilitatorStats, handleFacilitator } from "./facilitator";
import { admin } from "./admin";
import { edgeCache } from "./edgecache";
import { loadPrices } from "./prices";
import { wantedList, wantedPage } from "./discovery";
import { agentCard, catalogItemMarkdown, catalogItemPage, DISCOVERY_LINK_HEADER, llmsFullTxt, marketItem, marketMarkdown, marketPage, robotsTxt, sitemapFor, sitemapIndex, x402Discovery } from "./discovery";

type AppEnv = { Bindings: Env };

const app = new Hono<AppEnv>();

// Outermost, so a cache hit skips everything below (src/edgecache.ts).
app.use("*", edgeCache);

// Every response points agents at the machine-readable entry points.
app.use("*", async (c, next) => {
  await next();
  if (!c.res.headers.has("link")) c.res.headers.set("link", DISCOVERY_LINK_HEADER);
});

const html = (body: string) => new Response(body, { headers: { "content-type": "text/html; charset=utf-8" } });

app.get("/", (c) => html(landingPage(c.env)));
app.get("/docs", (c) => html(docsPage(c.env)));
app.get("/privacy", (c) => html(privacyPage(c.env)));
app.get("/billing", (c) => html(billingPage(c.env, c.req.query("paid") === "1")));
app.get("/llms.txt", (c) => c.text(llmsTxt(c.env)));
app.get("/openapi.json", (c) => c.json(openApi(c.env)));
app.get("/.well-known/mcp/server-card.json", (c) => c.json(serverCard(c.env)));
app.get("/.well-known/mcp.json", (c) => c.json(serverCard(c.env)));
const xml = (body: string) => new Response(body, { headers: { "content-type": "application/xml", "cache-control": "public, max-age=3600" } });
app.get("/robots.txt", (c) => c.text(robotsTxt(c.env)));
app.get("/sitemap.xml", (c) => xml(sitemapIndex(c.env)));
app.get("/sitemaps/:name{[a-z]+\\.xml}", async (c) => {
  const map = await sitemapFor(c.env, c.req.param("name").replace(/\.xml$/, ""));
  return map ? xml(map) : c.notFound();
});
app.get("/llms-full.txt", (c) => c.text(llmsFullTxt(c.env, llmsTxt(c.env))));
app.get("/.well-known/agent-card.json", (c) => c.json(agentCard(c.env)));
app.get("/.well-known/agent.json", (c) => c.json(agentCard(c.env)));
app.get("/.well-known/x402", (c) => c.json(x402Discovery(c.env)));
const wantsMarkdown = (accept: string | undefined) => /text\/markdown/i.test(accept ?? "");
const markdown = (body: string) => new Response(body, { headers: { "content-type": "text/markdown; charset=utf-8", vary: "Accept" } });
app.get("/market", async (c) => {
  const kind = c.req.query("kind");
  const k = KINDS.includes(kind as Kind) ? (kind as Kind) : undefined;
  const q = c.req.query("q") ?? "";
  if (q) {
    const { total } = await searchCatalog(c.env, { q, kind: k, limit: 1 });
    logSearch(c.env, c.executionCtx as unknown as ExecutionContext, q, k, total, "web");
  }
  return wantsMarkdown(c.req.header("accept")) ? markdown(await marketMarkdown(c.env, q, k)) : html(await marketPage(c.env, q, k));
});
app.post("/a2a", (c) => handleA2A(c.req.raw, c.env, c.executionCtx as unknown as ExecutionContext));
app.get("/facilitator", async (c) => c.json({
  name: "AIPayGen x402 facilitator",
  non_custodial: true,
  endpoints: { supported: "GET /facilitator/supported", verify: "POST /facilitator/verify", settle: "POST /facilitator/settle (Authorization: Bearer apg_...)" },
  enabled: facilitatorEnabled(c.env),
  paused: await facilitatorPaused(c.env).catch(() => false),
  networks: facilitatorNetworks(c.env),
  stats: await facilitatorStats(c.env).catch(() => null),
  use_it: "Set your x402 resource server's facilitator URL to https://aipaygen.com/facilitator and pass your apg_ key for settle.",
}));
app.all("/facilitator/*", (c) => handleFacilitator(c.req.raw, c.env, c.executionCtx as unknown as ExecutionContext));
app.get("/market/wanted", async (c) => html(await wantedPage(c.env)));
app.get("/v1/catalog/wanted", async (c) => c.json(await wantedList(c.env), 200, { "cache-control": "public, max-age=600" }));
app.get("/market/:kind/:id", async (c) => {
  const item = await marketItem(c.env, c.req.param("kind"), c.req.param("id"));
  if (!item) return c.notFound();
  if (wantsMarkdown(c.req.header("accept"))) return markdown(catalogItemMarkdown(c.env, item));
  return html(catalogItemPage(c.env, item, await relatedTo(c.env, item.name, item.id, 6)));
});
app.get("/bot", (c) => c.text("AIPayGenBot fetches public pages only when an AIPayGen user asks about a site. It makes one request per lookup and caches results."));

app.get("/health", async (c) => {
  let db = false;
  try {
    await c.env.DB.prepare("SELECT 1").first();
    db = true;
  } catch {
    db = false;
  }
  return c.json({ ok: db, version: APP_VERSION, db, x402: x402Enabled(c.env), tools: catalog(c.env).length }, db ? 200 : 503);
});

app.route("/v1", apiRoutes());

app.post("/billing/checkout", async (c) => {
  let body: { api_key?: string; pack?: string } = {};
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }
  const r = await createCheckout(c.env, body.api_key ?? "", body.pack ?? "");
  return "url" in r ? c.json({ url: r.url }) : c.json({ error: r.error }, r.status as 400);
});

app.post("/billing/webhook", async (c) => {
  const payload = await c.req.text();
  const r = await handleStripeWebhook(c.env, payload, c.req.header("stripe-signature") ?? null);
  return c.json({ received: r.status === 200, status: r.message }, r.status as 200);
});

// Owner controls (src/admin.ts). The three GET routes below are matched first and keep their own checks.
app.get("/admin/freshness", async (c) => {
  const token = c.env.ADMIN_TOKEN;
  if (!token || c.req.header("authorization") !== `Bearer ${token}`) return c.json({ error: "unauthorized" }, 401);
  const [last, sources] = await c.env.DB.batch([
    c.env.DB.prepare("SELECT value, updated_at FROM sync_state WHERE key = 'last_freshness_run'"),
    c.env.DB.prepare("SELECT source, COUNT(*) AS items, SUM(fail_count >= 3) AS hidden, SUM(checked_at > 0) AS checked FROM catalog GROUP BY source"),
  ]);
  return c.json({ last_run: last?.results[0] ?? null, sources: sources?.results ?? [] });
});

app.get("/admin/demand", async (c) => {
  const token = c.env.ADMIN_TOKEN;
  if (!token || c.req.header("authorization") !== `Bearer ${token}`) return c.json({ error: "unauthorized" }, 401);
  return c.json(await demandReport(c.env, Math.min(Number(c.req.query("days")) || 30, 365)));
});

app.get("/admin/stats", async (c) => {
  const token = c.env.ADMIN_TOKEN;
  if (!token || c.req.header("authorization") !== `Bearer ${token}`) return c.json({ error: "unauthorized" }, 401);
  const since = Date.now() - 30 * 86_400_000;
  const [byTool, byDay, keys] = await Promise.all([
    c.env.DB.prepare(
      "SELECT tool, payment, COUNT(*) AS calls, SUM(ok) AS ok, SUM(CASE WHEN ok = 1 THEN price_micro ELSE 0 END) AS revenue_micro FROM usage WHERE created_at > ? GROUP BY tool, payment ORDER BY revenue_micro DESC",
    ).bind(since).all(),
    c.env.DB.prepare(
      "SELECT date(created_at / 1000, 'unixepoch') AS day, COUNT(*) AS calls, SUM(CASE WHEN ok = 1 THEN price_micro ELSE 0 END) AS revenue_micro, COUNT(DISTINCT payer) AS payers FROM usage WHERE created_at > ? GROUP BY day ORDER BY day",
    ).bind(since).all(),
    c.env.DB.prepare("SELECT COUNT(*) AS keys, SUM(balance_micro) AS outstanding_micro FROM api_keys").first(),
  ]);
  return c.json({ window_days: 30, by_tool: byTool.results, by_day: byDay.results, keys });
});

app.route("/admin", admin);

// When the database is unavailable (most likely D1's daily free quota, which resets at
// midnight UTC), say so with a 503 and Retry-After instead of a bare 500.
app.onError((err, c) => {
  const message = err instanceof Error ? err.message : String(err);
  console.log("unhandled", c.req.path, message.slice(0, 300));
  if (!/D1_|row read limit|daily .*limit|exceeded .*quota/i.test(message)) return c.json({ error: { code: "INTERNAL", message: "Something went wrong. Try again." } }, 500);
  const now = new Date();
  const retry = Math.max(60, Math.ceil((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1) - now.getTime()) / 1000));
  const headers = { "retry-after": String(retry), "cache-control": "no-store" };
  const text = "The AIPayGen catalog is temporarily unavailable and will be back by 00:00 UTC. Tools that don't use the catalog still work.";
  if (/text\/html/i.test(c.req.header("accept") ?? "")) {
    return c.html(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIPayGen: back soon</title><body style="font:16px/1.5 system-ui;max-width:34rem;margin:18vh auto;padding:0 1.25rem;color:#e8eaf0;background:#0b0d12"><h1 style="font-size:1.4rem">The catalog is taking a short break</h1><p>${text}</p><p><a style="color:#6cc7ff" href="/">Back to the homepage</a></p></body>`, 503, headers);
  }
  return c.json({ error: { code: "TEMPORARILY_UNAVAILABLE", message: text, retry_after_seconds: retry } }, 503, headers);
});

app.notFound(async (c) => {
  // Anything the Worker doesn't serve itself belongs to the core (v1 marketplace), when it is configured.
  const core = await handleCore(c.req.raw, c.env, c.executionCtx as unknown as ExecutionContext);
  return core ?? c.json({ error: { code: "NOT_FOUND", message: "Not found. See /docs." } }, 404);
});

export default {
  // Cron trigger (wrangler.jsonc): keep the catalog fresh. See src/refresh.ts.
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (event.cron === RECONCILE_CRON) {
      ctx.waitUntil(reconcilePayments(env).then((r) => console.log("reconcile", JSON.stringify(r))));
      return;
    }
    ctx.waitUntil(runFreshness(env).then((r) => console.log("freshness", JSON.stringify(r))));
  },

  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    // Owner price overrides (src/prices.ts): one cached read per isolate per minute.
    await loadPrices(env);
    if (url.pathname === "/mcp") {
      const host = new URL(env.PUBLIC_URL).hostname;
      // mcp.* and api.* keep the hostnames used by existing directory listings working.
      const hosts = [host, `www.${host}`, `mcp.${host}`, `api.${host}`, "localhost", "127.0.0.1"];
      const handler = createMcpHandler(() => buildMcpServer(env, ctx), {
        route: "/mcp",
        allowedHostnames: hosts,
        allowedOriginHostnames: [...hosts, "playground.ai.cloudflare.com", "inspector.modelcontextprotocol.io"],
      });
      return handler(request, env, ctx);
    }
    return app.fetch(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
