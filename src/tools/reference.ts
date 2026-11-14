import { z } from "zod";
import { fetchBytes, fetchJson } from "../lib/net";
import { ToolError } from "../lib/errors";
import { resolve } from "./dns";
import { defineTool } from "./types";

/**
 * More categories from free, keyless sources that allow reuse: document parsing
 * (Workers AI), email checks, Crossref, the Federal Register, openFDA,
 * ClinicalTrials.gov, Open Library, the World Bank, the US National Weather
 * Service and Open Food Facts, plus offline text utilities.
 */

const strip = (s: unknown, max = 600) =>
  typeof s === "string" ? s.replace(/<[^>]+>/g, " ").replace(/&[a-z]+;/g, " ").replace(/\s+/g, " ").trim().slice(0, max) : null;

// ---------- documents ----------

const DOC_TYPES: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.ms-excel": "xls",
  "application/vnd.oasis.opendocument.text": "odt",
  "application/vnd.oasis.opendocument.spreadsheet": "ods",
  "text/csv": "csv",
  "text/html": "html",
  "application/xml": "xml",
  "text/xml": "xml",
};

export const documentToMarkdown = defineTool({
  name: "document_to_markdown",
  title: "PDF and document to Markdown",
  description:
    "Convert a PDF, Word (.docx), Excel (.xlsx/.xls), OpenDocument, CSV, HTML or XML file at a URL into clean Markdown text an LLM can read. Up to 10 MB. Great for invoices, reports, papers, contracts and spreadsheets.",
  priceMicro: 4000,
  cacheTtl: 86_400,
  input: z.object({
    url: z.string().max(2000).describe("Public URL of the document."),
    max_chars: z.number().int().min(1000).max(200_000).optional().describe("Longest Markdown to return. Default 50,000."),
  }),
  example: { url: "https://arxiv.org/pdf/1706.03762" },
  async run({ url, max_chars }, { env }) {
    if (!env.AI) throw new ToolError("Document conversion is not available right now.", "UNAVAILABLE", 503);
    const file = await fetchBytes(url, { maxBytes: 10_000_000, timeoutMs: 20_000 });
    const ext = (/\.([a-z0-9]{2,5})(?:$|\?)/i.exec(new URL(file.url).pathname)?.[1] ?? "").toLowerCase();
    const kind = DOC_TYPES[file.contentType] ?? (Object.values(DOC_TYPES).includes(ext) ? ext : null);
    if (!kind) throw new ToolError("Unsupported file type. Send a PDF, DOCX, XLSX, XLS, ODT, ODS, CSV, HTML or XML file.", "UNSUPPORTED_TYPE", 415);
    let out: { data?: string; tokens?: number; format?: string; error?: string };
    try {
      out = (await env.AI.toMarkdown({ name: `document.${kind}`, blob: new Blob([file.bytes], { type: file.contentType || "application/octet-stream" }) })) as typeof out;
    } catch (err) {
      console.log("toMarkdown failed", err instanceof Error ? err.message : String(err));
      throw new ToolError("Couldn't read that document. It may be scanned, encrypted or damaged.", "CONVERSION_FAILED", 422);
    }
    const md = (out.data ?? "").trim();
    if (!md) throw new ToolError(out.error ? `Couldn't read that document: ${out.error}` : "No text found in that document (it may be a scanned image).", "EMPTY_DOCUMENT", 422);
    const limit = max_chars ?? 50_000;
    return {
      url: file.url,
      type: kind,
      bytes: file.bytes.byteLength,
      characters: md.length,
      truncated: md.length > limit,
      markdown: md.length > limit ? `${md.slice(0, limit)}\n\n[truncated]` : md,
    };
  },
});

// ---------- email verification ----------

const FREE_PROVIDERS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com",
  "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.net", "mail.com", "zoho.com", "yandex.com", "yandex.ru", "qq.com", "163.com", "126.com", "fastmail.com", "tutanota.com", "hey.com",
]);
const ROLE = /^(admin|administrator|billing|contact|enquiries|help|hello|hi|hr|info|inquiries|jobs|careers|legal|marketing|media|newsletter|no-?reply|office|orders|postmaster|press|privacy|sales|security|support|team|webmaster|abuse)$/;
const TYPOS: Record<string, string> = {
  "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gamil.com": "gmail.com", "gmail.co": "gmail.com", "gnail.com": "gmail.com", "gmail.con": "gmail.com",
  "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmail.co": "hotmail.com", "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.co": "yahoo.com",
  "outlok.com": "outlook.com", "outloo.com": "outlook.com", "iclud.com": "icloud.com", "icloud.co": "icloud.com",
};
const DISPOSABLE_URL = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/disposable_email_blocklist.conf";
let disposable: { at: number; set: Set<string> } | null = null;

async function disposableDomains(): Promise<Set<string> | null> {
  if (disposable && Date.now() - disposable.at < 86_400_000) return disposable.set;
  try {
    const res = await fetch(DISPOSABLE_URL, { signal: AbortSignal.timeout(6000), cf: { cacheTtl: 86_400, cacheEverything: true } } as RequestInit);
    if (!res.ok) return disposable?.set ?? null;
    const set = new Set((await res.text()).split("\n").map((l) => l.trim().toLowerCase()).filter((l) => l && !l.startsWith("#")));
    disposable = { at: Date.now(), set };
    return set;
  } catch {
    return disposable?.set ?? null;
  }
}

/** Syntax check close to what mail providers accept (not the full RFC 5322 grammar). */
export function emailSyntax(email: string): { ok: boolean; local: string; domain: string; reason?: string } {
  const e = email.trim();
  const at = e.lastIndexOf("@");
  if (at < 1 || at === e.length - 1) return { ok: false, local: "", domain: "", reason: "Missing @ or a part before/after it." };
  const local = e.slice(0, at);
  const domain = e.slice(at + 1).toLowerCase();
  if (local.length > 64) return { ok: false, local, domain, reason: "The part before @ is longer than 64 characters." };
  if (!/^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$/.test(local) || local.startsWith(".") || local.endsWith(".") || local.includes(".."))
    return { ok: false, local, domain, reason: "The part before @ has characters or dots that aren't allowed." };
  if (!/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain)) return { ok: false, local, domain, reason: "The domain isn't valid." };
  return { ok: true, local, domain };
}

export const emailVerify = defineTool({
  name: "email_verify",
  title: "Email address verification",
  description:
    "Check if an email address can receive mail before you send: syntax, whether the domain has mail servers (MX), disposable/throwaway providers (100k+ domains), role addresses like info@ or support@, free-provider detection and typo suggestions (gmial.com -> gmail.com). Returns a deliverable / risky / undeliverable verdict.",
  priceMicro: 2000,
  cacheTtl: 86_400,
  input: z.object({ email: z.string().min(3).max(320).describe("The email address to check.") }),
  example: { email: "jane.doe@gmial.com" },
  async run({ email }) {
    const syn = emailSyntax(email);
    if (!syn.ok) return { email, verdict: "undeliverable", reason: syn.reason, syntax_ok: false };
    const { local, domain } = syn;
    const [mx, aRecords, disp] = await Promise.all([
      resolve(domain, "MX").catch(() => null),
      resolve(domain, "A").catch(() => null),
      disposableDomains(),
    ]);
    const mxHosts = (mx ?? []).map((r) => r.value.split(/\s+/).pop()!.replace(/\.$/, "")).filter((h) => h && h !== "");
    const nullMx = mxHosts.length === 1 && (mxHosts[0] === "" || mxHosts[0] === ".");
    const acceptsMail = mxHosts.length > 0 ? !nullMx : (aRecords?.length ?? 0) > 0; // RFC 5321: fall back to the A record
    const isDisposable = disp ? disp.has(domain) || [...domain.split(".").keys()].some((i) => i > 0 && disp.has(domain.split(".").slice(i).join("."))) : null;
    const isRole = ROLE.test(local.toLowerCase());
    const suggestion = TYPOS[domain] ? `${local}@${TYPOS[domain]}` : null;
    const reasons: string[] = [];
    if (mx === null) reasons.push("Couldn't check the domain's mail servers right now.");
    else if (!acceptsMail) reasons.push("The domain has no mail servers, so mail will bounce.");
    if (isDisposable) reasons.push("Disposable (throwaway) email provider.");
    if (isRole) reasons.push("Role address: often a shared inbox, lower engagement.");
    if (suggestion) reasons.push(`Possible typo: did you mean ${suggestion}?`);
    const verdict = mx !== null && !acceptsMail ? "undeliverable" : isDisposable || suggestion || isRole || mx === null ? "risky" : "deliverable";
    return {
      email, verdict, reasons, syntax_ok: true, domain,
      has_mx: mxHosts.length > 0 && !nullMx, mx: mxHosts.slice(0, 5),
      disposable: isDisposable, role_address: isRole, free_provider: FREE_PROVIDERS.has(domain), suggestion,
      note: "Mailbox existence isn't probed (SMTP checks are unreliable and often blocked); this checks everything short of sending.",
    };
  },
});

// ---------- scholarly works (Crossref) ----------

interface CrossrefWork {
  DOI: string; title?: string[]; author?: { given?: string; family?: string; name?: string }[]; published?: { "date-parts"?: number[][] };
  "container-title"?: string[]; "is-referenced-by-count"?: number; type?: string; URL?: string; abstract?: string; publisher?: string;
}

export const scholarSearch = defineTool({
  name: "scholar_search",
  title: "Scholarly article search (Crossref)",
  description:
    "Search 160M+ journal articles, conference papers, books and preprints across every field via Crossref: title, authors, journal, year, DOI, citation count and abstract. Or look up one DOI. Complements arXiv paper_search.",
  priceMicro: 2000,
  cacheTtl: 86_400,
  input: z.object({
    query: z.string().max(300).optional().describe('Topic, title or author, e.g. "CRISPR off-target effects". Use this or doi.'),
    doi: z.string().max(200).optional().describe('A DOI to look up, e.g. "10.1038/nature14539".'),
    sort: z.enum(["relevance", "newest", "most_cited"]).optional().describe('"relevance" (default), "newest" or "most_cited".'),
    limit: z.number().int().min(1).max(25).optional().describe("Number of results. Default 10."),
  }),
  example: { query: "large language model agents", sort: "most_cited", limit: 5 },
  async run({ query, doi, sort, limit }) {
    const shape = (w: CrossrefWork) => ({
      title: w.title?.[0] ?? null,
      authors: (w.author ?? []).slice(0, 10).map((a) => a.name ?? [a.given, a.family].filter(Boolean).join(" ")),
      year: w.published?.["date-parts"]?.[0]?.[0] ?? null,
      venue: w["container-title"]?.[0] ?? null,
      publisher: w.publisher ?? null,
      type: w.type ?? null,
      citations: w["is-referenced-by-count"] ?? null,
      doi: w.DOI,
      url: w.URL ?? `https://doi.org/${w.DOI}`,
      abstract: strip(w.abstract, 1200),
    });
    if (doi?.trim()) {
      const d = doi.trim().replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
      if (!/^10\.\d{4,9}\/\S+$/.test(d)) throw new ToolError(`"${doi}" isn't a valid DOI.`, "INVALID_INPUT", 400);
      const { status, data } = await fetchJson<{ message: CrossrefWork }>(`https://api.crossref.org/works/${encodeURIComponent(d)}`, { timeoutMs: 10_000 });
      if (!data) throw new ToolError(status === 404 ? `No work found for DOI ${d}.` : `Crossref didn't answer (status ${status}).`, status === 404 ? "NOT_FOUND" : "UPSTREAM_ERROR", status === 404 ? 404 : 502);
      return { results: [shape(data.message)], total: 1, credit: "Metadata: Crossref (CC0)." };
    }
    if (!query?.trim()) throw new ToolError("Pass a query or a DOI.", "INVALID_INPUT", 400);
    const qs = new URLSearchParams({
      query: query.trim(),
      rows: String(limit ?? 10),
      select: "DOI,title,author,published,container-title,is-referenced-by-count,type,URL,abstract,publisher",
    });
    // "most_cited" ranks the 50 most relevant by citations; sorting all matches by citations returns famous but off-topic papers.
    if (sort === "most_cited") qs.set("rows", "50");
    if (sort === "newest") {
      qs.set("sort", "published");
      qs.set("order", "desc");
    }
    const { status, data } = await fetchJson<{ message: { "total-results": number; items: CrossrefWork[] } }>(`https://api.crossref.org/works?${qs}`, { timeoutMs: 12_000 });
    if (!data) throw new ToolError(`Crossref didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    let items = data.message.items;
    if (sort === "most_cited") items = [...items].sort((a, b) => (b["is-referenced-by-count"] ?? 0) - (a["is-referenced-by-count"] ?? 0)).slice(0, limit ?? 10);
    return { query, total: data.message["total-results"], results: items.map(shape), credit: "Metadata: Crossref (CC0)." };
  },
});

// ---------- US Federal Register ----------

interface FrDoc { title: string; type: string; abstract?: string; document_number: string; html_url: string; pdf_url?: string; publication_date: string; agencies?: { name?: string }[]; effective_on?: string | null; comments_close_on?: string | null }

export const regulationsSearch = defineTool({
  name: "regulations_search",
  title: "US regulations and rules search",
  description:
    "Search the US Federal Register: final rules, proposed rules, notices and presidential documents from every federal agency since 1994, with agency, dates, comment deadlines and links. Good for compliance, policy and legal research.",
  priceMicro: 2000,
  cacheTtl: 3600,
  input: z.object({
    query: z.string().min(1).max(300).describe('Search words, e.g. "stablecoin" or "AI disclosure".'),
    type: z.enum(["rule", "proposed_rule", "notice", "presidential"]).optional().describe("Only this document type."),
    agency: z.string().max(100).optional().describe('Agency slug, e.g. "securities-and-exchange-commission", "federal-trade-commission".'),
    since: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Published on or after (YYYY-MM-DD)."),
    limit: z.number().int().min(1).max(20).optional().describe("Number of documents. Default 10, newest first."),
  }),
  example: { query: "stablecoin", type: "rule", limit: 5 },
  async run({ query, type, agency, since, limit }) {
    const qs = new URLSearchParams({ "conditions[term]": query, per_page: String(limit ?? 10), order: "newest" });
    if (type) qs.set("conditions[type][]", { rule: "RULE", proposed_rule: "PRORULE", notice: "NOTICE", presidential: "PRESDOCU" }[type]);
    if (agency) qs.set("conditions[agencies][]", agency.trim().toLowerCase());
    if (since) qs.set("conditions[publication_date][gte]", since);
    const { status, data } = await fetchJson<{ count: number; results?: FrDoc[] }>(`https://www.federalregister.gov/api/v1/documents.json?${qs}`, { timeoutMs: 10_000 });
    if (!data) throw new ToolError(`The Federal Register didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    return {
      query,
      total: data.count,
      documents: (data.results ?? []).map((d) => ({
        title: d.title, type: d.type, agencies: (d.agencies ?? []).map((a) => a.name).filter(Boolean),
        published: d.publication_date, effective: d.effective_on ?? null, comments_close: d.comments_close_on ?? null,
        summary: strip(d.abstract, 800), document_number: d.document_number, url: d.html_url, pdf: d.pdf_url ?? null,
      })),
      credit: "Federal Register (federalregister.gov), public domain.",
    };
  },
});

// ---------- drugs (openFDA) ----------

const first = (v: unknown, max = 700) => (Array.isArray(v) ? strip(v[0], max) : strip(v, max));

export const drugInfo = defineTool({
  name: "drug_info",
  title: "Drug label and recall lookup (FDA)",
  description:
    "Look up a US medicine by brand or generic name in FDA data: what it's for, active ingredients, dosage, warnings, when to ask a doctor, manufacturer, plus recent FDA recalls. Information only, not medical advice.",
  priceMicro: 2000,
  cacheTtl: 86_400,
  input: z.object({ name: z.string().min(2).max(100).describe('Brand or generic name, e.g. "Advil" or "metformin".') }),
  example: { name: "ibuprofen" },
  async run({ name }) {
    const term = name.trim().replace(/[^\p{L}\p{N} -]/gu, "");
    if (!term) throw new ToolError("Give a drug name.", "INVALID_INPUT", 400);
    const q = encodeURIComponent(`openfda.brand_name:"${term}" OR openfda.generic_name:"${term}"`);
    const [label, recalls] = await Promise.all([
      fetchJson<{ results?: Record<string, unknown>[] }>(`https://api.fda.gov/drug/label.json?search=${q}&limit=1`, { timeoutMs: 10_000 }),
      fetchJson<{ results?: Record<string, string>[] }>(
        `https://api.fda.gov/drug/enforcement.json?search=${encodeURIComponent(`product_description:"${term}"`)}&limit=5&sort=report_date:desc`,
        { timeoutMs: 10_000 },
      ).catch(() => ({ data: null })),
    ]);
    const l = label.data?.results?.[0];
    if (!l) throw new ToolError(`No FDA drug label found for "${name}".`, "NOT_FOUND", 404);
    const fda = (l.openfda ?? {}) as Record<string, string[]>;
    return {
      brand_names: fda.brand_name ?? [], generic_names: fda.generic_name ?? [], manufacturer: fda.manufacturer_name?.[0] ?? null,
      route: fda.route ?? [], product_type: fda.product_type?.[0] ?? null,
      purpose: first(l.purpose), uses: first(l.indications_and_usage), active_ingredients: first(l.active_ingredient, 400),
      dosage: first(l.dosage_and_administration, 1000), warnings: first(l.warnings ?? l.boxed_warning, 1200),
      do_not_use: first(l.do_not_use), ask_doctor: first(l.ask_doctor), stop_use: first(l.stop_use),
      pregnancy: first(l.pregnancy_or_breast_feeding ?? l.pregnancy, 400),
      label_updated: typeof l.effective_time === "string" ? `${l.effective_time.slice(0, 4)}-${l.effective_time.slice(4, 6)}-${l.effective_time.slice(6, 8)}` : null,
      recent_recalls: (recalls.data?.results ?? []).map((r) => ({
        date: r.report_date ? `${r.report_date.slice(0, 4)}-${r.report_date.slice(4, 6)}-${r.report_date.slice(6, 8)}` : null,
        class: r.classification, status: r.status, firm: r.recalling_firm, reason: strip(r.reason_for_recall, 300), product: strip(r.product_description, 200),
      })),
      disclaimer: "From FDA labeling data (openFDA). Not medical advice; ask a doctor or pharmacist.",
    };
  },
});

// ---------- clinical trials ----------

interface CtStudy { protocolSection: Record<string, Record<string, unknown>> }

export const clinicalTrials = defineTool({
  name: "clinical_trials",
  title: "Clinical trials search",
  description:
    "Search 500k+ clinical studies worldwide on ClinicalTrials.gov by condition, drug or keyword: status (recruiting, completed...), phase, sponsor, enrollment, start date, countries and the study link.",
  priceMicro: 2000,
  cacheTtl: 3600,
  input: z.object({
    query: z.string().min(1).max(200).describe('Condition, drug or keyword, e.g. "GLP-1 obesity".'),
    status: z.enum(["recruiting", "active", "completed", "any"]).optional().describe('Filter by status. Default "any".'),
    limit: z.number().int().min(1).max(25).optional().describe("Number of studies. Default 10."),
  }),
  example: { query: "GLP-1 obesity", status: "recruiting", limit: 5 },
  async run({ query, status, limit }) {
    const qs = new URLSearchParams({
      "query.term": query,
      pageSize: String(limit ?? 10),
      countTotal: "true",
      fields: "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,LeadSponsorName,StartDate,PrimaryCompletionDate,EnrollmentCount,LocationCountry,BriefSummary",
    });
    const map = { recruiting: "RECRUITING", active: "ACTIVE_NOT_RECRUITING", completed: "COMPLETED" } as const;
    if (status && status !== "any") qs.set("filter.overallStatus", map[status]);
    const { status: http, data } = await fetchJson<{ totalCount?: number; studies?: CtStudy[] }>(`https://clinicaltrials.gov/api/v2/studies?${qs}`, { timeoutMs: 12_000 });
    if (!data) throw new ToolError(`ClinicalTrials.gov didn't answer (status ${http}).`, "UPSTREAM_ERROR", 502);
    return {
      query,
      total: data.totalCount ?? null,
      studies: (data.studies ?? []).map(({ protocolSection: p }) => {
        const id = p.identificationModule as { nctId: string; briefTitle?: string };
        const st = (p.statusModule ?? {}) as { overallStatus?: string; startDateStruct?: { date?: string }; primaryCompletionDateStruct?: { date?: string } };
        const design = (p.designModule ?? {}) as { phases?: string[]; enrollmentInfo?: { count?: number } };
        const locs = ((p.contactsLocationsModule ?? {}) as { locations?: { country?: string }[] }).locations ?? [];
        return {
          id: id.nctId, title: id.briefTitle ?? null, status: st.overallStatus ?? null, phases: design.phases ?? [],
          conditions: ((p.conditionsModule ?? {}) as { conditions?: string[] }).conditions ?? [],
          interventions: (((p.armsInterventionsModule ?? {}) as { interventions?: { name?: string }[] }).interventions ?? []).map((i) => i.name).filter(Boolean),
          sponsor: ((p.sponsorCollaboratorsModule ?? {}) as { leadSponsor?: { name?: string } }).leadSponsor?.name ?? null,
          enrollment: design.enrollmentInfo?.count ?? null, start: st.startDateStruct?.date ?? null, primary_completion: st.primaryCompletionDateStruct?.date ?? null,
          countries: [...new Set(locs.map((l) => l.country).filter(Boolean))].slice(0, 10),
          summary: strip(((p.descriptionModule ?? {}) as { briefSummary?: string }).briefSummary, 500),
          url: `https://clinicaltrials.gov/study/${id.nctId}`,
        };
      }),
      credit: "ClinicalTrials.gov (U.S. National Library of Medicine).",
    };
  },
});

// ---------- books ----------

export const bookSearch = defineTool({
  name: "book_search",
  title: "Book search (Open Library)",
  description:
    "Find books by title, author, subject or ISBN across 40M+ records in Open Library: authors, first published year, editions, page count, ISBNs, subjects, ratings and cover image.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({
    query: z.string().max(200).optional().describe('Title, author or keywords, e.g. "dune herbert". Use this or isbn.'),
    isbn: z.string().max(20).optional().describe("An ISBN-10 or ISBN-13."),
    limit: z.number().int().min(1).max(20).optional().describe("Number of books. Default 5."),
  }),
  example: { query: "the pragmatic programmer" },
  async run({ query, isbn, limit }) {
    const q = isbn?.trim() ? `isbn:${isbn.replace(/[^0-9Xx]/g, "")}` : query?.trim();
    if (!q) throw new ToolError("Pass a query or an ISBN.", "INVALID_INPUT", 400);
    const qs = new URLSearchParams({
      q, limit: String(limit ?? 5),
      fields: "key,title,subtitle,author_name,first_publish_year,isbn,subject,edition_count,cover_i,ratings_average,ratings_count,number_of_pages_median,publisher,language",
    });
    const { status, data } = await fetchJson<{ numFound: number; docs: Record<string, unknown>[] }>(`https://openlibrary.org/search.json?${qs}`, { timeoutMs: 10_000 });
    if (!data) throw new ToolError(`Open Library didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    if (!data.docs.length) throw new ToolError("No books found.", "NOT_FOUND", 404);
    return {
      total: data.numFound,
      books: data.docs.map((d) => ({
        title: [d.title, d.subtitle].filter(Boolean).join(": "),
        authors: (d.author_name as string[] | undefined) ?? [],
        first_published: d.first_publish_year ?? null,
        editions: d.edition_count ?? null,
        pages: d.number_of_pages_median ?? null,
        rating: typeof d.ratings_average === "number" ? Math.round((d.ratings_average as number) * 100) / 100 : null,
        ratings: d.ratings_count ?? null,
        isbns: ((d.isbn as string[] | undefined) ?? []).slice(0, 5),
        subjects: ((d.subject as string[] | undefined) ?? []).slice(0, 8),
        publishers: ((d.publisher as string[] | undefined) ?? []).slice(0, 3),
        cover: d.cover_i ? `https://covers.openlibrary.org/b/id/${d.cover_i}-L.jpg` : null,
        url: `https://openlibrary.org${d.key}`,
      })),
      credit: "Open Library (Internet Archive).",
    };
  },
});

// ---------- economic data (World Bank) ----------

export const INDICATORS: Record<string, { code: string; label: string }> = {
  gdp: { code: "NY.GDP.MKTP.CD", label: "GDP (current US$)" },
  gdp_growth: { code: "NY.GDP.MKTP.KD.ZG", label: "GDP growth (annual %)" },
  gdp_per_capita: { code: "NY.GDP.PCAP.CD", label: "GDP per capita (current US$)" },
  population: { code: "SP.POP.TOTL", label: "Population, total" },
  inflation: { code: "FP.CPI.TOTL.ZG", label: "Inflation, consumer prices (annual %)" },
  unemployment: { code: "SL.UEM.TOTL.ZS", label: "Unemployment (% of labor force)" },
  life_expectancy: { code: "SP.DYN.LE00.IN", label: "Life expectancy at birth (years)" },
  debt_to_gdp: { code: "GC.DOD.TOTL.GD.ZS", label: "Central government debt (% of GDP)" },
  exports: { code: "NE.EXP.GNFS.CD", label: "Exports of goods and services (current US$)" },
  internet_users: { code: "IT.NET.USER.ZS", label: "Internet users (% of population)" },
  co2_per_capita: { code: "EN.GHG.CO2.PC.CE.AR5", label: "CO2 emissions (t per capita)" },
};

export const economicData = defineTool({
  name: "economic_data",
  title: "Country economic indicators",
  description:
    "Official World Bank figures for any country and year range: GDP, growth, GDP per capita, population, inflation, unemployment, life expectancy, government debt, exports, internet use and CO2, or any World Bank indicator code.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({
    country: z.string().min(2).max(3).describe('ISO country code, e.g. "US", "DE", "BRA", or "WLD" for the world.'),
    indicator: z.string().min(2).max(40).describe(`One of: ${Object.keys(INDICATORS).join(", ")}; or a World Bank code like "NY.GDP.MKTP.CD".`),
    years: z.number().int().min(1).max(60).optional().describe("Most recent N years with data. Default 10."),
  }),
  example: { country: "US", indicator: "inflation", years: 5 },
  async run({ country, indicator, years }) {
    const cc = country.trim().toUpperCase();
    if (!/^[A-Z]{2,3}$/.test(cc)) throw new ToolError("Use a 2- or 3-letter country code.", "INVALID_INPUT", 400);
    const known = INDICATORS[indicator.trim().toLowerCase()];
    const code = known?.code ?? indicator.trim().toUpperCase();
    if (!/^[A-Z0-9._]{3,40}$/.test(code)) throw new ToolError(`Unknown indicator "${indicator}".`, "INVALID_INPUT", 400);
    // The World Bank API sometimes hangs on a request that answers instantly when retried.
    type WbRows = [{ message?: { value: string }[] } & Record<string, unknown>, { date: string; value: number | null; country: { value: string }; indicator: { value: string } }[] | null];
    const wbUrl = `https://api.worldbank.org/v2/country/${cc}/indicator/${code}?format=json&mrv=${(years ?? 10) + 5}`; // mrnev hangs; drop gaps ourselves
    let res: { status: number; data: WbRows | null } = { status: 0, data: null };
    for (let attempt = 0; attempt < 2 && !res.data; attempt++) {
      try {
        res = await fetchJson<WbRows>(wbUrl, { timeoutMs: 6000 });
      } catch (err) {
        if (attempt === 1) throw err;
      }
    }
    const { status, data } = res;
    const rows = data?.[1]?.filter((r) => r.value !== null).slice(0, years ?? 10);
    if (!rows?.length) {
      const msg = data?.[0]?.message?.[0]?.value;
      throw new ToolError(msg ? `World Bank: ${msg}` : `No data for ${cc} / ${code} (status ${status}).`, "NOT_FOUND", 404);
    }
    return {
      country: rows[0]!.country.value,
      indicator: rows[0]!.indicator.value,
      code,
      values: rows.map((r) => ({ year: Number(r.date), value: r.value })).sort((a, b) => b.year - a.year),
      credit: "World Bank Open Data (CC BY 4.0).",
    };
  },
});

// ---------- US weather alerts ----------

interface NwsAlert { properties: { event: string; severity: string; urgency: string; certainty: string; headline?: string; areaDesc: string; effective?: string; expires?: string; senderName?: string; description?: string; instruction?: string | null } }

export const weatherAlerts = defineTool({
  name: "weather_alerts",
  title: "Severe weather alerts (US)",
  description:
    "Active US National Weather Service warnings, watches and advisories (tornado, flood, hurricane, heat, winter storm, fire weather...) for a state or a point: event, severity, area, start and end times and safety instructions.",
  priceMicro: 1000,
  cacheTtl: 300,
  input: z.object({
    state: z.string().length(2).optional().describe('US state code, e.g. "TX". Use this or lat/lon.'),
    lat: z.number().min(-90).max(90).optional().describe("Latitude of a US location."),
    lon: z.number().min(-180).max(180).optional().describe("Longitude of a US location."),
  }),
  example: { state: "TX" },
  async run({ state, lat, lon }) {
    let qs: string;
    if (typeof lat === "number" && typeof lon === "number") qs = `point=${Math.round(lat * 1e4) / 1e4},${Math.round(lon * 1e4) / 1e4}`;
    else if (state && /^[A-Za-z]{2}$/.test(state)) qs = `area=${state.toUpperCase()}`;
    else throw new ToolError("Pass a 2-letter US state, or lat and lon.", "INVALID_INPUT", 400);
    const { status, data } = await fetchJson<{ features?: NwsAlert[] }>(`https://api.weather.gov/alerts/active?${qs}`, {
      timeoutMs: 10_000,
      headers: { accept: "application/geo+json" },
    });
    if (!data?.features) throw new ToolError(status === 400 ? "That location isn't covered by the US National Weather Service." : `The weather service didn't answer (status ${status}).`, "UPSTREAM_ERROR", status === 400 ? 400 : 502);
    const order = ["Extreme", "Severe", "Moderate", "Minor", "Unknown"];
    const alerts = data.features
      .map(({ properties: a }) => ({
        event: a.event, severity: a.severity, urgency: a.urgency, certainty: a.certainty, headline: a.headline ?? null,
        area: a.areaDesc, starts: a.effective ?? null, ends: a.expires ?? null, issued_by: a.senderName ?? null,
        description: strip(a.description, 800), instruction: strip(a.instruction, 500),
      }))
      .sort((x, y) => order.indexOf(x.severity) - order.indexOf(y.severity));
    return { count: alerts.length, alerts, credit: "U.S. National Weather Service (public domain)." };
  },
});

// ---------- food products (Open Food Facts) ----------

export const productLookup = defineTool({
  name: "product_lookup",
  title: "Food product and barcode lookup",
  description:
    "Look up a packaged food or drink by barcode (EAN/UPC) or name in Open Food Facts (3M+ products): brand, ingredients, allergens, Nutri-Score, NOVA processing level and nutrition per 100 g.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({
    barcode: z.string().max(20).optional().describe("EAN-13 / UPC barcode digits."),
    query: z.string().max(100).optional().describe('Product name, e.g. "nutella". Use this or barcode.'),
  }),
  example: { barcode: "3017620422003" },
  async run({ barcode, query }) {
    type Product = Record<string, unknown> & { nutriments?: Record<string, number> };
    let product: Product | undefined;
    const fields = "code,product_name,brands,quantity,categories,ingredients_text,allergens_tags,nutriscore_grade,nova_group,nutriments,image_url,countries";
    if (barcode?.trim()) {
      const code = barcode.replace(/\D/g, "");
      if (code.length < 8) throw new ToolError("A barcode needs at least 8 digits.", "INVALID_INPUT", 400);
      const { data } = await fetchJson<{ status: number; product?: Product }>(`https://world.openfoodfacts.org/api/v2/product/${code}.json?fields=${fields}`, { timeoutMs: 10_000 });
      product = data?.status === 1 ? data.product : undefined;
    } else if (query?.trim()) {
      const { data } = await fetchJson<{ hits?: Product[] }>(`https://search.openfoodfacts.org/search?q=${encodeURIComponent(query.trim())}&page_size=1&fields=${fields}`, { timeoutMs: 10_000 });
      product = data?.hits?.[0];
    } else throw new ToolError("Pass a barcode or a product name.", "INVALID_INPUT", 400);
    if (!product) throw new ToolError("Product not found.", "NOT_FOUND", 404);
    const n = product.nutriments ?? {};
    const pick = (k: string) => (typeof n[`${k}_100g`] === "number" ? Math.round(n[`${k}_100g`]! * 100) / 100 : null);
    const brands = product.brands;
    return {
      barcode: product.code ?? barcode ?? null,
      name: product.product_name ?? null,
      brands: Array.isArray(brands) ? brands : typeof brands === "string" ? brands.split(",").map((b) => b.trim()) : [],
      quantity: product.quantity ?? null,
      nutriscore: typeof product.nutriscore_grade === "string" ? product.nutriscore_grade.toUpperCase() : null,
      nova_group: product.nova_group ?? null,
      allergens: ((product.allergens_tags as string[] | undefined) ?? []).map((a) => a.replace(/^[a-z]{2}:/, "")),
      ingredients: strip(product.ingredients_text, 1500),
      per_100g: { energy_kcal: pick("energy-kcal"), fat_g: pick("fat"), saturated_fat_g: pick("saturated-fat"), carbs_g: pick("carbohydrates"), sugars_g: pick("sugars"), fiber_g: pick("fiber"), protein_g: pick("proteins"), salt_g: pick("salt") },
      image: product.image_url ?? null,
      url: product.code ? `https://world.openfoodfacts.org/product/${product.code}` : null,
      credit: "Open Food Facts (ODbL).",
    };
  },
});

// ---------- text utilities (no network) ----------

async function digest(algo: "SHA-1" | "SHA-256" | "SHA-512", text: string) {
  const buf = await crypto.subtle.digest(algo, new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export const textUtils = defineTool({
  name: "text_utils",
  title: "Text utilities (hash, encode, UUID, stats)",
  description:
    "Everyday text operations in one call: SHA-1/256/512 hashes, Base64 and URL encode/decode, slugs, UUIDs, JSON validation and pretty-printing, and word/character/sentence counts with reading time.",
  priceMicro: 1000,
  cacheTtl: 0,
  input: z.object({
    op: z.enum(["sha256", "sha1", "sha512", "base64_encode", "base64_decode", "url_encode", "url_decode", "slugify", "uuid", "json_format", "stats"]).describe("The operation."),
    text: z.string().max(100_000).optional().describe("Input text (not needed for uuid)."),
    count: z.number().int().min(1).max(100).optional().describe("How many UUIDs. Default 1."),
  }),
  example: { op: "stats", text: "Agents pay per call with x402. No accounts, no keys." },
  async run({ op, text, count }) {
    const t = text ?? "";
    const need = () => {
      if (!text) throw new ToolError("This operation needs text.", "INVALID_INPUT", 400);
    };
    switch (op) {
      case "uuid":
        return { op, uuids: Array.from({ length: count ?? 1 }, () => crypto.randomUUID()) };
      case "sha256":
      case "sha1":
      case "sha512":
        need();
        return { op, hex: await digest(op === "sha1" ? "SHA-1" : op === "sha256" ? "SHA-256" : "SHA-512", t) };
      case "base64_encode":
        need();
        return { op, result: btoa(String.fromCharCode(...new TextEncoder().encode(t))) };
      case "base64_decode": {
        need();
        try {
          const bin = atob(t.replace(/\s+/g, "").replace(/-/g, "+").replace(/_/g, "/"));
          return { op, result: new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))) };
        } catch {
          throw new ToolError("That isn't valid Base64.", "INVALID_INPUT", 400);
        }
      }
      case "url_encode":
        need();
        return { op, result: encodeURIComponent(t) };
      case "url_decode":
        need();
        try {
          return { op, result: decodeURIComponent(t.replace(/\+/g, " ")) };
        } catch {
          throw new ToolError("That isn't valid URL encoding.", "INVALID_INPUT", 400);
        }
      case "slugify":
        need();
        return { op, result: t.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 120) };
      case "json_format":
        need();
        try {
          return { op, valid: true, result: JSON.stringify(JSON.parse(t), null, 2) };
        } catch (err) {
          return { op, valid: false, error: err instanceof Error ? err.message : "Invalid JSON" };
        }
      case "stats": {
        need();
        const words = t.trim() ? t.trim().split(/\s+/).length : 0;
        return {
          op, characters: t.length, characters_no_spaces: t.replace(/\s/g, "").length, words,
          sentences: (t.match(/[^.!?]+[.!?]+/g) ?? []).length || (t.trim() ? 1 : 0),
          paragraphs: t.split(/\n\s*\n/).filter((p) => p.trim()).length,
          reading_time_seconds: Math.ceil((words / 238) * 60),
        };
      }
    }
  },
});
