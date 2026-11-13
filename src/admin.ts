import { Hono } from "hono";
import { OWNER_HIDDEN } from "./catalog";
import type { Env } from "./env";
import { facilitatorPaused, setFacilitatorPaused } from "./facilitator";
import { runFreshness } from "./refresh";

/**
 * Owner controls, used by the Mac app (apps/mac). Every route needs
 * Authorization: Bearer <ADMIN_TOKEN>.
 *
 *   GET  /admin/overview            what the controls currently say
 *   POST /admin/refresh             run the 10-minute update now
 *   POST /admin/facilitator         { "paused": true|false }   stop or resume settlements
 *   POST /admin/catalog/hide        { "id": "api:...", "hidden": true|false }
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
