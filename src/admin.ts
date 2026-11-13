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

admin.get("/overview", async (c) => {
  const [last, hidden] = await c.env.DB.batch([
    c.env.DB.prepare("SELECT value FROM sync_state WHERE key = 'last_freshness_run'"),
    c.env.DB.prepare("SELECT id, kind, name FROM catalog WHERE fail_count >= ? ORDER BY updated_at DESC LIMIT 50").bind(OWNER_HIDDEN),
  ]);
  let lastRun: unknown = null;
  try {
    lastRun = JSON.parse((last?.results[0] as { value?: string } | undefined)?.value ?? "null");
  } catch {
    // leave null
  }
  return c.json({ facilitator_paused: await facilitatorPaused(c.env, true), last_run: lastRun, hidden: hidden?.results ?? [] });
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
  // Unhiding sets 0, so the next health check decides from scratch.
  const r = await c.env.DB.prepare("UPDATE catalog SET fail_count = ? WHERE id = ?").bind(body.hidden ? OWNER_HIDDEN : 0, body.id).run();
  if (!r.meta.changes) return c.json({ error: "No listing with that id." }, 404);
  return c.json({ ok: true, id: body.id, hidden: body.hidden });
});
