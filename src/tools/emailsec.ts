import { z } from "zod";
import { normalizeDomain } from "../lib/net";
import { defineTool } from "./types";
import { detectMailProvider, resolve } from "./dns";

const DKIM_SELECTORS = ["google", "selector1", "selector2", "default", "k1", "s1", "s2", "mail", "dkim", "smtp", "mxvault", "zoho", "fm1", "protonmail"];

export interface EmailSecurityInput {
  mx: string[];
  txt: string[];
  dmarc: string[];
  dkimSelectors: string[];
  mtaSts: string[];
  tlsRpt: string[];
  bimi: string[];
}

/** Grade SPF/DMARC/DKIM/MTA-STS from already-resolved TXT records. Pure, so it is easy to test. */
export function gradeEmailSecurity(domain: string, r: EmailSecurityInput) {
  const issues: string[] = [];
  let score = 0;

  const spf = r.txt.filter((t) => /^v=spf1\b/i.test(t));
  const spfRecord = spf[0] ?? null;
  const spfAll = spfRecord ? (/([~?+-])all\b/.exec(spfRecord)?.[1] ?? null) : null;
  const lookups = spfRecord ? (spfRecord.match(/\b(include:|a\b|a:|mx\b|mx:|ptr|exists:|redirect=)/gi) ?? []).length : 0;
  if (!spfRecord) issues.push("No SPF record: anyone can send mail claiming to be this domain.");
  else {
    if (spf.length > 1) issues.push("Multiple SPF records: receivers treat this as an error.");
    if (spfAll === "+" || spfAll === "?") issues.push(`SPF ends in "${spfAll}all", which does not block spoofing.`);
    if (lookups > 10) issues.push(`SPF needs about ${lookups} DNS lookups; the limit is 10.`);
    score += spfAll === "-" ? 25 : spfAll === "~" ? 20 : 10;
  }

  const dmarcRecord = r.dmarc.find((t) => /^v=DMARC1\b/i.test(t)) ?? null;
  const tag = (name: string) => (dmarcRecord ? (new RegExp(`(?:^|;)\\s*${name}=([^;]+)`, "i").exec(dmarcRecord)?.[1]?.trim() ?? null) : null);
  const policy = tag("p")?.toLowerCase() ?? null;
  const pct = Number(tag("pct") ?? 100);
  if (!dmarcRecord) issues.push("No DMARC record: spoofed mail is not rejected and no reports are sent.");
  else {
    if (policy === "none") issues.push('DMARC policy is "none": monitoring only, spoofed mail still gets delivered.');
    if (pct < 100) issues.push(`DMARC applies to only ${pct}% of mail.`);
    if (!tag("rua")) issues.push("DMARC has no rua address, so no aggregate reports are collected.");
    score += policy === "reject" ? 35 : policy === "quarantine" ? 28 : 10;
  }

  if (r.dkimSelectors.length) score += 20;
  else issues.push("No DKIM key found on common selectors (it may use a custom selector).");

  if (r.mtaSts.some((t) => /^v=STSv1/i.test(t))) score += 10;
  else issues.push("No MTA-STS: mail to this domain can be downgraded to unencrypted delivery.");
  if (r.tlsRpt.some((t) => /^v=TLSRPTv1/i.test(t))) score += 5;
  if (r.bimi.some((t) => /^v=BIMI1/i.test(t))) score += 5;

  if (!r.mx.length) issues.push("No MX records: this domain does not receive email.");

  const grade = score >= 90 ? "A" : score >= 75 ? "B" : score >= 55 ? "C" : score >= 35 ? "D" : "F";
  return {
    domain,
    grade,
    score,
    receives_email: r.mx.length > 0,
    email_provider: detectMailProvider(r.mx),
    mx: r.mx,
    spf: spfRecord ? { record: spfRecord, all: spfAll ? `${spfAll}all` : null, dns_lookups: lookups } : null,
    dmarc: dmarcRecord ? { record: dmarcRecord, policy, pct, reports_to: tag("rua") } : null,
    dkim_selectors_found: r.dkimSelectors,
    mta_sts: r.mtaSts.length > 0,
    tls_rpt: r.tlsRpt.length > 0,
    bimi: r.bimi.length > 0,
    spoofable: !dmarcRecord || policy === "none" || !spfRecord,
    issues,
  };
}

export async function collectEmailRecords(d: string): Promise<EmailSecurityInput> {
  const txt = (name: string) => resolve(name, "TXT").then((rs) => rs.map((r) => r.value)).catch(() => [] as string[]);
  const [mxRecords, rootTxt, dmarc, mtaSts, tlsRpt, bimi, ...dkim] = await Promise.all([
    resolve(d, "MX").catch(() => []),
    txt(d),
    txt(`_dmarc.${d}`),
    txt(`_mta-sts.${d}`),
    txt(`_smtp._tls.${d}`),
    txt(`default._bimi.${d}`),
    ...DKIM_SELECTORS.map((s) => txt(`${s}._domainkey.${d}`)),
  ]);
  return {
    mx: mxRecords.map((r) => r.value.split(" ").pop()!),
    txt: rootTxt,
    dmarc,
    mtaSts,
    tlsRpt,
    bimi,
    dkimSelectors: DKIM_SELECTORS.filter((_, i) => dkim[i]!.some((t) => /p=/i.test(t))),
  };
}

export const emailSecurity = defineTool({
  name: "email_security",
  title: "Email security audit",
  description:
    "Audit a domain's email security: SPF, DMARC policy, DKIM keys, MX/email provider, MTA-STS, TLS-RPT and BIMI, with an A-F grade, a spoofability verdict and plain-English issues.",
  priceMicro: 2000,
  cacheTtl: 1800,
  input: z.object({ domain: z.string().describe("Domain name, e.g. github.com") }),
  example: { domain: "github.com" },
  async run({ domain }) {
    const d = normalizeDomain(domain);
    return gradeEmailSecurity(d, await collectEmailRecords(d));
  },
});
