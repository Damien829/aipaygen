import { z } from "zod";
import { fetchPage } from "../lib/net";
import { parseHtml } from "../lib/html";
import { defineTool } from "./types";
import { TECH_SIGNATURES, type TechSignature } from "./techSignatures";

export interface DetectedTech {
  name: string;
  category: string;
  evidence: string;
}

/** Detect technologies from a page's HTML and headers. Pure, for testing. */
export function detectTech(html: string, headers: Headers): DetectedTech[] {
  const root = parseHtml(html);
  const scripts = root.querySelectorAll("script[src]").map((s) => s.getAttribute("src") ?? "");
  const metas: Record<string, string> = {};
  for (const m of root.querySelectorAll("meta[name]")) {
    metas[(m.getAttribute("name") ?? "").toLowerCase()] = m.getAttribute("content") ?? "";
  }
  const cookies = (headers.get("set-cookie") ?? "").split(/,(?=\s*[A-Za-z0-9_.-]+=)/).map((c) => c.trim());
  const htmlSample = html.length > 600_000 ? html.slice(0, 600_000) : html;

  const found = new Map<string, DetectedTech>();
  const add = (sig: TechSignature, evidence: string) => {
    if (!found.has(sig.name)) found.set(sig.name, { name: sig.name, category: sig.category, evidence });
  };

  for (const sig of TECH_SIGNATURES) {
    for (const [h, re] of Object.entries(sig.headers ?? {})) {
      const v = headers.get(h);
      if (v && re.test(v)) add(sig, `header ${h}`);
    }
    for (const re of sig.cookies ?? []) if (cookies.some((c) => re.test(c))) add(sig, "cookie");
    for (const [name, re] of Object.entries(sig.meta ?? {})) if (metas[name] && re.test(metas[name]!)) add(sig, `meta ${name}`);
    for (const re of sig.scripts ?? []) if (scripts.some((s) => re.test(s))) add(sig, "script");
    for (const re of sig.html ?? []) if (re.test(htmlSample)) add(sig, "html");
  }

  // Follow "implies" links (e.g. Next.js -> React) until nothing new is added.
  let changed = true;
  while (changed) {
    changed = false;
    for (const t of [...found.values()]) {
      const sig = TECH_SIGNATURES.find((s) => s.name === t.name);
      for (const implied of sig?.implies ?? []) {
        const target = TECH_SIGNATURES.find((s) => s.name === implied);
        if (target && !found.has(implied)) {
          add(target, `implied by ${t.name}`);
          changed = true;
        }
      }
    }
  }
  return [...found.values()].sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
}

export function groupByCategory(techs: DetectedTech[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const t of techs) (out[t.category] ??= []).push(t.name);
  return out;
}

export const techStack = defineTool({
  name: "tech_stack",
  title: "Website tech stack",
  description:
    "Detect what a website is built with: framework, CMS or site builder, hosting/CDN, web server, analytics, ad pixels, payments, chat, auth and more (90+ technologies), with the evidence for each.",
  priceMicro: 3000,
  cacheTtl: 43_200,
  input: z.object({ url: z.string().describe("Website URL or domain, e.g. linear.app") }),
  example: { url: "https://linear.app" },
  async run({ url }) {
    const page = await fetchPage(url);
    const technologies = detectTech(page.body, page.headers);
    return {
      url: page.url,
      status: page.status,
      technology_count: technologies.length,
      by_category: groupByCategory(technologies),
      technologies,
    };
  },
});
