import { Hono, type Context } from "hono";
import { encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { z } from "zod";
import type { Env } from "./env";
import { TOOLS, TOOLS_BY_NAME } from "./tools";
import { formatPrice, type ToolDef } from "./tools/types";
import { apiKeyFromHeaders, createApiKey, findApiKey, sha256Hex } from "./billing/keys";
import { chargeAndRun } from "./billing/charge";
import { microToUsd, toolJsonSchema, x402Enabled } from "./billing/x402";
import { errorMessage } from "./lib/errors";

type AppEnv = { Bindings: Env };

/** Turn query-string values into the types the tool's schema expects. */
export function coerceQuery(tool: ToolDef, query: Record<string, string>): Record<string, unknown> {
  const shape = tool.input.shape as Record<string, z.ZodType>;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(query)) {
    let s = shape[k];
    if (!s) continue;
    while (s instanceof z.ZodOptional || s instanceof z.ZodDefault) s = (s as z.ZodOptional).unwrap() as z.ZodType;
    if (s instanceof z.ZodArray) out[k] = v.split(",").map((x) => x.trim()).filter(Boolean);
    else if (s instanceof z.ZodNumber) out[k] = Number(v);
    else if (s instanceof z.ZodBoolean) out[k] = v === "true" || v === "1";
    else out[k] = v;
  }
  return out;
}

function json(c: Context<AppEnv>, status: number, data: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*", ...headers },
  });
}

async function handleTool(c: Context<AppEnv>, tool: ToolDef) {
  let raw: Record<string, unknown>;
  if (c.req.method === "POST") {
    try {
      raw = (await c.req.json()) as Record<string, unknown>;
    } catch {
      return json(c, 400, { error: { code: "INVALID_JSON", message: "Request body must be JSON." } });
    }
  } else {
    raw = coerceQuery(tool, c.req.query());
  }
  const parsed = tool.input.safeParse(raw);
  if (!parsed.success) {
    return json(c, 400, {
      error: { code: "INVALID_INPUT", message: parsed.error.issues.map((i) => `${i.path.join(".") || "input"}: ${i.message}`).join("; ") },
      input_schema: toolJsonSchema(tool),
      example: tool.example,
    });
  }

  const headers = c.req.raw.headers;
  const apiKey = apiKeyFromHeaders(headers);
  if (c.env.TOOL_LIMITER) {
    const { success } = await c.env.TOOL_LIMITER.limit({ key: apiKey ? await sha256Hex(apiKey) : headers.get("cf-connecting-ip") ?? "unknown" });
    if (!success) return json(c, 429, { error: { code: "RATE_LIMITED", message: "Too many calls. Slow down to 60 per minute." } }, { "retry-after": "60" });
  }

  const outcome = await chargeAndRun({
    env: c.env,
    ctx: c.executionCtx as unknown as ExecutionContext,
    tool,
    args: parsed.data as Record<string, unknown>,
    channel: "http",
    payment: { apiKey, paymentToken: headers.get("payment-signature") ?? headers.get("x-payment") },
    resourceUrl: `${c.env.PUBLIC_URL}/v1/${tool.name}`,
  });

  if (outcome.kind === "ok") {
    const extra: Record<string, string> = { "x-aipaygen-price": outcome.receipt.price, "x-aipaygen-cache": outcome.receipt.cached ? "hit" : "miss" };
    if (outcome.receipt.balance_remaining) extra["x-aipaygen-balance"] = outcome.receipt.balance_remaining;
    if (outcome.receipt.payment === "x402" && outcome.receipt.transaction) {
      extra["payment-response"] = encodePaymentResponseHeader({
        success: true,
        transaction: outcome.receipt.transaction,
        network: outcome.receipt.network as `${string}:${string}`,
      } as Parameters<typeof encodePaymentResponseHeader>[0]);
    }
    return json(c, 200, { tool: tool.name, data: outcome.result, receipt: outcome.receipt }, extra);
  }
  if (outcome.kind === "payment_required") {
    return json(c, 402, outcome.body, {
      "payment-required": encodePaymentRequiredHeader(outcome.body as unknown as Parameters<typeof encodePaymentRequiredHeader>[0]),
      "cache-control": "private, no-store",
    });
  }
  return json(c, outcome.status, { error: { code: outcome.code, message: outcome.message } });
}

export function catalog(env: Env) {
  return TOOLS.map((t) => ({
    name: t.name,
    title: t.title,
    description: t.description,
    price: formatPrice(t.priceMicro),
    price_usd: t.priceMicro / 1_000_000,
    http: `${env.PUBLIC_URL}/v1/${t.name}`,
    input_schema: toolJsonSchema(t),
    example: t.example,
  }));
}

export function apiRoutes(): Hono<AppEnv> {
  const api = new Hono<AppEnv>();

  api.get("/tools", (c) =>
    json(c, 200, {
      payment_methods: { api_key: true, x402: x402Enabled(c.env) ? { network: c.env.X402_NETWORK, asset: "USDC" } : false },
      tools: catalog(c.env),
    }),
  );

  api.post("/keys", async (c) => {
    try {
      const ip = c.req.header("cf-connecting-ip") ?? "unknown";
      if (c.env.KEY_LIMITER && !(await c.env.KEY_LIMITER.limit({ key: ip })).success) {
        return json(c, 429, { error: { code: "RATE_LIMITED", message: "Too many keys created. Try again later." } });
      }
      let label: string | undefined;
      try {
        const body = (await c.req.json()) as { label?: unknown };
        if (typeof body.label === "string") label = body.label;
      } catch {
        // label is optional
      }
      const k = await createApiKey(c.env, { label, creatorHash: await sha256Hex(`creator:${ip}`) });
      return json(c, 201, { api_key: k.api_key, balance: microToUsd(k.balance_micro), note: "Store this key now. It is shown only once." });
    } catch (err) {
      const status = (err as { status?: number }).status ?? 500;
      return json(c, status, { error: { code: (err as { code?: string }).code ?? "INTERNAL", message: errorMessage(err) } });
    }
  });

  api.get("/balance", async (c) => {
    const raw = apiKeyFromHeaders(c.req.raw.headers);
    if (!raw) return json(c, 401, { error: { code: "API_KEY_REQUIRED", message: "Send Authorization: Bearer apg_..." } });
    const key = await findApiKey(c.env, raw);
    if (!key) return json(c, 401, { error: { code: "INVALID_API_KEY", message: "That API key is not valid." } });
    return json(c, 200, { key: `${key.key_prefix}…`, label: key.label, balance: microToUsd(key.balance_micro), balance_micro: key.balance_micro });
  });

  api.on(["GET", "POST"], "/:tool", async (c) => {
    const tool = TOOLS_BY_NAME.get(c.req.param("tool"));
    if (!tool) return json(c, 404, { error: { code: "UNKNOWN_TOOL", message: "No such tool. See /v1/tools." } });
    return handleTool(c, tool);
  });

  return api;
}
