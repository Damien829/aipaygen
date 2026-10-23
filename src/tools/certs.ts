import { z } from "zod";
import { fetchJson, normalizeDomain } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

export interface CrtShEntry {
  id: number;
  issuer_name: string;
  common_name: string;
  name_value: string;
  not_before: string;
  not_after: string;
}

interface CertSpotterEntry {
  id: string;
  dns_names: string[];
  not_before: string;
  not_after: string;
  issuer?: { friendly_name?: string; name?: string };
}

interface Cert {
  issuer: string;
  names: string[];
  not_before: string;
  not_after: string;
}

function issuerOrg(issuerName: string): string {
  return /O=("?)([^,"]+)\1/.exec(issuerName)?.[2]?.trim() ?? /CN=([^,]+)/.exec(issuerName)?.[1]?.trim() ?? issuerName;
}

const asUtc = (s: string) => (/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);

/** Summarize certificate history: current certs, issuers, and discovered subdomains. */
export function summarizeCerts(domain: string, certs: Cert[]) {
  const now = Date.now();
  const subdomains = new Set<string>();
  for (const c of certs) {
    for (const raw of c.names) {
      const n = raw.trim().toLowerCase().replace(/^\*\./, "");
      if (n === domain || n.endsWith(`.${domain}`)) subdomains.add(n);
    }
  }
  const valid = certs
    .filter((c) => Date.parse(asUtc(c.not_before)) <= now && Date.parse(asUtc(c.not_after)) > now)
    .sort((a, b) => Date.parse(asUtc(b.not_after)) - Date.parse(asUtc(a.not_after)));
  const issuers: Record<string, number> = {};
  for (const c of certs) issuers[c.issuer] = (issuers[c.issuer] ?? 0) + 1;
  const covering = valid.filter((c) => c.names.some((n) => n === domain || n === `*.${domain}`));
  const soonest = covering.length ? covering.reduce((a, b) => (Date.parse(asUtc(a.not_after)) < Date.parse(asUtc(b.not_after)) ? a : b)) : null;
  const latest = covering[0] ?? null;

  return {
    domain,
    certificates_seen: certs.length,
    currently_valid: valid.length,
    current_certificate: latest
      ? {
          issuer: latest.issuer,
          valid_from: asUtc(latest.not_before),
          valid_until: asUtc(latest.not_after),
          days_remaining: Math.floor((Date.parse(asUtc(latest.not_after)) - now) / 86_400_000),
          names: latest.names.slice(0, 50),
        }
      : null,
    earliest_expiring_days: soonest ? Math.floor((Date.parse(asUtc(soonest.not_after)) - now) / 86_400_000) : null,
    issuers: Object.entries(issuers).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count })),
    subdomains: [...subdomains].sort().slice(0, 500),
    subdomain_count: subdomains.size,
    source: "Certificate Transparency logs",
  };
}

async function fromCrtSh(domain: string): Promise<Cert[] | null> {
  const { data } = await fetchJson<CrtShEntry[]>(`https://crt.sh/?q=${encodeURIComponent(domain)}&output=json&exclude=expired`, { timeoutMs: 15_000 });
  if (!data) return null;
  return data.slice(0, 2000).map((e) => ({
    issuer: issuerOrg(e.issuer_name),
    names: [...new Set([e.common_name, ...e.name_value.split("\n")].map((s) => s.trim().toLowerCase()).filter(Boolean))],
    not_before: e.not_before,
    not_after: e.not_after,
  }));
}

async function fromCertSpotter(domain: string): Promise<Cert[] | null> {
  const { data } = await fetchJson<CertSpotterEntry[]>(
    `https://api.certspotter.com/v1/issuances?domain=${encodeURIComponent(domain)}&include_subdomains=true&expand=dns_names&expand=issuer`,
    { timeoutMs: 10_000 },
  );
  if (!data) return null;
  return data.map((e) => ({
    issuer: e.issuer?.friendly_name ?? (e.issuer?.name ? issuerOrg(e.issuer.name) : "Unknown"),
    names: e.dns_names.map((n) => n.toLowerCase()),
    not_before: e.not_before,
    not_after: e.not_after,
  }));
}

export const sslCertificates = defineTool({
  name: "ssl_certificates",
  title: "SSL certificates and subdomains",
  description:
    "Check a domain's TLS certificates from Certificate Transparency logs: current certificate, issuer, days until expiry, and every subdomain that has appeared on a certificate.",
  priceMicro: 3000,
  cacheTtl: 21_600,
  input: z.object({ domain: z.string().describe("Domain name, e.g. shopify.com") }),
  example: { domain: "shopify.com" },
  async run({ domain }) {
    const d = normalizeDomain(domain);
    let certs: Cert[] | null = null;
    try {
      certs = await fromCrtSh(d);
    } catch {
      certs = null;
    }
    if (!certs) certs = await fromCertSpotter(d);
    if (!certs) throw new ToolError("Certificate Transparency sources are unavailable right now. Try again shortly.", "UPSTREAM_ERROR", 502);
    return summarizeCerts(d, certs);
  },
});
