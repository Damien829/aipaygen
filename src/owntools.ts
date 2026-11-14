import type { Env } from "./env";
import type { CatalogItem } from "./catalog";
import { registeredTools } from "./registry";
import type { ToolDef } from "./tools/types";
import { formatPrice } from "./tools/types";

/**
 * AIPayGen's own tools as marketplace results. They aren't rows in the catalog
 * table, so without this an agent searching "weather" on AIPayGen found 200
 * third-party APIs and never our weather tool. Matching runs in memory: no
 * database reads.
 */

/** Extra words agents use for each tool. */
const SYNONYMS: Record<string, string> = {
  weather: "forecast temperature rain climate wind humidity meteo",
  translate: "translation translator language languages multilingual localize",
  dns_lookup: "dns records nameserver resolve mx txt",
  security_headers: "http headers security csp hsts website audit",
  domain_whois: "whois registrar domain registration owner rdap expiry",
  email_security: "email spf dkim dmarc deliverability mail",
  site_metadata: "metadata title description opengraph social preview",
  page_to_markdown: "markdown scrape crawl extract webpage html text reader",
  ssl_certificates: "ssl tls certificate https expiry subdomains",
  tech_stack: "technology tech stack framework cms builtwith wappalyzer website",
  company_profile: "company enrichment business firmographics lead profile",
  domain_report: "domain report audit website analysis due diligence",
};

/** Not offered as search results: free helpers, and run_skill (it runs other listings). */
const SKIP = new Set(["search_marketplace", "register_agent", "run_skill"]);

const STOP = new Set(["the", "and", "for", "api", "apis", "tool", "tools", "get", "with", "from", "data", "service", "free", "check", "find", "lookup", "look", "any", "all"]);

/** Crude stem: "translation"/"translate" -> "transl", "headers" -> "head", "pages" -> "page". */
export const stem = (w: string) => w.replace(/(ations?|ions?|ings?|ers?|s)$/, "").slice(0, 6);

function words(s: string): string[] {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, " ").split(" ").filter((w) => w.length >= 2);
}

/** Share of the query's meaningful words that this tool covers (0..1). */
export function matchScore(query: string, haystack: string): number {
  const q = [...new Set(words(query).filter((w) => !STOP.has(w)))];
  if (!q.length) return 0;
  const hay = new Set(words(haystack).map(stem));
  const hit = q.filter((w) => hay.has(stem(w))).length;
  return hit / q.length;
}

type Tool = ToolDef;

const listed = () => registeredTools().filter((t) => t.priceMicro > 0 && !SKIP.has(t.name));

function toItem(base: string, t: Tool): CatalogItem {
  return {
    id: `api:aipaygen-${t.name.replace(/_/g, "-")}`,
    kind: "api",
    name: `${t.title} (AIPayGen)`,
    description: t.description,
    category: "AIPayGen tools",
    url: `${base}/v1/${t.name}`,
    price: formatPrice(t.priceMicro),
    x402: true,
    meta: {
      first_party: true,
      tool: t.name,
      http: `${t.httpMethod ?? "GET"} ${base}/v1/${t.name}`,
      mcp: `${base}/mcp`,
      docs: `${base}/docs#${t.name}`,
      pay: "x402 USDC on Base per call (no account), or an API key with prepaid credits. Low-cost tools: 3 free calls a day.",
      example: t.example,
    },
    trust: { verified: true, uptime_pct: null, latency_ms: null, checks: 0 },
  };
}

/** Up to `max` of our paid tools that match the query, best first. */
export function ownMatches(env: Pick<Env, "PUBLIC_URL">, query: string, max = 3): CatalogItem[] {
  return listed()
    .map((t) => ({ t, score: matchScore(query, `${t.name.replace(/_/g, " ")} ${t.title} ${t.description} ${SYNONYMS[t.name] ?? ""}`) }))
    .filter((x) => x.score >= 0.5)
    .sort((a, b) => b.score - a.score)
    // Only the best-matching tools: "translate text" shouldn't also offer page_to_markdown for the word "text".
    .filter((x, _, all) => x.score >= all[0]!.score - 0.01)
    .slice(0, max)
    .map(({ t }) => toItem(env.PUBLIC_URL, t));
}

/** Every listed tool, for sitemaps. */
export function allOwnItems(env: Pick<Env, "PUBLIC_URL">): CatalogItem[] {
  return listed().map((t) => toItem(env.PUBLIC_URL, t));
}

/** Finds one of our tools by its catalog id ("aipaygen-dns-lookup"), for /market/api/:id pages. */
export function ownItem(env: Pick<Env, "PUBLIC_URL">, id: string): CatalogItem | null {
  const t = listed().find((x) => `aipaygen-${x.name.replace(/_/g, "-")}` === id);
  return t ? toItem(env.PUBLIC_URL, t) : null;
}
