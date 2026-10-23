import { z } from "zod";
import { fetchPage, normalizeDomain } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool, type ToolContext } from "./types";
import { dnsLookup } from "./dns";
import { domainWhois } from "./whois";
import { emailSecurity } from "./emailsec";
import { sslCertificates } from "./certs";
import { gradeHeaders } from "./headers";
import { detectTechForPage, groupByCategory } from "./tech";
import { extractMetadata } from "./page";

type Settled<T> = { ok: true; value: T } | { ok: false; error: string };

async function settle<T>(p: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await p };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "failed" };
  }
}

const val = <T>(s: Settled<T>): T | null => (s.ok ? s.value : null);

async function homepage(domain: string) {
  try {
    return await fetchPage(`https://${domain}/`);
  } catch {
    return await fetchPage(`https://www.${domain}/`);
  }
}

/** Derive plain-English business signals from the collected data. */
export function deriveSignals(input: {
  techNames: string[];
  keyPages: Record<string, string>;
  domainAgeDays: number | null;
  emailProvider: string | null;
  socials: Record<string, string>;
}): string[] {
  const t = new Set(input.techNames);
  const s: string[] = [];
  if (["Stripe", "PayPal", "Paddle", "Lemon Squeezy"].some((x) => t.has(x))) s.push("Takes online payments");
  if (["Shopify", "WooCommerce", "Magento", "BigCommerce"].some((x) => t.has(x))) s.push("Runs an online store");
  if (input.keyPages.pricing) s.push("Publishes pricing (likely SaaS or self-serve)");
  if (input.keyPages.careers) s.push("Has a careers page (may be hiring)");
  if (input.keyPages.docs) s.push("Has developer documentation or an API");
  if (["Intercom", "Zendesk", "Drift", "Crisp", "Tawk.to"].some((x) => t.has(x))) s.push("Offers live chat support");
  if (["HubSpot", "Marketo", "Klaviyo", "Mailchimp"].some((x) => t.has(x))) s.push("Invests in marketing automation");
  if (["Meta Pixel", "Google Ads", "LinkedIn Insight", "TikTok Pixel"].some((x) => t.has(x))) s.push("Runs paid advertising");
  if (input.domainAgeDays !== null) {
    if (input.domainAgeDays < 365) s.push("Domain is under a year old (new company or rebrand)");
    else if (input.domainAgeDays > 365 * 10) s.push("Domain is over 10 years old (established)");
  }
  if (input.emailProvider === "Google Workspace" || input.emailProvider === "Microsoft 365") s.push(`Uses ${input.emailProvider} for email`);
  if (Object.keys(input.socials).length >= 4) s.push("Active on several social platforms");
  return s;
}

export const companyProfile = defineTool({
  name: "company_profile",
  title: "Company profile from a domain",
  description:
    "Build a company profile from just a domain: name, description, logo, location, social profiles, public contact info, domain age, email and hosting providers, key tech stack, and business signals (takes payments, hiring, runs ads...). One call instead of six.",
  priceMicro: 10_000,
  cacheTtl: 43_200,
  input: z.object({ domain: z.string().describe("Company domain, e.g. figma.com") }),
  example: { domain: "figma.com" },
  async run({ domain }, ctx: ToolContext) {
    const d = normalizeDomain(domain);
    const [page, whois, dns] = await Promise.all([
      settle(homepage(d)),
      settle(domainWhois.run({ domain: d }, ctx)),
      settle(dnsLookup.run({ domain: d, types: ["MX", "NS"] }, ctx)),
    ]);
    if (!page.ok && !whois.ok) throw new ToolError(`Could not reach ${d} or find registration data.`, "NOT_FOUND", 404);

    const meta = page.ok ? extractMetadata(page.value.body, page.value.url) : null;
    const tech = page.ok ? await detectTechForPage(page.value.url, page.value.body, page.value.headers).catch(() => []) : [];
    const w = val(whois) as Record<string, unknown> | null;
    const n = val(dns) as Record<string, unknown> | null;
    const ageDays = typeof w?.age_days === "number" ? w.age_days : null;

    const name =
      meta?.organization?.name ??
      meta?.site_name ??
      meta?.title?.split(/\s[|\-–—:]\s/)[0]?.trim() ??
      d.split(".")[0]!.replace(/^\w/, (c) => c.toUpperCase());

    return {
      domain: d,
      website: page.ok ? page.value.url : `https://${d}`,
      name,
      description: meta?.organization?.description ?? meta?.description ?? null,
      logo: meta?.organization?.logo ?? meta?.image ?? meta?.favicon ?? null,
      location: meta?.organization?.address ?? (w?.registrant_country as string | null) ?? null,
      founded: meta?.organization?.founding_date ?? null,
      language: meta?.language ?? null,
      social_profiles: meta?.social_profiles ?? {},
      contact: { emails: meta?.emails ?? [], phones: meta?.phones ?? [], contact_page: meta?.key_pages.contact ?? null },
      key_pages: meta?.key_pages ?? {},
      domain_info: w
        ? { registrar: w.registrar, created: w.created, expires: w.expires, age_days: ageDays }
        : null,
      email_provider: (n?.email_provider as string | null) ?? null,
      dns_provider: (n?.dns_provider as string | null) ?? null,
      tech_stack: groupByCategory(tech),
      signals: deriveSignals({
        techNames: tech.map((t) => t.name),
        keyPages: meta?.key_pages ?? {},
        domainAgeDays: ageDays,
        emailProvider: (n?.email_provider as string | null) ?? null,
        socials: meta?.social_profiles ?? {},
      }),
      sources_failed: [!page.ok && "website", !whois.ok && "registration", !dns.ok && "dns"].filter(Boolean),
    };
  },
});

export const domainReport = defineTool({
  name: "domain_report",
  title: "Full domain report",
  description:
    "Everything about a domain in one call: DNS, registration, certificates and subdomains, email security grade, HTTP security headers grade, tech stack and website metadata, plus an overall summary.",
  priceMicro: 20_000,
  cacheTtl: 21_600,
  input: z.object({ domain: z.string().describe("Domain name, e.g. cloudflare.com") }),
  example: { domain: "cloudflare.com" },
  async run({ domain }, ctx: ToolContext) {
    const d = normalizeDomain(domain);
    const [page, dns, whois, certs, email] = await Promise.all([
      settle(homepage(d)),
      settle(dnsLookup.run({ domain: d }, ctx)),
      settle(domainWhois.run({ domain: d }, ctx)),
      settle(sslCertificates.run({ domain: d }, ctx)),
      settle(emailSecurity.run({ domain: d }, ctx)),
    ]);
    const sections = { website: page, dns, whois, certs, email };
    if (Object.values(sections).every((s) => !s.ok)) throw new ToolError(`No data could be collected for ${d}.`, "NOT_FOUND", 404);

    const headers = page.ok ? { url: page.value.url, ...gradeHeaders(page.value.headers, page.value.url) } : null;
    const tech = page.ok ? await detectTechForPage(page.value.url, page.value.body, page.value.headers).catch(() => null) : null;
    const metadata = page.ok ? extractMetadata(page.value.body, page.value.url) : null;
    const e = val(email) as { grade?: string; spoofable?: boolean } | null;
    const c = val(certs) as { current_certificate?: { days_remaining?: number } | null; subdomain_count?: number } | null;
    const w = val(whois) as { days_until_expiry?: number | null; age_days?: number | null } | null;

    const warnings: string[] = [];
    if (c?.current_certificate?.days_remaining !== undefined && c.current_certificate.days_remaining < 14) warnings.push("TLS certificate expires within 14 days.");
    if (typeof w?.days_until_expiry === "number" && w.days_until_expiry < 30) warnings.push("Domain registration expires within 30 days.");
    if (e?.spoofable) warnings.push("Email from this domain can be spoofed.");
    if (headers && !headers.https) warnings.push("Website is not served over HTTPS.");

    return {
      domain: d,
      summary: {
        website_up: page.ok && page.value.status < 400,
        email_security_grade: e?.grade ?? null,
        security_headers_grade: headers?.grade ?? null,
        tls_days_remaining: c?.current_certificate?.days_remaining ?? null,
        domain_age_days: w?.age_days ?? null,
        subdomains_found: c?.subdomain_count ?? null,
        technologies_found: tech?.length ?? null,
        warnings,
      },
      dns: val(dns),
      registration: val(whois),
      certificates: val(certs),
      email_security: val(email),
      security_headers: headers,
      tech_stack: tech ? { by_category: groupByCategory(tech), technologies: tech } : null,
      metadata,
      errors: Object.fromEntries(Object.entries(sections).filter(([, s]) => !s.ok).map(([k, s]) => [k, (s as { error: string }).error])),
    };
  },
});
