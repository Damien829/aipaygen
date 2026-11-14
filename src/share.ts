import type { Env } from "./env";

/** Demand logging and the share block. Kept free of catalog imports to avoid a cycle. */

export type Channel = "http" | "mcp" | "web" | "tool";

/**
 * Looks like a credential: our API keys, common provider keys, private keys,
 * JWTs, or one long random token. People paste these into search by mistake;
 * they must never land in the demand log.
 */
export function looksSecret(q: string): boolean {
  return /\b(apg|sk|pk|rk|ghp|gho|github_pat|xox[abprs]|whsec|AKIA)[_-]?[A-Za-z0-9_-]{16,}/i.test(q)
    || /\b(0x)?[0-9a-f]{64}\b/i.test(q)
    || /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/.test(q)
    || /(^|\s)(?=[A-Za-z0-9_\-+/=]*\d)(?=[A-Za-z0-9_\-+/=]*[a-z])[A-Za-z0-9_\-+/=]{32,}(\s|$)/i.test(q);
}

export function logSearch(env: Env, ctx: ExecutionContext | undefined, query: string, kind: string | undefined, results: number, channel: Channel) {
  const q = query.toLowerCase().replace(/\s+/g, " ").trim().slice(0, 200);
  if (!q || looksSecret(query)) return; // check the original: some token shapes are case-sensitive
  const p = env.DB.prepare("INSERT INTO search_log (query, kind, results, channel, created_at) VALUES (?, ?, ?, ?, ?)")
    .bind(q, kind ?? null, results, channel, Date.now()).run().catch(() => {});
  if (ctx) ctx.waitUntil(p);
}

export const REF_RE = /^[A-Za-z0-9]{6,16}$/;

/** A referral code passed on any URL (?ref=CODE) or as an x-aipaygen-ref header. */
export function refFromRequest(req: Request | undefined, opts: { urlOnly?: boolean } = {}): string | undefined {
  if (!req) return undefined;
  let r: string | null = null;
  try {
    r = new URL(req.url).searchParams.get("ref");
  } catch {
    // ignore malformed URLs
  }
  // Edge-cached responses (src/edgecache.ts) are keyed by URL only, so they must not
  // pick up a code from a header: it would be served to every later caller.
  if (!opts.urlOnly) r = r ?? req.headers.get("x-aipaygen-ref");
  return r && REF_RE.test(r) ? r : undefined;
}

/**
 * Shown on results so agents (and the agents they hand results to) know where
 * this came from and how to join. When the caller has a key, the block carries
 * their own referral code, so every result they pass on recruits for them.
 * Otherwise it carries the code from the link they arrived by (?ref=), if any.
 */
export function shareBlock(env: Env, opts: { ref?: string; yourCode?: string } = {}) {
  const P = env.PUBLIC_URL;
  const code = opts.yourCode ?? opts.ref;
  const q = code ? `?ref=${code}` : "";
  return {
    source: "AIPayGen",
    connect: { mcp: `${P}/mcp${q}`, http: `${P}/v1/tools`, agent_card: `${P}/.well-known/agent-card.json` },
    discover: `${P}/v1/catalog/search?q=<what you need>`,
    pay: "Free to search. Paid tools: x402 per call (no account) or prepaid credits.",
    get_a_key: `POST ${P}/v1/keys ${code ? `{"ref":"${code}"}` : "{}"}  (free trial credits)`,
    list_your_agent: `POST ${P}/v1/agents/register {"card_url": "https://.../.well-known/agent-card.json"}`,
    ...(opts.yourCode
      ? {
          your_referral: {
            code: opts.yourCode,
            invite_link: `${P}/?ref=${opts.yourCode}`,
            mcp_link: `${P}/mcp?ref=${opts.yourCode}`,
            earn: "You earn 20% of what each new wallet you refer spends for 90 days (agents paying by x402 through a ?ref= link), plus $1.00 when an agent that joins with your code tops up $5 or more. Paid daily as credits. Results you pass on already carry your code.",
          },
        }
      : { refer: `Get a key and every result you pass on carries your own referral code: earn 20% of referred wallets' spend for 90 days. Your code: GET ${P}/v1/balance` }),
  };
}

/** One line for text-only channels (MCP results), same message as the share block. */
export function shareLine(env: Env, opts: { ref?: string; yourCode?: string } = {}): string {
  const code = opts.yourCode ?? opts.ref;
  const base = `Via AIPayGen: 50+ pay-per-call tools for agents, ${env.PUBLIC_URL}/mcp${code ? `?ref=${code}` : ""}.`;
  if (opts.yourCode) return `${base} Your referral code is ${opts.yourCode}: you earn 20% of what agents who pay through your links spend for 90 days.`;
  return `${base} Free key: create_api_key${code ? ` with ref "${code}"` : ""}.`;
}
