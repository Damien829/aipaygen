#!/usr/bin/env node
// aipaygen-mcp: relays MCP JSON-RPC between stdio and the hosted AIPayGen server
// (https://mcp.aipaygen.com/mcp), so stdio-only MCP clients get the same tools. No dependencies.
//
// Environment / flags:
//   AIPAYGEN_API_KEY   optional API key (apg_...), sent as a Bearer token. Without one, paid tools
//                      answer with an x402 price (pay per call) and 3 calls a day are free on cheap tools.
//   AIPAYGEN_TOOLSET   or --toolset <name>: a focused tool set (web, company, crypto, media, agent,
//                      data, dev, site).
//                      Fewer tools help an agent choose; default is every tool.
//   AIPAYGEN_MCP_URL   override the endpoint (default https://mcp.aipaygen.com/mcp)
import { createInterface } from "node:readline";

const VERSION = "2.1.1";
const DEFAULT_URL = "https://mcp.aipaygen.com/mcp";
const TOOLSETS = ["web", "company", "crypto", "media", "agent", "data", "dev", "site"];
const TIMEOUT_MS = 120_000;

const args = process.argv.slice(2);
if (args.includes("--version") || args.includes("-V")) { console.log(`aipaygen-mcp ${VERSION}`); process.exit(0); }
if (args.includes("--help") || args.includes("-h")) {
  console.log(`aipaygen-mcp ${VERSION}: AIPayGen tools for stdio MCP clients.\n\nUsage: npx -y aipaygen-mcp [--toolset ${TOOLSETS.join("|")}]\nEnv: AIPAYGEN_API_KEY (optional, apg_...), AIPAYGEN_TOOLSET, AIPAYGEN_MCP_URL\nDocs: https://aipaygen.com/docs`);
  process.exit(0);
}
const flagAt = args.indexOf("--toolset");
const toolset = (flagAt >= 0 ? args[flagAt + 1] : process.env.AIPAYGEN_TOOLSET || "").trim().toLowerCase();
if (toolset && !TOOLSETS.includes(toolset)) {
  console.error(`aipaygen-mcp: unknown toolset "${toolset}". Use one of: ${TOOLSETS.join(", ")} (or none for every tool).`);
  process.exit(2);
}
const base = (process.env.AIPAYGEN_MCP_URL || DEFAULT_URL).replace(/\/+$/, "");
const url = toolset ? `${base}/${toolset}` : base;
const apiKey = (process.env.AIPAYGEN_API_KEY || "").trim() || null;
// Never send the key in the clear: only https, or plain http to this machine (local testing).
{
  let u;
  try { u = new URL(url); } catch { console.error(`aipaygen-mcp: AIPAYGEN_MCP_URL is not a valid URL: ${url}`); process.exit(2); }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname);
  if (apiKey && u.protocol !== "https:" && !(u.protocol === "http:" && local)) {
    console.error(`aipaygen-mcp: refusing to send your API key to ${u.origin} over ${u.protocol.replace(":", "")}. Use an https URL.`);
    process.exit(2);
  }
}

let sessionId = null;
let protocolVersion = null;

function headers() {
  const h = { "content-type": "application/json", accept: "application/json, text/event-stream", "user-agent": `aipaygen-mcp/${VERSION} (stdio bridge, node)` };
  if (apiKey) h.authorization = `Bearer ${apiKey}`;
  if (sessionId) h["mcp-session-id"] = sessionId;
  if (protocolVersion) h["mcp-protocol-version"] = protocolVersion;
  return h;
}

const errorFor = (message, text) => ({ jsonrpc: "2.0", id: message.id ?? null, error: { code: -32603, message: text } });

/** Accept a JSON body or an SSE stream of data: events. */
export function parseBody(body, contentType) {
  body = body.trim();
  if (!body) return [];
  if (contentType.includes("text/event-stream") || body.startsWith("event:") || body.startsWith("data:")) {
    const out = [];
    let data = [];
    for (const line of [...body.split(/\r?\n/), ""]) {
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      else if (line === "" && data.length) {
        try { out.push(JSON.parse(data.join("\n"))); } catch { /* skip a malformed event */ }
        data = [];
      }
    }
    return out;
  }
  try { const p = JSON.parse(body); return Array.isArray(p) ? p : [p]; } catch { return []; }
}

async function forward(message) {
  let res;
  try {
    res = await fetch(url, { method: "POST", headers: headers(), body: JSON.stringify(message), signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (e) {
    return message.id === undefined ? [] : [errorFor(message, `Could not reach ${url}: ${e?.message ?? e}`)];
  }
  const sid = res.headers.get("mcp-session-id");
  if (sid) sessionId = sid;
  const body = await res.text().catch(() => "");
  if (!res.ok && res.status !== 202) {
    const replies = parseBody(body, res.headers.get("content-type") || "");
    if (replies.some((r) => r && (r.error || r.result))) return replies; // a JSON-RPC error body: pass it on
    return message.id === undefined ? [] : [errorFor(message, `AIPayGen server returned HTTP ${res.status}: ${body.slice(0, 300)}`)];
  }
  const replies = parseBody(body, res.headers.get("content-type") || "");
  for (const r of replies) {
    if (message.method === "initialize" && r?.result?.protocolVersion) protocolVersion = r.result.protocolVersion;
  }
  return replies;
}

// One message at a time, in order: MCP clients expect replies in the order they asked.
let queue = Promise.resolve();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;
  let parsed;
  try { parsed = JSON.parse(line); } catch { return; }
  const messages = Array.isArray(parsed) ? parsed : [parsed];
  queue = queue.then(async () => {
    for (const m of messages) for (const reply of await forward(m)) process.stdout.write(JSON.stringify(reply) + "\n");
  });
});
rl.on("close", () => { queue.finally(() => process.exit(0)); });
