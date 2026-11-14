import { Hono } from "hono";
import { OWNER_HIDDEN } from "./catalog";
import type { Env } from "./env";
import { facilitatorPaused, setFacilitatorPaused } from "./facilitator";
import { runFreshness } from "./refresh";
import { addCredits, sha256Hex } from "./billing/keys";
import { checkPrice, defaultPrice, getOverrides, setPrice } from "./prices";
import { TOOLS } from "./tools";

/**
 * Owner controls, used by the Mac app (apps/mac). Every route needs
 * Authorization: Bearer <ADMIN_TOKEN>.
 *
 *   GET  /admin/overview            what the controls currently say
 *   POST /admin/refresh             run the 10-minute update now
 *   POST /admin/facilitator         { "paused": true|false }   stop or resume settlements
 *   POST /admin/catalog/hide        { "id": "api:...", "hidden": true|false }
 *   GET  /admin/money               earnings today / 7d / 30d, top tools, recent sales
 *   GET  /admin/sales?after=<id>    sales newer than id (cheap; the app polls it for alerts)
 *   GET  /admin/prices              every paid tool's code price and live price
 *   POST /admin/prices              { "tool": "...", "price_micro": 20000 | null }   null = back to default
 *   GET  /admin/keys?q=...          find API keys by full key, id, prefix or label
 *   POST /admin/keys/credit         { "id": "...", "amount_micro": 50000 }   add free credits
 *   POST /admin/keys/disable        { "id": "...", "disabled": true|false }
 *
 * Every query here is indexed and limited: the database has a daily read quota.
 */

/** Compares digests, so timing doesn't leak how much of the token matched. */
export async function isAdmin(env: Pick<Env, "ADMIN_TOKEN">, header: string | undefined | null): Promise<boolean> {
  if (!env.ADMIN_TOKEN || !header) return false;
  const enc = new TextEncoder();
  const [a, b] = (await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(header)),
    crypto.subtle.digest("SHA-256", enc.encode(`Bearer ${env.ADMIN_TOKEN}`)),
  ])).map((d) => new Uint8Array(d));
  let diff = 0;
  for (let i = 0; i < a!.length; i++) diff |= a![i]! ^ b![i]!;
  return diff === 0;
}

export const admin = new Hono<{ Bindings: Env }>();

admin.use("*", async (c, next) => {
  if (!(await isAdmin(c.env, c.req.header("authorization")))) return c.json({ error: "unauthorized" }, 401);
  await next();
});

interface HiddenItem { id: string; kind: string; name: string }

/** Owner-hidden listings are tracked in sync_state, so listing them doesn't scan the catalog. */
async function hiddenList(env: Env): Promise<HiddenItem[]> {
  const r = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'owner_hidden'").first<{ value: string }>();
  try {
    const v = JSON.parse(r?.value ?? "[]") as unknown;
    return Array.isArray(v) ? (v as HiddenItem[]) : [];
  } catch {
    return [];
  }
}

admin.get("/overview", async (c) => {
  const last = await c.env.DB.prepare("SELECT value FROM sync_state WHERE key = 'last_freshness_run'").first<{ value: string }>();
  let lastRun: unknown = null;
  try {
    lastRun = JSON.parse(last?.value ?? "null");
  } catch {
    // leave null
  }
  return c.json({ facilitator_paused: await facilitatorPaused(c.env, true), last_run: lastRun, hidden: await hiddenList(c.env) });
});

admin.post("/refresh", async (c) => c.json({ ok: true, result: await runFreshness(c.env) }));

admin.post("/facilitator", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { paused?: unknown } | null;
  if (typeof body?.paused !== "boolean") return c.json({ error: 'Send { "paused": true } or { "paused": false }.' }, 400);
  await setFacilitatorPaused(c.env, body.paused);
  return c.json({ ok: true, facilitator_paused: body.paused });
});

admin.post("/catalog/hide", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { id?: unknown; hidden?: unknown } | null;
  if (typeof body?.id !== "string" || typeof body.hidden !== "boolean") return c.json({ error: 'Send { "id": "...", "hidden": true|false }.' }, 400);
  const item = await c.env.DB.prepare("SELECT id, kind, name FROM catalog WHERE id = ?").bind(body.id).first<HiddenItem>();
  if (!item) return c.json({ error: "No listing with that id." }, 404);
  const list = (await hiddenList(c.env)).filter((h) => h.id !== item.id);
  if (body.hidden) list.unshift(item);
  await c.env.DB.batch([
    // Unhiding sets 0, so the next health check decides from scratch.
    c.env.DB.prepare("UPDATE catalog SET fail_count = ? WHERE id = ?").bind(body.hidden ? OWNER_HIDDEN : 0, item.id),
    c.env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('owner_hidden', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
      .bind(JSON.stringify(list.slice(0, 500)), Date.now()),
  ]);
  return c.json({ ok: true, id: body.id, hidden: body.hidden });
});

// ───────────── Money ─────────────

const DAY = 86_400_000;

interface Sale { id: number; tool: string; payment: string; payer: string | null; price_micro: number; tx: string | null; created_at: number }

admin.get("/money", async (c) => {
  const now = Date.now();
  const startOfDay = new Date(new Date(now).toISOString().slice(0, 10)).getTime(); // midnight UTC
  const since30 = now - 30 * DAY;
  const [totals, byTool, recent] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT
         SUM(CASE WHEN created_at >= ?1 THEN price_micro ELSE 0 END) AS today_micro,
         SUM(CASE WHEN created_at >= ?1 THEN 1 ELSE 0 END) AS today_calls,
         SUM(CASE WHEN created_at >= ?2 THEN price_micro ELSE 0 END) AS week_micro,
         SUM(CASE WHEN created_at >= ?2 THEN 1 ELSE 0 END) AS week_calls,
         SUM(price_micro) AS month_micro,
         COUNT(*) AS month_calls,
         SUM(CASE WHEN payment = 'x402' THEN price_micro ELSE 0 END) AS month_x402_micro,
         COUNT(DISTINCT payer) AS month_payers
       FROM usage WHERE created_at >= ?3 AND ok = 1`,
    ).bind(startOfDay, now - 7 * DAY, since30),
    c.env.DB.prepare(
      "SELECT tool, COUNT(*) AS calls, SUM(price_micro) AS revenue_micro FROM usage WHERE created_at >= ? AND ok = 1 GROUP BY tool ORDER BY revenue_micro DESC LIMIT 15",
    ).bind(since30),
    c.env.DB.prepare("SELECT id, tool, payment, payer, price_micro, tx, created_at FROM usage WHERE ok = 1 ORDER BY id DESC LIMIT 25"),
  ]);
  const t = (totals?.results[0] ?? {}) as Record<string, number | null>;
  const n = (k: string) => Number(t[k] ?? 0);
  return c.json({
    pay_to: c.env.PAY_TO,
    network: c.env.X402_NETWORK,
    today: { revenue_micro: n("today_micro"), calls: n("today_calls") },
    week: { revenue_micro: n("week_micro"), calls: n("week_calls") },
    month: { revenue_micro: n("month_micro"), calls: n("month_calls"), x402_micro: n("month_x402_micro"), payers: n("month_payers") },
    by_tool: byTool?.results ?? [],
    recent: (recent?.results ?? []) as unknown as Sale[],
  });
});

admin.get("/sales", async (c) => {
  const after = Math.max(0, Math.floor(Number(c.req.query("after")) || 0));
  // Primary-key range: reads only the new rows.
  const r = await c.env.DB.prepare("SELECT id, tool, payment, payer, price_micro, tx, created_at FROM usage WHERE id > ? AND ok = 1 ORDER BY id LIMIT 20")
    .bind(after).all<Sale>();
  const last = await c.env.DB.prepare("SELECT MAX(id) AS id FROM usage").first<{ id: number | null }>();
  return c.json({ sales: r.results, last_id: last?.id ?? 0 });
});

// ───────────── Prices ─────────────

admin.get("/prices", async (c) => {
  const overrides = await getOverrides(c.env);
  return c.json({
    tools: TOOLS.filter((t) => (defaultPrice(t.name) ?? 0) > 0).map((t) => ({
      name: t.name,
      title: t.title,
      default_micro: defaultPrice(t.name),
      price_micro: overrides[t.name] ?? defaultPrice(t.name),
      overridden: t.name in overrides,
    })),
  });
});

admin.post("/prices", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { tool?: unknown; price_micro?: unknown } | null;
  if (typeof body?.tool !== "string") return c.json({ error: 'Send { "tool": "...", "price_micro": 20000 } (or null to reset).' }, 400);
  if (body.price_micro !== null) {
    const err = checkPrice(body.tool, body.price_micro);
    if (err) return c.json({ error: err }, 400);
  } else if (defaultPrice(body.tool) === undefined) {
    return c.json({ error: "No tool with that name." }, 400);
  }
  const overrides = await setPrice(c.env, body.tool, body.price_micro as number | null);
  return c.json({ ok: true, tool: body.tool, price_micro: overrides[body.tool] ?? defaultPrice(body.tool) });
});

// ───────────── API keys ─────────────

interface KeyRow { id: string; key_prefix: string; label: string | null; balance_micro: number; created_at: number; disabled: number }

admin.get("/keys", async (c) => {
  const q = (c.req.query("q") ?? "").trim();
  const cols = "SELECT id, key_prefix, label, balance_micro, created_at, disabled FROM api_keys";
  let rows: KeyRow[] = [];
  if (!q) {
    rows = (await c.env.DB.prepare(`${cols} ORDER BY created_at DESC LIMIT 10`).all<KeyRow>()).results;
  } else if (/^apg_[A-Za-z0-9_-]{20,}$/.test(q)) {
    const hit = await c.env.DB.prepare(`${cols} WHERE key_hash = ?`).bind(await sha256Hex(q)).first<KeyRow>();
    rows = hit ? [hit] : [];
  } else {
    const like = `%${q.replace(/[%_\\]/g, (m) => `\\${m}`)}%`;
    rows = (await c.env.DB.prepare(`${cols} WHERE id = ? OR key_prefix LIKE ? ESCAPE '\\' OR label LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 10`)
      .bind(q, like, like).all<KeyRow>()).results;
  }
  const since = Date.now() - 30 * DAY;
  const keys = await Promise.all(rows.map(async (k) => {
    const [use, ledger] = await c.env.DB.batch([
      c.env.DB.prepare("SELECT COUNT(*) AS calls, SUM(CASE WHEN ok = 1 THEN price_micro ELSE 0 END) AS spent_micro, MAX(created_at) AS last_used FROM usage WHERE payer = ? AND created_at >= ?").bind(k.id, since),
      c.env.DB.prepare("SELECT delta_micro, reason, created_at FROM ledger WHERE key_id = ? ORDER BY created_at DESC LIMIT 8").bind(k.id),
    ]);
    const u = (use?.results[0] ?? {}) as { calls?: number; spent_micro?: number | null; last_used?: number | null };
    return { ...k, disabled: k.disabled === 1, calls_30d: u.calls ?? 0, spent_30d_micro: u.spent_micro ?? 0, last_used: u.last_used ?? null, ledger: ledger?.results ?? [] };
  }));
  return c.json({ keys });
});

const MAX_GRANT_MICRO = 100_000_000; // $100 per grant

admin.post("/keys/credit", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { id?: unknown; amount_micro?: unknown } | null;
  const amount = body?.amount_micro;
  if (typeof body?.id !== "string" || typeof amount !== "number" || !Number.isInteger(amount) || amount <= 0 || amount > MAX_GRANT_MICRO) {
    return c.json({ error: 'Send { "id": "...", "amount_micro": 50000 } (positive, up to $100).' }, 400);
  }
  const key = await c.env.DB.prepare("SELECT id FROM api_keys WHERE id = ?").bind(body.id).first();
  if (!key) return c.json({ error: "No API key with that id." }, 404);
  await addCredits(c.env, body.id, amount, "owner_grant", `owner:${crypto.randomUUID()}`);
  const after = await c.env.DB.prepare("SELECT balance_micro FROM api_keys WHERE id = ?").bind(body.id).first<{ balance_micro: number }>();
  return c.json({ ok: true, id: body.id, balance_micro: after?.balance_micro ?? null });
});

admin.post("/keys/disable", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { id?: unknown; disabled?: unknown } | null;
  if (typeof body?.id !== "string" || typeof body.disabled !== "boolean") return c.json({ error: 'Send { "id": "...", "disabled": true|false }.' }, 400);
  const r = await c.env.DB.prepare("UPDATE api_keys SET disabled = ? WHERE id = ?").bind(body.disabled ? 1 : 0, body.id).run();
  if (!r.meta.changes) return c.json({ error: "No API key with that id." }, 404);
  return c.json({ ok: true, id: body.id, disabled: body.disabled });
});
