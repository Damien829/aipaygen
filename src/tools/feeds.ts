import { z } from "zod";
import type { Env } from "../env";
import { ToolError } from "../lib/errors";
import { fetchJson } from "../lib/net";
import { defineTool } from "./types";

/**
 * Data feeds from official, free sources whose terms allow commercial use:
 * GitHub's search API, the ECB reference rates (via Frankfurter) and SEC EDGAR.
 */

const SEC_UA = { "user-agent": "AIPayGen data tool (+https://aipaygen.com/bot)" };

interface GhRepo {
  full_name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  stargazers_count: number;
  forks_count: number;
  created_at: string;
  topics?: string[];
  license?: { spdx_id?: string } | null;
}

export const githubTrending = defineTool({
  name: "github_trending",
  title: "Trending GitHub repositories",
  description:
    "The fastest-rising new GitHub repositories: created in the last N days, ranked by stars, optionally filtered by language or topic. Names, descriptions, stars, forks, license and links. Good for spotting new tools and libraries early.",
  priceMicro: 1000,
  cacheTtl: 1800,
  input: z.object({
    days: z.number().int().min(1).max(90).optional().describe("Look at repositories created in the last N days. Default 7."),
    language: z.string().max(30).optional().describe('Programming language, e.g. "TypeScript" or "Rust".'),
    topic: z.string().max(50).optional().describe('GitHub topic, e.g. "mcp" or "ai-agents".'),
    limit: z.number().int().min(1).max(30).optional().describe("Number of repositories. Default 10."),
  }),
  example: { days: 7, topic: "mcp", limit: 5 },
  async run({ days, language, topic, limit }, { env }) {
    const since = new Date(Date.now() - (days ?? 7) * 86_400_000).toISOString().slice(0, 10);
    const clean = (s: string) => s.trim().replace(/[^\p{L}\p{N}+#.\- ]/gu, "").replace(/\s+/g, "-");
    const q = [`created:>${since}`, language ? `language:${clean(language)}` : "", topic ? `topic:${clean(topic).toLowerCase()}` : ""].filter(Boolean).join(" ");
    // Unauthenticated search is 10/min per IP and Cloudflare's IPs are shared; use the owner's token when set.
    const token = (env as Env).GITHUB_ALERT_TOKEN;
    const { status, data } = await fetchJson<{ total_count: number; items: GhRepo[] }>(
      `https://api.github.com/search/repositories?q=${encodeURIComponent(q)}&sort=stars&order=desc&per_page=${limit ?? 10}`,
      { timeoutMs: 8000, headers: { accept: "application/vnd.github+json", ...(token ? { authorization: `Bearer ${token}` } : {}) } },
    );
    if (!data) {
      if (status === 403 || status === 429) throw new ToolError("GitHub's search rate limit is reached. Try again in a minute.", "UPSTREAM_RATE_LIMITED", 503);
      throw new ToolError(`GitHub search didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    }
    return {
      since,
      matching: data.total_count,
      repositories: data.items.map((r) => ({
        name: r.full_name,
        url: r.html_url,
        description: r.description,
        language: r.language,
        stars: r.stargazers_count,
        forks: r.forks_count,
        created: r.created_at,
        topics: r.topics ?? [],
        license: r.license?.spdx_id ?? null,
      })),
    };
  },
});

const CURRENCY = /^[A-Za-z]{3}$/;

export const fxHistory = defineTool({
  name: "fx_history",
  title: "Exchange rate history",
  description:
    "Daily exchange rate history between currencies over a date range (European Central Bank reference rates, back to 1999), with the change over the period, high and low. For charts, backtests, invoices and trend questions.",
  priceMicro: 1000,
  cacheTtl: 21_600,
  input: z.object({
    base: z.string().regex(CURRENCY).describe('Currency code to convert from, e.g. "USD".'),
    symbols: z.array(z.string().regex(CURRENCY)).min(1).max(10).describe('Currencies to show, e.g. ["EUR", "JPY"].'),
    start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("First day, YYYY-MM-DD."),
    end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Last day, YYYY-MM-DD. Default today."),
  }),
  example: { base: "USD", symbols: ["EUR", "JPY"], start: "2026-10-01" },
  async run({ base, symbols, start, end }) {
    const days = (Date.parse(end ?? new Date().toISOString().slice(0, 10)) - Date.parse(start)) / 86_400_000;
    if (!(days >= 0)) throw new ToolError("start must be on or before end.", "INVALID_INPUT", 400);
    if (days > 731) throw new ToolError("At most two years per call.", "INVALID_INPUT", 400);
    const syms = [...new Set(symbols.map((s) => s.toUpperCase()))];
    const { status, data } = await fetchJson<{ base: string; start_date: string; end_date: string; rates: Record<string, Record<string, number>> }>(
      `https://api.frankfurter.dev/v1/${start}..${end ?? ""}?base=${base.toUpperCase()}&symbols=${syms.join(",")}`,
      { timeoutMs: 8000 },
    );
    if (!data) throw new ToolError(status === 404 ? "Unknown currency or no data for those dates." : `The rates service didn't answer (status ${status}).`, status === 404 ? "NOT_FOUND" : "UPSTREAM_ERROR", status === 404 ? 404 : 502);
    const dates = Object.keys(data.rates).sort();
    const series = Object.fromEntries(syms.map((s) => {
      const pts = dates.map((d) => ({ date: d, rate: data.rates[d]?.[s] })).filter((p): p is { date: string; rate: number } => typeof p.rate === "number");
      const first = pts[0]?.rate;
      const last = pts.at(-1)?.rate;
      return [s, {
        first: first ?? null,
        last: last ?? null,
        change_pct: first && last ? Math.round(((last - first) / first) * 10_000) / 100 : null,
        high: pts.length ? Math.max(...pts.map((p) => p.rate)) : null,
        low: pts.length ? Math.min(...pts.map((p) => p.rate)) : null,
        daily: pts,
      }];
    }));
    return { base: data.base, start: data.start_date, end: data.end_date, source: "European Central Bank reference rates", series };
  },
});

interface SecFact { start?: string; end: string; val: number; form: string; filed: string }

/**
 * Latest fiscal-year value of a us-gaap concept from 10-K filings, trying names in order.
 * Flows (revenue, income) must cover about a year; balances (assets) are point-in-time.
 * Picked by period end, not SEC's calendar frames, so non-December fiscal years work.
 */
async function annualFact(cik: string, names: string[], instant = false): Promise<{ value: number; fiscal_year_end: string; concept: string } | null> {
  // Companies switch tags over the years (e.g. Revenues vs RevenueFromContract...), so read them all and keep the newest.
  const found = await Promise.all(names.map(async (name) => {
    const { data } = await fetchJson<{ units?: Record<string, SecFact[]> }>(
      `https://data.sec.gov/api/xbrl/companyconcept/CIK${cik}/us-gaap/${name}.json`,
      { timeoutMs: 8000, headers: SEC_UA },
    ).catch(() => ({ data: null }));
    const facts = (data?.units?.USD ?? []).filter((f) => {
      if (!f.form.startsWith("10-K")) return false;
      if (instant) return !f.start;
      const days = f.start ? (Date.parse(f.end) - Date.parse(f.start)) / 86_400_000 : 0;
      return days >= 350 && days <= 380;
    });
    if (!facts.length) return null;
    // Latest period; among restatements of it, the most recently filed.
    const f = facts.reduce((a, b) => (b.end > a.end || (b.end === a.end && b.filed > a.filed) ? b : a));
    return { value: f.val, fiscal_year_end: f.end, concept: name };
  }));
  return found.reduce<{ value: number; fiscal_year_end: string; concept: string } | null>((best, f) => (f && (!best || f.fiscal_year_end > best.fiscal_year_end) ? f : best), null);
}

export const secFilings = defineTool({
  name: "sec_filings",
  title: "SEC filings and company financials",
  description:
    "US public company data from SEC EDGAR by ticker or name: legal name, CIK, industry, state, recent filings (10-K, 10-Q, 8-K...) with links, and latest annual revenue, net income and total assets from XBRL. Official data, not stock prices.",
  priceMicro: 2000,
  cacheTtl: 21_600,
  input: z.object({
    company: z.string().min(1).max(80).describe('Ticker or company name, e.g. "AAPL" or "Nvidia".'),
    forms: z.array(z.string().max(10)).max(5).optional().describe('Only these filing types, e.g. ["10-K", "8-K"].'),
    limit: z.number().int().min(1).max(25).optional().describe("Number of recent filings. Default 10."),
  }),
  example: { company: "AAPL", forms: ["10-K", "10-Q"], limit: 5 },
  async run({ company, forms, limit }) {
    const { data: hits } = await fetchJson<{ hits?: { hits?: { _id: string; _source: { entity: string; tickers?: string } }[] } }>(
      `https://efts.sec.gov/LATEST/search-index?keysTyped=${encodeURIComponent(company.trim())}`,
      { timeoutMs: 8000, headers: SEC_UA },
    );
    const list = hits?.hits?.hits ?? [];
    const want = company.trim().toUpperCase();
    const best = list.find((h) => (h._source.tickers ?? "").split(/[, ]+/).includes(want)) ?? list[0];
    if (!best) throw new ToolError(`No SEC-registered company matches "${company}".`, "NOT_FOUND", 404);
    const cik = best._id.padStart(10, "0");

    type Recent = { form: string[]; filingDate: string[]; accessionNumber: string[]; primaryDocument: string[]; primaryDocDescription: string[] };
    const { status, data: sub } = await fetchJson<{
      name: string; tickers: string[]; exchanges: string[]; sicDescription: string; stateOfIncorporation: string; fiscalYearEnd: string;
      website?: string; filings: { recent: Recent };
    }>(`https://data.sec.gov/submissions/CIK${cik}.json`, { timeoutMs: 8000, headers: SEC_UA });
    if (!sub) throw new ToolError(`SEC EDGAR didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);

    const r = sub.filings.recent;
    const wanted = forms?.map((f) => f.toUpperCase());
    const filings = r.form
      .map((form, i) => ({ form, i }))
      .filter(({ form }) => !wanted || wanted.includes(form.toUpperCase()))
      .slice(0, limit ?? 10)
      .map(({ form, i }) => {
        const acc = r.accessionNumber[i]!;
        return {
          form,
          filed: r.filingDate[i],
          description: r.primaryDocDescription[i] || null,
          url: `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${acc.replace(/-/g, "")}/${r.primaryDocument[i]}`,
        };
      });

    const [revenue, netIncome, assets] = await Promise.all([
      annualFact(cik, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]),
      annualFact(cik, ["NetIncomeLoss"]),
      annualFact(cik, ["Assets"], true),
    ]);
    return {
      name: sub.name,
      cik,
      tickers: sub.tickers,
      exchanges: sub.exchanges,
      industry: sub.sicDescription || null,
      state_of_incorporation: sub.stateOfIncorporation || null,
      fiscal_year_end: sub.fiscalYearEnd ? `${sub.fiscalYearEnd.slice(0, 2)}-${sub.fiscalYearEnd.slice(2)}` : null,
      financials_usd: { revenue, net_income: netIncome, total_assets: assets },
      recent_filings: filings,
      source: "SEC EDGAR",
    };
  },
});
