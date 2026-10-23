import { z } from "zod";
import { fetchJson, normalizeDomain } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

interface RdapEntity {
  roles?: string[];
  vcardArray?: [string, [string, Record<string, unknown>, string, unknown][]];
  publicIds?: { type: string; identifier: string }[];
  entities?: RdapEntity[];
}

export interface RdapDomain {
  ldhName?: string;
  status?: string[];
  events?: { eventAction: string; eventDate: string }[];
  nameservers?: { ldhName?: string }[];
  secureDNS?: { delegationSigned?: boolean };
  entities?: RdapEntity[];
}

function vcardField(entity: RdapEntity, field: string): string | null {
  const props = entity.vcardArray?.[1] ?? [];
  const hit = props.find((p) => p[0] === field);
  if (!hit) return null;
  const v = hit[3];
  if (Array.isArray(v)) return v.filter(Boolean).join(", ") || null;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function findEntity(entities: RdapEntity[] | undefined, role: string): RdapEntity | null {
  for (const e of entities ?? []) {
    if (e.roles?.includes(role)) return e;
    const nested = findEntity(e.entities, role);
    if (nested) return nested;
  }
  return null;
}

/** Turn a raw RDAP domain object into a compact, agent-friendly summary. */
export function summarizeRdap(domain: string, rdap: RdapDomain) {
  const event = (action: string) => rdap.events?.find((e) => e.eventAction === action)?.eventDate ?? null;
  const registrar = findEntity(rdap.entities, "registrar");
  const registrant = findEntity(rdap.entities, "registrant");
  const created = event("registration");
  const expires = event("expiration");
  const now = Date.now();
  const redacted = (v: string | null) => (v && /redacted|privacy|withheld|not disclosed|data protected/i.test(v) ? null : v);

  return {
    domain,
    registered: true,
    registrar: registrar ? vcardField(registrar, "fn") : null,
    registrar_iana_id: registrar?.publicIds?.find((p) => /iana/i.test(p.type))?.identifier ?? null,
    created,
    updated: event("last changed"),
    expires,
    age_days: created ? Math.floor((now - Date.parse(created)) / 86_400_000) : null,
    days_until_expiry: expires ? Math.floor((Date.parse(expires) - now) / 86_400_000) : null,
    status: rdap.status ?? [],
    nameservers: (rdap.nameservers ?? []).map((n) => n.ldhName?.toLowerCase()).filter(Boolean),
    dnssec: rdap.secureDNS?.delegationSigned ?? false,
    registrant_org: registrant ? redacted(vcardField(registrant, "org") ?? vcardField(registrant, "fn")) : null,
    registrant_country: registrant ? redacted(vcardField(registrant, "adr")?.split(", ").pop() ?? null) : null,
  };
}

export const domainWhois = defineTool({
  name: "domain_whois",
  title: "Domain registration (RDAP/WHOIS)",
  description:
    "Look up who registered a domain and when: registrar, creation and expiry dates, domain age, status codes, nameservers and DNSSEC, via RDAP (the modern WHOIS).",
  priceMicro: 2000,
  cacheTtl: 86_400,
  input: z.object({ domain: z.string().describe("Domain name, e.g. openai.com") }),
  example: { domain: "openai.com" },
  async run({ domain }) {
    const d = normalizeDomain(domain);
    // rdap.org redirects to the authoritative registry's RDAP server for the TLD.
    const { status, data } = await fetchJson<RdapDomain>(`https://rdap.org/domain/${encodeURIComponent(d)}`, {
      headers: { accept: "application/rdap+json" },
      timeoutMs: 10_000,
    });
    if (status === 404) return { domain: d, registered: false };
    if (!data) throw new ToolError("No RDAP data is available for this domain's TLD.", "UPSTREAM_ERROR", 502);
    return summarizeRdap(d, data);
  },
});
