import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { APP_VERSION, SERVICE_NAME, type Env } from "./env";
import { TOOLS } from "./tools";
import { formatPrice } from "./tools/types";
import { apiKeyFromHeaders, createApiKey, findApiKey, sha256Hex } from "./billing/keys";
import { chargeAndRun, type ChargeOutcome } from "./billing/charge";
import { microToUsd, x402Enabled } from "./billing/x402";
import { errorMessage } from "./lib/errors";

type ToolResult = {
  content: { type: "text"; text: string }[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
  _meta?: Record<string, unknown>;
};

const text = (t: string): ToolResult => ({ content: [{ type: "text", text: t }] });

export function outcomeToToolResult(outcome: ChargeOutcome): ToolResult {
  if (outcome.kind === "ok") {
    const meta: Record<string, unknown> = { "aipaygen/receipt": outcome.receipt };
    if (outcome.receipt.payment === "x402") {
      meta["x402/payment-response"] = { success: true, transaction: outcome.receipt.transaction, network: outcome.receipt.network };
    }
    return { content: [{ type: "text", text: JSON.stringify(outcome.result, null, 2) }], structuredContent: outcome.result, _meta: meta };
  }
  if (outcome.kind === "payment_required") {
    // Shape recommended by the x402 MCP transport (also read by the Cloudflare Agents x402 client).
    return {
      isError: true,
      structuredContent: outcome.body as unknown as Record<string, unknown>,
      content: [{ type: "text", text: JSON.stringify(outcome.body) }],
      _meta: { "x402/error": outcome.body },
    };
  }
  return { isError: true, content: [{ type: "text", text: `${outcome.code}: ${outcome.message}` }] };
}

interface McpContextLike {
  mcpReq?: { _meta?: Record<string, unknown> };
  http?: { req?: Request };
}

function paymentFrom(ctx: McpContextLike) {
  const headers = ctx.http?.req?.headers;
  const metaToken = ctx.mcpReq?._meta?.["x402/payment"];
  return {
    apiKey: apiKeyFromHeaders(headers),
    paymentToken:
      (typeof metaToken === "string" ? metaToken : null) ?? headers?.get("payment-signature") ?? headers?.get("x-payment") ?? null,
  };
}

function clientIp(ctx: McpContextLike): string {
  return ctx.http?.req?.headers.get("cf-connecting-ip") ?? "unknown";
}

/** Build a fresh MCP server for one request (stateless handler). */
export function buildMcpServer(env: Env, execCtx?: ExecutionContext): McpServer {
  const server = new McpServer(
    { name: "aipaygen-site-intel", title: SERVICE_NAME, version: APP_VERSION, websiteUrl: env.PUBLIC_URL },
    {
      instructions:
        "Website and company intelligence from public data. Paid tools accept an API key (Authorization: Bearer apg_...)" +
        (x402Enabled(env) ? " or x402 USDC payments per call. " : ". ") +
        "Call `pricing` to see costs. No key yet? Call `create_api_key` for free trial credits. Failed calls are never charged.",
    },
  );

  for (const tool of TOOLS) {
    server.registerTool(
      tool.name,
      {
        title: tool.title,
        description: `${tool.description} Price: ${formatPrice(tool.priceMicro)} per call.`,
        inputSchema: tool.input,
        annotations: { readOnlyHint: true, openWorldHint: true, idempotentHint: true, destructiveHint: false },
        _meta: { "aipaygen/priceUSD": tool.priceMicro / 1_000_000, "agents-x402/paymentRequired": true, "agents-x402/priceUSD": tool.priceMicro / 1_000_000 },
      },
      async (args: Record<string, unknown>, ctx: McpContextLike) => {
        try {
          const limiter = env.TOOL_LIMITER;
          if (limiter) {
            const p = paymentFrom(ctx);
            const { success } = await limiter.limit({ key: p.apiKey ? await sha256Hex(p.apiKey) : clientIp(ctx) });
            if (!success) return { isError: true, content: [{ type: "text", text: "RATE_LIMITED: Too many calls. Slow down to 60 per minute." }] };
          }
          const outcome = await chargeAndRun({
            env,
            ctx: execCtx,
            tool,
            args,
            channel: "mcp",
            payment: paymentFrom(ctx),
            resourceUrl: `${env.PUBLIC_URL}/mcp#${tool.name}`,
          });
          return outcomeToToolResult(outcome);
        } catch (err) {
          return { isError: true, content: [{ type: "text", text: errorMessage(err) }] };
        }
      },
    );
  }

  server.registerTool(
    "pricing",
    {
      title: "Pricing",
      description: "List every tool with its price per call and the accepted payment methods. Free.",
      inputSchema: z.object({}),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => {
      const data = {
        currency: "USD",
        payment_methods: ["api_key_credits", ...(x402Enabled(env) ? [`x402 (USDC on ${env.X402_NETWORK})`] : [])],
        failed_calls_charged: false,
        tools: TOOLS.map((t) => ({ name: t.name, title: t.title, price: formatPrice(t.priceMicro), price_usd: t.priceMicro / 1_000_000 })),
        top_up: `${env.PUBLIC_URL}/billing`,
      };
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
    },
  );

  server.registerTool(
    "create_api_key",
    {
      title: "Create a free API key",
      description: `Create an AIPayGen API key with ${microToUsd(Number(env.TRIAL_CREDITS_MICRO) || 0)} of free trial credits. Free. Store the key: it is shown only once.`,
      inputSchema: z.object({ label: z.string().max(80).optional().describe("Optional name for the key, e.g. your agent's name") }),
      annotations: { readOnlyHint: false, openWorldHint: false, idempotentHint: false },
    },
    async ({ label }: { label?: string }, ctx: McpContextLike) => {
      try {
        const ip = clientIp(ctx);
        if (env.KEY_LIMITER && !(await env.KEY_LIMITER.limit({ key: ip })).success) {
          return { isError: true, content: [{ type: "text", text: "RATE_LIMITED: Too many keys created. Try again later." }] };
        }
        const k = await createApiKey(env, { label, creatorHash: await sha256Hex(`creator:${ip}`) });
        const data = {
          api_key: k.api_key,
          balance: microToUsd(k.balance_micro),
          usage: "Send it as `Authorization: Bearer <api_key>` on MCP or HTTP requests.",
          top_up: `${env.PUBLIC_URL}/billing`,
        };
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
      } catch (err) {
        return { isError: true, content: [{ type: "text", text: errorMessage(err) }] };
      }
    },
  );

  server.registerTool(
    "account_balance",
    {
      title: "Account balance",
      description: "Show the remaining credit balance of the API key sent with this request. Free.",
      inputSchema: z.object({}),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async (_args: Record<string, never>, ctx: McpContextLike) => {
      const raw = apiKeyFromHeaders(ctx.http?.req?.headers);
      if (!raw) return text("No API key was sent. Add `Authorization: Bearer apg_...` to your MCP connection headers.");
      const key = await findApiKey(env, raw);
      if (!key) return { isError: true, content: [{ type: "text", text: "INVALID_API_KEY: That API key is not valid." }] };
      const data = { key: `${key.key_prefix}…`, label: key.label, balance: microToUsd(key.balance_micro), top_up: `${env.PUBLIC_URL}/billing` };
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
    },
  );

  server.registerPrompt(
    "research_company",
    {
      title: "Research a company",
      description: "Research a company from its domain using AIPayGen tools.",
      argsSchema: z.object({ domain: z.string().describe("The company's domain") }),
    },
    ({ domain }: { domain: string }) => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text: `Research the company at ${domain}. Call company_profile first. If you need more depth, use tech_stack, email_security and ssl_certificates. Summarize what they do, how established they are, their tech and any risks.`,
          },
        },
      ],
    }),
  );

  return server;
}
