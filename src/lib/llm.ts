import type { Env } from "../env";
import { ToolError } from "./errors";

/** Workers AI chat models: the large one first, the small fast one as fallback (also when the daily allowance runs low). */
export const LLM_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
export const LLM_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast";

/** Runs a chat prompt, trying each model in turn. Returns the text and the model that answered. */
export async function chat(
  env: Pick<Env, "AI"> & { DEBUG_AI?: string },
  system: string,
  user: string,
  opts: { maxTokens?: number; models?: string[] } = {},
): Promise<{ text: string; model: string }> {
  if (!env.AI) throw new ToolError("AI processing is not available right now.", "UNAVAILABLE", 503);
  let lastError = "";
  for (const model of opts.models ?? [LLM_LARGE, LLM_SMALL]) {
    try {
      const out = (await env.AI.run(model as Parameters<Ai["run"]>[0], {
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        max_tokens: opts.maxTokens ?? 1024,
        temperature: 0,
      } as never)) as { response?: unknown };
      // When a reply is pure JSON, Workers AI may hand it back already parsed.
      const r = out.response;
      const text = typeof r === "string" ? r.replace(/<think>[\s\S]*?<\/think>/g, "").trim() : r && typeof r === "object" ? JSON.stringify(r) : "";
      if (text) return { text, model };
      lastError = `empty reply (${typeof r})`;
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    console.log("llm failed", model, lastError);
  }
  if (env.DEBUG_AI) throw new ToolError(`The AI model didn't answer: ${lastError}`, "AI_FAILED", 502);
  throw new ToolError("The AI model didn't answer. Try again in a moment.", "AI_FAILED", 502);
}

/** Pulls the first JSON object out of a model reply (models sometimes wrap it in prose or ``` fences). */
export function parseJsonObject(raw: string): Record<string, unknown> | null {
  const s = raw.replace(/```(?:json)?/gi, "");
  const start = s.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let inStr = false;
  for (let i = start; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (ch === "\\") i++;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) {
      try {
        const v = JSON.parse(s.slice(start, i + 1));
        return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
      } catch {
        return null;
      }
    }
  }
  return null;
}
