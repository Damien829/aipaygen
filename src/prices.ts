import type { Env } from "./env";
import { TOOLS } from "./tools";

/**
 * Owner price overrides, set from the Mac app (POST /admin/prices).
 *
 * Stored as one JSON row in sync_state ({ "tool_name": micro }). Each isolate
 * reloads it at most once a minute, so it costs one row read per isolate per
 * minute, not one per call (D1 free plan: 5M reads/day). Overrides are applied
 * to the shared TOOLS objects, so every page, quote and charge sees the same
 * price.
 */

export const MIN_PRICE_MICRO = 1_000; // $0.001
export const MAX_PRICE_MICRO = 10_000_000; // $10
const KEY = "price_overrides";
const TTL_MS = 60_000;

/** Prices in the code, captured before any override touches them. */
const DEFAULTS = new Map(TOOLS.map((t) => [t.name, t.priceMicro]));
let loadedAt = 0;
let loading: Promise<void> | null = null;

export function defaultPrice(tool: string): number | undefined {
  return DEFAULTS.get(tool);
}

/** Free tools stay free; paid tools must stay within MIN..MAX. Returns an error message, or null when valid. */
export function checkPrice(tool: string, micro: unknown): string | null {
  const base = DEFAULTS.get(tool);
  if (base === undefined) return "No tool with that name.";
  if (base === 0) return "That tool is free and stays free.";
  if (typeof micro !== "number" || !Number.isInteger(micro)) return "Price must be a whole number of micro-USD.";
  if (micro < MIN_PRICE_MICRO || micro > MAX_PRICE_MICRO) return `Price must be between $${MIN_PRICE_MICRO / 1e6} and $${MAX_PRICE_MICRO / 1e6}.`;
  return null;
}

/** Keeps only valid entries, so a bad row can never set a broken price. */
export function parseOverrides(raw: string | null | undefined): Record<string, number> {
  let v: unknown;
  try {
    v = JSON.parse(raw ?? "{}");
  } catch {
    return {};
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  const out: Record<string, number> = {};
  for (const [tool, micro] of Object.entries(v)) if (checkPrice(tool, micro) === null) out[tool] = micro as number;
  return out;
}

function apply(overrides: Record<string, number>): void {
  for (const t of TOOLS) t.priceMicro = overrides[t.name] ?? DEFAULTS.get(t.name) ?? t.priceMicro;
}

async function read(env: Env): Promise<Record<string, number>> {
  const row = await env.DB.prepare("SELECT value FROM sync_state WHERE key = ?").bind(KEY).first<{ value: string }>();
  return parseOverrides(row?.value);
}

/** Call at the start of each request. Cheap: reloads at most once a minute per isolate. */
export async function loadPrices(env: Env): Promise<void> {
  if (Date.now() - loadedAt < TTL_MS) return;
  loading ??= read(env)
    .then(apply)
    .catch(() => {}) // keep the current prices if the database is unavailable
    .finally(() => {
      loadedAt = Date.now();
      loading = null;
    });
  await loading;
}

export async function getOverrides(env: Env): Promise<Record<string, number>> {
  return read(env);
}

/** Sets (micro) or clears (null) one tool's price, and applies it in this isolate right away. */
export async function setPrice(env: Env, tool: string, micro: number | null): Promise<Record<string, number>> {
  const overrides = await read(env);
  if (micro === null || micro === DEFAULTS.get(tool)) delete overrides[tool];
  else overrides[tool] = micro;
  await env.DB.prepare(
    "INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
  ).bind(KEY, JSON.stringify(overrides), Date.now()).run();
  apply(overrides);
  loadedAt = Date.now();
  return overrides;
}
