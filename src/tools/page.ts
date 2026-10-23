import { z } from "zod";
import { NodeHtmlMarkdown } from "node-html-markdown";
import { fetchPage } from "../lib/net";
import { ToolError } from "../lib/errors";
import { absolute, clean, jsonLd, metaContent, parseHtml } from "../lib/html";
import { defineTool } from "./types";

const SOCIAL_HOSTS: [RegExp, string][] = [
  [/(^|\.)(twitter|x)\.com$/, "x"],
  [/(^|\.)linkedin\.com$/, "linkedin"],
  [/(^|\.)github\.com$/, "github"],
  [/(^|\.)facebook\.com$/, "facebook"],
  [/(^|\.)instagram\.com$/, "instagram"],
  [/(^|\.)youtube\.com$/, "youtube"],
  [/(^|\.)tiktok\.com$/, "tiktok"],
  [/(^|\.)discord\.(gg|com)$/, "discord"],
  [/(^|\.)threads\.(net|com)$/, "threads"],
  [/(^|\.)bsky\.app$/, "bluesky"],
  [/(^|\.)reddit\.com$/, "reddit"],
  [/(^|\.)crunchbase\.com$/, "crunchbase"],
];

const SOCIAL_SKIP = /\/(share|sharer|intent|home\?status|dialog)|\/hashtag\//i;

const KEY_PAGES: [RegExp, string][] = [
  [/\b(contact|contact-us|get-in-touch)\b/i, "contact"],
  [/\b(about|about-us|company|team)\b/i, "about"],
  [/\bpricing|plans\b/i, "pricing"],
  [/\b(careers|jobs|join-us|hiring)\b/i, "careers"],
  [/\b(blog|news|articles)\b/i, "blog"],
  [/\b(docs|documentation|developers|api)\b/i, "docs"],
  [/\b(privacy|privacy-policy)\b/i, "privacy"],
  [/\b(terms|tos|terms-of-service)\b/i, "terms"],
];

const EMAIL_RE = /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,24}/gi;
const EMAIL_SKIP = /\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|@2x|domain\.com|email\.com|yourdomain/i;

/** Extract structured metadata from HTML. Pure, for testing. */
export function extractMetadata(html: string, pageUrl: string) {
  const root = parseHtml(html);
  const host = new URL(pageUrl).hostname.replace(/^www\./, "");

  const socials: Record<string, string> = {};
  const keyPages: Record<string, string> = {};
  const emails = new Set<string>();
  const phones = new Set<string>();

  for (const a of root.querySelectorAll("a[href]")) {
    const raw = a.getAttribute("href") ?? "";
    if (raw.startsWith("mailto:")) {
      const e = decodeURIComponent(raw.slice(7).split("?")[0]!).trim().toLowerCase();
      if (/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(e)) emails.add(e);
      continue;
    }
    if (raw.startsWith("tel:")) {
      const p = raw.slice(4).replace(/[^\d+]/g, "");
      if (p.length >= 7) phones.add(p);
      continue;
    }
    const href = absolute(raw, pageUrl);
    if (!href) continue;
    const u = new URL(href);
    const h = u.hostname.replace(/^www\./, "");
    const social = SOCIAL_HOSTS.find(([re]) => re.test(h));
    if (social && !socials[social[1]] && u.pathname.length > 1 && !SOCIAL_SKIP.test(u.pathname + u.search)) {
      socials[social[1]] = `${u.origin}${u.pathname}`.replace(/\/$/, "");
      continue;
    }
    if (h === host || h.endsWith(`.${host}`)) {
      const label = `${u.pathname} ${clean(a.textContent, 60) ?? ""}`;
      for (const [re, name] of KEY_PAGES) if (!keyPages[name] && re.test(label)) keyPages[name] = href;
    }
  }

  // Treat every tag as a word break so adjacent elements don't glue together.
  const bodyText = html
    .replace(/<(script|style|noscript|svg)\b[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#64;|&commat;/gi, "@");
  for (const m of bodyText.matchAll(EMAIL_RE)) {
    const e = m[0].toLowerCase();
    if (!EMAIL_SKIP.test(e) && emails.size < 20) emails.add(e);
  }

  const ld = jsonLd(root);
  const org = ld.find((x) => /Organization|Corporation|LocalBusiness|Brand|Store|Restaurant|Company/i.test(String(x["@type"] ?? "")));
  const sameAs = org && (Array.isArray(org.sameAs) ? org.sameAs : org.sameAs ? [org.sameAs] : []);
  for (const s of (sameAs as unknown[] | undefined) ?? []) {
    const href = typeof s === "string" ? absolute(s, pageUrl) : null;
    if (!href) continue;
    const social = SOCIAL_HOSTS.find(([re]) => re.test(new URL(href).hostname.replace(/^www\./, "")));
    if (social && !socials[social[1]]) socials[social[1]] = href;
  }

  const iconHref =
    root.querySelector('link[rel="icon"]')?.getAttribute("href") ??
    root.querySelector('link[rel="shortcut icon"]')?.getAttribute("href") ??
    root.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href") ??
    "/favicon.ico";

  const address = org?.address && typeof org.address === "object" ? (org.address as Record<string, unknown>) : null;

  return {
    url: pageUrl,
    title: clean(root.querySelector("title")?.textContent, 300),
    description: metaContent(root, "description") ?? metaContent(root, "og:description"),
    language: clean(root.querySelector("html")?.getAttribute("lang"), 20),
    canonical: absolute(root.querySelector('link[rel="canonical"]')?.getAttribute("href"), pageUrl),
    site_name: metaContent(root, "og:site_name"),
    image: absolute(metaContent(root, "og:image") ?? undefined, pageUrl),
    favicon: absolute(iconHref, pageUrl),
    robots: metaContent(root, "robots"),
    feeds: root
      .querySelectorAll('link[type="application/rss+xml"], link[type="application/atom+xml"]')
      .map((l) => absolute(l.getAttribute("href"), pageUrl))
      .filter(Boolean)
      .slice(0, 5),
    social_profiles: socials,
    emails: [...emails].slice(0, 20),
    phones: [...phones].slice(0, 10),
    key_pages: keyPages,
    organization: org
      ? {
          name: clean(String(org.name ?? ""), 200),
          legal_name: clean(String(org.legalName ?? ""), 200),
          description: clean(String(org.description ?? ""), 500),
          logo: typeof org.logo === "string" ? org.logo : (org.logo as { url?: string } | undefined)?.url ?? null,
          founding_date: clean(String(org.foundingDate ?? ""), 40),
          address: address
            ? clean([address.streetAddress, address.addressLocality, address.addressRegion, address.postalCode, address.addressCountry].filter(Boolean).join(", "), 300)
            : null,
        }
      : null,
    structured_data_types: [...new Set(ld.map((x) => String(x["@type"] ?? "")).filter(Boolean))].slice(0, 20),
  };
}

const nhm = new NodeHtmlMarkdown({
  maxConsecutiveNewlines: 2,
  bulletMarker: "-",
  strongDelimiter: "**",
  emDelimiter: "*",
  keepDataImages: false,
  useLinkReferenceDefinitions: false,
});

const STRIP = "script, style, noscript, svg, iframe, form, nav, footer, header, aside, template, canvas, [role=navigation], [role=banner], [role=contentinfo], [aria-hidden=true], .cookie, .cookies, #cookie-banner, .advert, .ads";

/** Convert the main content of an HTML page to Markdown. Pure, for testing. */
export function htmlToMarkdown(html: string, pageUrl: string, maxChars: number) {
  const root = parseHtml(html);
  const title = clean(root.querySelector("title")?.textContent, 300);
  const main =
    root.querySelector("main") ?? root.querySelector("article") ?? root.querySelector("[role=main]") ?? root.querySelector("#content") ?? root.querySelector("body") ?? root;
  for (const el of main.querySelectorAll(STRIP)) el.remove();
  for (const a of main.querySelectorAll("a[href]")) {
    const abs = absolute(a.getAttribute("href"), pageUrl);
    if (abs) a.setAttribute("href", abs);
    else a.removeAttribute("href");
  }
  for (const img of main.querySelectorAll("img[src]")) {
    const abs = absolute(img.getAttribute("src"), pageUrl);
    if (abs) img.setAttribute("src", abs);
    else img.remove();
  }
  let markdown = nhm.translate(main.toString()).replace(/\n{3,}/g, "\n\n").trim();
  const words = markdown.split(/\s+/).filter(Boolean).length;
  const truncated = markdown.length > maxChars;
  if (truncated) markdown = `${markdown.slice(0, maxChars)}\n\n[truncated]`;
  return { url: pageUrl, title, word_count: words, truncated, markdown };
}

export const siteMetadata = defineTool({
  name: "site_metadata",
  title: "Website metadata and contacts",
  description:
    "Extract a website's title, description, language, social profiles, public contact emails and phones, key pages (contact, pricing, careers, docs), RSS feeds and schema.org organization data.",
  priceMicro: 2000,
  cacheTtl: 21_600,
  input: z.object({ url: z.string().describe("Website URL or domain, e.g. notion.so") }),
  example: { url: "https://www.notion.so" },
  async run({ url }) {
    const page = await fetchPage(url);
    if (!/html|xml/i.test(page.headers.get("content-type") ?? "text/html")) {
      throw new ToolError("That URL did not return an HTML page.", "NOT_HTML");
    }
    return { status: page.status, ...extractMetadata(page.body, page.url) };
  },
});

export const pageToMarkdown = defineTool({
  name: "page_to_markdown",
  title: "Web page to Markdown",
  description:
    "Fetch a web page and return its main content as clean Markdown (navigation, ads, scripts and cookie banners removed), ready for an LLM to read.",
  priceMicro: 2000,
  cacheTtl: 3600,
  input: z.object({
    url: z.string().describe("Page URL, e.g. https://blog.cloudflare.com"),
    max_chars: z.number().int().min(1000).max(100_000).optional().describe("Maximum Markdown length. Default 20000."),
  }),
  example: { url: "https://en.wikipedia.org/wiki/Model_Context_Protocol" },
  async run({ url, max_chars }) {
    const page = await fetchPage(url);
    const type = page.headers.get("content-type") ?? "text/html";
    if (/text\/plain|markdown/i.test(type)) {
      const text = page.body.slice(0, max_chars ?? 20_000);
      return { url: page.url, title: null, word_count: text.split(/\s+/).length, truncated: page.body.length > text.length, markdown: text };
    }
    if (!/html|xml/i.test(type)) throw new ToolError("That URL did not return an HTML or text page.", "NOT_HTML");
    return { status: page.status, ...htmlToMarkdown(page.body, page.url, max_chars ?? 20_000) };
  },
});
