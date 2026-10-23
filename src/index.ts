import { Hono } from "hono";
import { createMcpHandler } from "agents/mcp/server";
import { APP_VERSION, type Env } from "./env";
import { buildMcpServer } from "./mcp";
import { apiRoutes, catalog } from "./http";
import { billingPage, docsPage, landingPage, llmsTxt, openApi, serverCard } from "./pages";
import { createCheckout, handleStripeWebhook } from "./billing/stripe";
import { x402Enabled } from "./billing/x402";

type AppEnv = { Bindings: Env };

const app = new Hono<AppEnv>();

const html = (body: string) => new Response(body, { headers: { "content-type": "text/html; charset=utf-8" } });

app.get("/", (c) => html(landingPage(c.env)));
app.get("/docs", (c) => html(docsPage(c.env)));
app.get("/billing", (c) => html(billingPage(c.env, c.req.query("paid") === "1")));
app.get("/llms.txt", (c) => c.text(llmsTxt(c.env)));
app.get("/openapi.json", (c) => c.json(openApi(c.env)));
app.get("/.well-known/mcp/server-card.json", (c) => c.json(serverCard(c.env)));
app.get("/.well-known/mcp.json", (c) => c.json(serverCard(c.env)));
app.get("/robots.txt", (c) => c.text(`User-agent: *\nAllow: /\nSitemap: ${c.env.PUBLIC_URL}/sitemap.xml\n`));
app.get("/sitemap.xml", (c) => {
  const urls = ["/", "/docs", "/billing", "/llms.txt"].map((p) => `<url><loc>${c.env.PUBLIC_URL}${p}</loc></url>`).join("");
  return c.body(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`, 200, {
    "content-type": "application/xml",
  });
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

app.notFound((c) => c.json({ error: { code: "NOT_FOUND", message: "Not found. See /docs." } }, 404));

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
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
