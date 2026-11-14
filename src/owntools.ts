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
  summarize: "summary summarizer tldr digest condense article recap llm",
  extract_data: "extract extraction structured json parse scrape fields entity llm",
  classify_text: "classify classification sentiment analysis categorize label intent topic spam moderation",
  currency_convert: "currency exchange rate fx forex convert money usd eur",
  public_holidays: "holiday holidays calendar business day bank national",
  wikipedia: "wiki encyclopedia knowledge facts summary entity lookup",
  hacker_news: "hn hackernews news stories tech discussion ycombinator",
  paper_search: "paper papers research academic arxiv science scholar publication",
  package_vulns: "vulnerability vulnerabilities cve security advisory dependency osv npm pypi",
  package_info: "package npm pypi crates library dependency version registry downloads",
  ip_lookup: "ip address geolocation owner asn network rdap reverse",
  redirect_check: "redirect unshorten shortener link url expand bitly tracking",
  geocode: "geocode geocoding address coordinates latitude longitude location map reverse",
  earthquakes: "earthquake earthquakes seismic quake usgs disaster",
  crypto_price: "crypto cryptocurrency price bitcoin btc ethereum eth solana coin market cap fear greed",
  dex_token: "dex token pair liquidity uniswap raydium memecoin dexscreener onchain",
  wallet_balance: "wallet balance address eth usdc evm onchain holdings",
  gas_price: "gas fee gwei ethereum base arbitrum chain",
  token_security: "token security honeypot scam rug rugpull audit contract risk tax",
  embed_text: "embedding embeddings vector vectors semantic similarity rag",
  rank_texts: "rerank reranker ranking relevance rag search",
  domain_available: "domain availability available register registration name check",
  describe_image: "image vision ocr picture photo screenshot caption describe read",
  text_to_speech: "tts speech voice audio speak narration",
  ask_llm: "llm chat completion gpt ai model prompt llama",
  transcribe_audio: "transcribe transcription speech stt audio whisper podcast voice",
  generate_image: "image generation generate picture art text-to-image flux illustration",
  document_to_markdown: "pdf docx word excel xlsx spreadsheet document parse parsing convert extract text file",
  email_verify: "email verify verification validate validation deliverability bounce disposable mx",
  scholar_search: "scholar academic paper papers journal article doi citation research crossref",
  regulations_search: "regulation regulations rule rules legal law federal register compliance policy government agency",
  drug_info: "drug drugs medicine medication fda pharmacy label recall health dosage",
  clinical_trials: "clinical trial trials study studies medical health research recruiting",
  book_search: "book books isbn author library novel reading publisher",
  economic_data: "economy economic gdp inflation unemployment population world bank indicator macro country",
  weather_alerts: "weather alert alerts warning storm tornado hurricane flood nws severe",
  product_lookup: "product barcode upc ean food nutrition ingredients allergens grocery",
  text_utils: "hash sha256 base64 encode decode uuid slug json format utility utilities word count readability flesch grade",
  jwt_decode: "jwt token decode claims bearer expiry auth jose",
  data_convert: "convert conversion json csv yaml xml tsv format transform",
  date_calc: "date dates business days working days calendar weekday add days difference deadline",
  time_zone: "timezone time zone convert clock utc offset dst local time",
  country_info: "country countries capital currency language calling code iso flag nation",
  math_calc: "math calculator calculate expression statistics stats mean median unit units convert",
  language_detect: "language detect detection identify which language",
  favicon: "favicon icon logo website brand touch icon",
  ens_lookup: "ens ethereum name service eth address resolve reverse",
  github_trending: "github trending repos repositories open source new projects stars libraries",
  fx_history: "exchange rate history forex fx currency historical rates chart ecb",
  sec_filings: "sec edgar filings 10-k 10-q 8-k annual report revenue earnings financials public company stock ticker"
};

/** Phrases where word order decides the tool ("speech to text" vs "text to speech"); word matching alone can't tell. */
const PHRASES: [RegExp, string][] = [
  [/speech[\s-]*(to|2)[\s-]*text|\bstt\b|transcri/i, "transcribe_audio"],
  [/text[\s-]*(to|2)[\s-]*speech|\btts\b|read (it )?aloud/i, "text_to_speech"],
  [/image[\s-]*(to|2)[\s-]*text|\bocr\b/i, "describe_image"],
  [/text[\s-]*(to|2)[\s-]*image/i, "generate_image"],
];

/** Not offered as search results: free helpers, and run_skill (it runs other listings). */
const SKIP = new Set(["search_marketplace", "register_agent", "run_skill"]);

const STOP = new Set(["an", "to", "of", "in", "on", "at", "is", "it", "my", "me", "or", "by", "be", "do", "how", "what", "can", "want", "need", "some", "this", "that", "the", "and", "for", "api", "apis", "tool", "tools", "get", "with", "from", "data", "service", "free", "check", "find", "lookup", "look", "any", "all"]);

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
    .map((t) => {
      // "Strong" words are the tool's name, title and synonyms: a hit there counts more than one in the description.
      const strong = matchScore(query, `${t.name.replace(/_/g, " ")} ${t.title} ${SYNONYMS[t.name] ?? ""}`);
      const score = matchScore(query, `${t.name.replace(/_/g, " ")} ${t.title} ${t.description} ${SYNONYMS[t.name] ?? ""}`);
      // A query that is exactly a tool's name ("weather") should rank that tool above its relatives ("weather_alerts").
      const exact = words(query).join(" ") === t.name.replace(/_/g, " ") ? 1 : 0;
      // Share of the tool's own name the query covers: "weather in paris" covers all of weather but half of weather_alerts.
      const nameWords = t.name.split("_");
      const qStems = new Set(words(query).map(stem));
      const coverage = nameWords.filter((w) => qStems.has(stem(w))).length / nameWords.length;
      const phrase = PHRASES.some(([re, tool]) => tool === t.name && re.test(query)) ? 1 : 0;
      return { t, score, strong, rank: score + strong / 2 + exact + coverage * 0.3 + phrase };
    })
    // Half the words matching only in the description is too weak ("image generation" vs "...an image...").
    .filter((x) => x.score >= 0.5 && (x.strong > 0 || x.score === 1))
    .sort((a, b) => b.rank - a.rank)
    // Only the best-matching tools: "translate text" shouldn't also offer page_to_markdown for the word "text".
    .filter((x, _, all) => x.rank >= all[0]!.rank - 0.01)
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
