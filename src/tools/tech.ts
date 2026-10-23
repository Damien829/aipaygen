import { z } from "zod";
import { fetchPage } from "../lib/net";
import { parseHtml } from "../lib/html";
import { defineTool } from "./types";
import { resolve } from "./dns";
import { TECH_SIGNATURES, type TechSignature } from "./techSignatures";

// https://www.cloudflare.com/ips-v4
const CLOUDFLARE_V4 = [
  "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
  "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
  "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
];

function ipToInt(ip: string): number {
  return ip.split(".").reduce((acc, p) => (acc << 8) + Number(p), 0) >>> 0;
}

export function isCloudflareIp(ip: string): boolean {
  if (ip.includes(":")) return /^2606:4700:|^2803:f800:|^2405:b500:|^2405:8100:|^2a06:98c|^2c0f:f248:|^2400:cb00:/i.test(ip);
  const n = ipToInt(ip);
  return CLOUDFLARE_V4.some((cidr) => {
    const [base, bits] = cidr.split("/") as [string, string];
    const mask = Number(bits) === 0 ? 0 : (~0 << (32 - Number(bits))) >>> 0;
    return (n & mask) === (ipToInt(base) & mask);
  });
}

/**
 * Responses fetched from inside a Worker carry Cloudflare's own `server` and
 * `cf-*` headers even when the site is not on Cloudflare. Strip those unless
 * the site's addresses really are Cloudflare's.
 */
export async function siteHeaders(url: string, headers: Headers): Promise<{ headers: Headers; onCloudflare: boolean }> {
  const host = new URL(url).hostname;
  let onCloudflare = false;
  try {
    const [a, aaaa] = await Promise.all([resolve(host, "A"), resolve(host, "AAAA")]);
    onCloudflare = [...a, ...aaaa].some((r) => isCloudflareIp(r.value));
  } catch {
    onCloudflare = false;
  }
  const cleaned = new Headers(headers);
  if (!onCloudflare) {
    if (/cloudflare/i.test(cleaned.get("server") ?? "")) cleaned.delete("server");
    for (const h of ["cf-ray", "cf-cache-status", "cf-apo-via", "cf-edge-cache"]) cleaned.delete(h);
  }
  return { headers: cleaned, onCloudflare };
}

/** Full detection for a fetched page, including the IP-based Cloudflare check. */
export async function detectTechForPage(url: string, html: string, headers: Headers): Promise<DetectedTech[]> {
  const site = await siteHeaders(url, headers);
  const techs = detectTech(html, site.headers);
  if (site.onCloudflare) techs.push({ name: "Cloudflare", category: "CDN", evidence: "IP address" });
  return techs.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
}

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
    const technologies = await detectTechForPage(page.url, page.body, page.headers);
    return {
      url: page.url,
      status: page.status,
      technology_count: technologies.length,
      by_category: groupByCategory(technologies),
      technologies,
    };
  },
});
