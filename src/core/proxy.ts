import { encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { z } from "zod";
import table from "../../pricing/core-routes.json";
import { chargeAndRun } from "../billing/charge";
import { apiKeyFromHeaders } from "../billing/keys";
import type { Env } from "../env";
import { ToolError } from "../lib/errors";
import type { ToolDef } from "../tools/types";

/**
 * The core (v1 marketplace, Python) sits behind the Cloudflare Tunnel. The Worker
 * is its only way in and its only payment layer: priced routes from
 * pricing/core-routes.json are charged here (credits or x402, settled only when
 * the core answers 2xx), then forwarded with a signature the core verifies
 * (core/edge_auth.py). Everything else is forwarded free.
 */

export interface CoreRoute {
  method: "GET" | "POST";
  path: string;
  price_micro: number;
  description: string;
}

export const CORE_ROUTES = table.routes as CoreRoute[];
const PRICED = new Map(CORE_ROUTES.map((r) => [`${r.method} ${r.path}`, r]));

export function corePrice(method: string, pathname: string): CoreRoute | undefined {
  return PRICED.get(`${method.toUpperCase()} ${pathname}`);
}

const enc = (s: string) => new TextEncoder().encode(s);
const hex = (buf: ArrayBuffer) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

/** Must build the same string as canonical() in core/edge_auth.py. */
export async function signCoreRequest(
  secret: string, ts: string, method: string, path: string, body: Uint8Array, paid: string, clientIp: string,
): Promise<string> {
  const msg = ["v1", ts, method.toUpperCase(), path, hex(await crypto.subtle.digest("SHA-256", body)), paid, clientIp].join("\n");
  const key = await crypto.subtle.importKey("raw", enc(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, enc(msg)));
}

// Never forwarded: hop-by-hop headers, client-supplied identity/IP claims, our own
// signature headers, and payment credentials the Worker has already consumed.
const DROP = new Set(["host", "connection", "content-length", "x-forwarded-for", "x-real-ip", "payment-signature", "x-payment"]);

async function forward(env: Env, request: Request, body: Uint8Array, paid: string): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname + url.search;
  const ts = String(Math.floor(Date.now() / 1000));
  const clientIp = request.headers.get("cf-connecting-ip") ?? "";
  const headers = new Headers();
  for (const [k, v] of request.headers) {
    const l = k.toLowerCase();
    if (DROP.has(l) || l.startsWith("x-aipaygen-") || l.startsWith("cf-")) continue;
    if (l === "authorization" && /^bearer\s+apg_/i.test(v)) continue; // Worker billing key, not the core's
    headers.set(k, v);
  }
  headers.set("x-aipaygen-edge-ts", ts);
  headers.set("x-aipaygen-paid", paid);
  headers.set("x-aipaygen-client-ip", clientIp);
  headers.set("x-aipaygen-edge-sig", await signCoreRequest(env.CORE_EDGE_SECRET!, ts, request.method, path, body, paid, clientIp));
  const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
  return fetch(new URL(path, env.CORE_ORIGIN), { method: request.method, headers, body: hasBody ? body : undefined, redirect: "manual" });
}

const jsonResponse = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

/** Handle a request bound for the core, or return null when core routes are off. */
export async function handleCore(request: Request, env: Env, ctx?: ExecutionContext): Promise<Response | null> {
  if (!env.CORE_ORIGIN || !env.CORE_EDGE_SECRET) return null;
  const url = new URL(request.url);
  const body = new Uint8Array(await request.arrayBuffer());
  const route = corePrice(request.method, url.pathname);
  if (!route) return forward(env, request, body, "free");

  const apiKey = apiKeyFromHeaders(request.headers);
  if (env.TOOL_LIMITER) {
    const who = apiKey ?? request.headers.get("cf-connecting-ip") ?? "unknown";
    if (!(await env.TOOL_LIMITER.limit({ key: who })).success) {
      return jsonResponse(429, { error: { code: "RATE_LIMITED", message: "Too many calls. Slow down to 60 per minute." } }, { "retry-after": "60" });
    }
  }

  let core: { status: number; contentType: string; text: string } | null = null;
  const tool: ToolDef = {
    name: `${route.method} ${route.path}`,
    title: route.path,
    description: route.description,
    priceMicro: route.price_micro,
    cacheTtl: 0,
    input: z.object({}).passthrough(),
    example: {},
    httpMethod: route.method,
    async run() {
      const res = await forward(env, request, body, apiKey ? "credits" : "x402");
      const text = await res.text();
      if (res.status < 200 || res.status >= 300) {
        let code = "CORE_ERROR";
        let message = text.slice(0, 300) || `Core returned ${res.status}`;
        try {
          const j = JSON.parse(text) as { error?: unknown; message?: unknown };
          if (typeof j.error === "string") code = j.error.toUpperCase();
          if (typeof j.message === "string") message = j.message;
        } catch {
          // not JSON
        }
        throw new ToolError(message, code, res.status); // not charged
      }
      core = { status: res.status, contentType: res.headers.get("content-type") ?? "application/json", text };
      return {};
    },
  };

  const outcome = await chargeAndRun({
    env,
    ctx,
    tool,
    args: {},
    channel: "http",
    payment: { apiKey, paymentToken: request.headers.get("payment-signature") ?? request.headers.get("x-payment") },
    resourceUrl: `${env.PUBLIC_URL}${route.path}`,
  });

  if (outcome.kind === "ok" && core) {
    const done = core as { status: number; contentType: string; text: string };
    const headers: Record<string, string> = { "content-type": done.contentType, "x-aipaygen-price": outcome.receipt.price };
    if (outcome.receipt.balance_remaining) headers["x-aipaygen-balance"] = outcome.receipt.balance_remaining;
    if (outcome.receipt.payment === "x402" && outcome.receipt.transaction) {
      headers["payment-response"] = encodePaymentResponseHeader({
        success: true,
        transaction: outcome.receipt.transaction,
        network: outcome.receipt.network as `${string}:${string}`,
      } as Parameters<typeof encodePaymentResponseHeader>[0]);
    }
    return new Response(done.text, { status: done.status, headers });
  }
  if (outcome.kind === "payment_required") {
    return jsonResponse(402, outcome.body, {
      "payment-required": encodePaymentRequiredHeader(outcome.body as unknown as Parameters<typeof encodePaymentRequiredHeader>[0]),
      "cache-control": "private, no-store",
    });
  }
  if (outcome.kind === "error") return jsonResponse(outcome.status, { error: { code: outcome.code, message: outcome.message } });
  return jsonResponse(502, { error: { code: "CORE_ERROR", message: "The core returned no response." } });
}
