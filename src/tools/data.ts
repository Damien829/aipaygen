import { z } from "zod";
import { fetchJson } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

/**
 * Reference data from free, keyless public sources that allow commercial use:
 * ECB exchange rates (via Frankfurter), public holidays (Nager.Date),
 * Wikipedia, Hacker News (Algolia) and arXiv.
 */

const CURRENCY = /^[A-Z]{3}$/;

export const currencyConvert = defineTool({
  name: "currency_convert",
  title: "Currency exchange rates",
  description:
    "Convert money between 30+ currencies (USD, EUR, GBP, JPY, CAD, AUD, CHF, CNY, INR, BRL, MXN...) at European Central Bank reference rates, for today or any date back to 1999.",
  priceMicro: 1000,
  cacheTtl: 3600,
  input: z.object({
    from: z.string().min(3).max(3).describe('Currency code to convert from, e.g. "USD".'),
    to: z.array(z.string().min(3).max(3)).max(40).optional().describe('Currency codes to convert to, e.g. ["EUR","JPY"]. Default: all.'),
    amount: z.number().positive().max(1e12).optional().describe("Amount to convert. Default 1."),
    date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Historical date (YYYY-MM-DD). Default: latest."),
  }),
  example: { from: "USD", to: ["EUR", "GBP", "JPY"], amount: 250 },
  async run({ from, to, amount, date }) {
    const base = from.toUpperCase();
    const targets = (to ?? []).map((c) => c.toUpperCase());
    if (![base, ...targets].every((c) => CURRENCY.test(c))) throw new ToolError("Use 3-letter currency codes like USD or EUR.", "INVALID_INPUT", 400);
    const qs = new URLSearchParams({ base, amount: String(amount ?? 1) });
    if (targets.length) qs.set("symbols", targets.filter((c) => c !== base).join(","));
    const { status, data } = await fetchJson<{ amount: number; base: string; date: string; rates: Record<string, number> }>(
      `https://api.frankfurter.dev/v1/${date ?? "latest"}?${qs}`,
      { timeoutMs: 6000 },
    );
    if (!data?.rates) {
      if (status === 404 || status === 422) throw new ToolError("Unknown currency code or date out of range (rates start 1999-01-04).", "INVALID_INPUT", 400);
      throw new ToolError(`The exchange-rate service didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    }
    const amt = amount ?? 1;
    return {
      from: base,
      amount: amt,
      rate_date: data.date,
      converted: data.rates,
      rates_per_unit: Object.fromEntries(Object.entries(data.rates).map(([k, v]) => [k, Math.round((v / amt) * 1e6) / 1e6])),
      credit: "European Central Bank reference rates via Frankfurter. Rates update once per working day around 16:00 CET.",
    };
  },
});

interface Holiday { date: string; localName: string; name: string; global: boolean; counties: string[] | null; types: string[] }

export const publicHolidays = defineTool({
  name: "public_holidays",
  title: "Public holidays by country",
  description:
    "Public and bank holidays for 100+ countries for any year, with local names, regional holidays and the next upcoming one. Useful for scheduling, delivery dates and business-day math.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({
    country: z.string().min(2).max(2).describe('ISO country code, e.g. "US", "GB", "DE", "BR".'),
    year: z.number().int().min(1975).max(2075).optional().describe("Year. Default: this year."),
  }),
  example: { country: "US" },
  async run({ country, year }) {
    const cc = country.toUpperCase();
    if (!/^[A-Z]{2}$/.test(cc)) throw new ToolError("Use a 2-letter country code like US or DE.", "INVALID_INPUT", 400);
    const today = new Date().toISOString().slice(0, 10);
    const y = year ?? Number(today.slice(0, 4));
    const { status, data } = await fetchJson<Holiday[]>(`https://date.nager.at/api/v3/PublicHolidays/${y}/${cc}`, { timeoutMs: 6000 });
    if (!Array.isArray(data)) {
      if (status === 404 || status === 204 || status === 200) throw new ToolError(`No holiday data for country "${cc}".`, "NOT_FOUND", 404);
      throw new ToolError(`The holiday service didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    }
    const holidays = data.map((h) => ({
      date: h.date,
      name: h.name,
      local_name: h.localName,
      nationwide: h.global,
      regions: h.counties,
      types: h.types,
    }));
    return {
      country: cc,
      year: y,
      count: holidays.length,
      next: holidays.find((h) => h.date >= today) ?? null,
      holidays,
      credit: "Nager.Date (date.nager.at).",
    };
  },
});

interface WikiSummary {
  title: string;
  description?: string;
  extract?: string;
  content_urls?: { desktop?: { page?: string } };
  thumbnail?: { source?: string };
  timestamp?: string;
  type?: string;
}

export const wikipedia = defineTool({
  name: "wikipedia",
  title: "Wikipedia lookup",
  description:
    "Look up any person, place, company, concept or event on Wikipedia and get a clean summary, a short description, an image and the article link. Any language edition. Good for grounding answers in facts.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({
    query: z.string().min(1).max(300).describe('What to look up, e.g. "Ada Lovelace" or "Model Context Protocol".'),
    lang: z.string().regex(/^[a-z]{2,3}(-[a-z]+)?$/).optional().describe('Wikipedia language code, e.g. "en" (default), "es", "de", "ja".'),
  }),
  example: { query: "Model Context Protocol" },
  async run({ query, lang }) {
    const host = `https://${lang ?? "en"}.wikipedia.org`;
    const search = await fetchJson<{ pages?: { key: string; title: string; description?: string }[] }>(
      `${host}/w/rest.php/v1/search/title?q=${encodeURIComponent(query)}&limit=5`,
      { timeoutMs: 6000 },
    );
    const pages = search.data?.pages ?? [];
    if (!pages.length) throw new ToolError(`No Wikipedia article found for "${query}".`, "NOT_FOUND", 404);
    const { data } = await fetchJson<WikiSummary>(`${host}/api/rest_v1/page/summary/${encodeURIComponent(pages[0]!.key)}`, { timeoutMs: 6000 });
    if (!data) throw new ToolError("Wikipedia didn't answer. Try again.", "UPSTREAM_ERROR", 502);
    return {
      title: data.title,
      description: data.description ?? null,
      summary: data.extract ?? null,
      disambiguation: data.type === "disambiguation",
      url: data.content_urls?.desktop?.page ?? `${host}/wiki/${pages[0]!.key}`,
      image: data.thumbnail?.source ?? null,
      last_edited: data.timestamp ?? null,
      other_matches: pages.slice(1).map((p) => ({ title: p.title, description: p.description ?? null })),
      credit: "Wikipedia, CC BY-SA 4.0.",
    };
  },
});

interface HnHit { objectID: string; title?: string; url?: string; author: string; points?: number; num_comments?: number; created_at: string; story_text?: string }

export const hackerNews = defineTool({
  name: "hacker_news",
  title: "Hacker News search",
  description:
    "Search Hacker News stories and discussions about any product, company or technology: titles, links, points, comment counts and dates. Sort by relevance or newest. Good for tech sentiment and launch tracking.",
  priceMicro: 1000,
  cacheTtl: 900,
  input: z.object({
    query: z.string().min(1).max(200).describe('Search words, e.g. "x402" or "Cloudflare Workers".'),
    sort: z.enum(["relevance", "newest"]).optional().describe('"relevance" (default) or "newest".'),
    limit: z.number().int().min(1).max(30).optional().describe("Number of stories. Default 10."),
  }),
  example: { query: "x402 payments", sort: "newest" },
  async run({ query, sort, limit }) {
    const path = sort === "newest" ? "search_by_date" : "search";
    const { status, data } = await fetchJson<{ nbHits: number; hits: HnHit[] }>(
      `https://hn.algolia.com/api/v1/${path}?query=${encodeURIComponent(query)}&tags=story&hitsPerPage=${limit ?? 10}`,
      { timeoutMs: 6000 },
    );
    if (!data) throw new ToolError(`Hacker News search didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    return {
      query,
      total: data.nbHits,
      stories: data.hits.map((h) => ({
        title: h.title ?? null,
        url: h.url ?? null,
        discussion: `https://news.ycombinator.com/item?id=${h.objectID}`,
        points: h.points ?? 0,
        comments: h.num_comments ?? 0,
        author: h.author,
        date: h.created_at,
      })),
    };
  },
});

const decodeXml = (s: string) =>
  s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const tag = (xml: string, name: string) => {
  const m = new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`).exec(xml);
  return m ? decodeXml(m[1]!.replace(/\s+/g, " ").trim()) : null;
};

/** Parses arXiv's Atom feed into plain paper records. */
export function parseArxiv(xml: string) {
  const total = Number(/<opensearch:totalResults>(\d+)</.exec(xml)?.[1] ?? 0);
  const papers = [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(([, e]) => {
    const id = tag(e!, "id") ?? "";
    return {
      title: tag(e!, "title"),
      authors: [...e!.matchAll(/<author>\s*<name>([\s\S]*?)<\/name>/g)].map((m) => decodeXml(m[1]!.trim())),
      published: tag(e!, "published"),
      updated: tag(e!, "updated"),
      abstract: tag(e!, "summary"),
      categories: [...e!.matchAll(/<category term="([^"]+)"/g)].map((m) => m[1]!),
      url: id.replace(/^http:/, "https:"),
      pdf: /<link[^>]*title="pdf"[^>]*href="([^"]+)"|<link[^>]*href="([^"]+)"[^>]*title="pdf"/.exec(e!)?.slice(1).find(Boolean) ?? null,
    };
  });
  return { total, papers };
}

export const paperSearch = defineTool({
  name: "paper_search",
  title: "Research paper search (arXiv)",
  description:
    "Search 2.4M+ research papers on arXiv (AI, machine learning, physics, math, CS, economics, biology): titles, authors, abstracts, dates and PDF links. Sort by relevance or newest.",
  priceMicro: 2000,
  cacheTtl: 3600,
  input: z.object({
    query: z.string().min(1).max(300).describe('Topic or keywords, e.g. "retrieval augmented generation".'),
    sort: z.enum(["relevance", "newest"]).optional().describe('"relevance" (default) or "newest".'),
    limit: z.number().int().min(1).max(25).optional().describe("Number of papers. Default 10."),
  }),
  example: { query: "AI agent payments", sort: "newest", limit: 5 },
  async run({ query, sort, limit }) {
    const terms = query.replace(/[^\p{L}\p{N}\s-]/gu, " ").trim().split(/\s+/).filter(Boolean).slice(0, 12);
    if (!terms.length) throw new ToolError("Give some search words.", "INVALID_INPUT", 400);
    const q = terms.map((t) => `all:${t}`).join(" AND ");
    const qs = new URLSearchParams({
      search_query: q,
      max_results: String(limit ?? 10),
      sortBy: sort === "newest" ? "submittedDate" : "relevance",
      sortOrder: "descending",
    });
    let res: Response;
    try {
      res = await fetch(`https://export.arxiv.org/api/query?${qs}`, {
        headers: { "user-agent": "AIPayGenBot/2.0 (+https://aipaygen.com/bot)" },
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      throw new ToolError("arXiv is unreachable right now.", "UPSTREAM_UNREACHABLE", 502);
    }
    if (!res.ok) throw new ToolError(`arXiv didn't answer (status ${res.status}).`, "UPSTREAM_ERROR", 502);
    const { total, papers } = parseArxiv(await res.text());
    return { query, total, papers, credit: "Metadata from arXiv.org (thank you to arXiv for use of its open access interoperability)." };
  },
});
