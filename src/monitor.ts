import type { Env } from "./env";
import { openIssue } from "./lib/github";
import { parseQuote } from "./refresh";
import { TOOLS } from "./tools";
import type { ToolDef } from "./tools/types";

/**
 * Own-tool monitor: an hourly cron (wrangler.jsonc) runs the next few of our paid
 * tools on their own example input, straight through run() (no cache, no payment),
 * so a broken upstream shows up here before a buyer hits it. Tools failing twice in
 * a row open a GitHub issue, at most once a day.
 */

export const MONITOR_CRON = "35 * * * *";
const PER_RUN = 6; // keeps well under the invocation's 50 outbound requests
const TIMEOUT_MS = 25_000;
// Skipped: Workers AI media and LLM tools spend the free daily AI allowance; composites
// fan out to many upstreams (their parts are checked one by one anyway).
const SKIP = new Set(["generate_image", "text_to_speech", "transcribe_audio", "describe_image", "ask_llm", "run_skill",
  "summarize", "extract_data", "classify_text", "translate", "document_to_markdown", "language_detect", "embed_text", "rank_texts",
  "company_profile", "domain_report"]);

interface Result { ok: boolean; ms: number; error?: string; at: string; fails: number }
interface State { cursor: number; results: Record<string, Result>; alerted_day?: string; payment_day?: string }

export function monitoredTools(tools: ToolDef[] = TOOLS): ToolDef[] {
  return tools.filter((t) => t.priceMicro > 0 && !SKIP.has(t.name) && t.example);
}

async function readState(env: Env): Promise<State> {
  const r = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'tool_monitor'").first<{ value: string }>();
  try {
    return { cursor: 0, results: {}, ...(JSON.parse(r?.value ?? "{}") as Partial<State>) };
  } catch {
    return { cursor: 0, results: {} };
  }
}

export async function monitorTools(env: Env) {
  const tools = monitoredTools();
  if (!tools.length) return { checked: 0 };
  const state = await readState(env);
  const batch = Array.from({ length: Math.min(PER_RUN, tools.length) }, (_, i) => tools[(state.cursor + i) % tools.length]!);
  state.cursor = (state.cursor + batch.length) % tools.length;

  const outcomes: { name: string; ok: boolean; ms: number; error?: string }[] = await Promise.all(batch.map(async (t) => {
    const t0 = Date.now();
    try {
      await Promise.race([
        t.run(t.example as never, { env }),
        new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${TIMEOUT_MS / 1000}s`)), TIMEOUT_MS)),
      ]);
      return { name: t.name, ok: true, ms: Date.now() - t0 };
    } catch (err) {
      return { name: t.name, ok: false, ms: Date.now() - t0, error: (err instanceof Error ? err.message : String(err)).slice(0, 200) };
    }
  }));

  // Once a day, the payment path end to end: an unpaid call over HTTP must get a payable x402
  // quote (which also proves the facilitator connection) or be served from the free allowance.
  const day0 = new Date().toISOString().slice(0, 10);
  if (state.payment_day !== day0) {
    state.payment_day = day0;
    const t0 = Date.now();
    try {
      const res = await fetch(`${env.PUBLIC_URL}/v1/dns_lookup?domain=example.com`, {
        headers: { accept: "application/json", "user-agent": "AIPayGen monitor" },
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      const body = (await res.text()).slice(0, 50_000);
      const ok = res.status === 200 || (res.status === 402 && parseQuote(res.headers.get("payment-required"), body));
      outcomes.push({ name: "payment_path", ok, ms: Date.now() - t0, ...(ok ? {} : { error: `status ${res.status}: ${body.slice(0, 120)}` }) });
    } catch (err) {
      outcomes.push({ name: "payment_path", ok: false, ms: Date.now() - t0, error: err instanceof Error ? err.message : String(err) });
    }
  }

  const at = new Date().toISOString();
  for (const o of outcomes) {
    const prev = state.results[o.name];
    state.results[o.name] = { ok: o.ok, ms: o.ms, at, fails: o.ok ? 0 : (prev?.fails ?? 0) + 1, ...(o.error ? { error: o.error } : {}) };
  }

  const broken = Object.entries(state.results).filter(([, r]) => r.fails >= 2);
  const day = at.slice(0, 10);
  let alert: string | null | undefined;
  if (broken.length && state.alerted_day !== day) {
    alert = await openIssue(
      env,
      `Tools: ${broken.length} AIPayGen tool(s) failing`,
      `The hourly monitor ran these tools on their example input and they failed twice in a row:\n\n${broken.map(([n, r]) => `- \`${n}\`: ${r.error ?? "error"} (${r.at})`).join("\n")}\n\nBuyers calling them get an error and aren't charged.`,
      "tools",
    );
    if (alert === null) state.alerted_day = day;
  }
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('tool_monitor', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(JSON.stringify(state), Date.now()).run();
  return { checked: outcomes.length, failed: outcomes.filter((o) => !o.ok).map((o) => o.name), ...(alert !== undefined ? { alerted: alert === null } : {}) };
}

/** For /admin/overview: tools currently failing, and when each tool was last checked. */
export async function monitorSummary(env: Env) {
  const s = await readState(env);
  const entries = Object.entries(s.results);
  return {
    checked_tools: entries.length,
    of: monitoredTools().length,
    failing: entries.filter(([, r]) => !r.ok).map(([name, r]) => ({ name, error: r.error ?? null, fails: r.fails, at: r.at })),
  };
}
