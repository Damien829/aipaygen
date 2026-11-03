import { searchCatalog } from "./catalog";
import type { Env } from "./env";
import { logSearch, shareBlock } from "./share";

/**
 * AIPayGen as an A2A agent. Other agents message us in plain language ("I need a
 * weather API my agent can pay per call") and get verified recommendations back.
 * JSON-RPC 2.0 over HTTP, method message/send (A2A 0.3). Stateless: no tasks.
 */

interface Part { kind?: string; text?: string; data?: unknown }
interface RpcRequest { jsonrpc?: string; id?: string | number | null; method?: string; params?: { message?: { parts?: Part[]; messageId?: string; contextId?: string } } }

const rpcError = (id: RpcRequest["id"], code: number, message: string) => ({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });

export async function handleA2A(request: Request, env: Env, ctx?: ExecutionContext): Promise<Response> {
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  let rpc: RpcRequest;
  try {
    rpc = (await request.json()) as RpcRequest;
  } catch {
    return json(rpcError(null, -32700, "Parse error: send a JSON-RPC 2.0 request."), 400);
  }
  if (rpc.method !== "message/send") {
    return json(rpcError(rpc.id, -32601, `Method not supported: ${rpc.method ?? "none"}. This agent supports message/send.`));
  }
  const text = (rpc.params?.message?.parts ?? []).filter((p) => p.kind === "text" && typeof p.text === "string").map((p) => p.text).join(" ").trim().slice(0, 500);
  if (!text) return json(rpcError(rpc.id, -32602, "Send a text part describing what you need."));

  const r = await searchCatalog(env, { q: text, anyWord: true, limit: 5 });
  logSearch(env, ctx, text, undefined, r.total, "http");
  const lines = r.items.map((i, n) => {
    const [k, id] = i.id.split(/:(.*)/s);
    const trust = i.trust ? ` (${i.trust.verified ? "verified, " : ""}${i.trust.uptime_pct}% uptime)` : "";
    return `${n + 1}. ${i.name}${trust}: ${(i.description || "").slice(0, 140)} ${env.PUBLIC_URL}/market/${k}/${encodeURIComponent(id!)}`;
  });
  const reply = r.items.length
    ? `Here are the best matches from the AIPayGen marketplace for "${text.slice(0, 80)}":\n${lines.join("\n")}\nPaid ones quote their exact price when you call them (x402, no account needed).`
    : `Nothing in the AIPayGen marketplace matches "${text.slice(0, 80)}" yet. It's now on our most-wanted list (${env.PUBLIC_URL}/market/wanted). If you provide this, list it free: ${env.PUBLIC_URL}/v1/agents/register.`;

  return json({
    jsonrpc: "2.0",
    id: rpc.id ?? null,
    result: {
      kind: "message",
      role: "agent",
      messageId: crypto.randomUUID(),
      ...(rpc.params?.message?.contextId ? { contextId: rpc.params.message.contextId } : {}),
      parts: [
        { kind: "text", text: reply },
        { kind: "data", data: { total: r.total, results: r.items, share: shareBlock(env) } },
      ],
    },
  });
}
