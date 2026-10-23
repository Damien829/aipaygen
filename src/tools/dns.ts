import { z } from "zod";
import { fetchJson, normalizeDomain } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

const RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "CAA"] as const;
type RecordType = (typeof RECORD_TYPES)[number];

const TYPE_CODES: Record<number, string> = { 1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 15: "MX", 16: "TXT", 28: "AAAA", 257: "CAA" };

interface DohResponse {
  Status: number;
  Answer?: { name: string; type: number; TTL: number; data: string }[];
}

export interface DnsRecord {
  type: string;
  value: string;
  ttl: number;
}

const DOH_URL = "https://cloudflare-dns.com/dns-query";

/** Resolve one record type over DNS-over-HTTPS. */
export async function resolve(domain: string, type: RecordType): Promise<DnsRecord[]> {
  const { data } = await fetchJson<DohResponse>(`${DOH_URL}?name=${encodeURIComponent(domain)}&type=${type}`, {
    headers: { accept: "application/dns-json" },
    timeoutMs: 5000,
  });
  if (!data) throw new ToolError("DNS resolver did not respond.", "UPSTREAM_ERROR", 502);
  if (data.Status !== 0) return [];
  return (data.Answer ?? [])
    .filter((a) => TYPE_CODES[a.type] === type)
    .map((a) => ({ type, value: type === "TXT" ? unquoteTxt(a.data) : a.data.replace(/\.$/, ""), ttl: a.TTL }));
}

export function unquoteTxt(data: string): string {
  const parts = data.match(/"((?:[^"\\]|\\.)*)"/g);
  return parts ? parts.map((p) => p.slice(1, -1).replace(/\\"/g, '"')).join("") : data;
}

/** Map MX hosts to the email provider they belong to. */
export function detectMailProvider(mxHosts: string[]): string | null {
  const joined = mxHosts.join(" ").toLowerCase();
  const providers: [RegExp, string][] = [
    [/google\.com|googlemail\.com/, "Google Workspace"],
    [/outlook\.com|protection\.outlook/, "Microsoft 365"],
    [/zoho\./, "Zoho Mail"],
    [/protonmail\.ch|proton\.me/, "Proton Mail"],
    [/icloud\.com|apple\.com/, "iCloud Mail"],
    [/fastmail/, "Fastmail"],
    [/mimecast/, "Mimecast"],
    [/pphosted\.com|proofpoint/, "Proofpoint"],
    [/secureserver\.net/, "GoDaddy"],
    [/yandex/, "Yandex"],
    [/mailgun/, "Mailgun"],
    [/amazonaws\.com|awsapps/, "Amazon SES/WorkMail"],
    [/barracuda/, "Barracuda"],
    [/mx\.cloudflare\.net/, "Cloudflare Email Routing"],
  ];
  for (const [re, name] of providers) if (re.test(joined)) return name;
  return mxHosts.length ? "Self-hosted or other" : null;
}

/** Map nameservers to the DNS host. */
export function detectDnsProvider(nsHosts: string[]): string | null {
  const joined = nsHosts.join(" ").toLowerCase();
  const providers: [RegExp, string][] = [
    [/cloudflare\.com/, "Cloudflare"],
    [/awsdns/, "Amazon Route 53"],
    [/googledomains|google\.com|nsone\.net.*google/, "Google Cloud DNS"],
    [/azure-dns/, "Azure DNS"],
    [/domaincontrol\.com/, "GoDaddy"],
    [/nsone\.net/, "NS1"],
    [/dnsimple/, "DNSimple"],
    [/vercel-dns/, "Vercel"],
    [/netlify/, "Netlify"],
    [/registrar-servers\.com/, "Namecheap"],
    [/digitalocean/, "DigitalOcean"],
    [/hetzner/, "Hetzner"],
    [/squarespacedns|squarespace/, "Squarespace"],
    [/wixdns/, "Wix"],
    [/dynect|dyn\.com/, "Oracle Dyn"],
    [/ultradns/, "UltraDNS"],
    [/akam/, "Akamai"],
  ];
  for (const [re, name] of providers) if (re.test(joined)) return name;
  return nsHosts.length ? "Other" : null;
}

export const dnsLookup = defineTool({
  name: "dns_lookup",
  title: "DNS lookup",
  description:
    "Resolve DNS records for a domain (A, AAAA, CNAME, MX, NS, TXT, SOA, CAA) and identify its DNS host and email provider.",
  priceMicro: 1000,
  cacheTtl: 300,
  input: z.object({
    domain: z.string().describe("Domain name, e.g. stripe.com"),
    types: z.array(z.enum(RECORD_TYPES)).optional().describe("Record types to fetch. Defaults to A, AAAA, MX, NS, TXT."),
  }),
  example: { domain: "stripe.com" },
  async run({ domain, types }) {
    const d = normalizeDomain(domain);
    const wanted: RecordType[] = types?.length ? [...new Set(types)] : ["A", "AAAA", "MX", "NS", "TXT"];
    const results = await Promise.all(wanted.map((t) => resolve(d, t)));
    const records: Record<string, DnsRecord[]> = {};
    wanted.forEach((t, i) => (records[t] = results[i]!));
    const mx = (records.MX ?? (await resolve(d, "MX"))).map((r) => r.value.split(" ").pop()!);
    const ns = (records.NS ?? (await resolve(d, "NS"))).map((r) => r.value);
    return {
      domain: d,
      records,
      dns_provider: detectDnsProvider(ns),
      email_provider: detectMailProvider(mx),
      resolves: Boolean(records.A?.length || records.AAAA?.length || records.CNAME?.length),
    };
  },
});
