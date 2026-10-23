import { HTTPFacilitatorClient, x402ResourceServer } from "@x402/core/server";
import { registerExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";
import { z } from "zod";
import type { Env } from "../env";
import type { ToolDef } from "../tools/types";

type ResourceServer = InstanceType<typeof x402ResourceServer>;
type PaymentRequirements = Awaited<ReturnType<ResourceServer["buildPaymentRequirements"]>>[number];
type PaymentPayload = Parameters<ResourceServer["verifyPayment"]>[0];

export interface PaymentRequiredBody {
  x402Version: 2;
  error: string;
  resource: { url: string; description: string; mimeType: string };
  accepts: PaymentRequirements[];
  extensions?: Record<string, unknown>;
}

let cached: { key: string; server: ResourceServer; ready: Promise<void> } | null = null;

export function x402Enabled(env: Env): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(env.PAY_TO ?? "");
}

function resourceServer(env: Env): { server: ResourceServer; ready: Promise<void> } {
  const key = `${env.FACILITATOR_URL}|${env.X402_NETWORK}`;
  if (cached?.key === key) return cached;
  const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: env.FACILITATOR_URL, timeoutMs: 20_000 }));
  registerExactEvmScheme(server);
  const ready = server.initialize().catch((err: unknown) => {
    cached = null;
    throw err;
  });
  cached = { key, server, ready };
  return cached;
}

export function microToUsd(micro: number): string {
  return `$${(micro / 1_000_000).toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
}

export async function buildRequirements(env: Env, priceMicro: number): Promise<PaymentRequirements[]> {
  const { server, ready } = resourceServer(env);
  await ready;
  return server.buildPaymentRequirements({
    scheme: "exact",
    payTo: env.PAY_TO,
    price: microToUsd(priceMicro),
    network: env.X402_NETWORK as `${string}:${string}`,
    maxTimeoutSeconds: 300,
  });
}

export function toolJsonSchema(tool: ToolDef): Record<string, unknown> {
  const schema = z.toJSONSchema(tool.input) as Record<string, unknown>;
  delete schema.$schema;
  return schema;
}

/** Bazaar discovery metadata so facilitators can catalog this tool. */
export function discoveryExtension(tool: ToolDef, channel: "mcp" | "http"): Record<string, unknown> {
  try {
    if (channel === "mcp") {
      return declareDiscoveryExtension({
        toolName: tool.name,
        description: tool.description,
        transport: "streamable-http",
        inputSchema: toolJsonSchema(tool),
        example: tool.example as Record<string, unknown>,
      });
    }
    const ext = declareDiscoveryExtension({ input: tool.example as Record<string, unknown>, inputSchema: toolJsonSchema(tool) }) as {
      bazaar?: { info?: { input?: Record<string, unknown> } };
    };
    // Normally injected per-route by the HTTP middleware; we build 402s ourselves, so set it here.
    // Without it facilitators reject the listing ("Invalid input at info.input").
    if (ext.bazaar?.info?.input) ext.bazaar.info.input.method = "GET";
    return ext;
  } catch {
    return {};
  }
}

export function paymentRequiredBody(
  tool: ToolDef,
  accepts: PaymentRequirements[],
  resourceUrl: string,
  channel: "mcp" | "http",
  error = "PAYMENT_REQUIRED",
): PaymentRequiredBody {
  return {
    x402Version: 2,
    error,
    resource: { url: resourceUrl, description: tool.description, mimeType: "application/json" },
    accepts,
    extensions: discoveryExtension(tool, channel),
  };
}

export function decodePaymentToken(token: string): PaymentPayload | null {
  try {
    return JSON.parse(atob(token)) as PaymentPayload;
  } catch {
    return null;
  }
}

export async function verifyPayment(env: Env, payload: PaymentPayload, accepts: PaymentRequirements[]) {
  const { server, ready } = resourceServer(env);
  await ready;
  const match = server.findMatchingRequirements(accepts, payload);
  if (!match) return { ok: false as const, reason: "INVALID_PAYMENT" };
  try {
    const vr = await server.verifyPayment(payload, match);
    return vr.isValid ? { ok: true as const, match, payer: vr.payer ?? null } : { ok: false as const, reason: vr.invalidReason ?? "INVALID_PAYMENT" };
  } catch {
    return { ok: false as const, reason: "VERIFY_FAILED" };
  }
}

export async function settlePayment(env: Env, payload: PaymentPayload, match: PaymentRequirements) {
  const { server, ready } = resourceServer(env);
  await ready;
  try {
    const s = await server.settlePayment(payload, match);
    return s.success
      ? { ok: true as const, transaction: s.transaction, network: s.network, payer: s.payer ?? null }
      : { ok: false as const, reason: s.errorReason ?? "SETTLEMENT_FAILED" };
  } catch {
    return { ok: false as const, reason: "SETTLEMENT_FAILED" };
  }
}
