import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { upsertCatalogItem } from "./catalog";
import type { Env } from "./env";
import { ToolError } from "./lib/errors";
import { defineTool } from "./tools/types";

/**
 * Marketplace skills, runnable. Each skill is a prompt template with {{input}}
 * (stored privately in skill_prompts). run_skill fills it in and runs it on
 * Claude Haiku 5.5. Failures and refusals are never charged (chargeAndRun).
 */

const SKILL_MODEL = "claude-haiku-5-5";
const SYSTEM = "You are running an AIPayGen marketplace skill for another AI agent. Follow the skill's instructions exactly. When it asks for JSON, reply with only valid JSON and no commentary.";

function client(env: Env): Anthropic {
  if (!env.ANTHROPIC_API_KEY) throw new ToolError("Skills are temporarily unavailable.", "SKILLS_UNAVAILABLE", 503);
  return new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
}

/** Text of a Messages response; refusals and empty answers become uncharged errors. */
async function ask(env: Env, prompt: string, maxTokens: number): Promise<{ text: string; usage: unknown }> {
  let res;
  try {
    res = await client(env).messages.create({
      model: SKILL_MODEL,
      max_tokens: maxTokens,
      thinking: { type: "disabled" }, // skills are single-shot prompts; keep latency and cost low
      system: SYSTEM,
      messages: [{ role: "user", content: prompt }],
    });
  } catch (err) {
    if (err instanceof Anthropic.RateLimitError) throw new ToolError("Skill runtime is busy. Retry shortly.", "RATE_LIMITED", 429);
    if (err instanceof Anthropic.APIError) throw new ToolError("Skill runtime error.", "SKILL_RUNTIME_ERROR", 502);
    throw err;
  }
  if (res.stop_reason === "refusal") throw new ToolError("The model declined this request.", "REFUSED", 422);
  const text = res.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("").trim();
  if (!text) throw new ToolError("The skill returned no output.", "EMPTY_OUTPUT", 502);
  return { text, usage: res.usage };
}

/** JSON if the skill returned JSON (fenced or bare), else the text. */
function parseOutput(text: string): unknown {
  const m = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/);
  const body = (m ? m[1] : text)!.trim();
  if (/^[[{]/.test(body)) {
    try {
      return JSON.parse(body);
    } catch {
      // not JSON after all
    }
  }
  return text;
}

export const runSkill = defineTool({
  name: "run_skill",
  title: "Run a marketplace skill",
  description:
    "Run any of 4,000+ ready-made AI skills from the AIPayGen marketplace on your input: research, code review, market analysis, writing, extraction, summarizing and more. Find skill ids with search_marketplace (kind: skill). Failed or refused runs are never charged.",
  priceMicro: 5_000,
  cacheTtl: 3600,
  httpMethod: "POST",
  input: z.object({
    skill_id: z.string().min(1).max(64).describe('Skill id from search results, e.g. "skill:3683" or "3683"'),
    input: z.string().min(1).max(20_000).describe("What the skill should work on (a topic, text, code, ...)"),
  }),
  example: { skill_id: "skill:1", input: "AI agent payment protocols in 2026" },
  async run(args, { env }) {
    const id = args.skill_id.startsWith("skill:") ? args.skill_id : `skill:${args.skill_id}`;
    const row = await env.DB.prepare(
      "SELECT c.name, c.description, p.prompt_template FROM skill_prompts p JOIN catalog c ON c.id = p.id WHERE p.id = ? AND c.fail_count < 3",
    ).bind(id).first<{ name: string; description: string; prompt_template: string }>();
    if (!row) throw new ToolError("No runnable skill with that id. Find one with search_marketplace (kind: skill).", "UNKNOWN_SKILL", 404);
    const prompt = row.prompt_template.includes("{{input}}") ? row.prompt_template.replaceAll("{{input}}", args.input) : `${row.prompt_template}\n\n${args.input}`;
    const { text, usage } = await ask(env, prompt, 4096);
    return { skill: { id, name: row.name }, output: parseOutput(text), model: SKILL_MODEL, usage };
  },
});

// ── New skills from unmet demand ─────────────────────────────────────────

const draftSchema = z.object({
  name: z.string().min(3).max(60).regex(/^[a-z0-9_]+$/),
  description: z.string().min(20).max(300),
  category: z.string().min(2).max(30),
  prompt_template: z.string().min(40).max(3000).refine((t) => t.includes("{{input}}"), "must contain {{input}}"),
});

/**
 * Turn searches agents keep making but can't satisfy into new skills. Runs from the
 * cron at most once an hour, two queries per run. New skills are labeled
 * auto-generated and are runnable immediately with run_skill.
 */
export async function skillsFromDemand(env: Env, limit = 2) {
  if (!env.ANTHROPIC_API_KEY) return { skipped: "no ANTHROPIC_API_KEY" };
  const last = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'skills_from_demand_at'").first<{ value: string }>();
  if (last && Date.now() - Number(last.value) < 3_600_000) return { skipped: "ran within the hour" };
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('skills_from_demand_at', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(String(Date.now()), Date.now()).run();

  const { results } = await env.DB.prepare(
    `SELECT query FROM search_log WHERE results = 0 AND created_at > ? AND length(query) BETWEEN 4 AND 60 AND query NOT GLOB '*[^a-z0-9 -]*'
     AND NOT EXISTS (SELECT 1 FROM catalog WHERE id = 'skill:auto-' || replace(search_log.query, ' ', '-'))
     GROUP BY query HAVING COUNT(*) >= 3 ORDER BY COUNT(*) DESC LIMIT ?`,
  ).bind(Date.now() - 14 * 86_400_000, limit).all<{ query: string }>();

  const made: string[] = [];
  for (const { query } of results) {
    try {
      const { text } = await ask(env,
        `AI agents keep searching a skills marketplace for "${query}" and finding nothing. Design one reusable skill that serves this need.\n` +
        `Return only JSON: {"name": "snake_case_name", "description": "one sentence for agents", "category": "one word", "prompt_template": "instructions to a model, containing {{input}} where the caller's input goes, and saying what format to return"}.\n` +
        `If the need is harmful, illegal or deceptive, return {"name": "skip"}.`, 1500);
      const parsed = draftSchema.safeParse(parseOutput(text));
      if (!parsed.success) continue;
      const d = parsed.data;
      const id = `skill:auto-${query.replace(/ /g, "-")}`;
      await upsertCatalogItem(env, {
        id, kind: "skill", name: d.name, description: `${d.description} (AI-generated from agent demand)`, category: d.category.toLowerCase(),
        url: `${env.PUBLIC_URL}/v1/catalog/skill/${id.slice(6)}`, priceMicro: null, x402: false, source: "auto-skill",
        meta: { generated_from: query, runnable_with: "run_skill" },
      });
      await env.DB.prepare("INSERT OR REPLACE INTO skill_prompts (id, prompt_template, input_schema, output_hint) VALUES (?, ?, ?, NULL)")
        .bind(id, d.prompt_template, JSON.stringify({ input: query })).run();
      made.push(d.name);
    } catch {
      // one bad draft shouldn't stop the run
    }
  }
  return { considered: results.length, created: made };
}
