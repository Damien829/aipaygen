import { z } from "zod";
import { fetchPage } from "../lib/net";
import { defineTool } from "./types";

interface Check {
  header: string;
  weight: number;
  test(value: string | null): { ok: boolean; note?: string };
}

const CHECKS: Check[] = [
  {
    header: "strict-transport-security",
    weight: 25,
    test: (v) => {
      if (!v) return { ok: false, note: "Missing HSTS: browsers may connect over plain HTTP first." };
      const maxAge = Number(/max-age=(\d+)/i.exec(v)?.[1] ?? 0);
      return maxAge >= 15_552_000 ? { ok: true } : { ok: false, note: "HSTS max-age is under 180 days." };
    },
  },
  {
    header: "content-security-policy",
    weight: 25,
    test: (v) => {
      if (!v) return { ok: false, note: "Missing Content-Security-Policy: no defense in depth against XSS." };
      return /'unsafe-inline'/.test(v) && !/'nonce-|'strict-dynamic'/.test(v)
        ? { ok: false, note: "CSP allows 'unsafe-inline' scripts." }
        : { ok: true };
    },
  },
  {
    header: "x-content-type-options",
    weight: 10,
    test: (v) => (v?.toLowerCase() === "nosniff" ? { ok: true } : { ok: false, note: "Missing X-Content-Type-Options: nosniff." }),
  },
  {
    header: "x-frame-options",
    weight: 10,
    test: (v) => (v ? { ok: true } : { ok: false, note: "Missing X-Frame-Options (clickjacking), unless CSP frame-ancestors is set." }),
  },
  {
    header: "referrer-policy",
    weight: 10,
    test: (v) => (v ? { ok: true } : { ok: false, note: "Missing Referrer-Policy: full URLs may leak to other sites." }),
  },
  {
    header: "permissions-policy",
    weight: 10,
    test: (v) => (v ? { ok: true } : { ok: false, note: "Missing Permissions-Policy." }),
  },
  {
    header: "cross-origin-opener-policy",
    weight: 10,
    test: (v) => (v ? { ok: true } : { ok: false, note: "Missing Cross-Origin-Opener-Policy." }),
  },
];

/** Score response headers. Pure, for testing. */
export function gradeHeaders(headers: Headers, finalUrl: string) {
  const csp = headers.get("content-security-policy");
  let score = 0;
  const present: Record<string, string> = {};
  const issues: string[] = [];
  for (const c of CHECKS) {
    let value = headers.get(c.header);
    if (c.header === "x-frame-options" && !value && csp && /frame-ancestors/i.test(csp)) value = "(via CSP frame-ancestors)";
    if (value) present[c.header] = value.slice(0, 500);
    const r = c.test(value);
    if (r.ok) score += c.weight;
    else if (r.note) issues.push(r.note);
  }
  const leaks = ["server", "x-powered-by", "x-aspnet-version", "x-generator"]
    .map((h) => [h, headers.get(h)] as const)
    .filter(([, v]) => v && /\d/.test(v))
    .map(([h, v]) => `${h}: ${v}`);
  if (leaks.length) issues.push(`Version information exposed: ${leaks.join("; ")}.`);
  if (!finalUrl.startsWith("https://")) {
    issues.unshift("Site does not end up on HTTPS.");
    score = Math.min(score, 20);
  }
  const grade = score >= 90 ? "A" : score >= 75 ? "B" : score >= 55 ? "C" : score >= 35 ? "D" : "F";
  return { grade, score, https: finalUrl.startsWith("https://"), headers: present, issues };
}

export const securityHeaders = defineTool({
  name: "security_headers",
  title: "HTTP security headers",
  description:
    "Grade a website's HTTP security headers (HSTS, CSP, X-Frame-Options, Referrer-Policy and more) A-F, list what is missing, and flag exposed server version info.",
  priceMicro: 1000,
  cacheTtl: 1800,
  input: z.object({ url: z.string().describe("Website URL or domain, e.g. https://example.com") }),
  example: { url: "https://vercel.com" },
  async run({ url }) {
    const page = await fetchPage(url, { timeoutMs: 10_000 });
    return { url: page.url, status: page.status, redirects: page.redirects, ...gradeHeaders(page.headers, page.url) };
  },
});
