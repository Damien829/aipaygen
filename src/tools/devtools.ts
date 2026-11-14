import { z } from "zod";
import { fetchJson, fetchPage, isIPv4, isPrivateIPv4, isPrivateIPv6 } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

/** Developer and network tools: OSV vulnerabilities, package registries, IP ownership, redirect chains. */

const USER_AGENT = "AIPayGenBot/2.0 (+https://aipaygen.com/bot)";

const ECOSYSTEMS: Record<string, string> = {
  npm: "npm", pypi: "PyPI", python: "PyPI", pip: "PyPI", go: "Go", golang: "Go", "crates.io": "crates.io", cargo: "crates.io", rust: "crates.io",
  maven: "Maven", java: "Maven", rubygems: "RubyGems", ruby: "RubyGems", gem: "RubyGems", nuget: "NuGet", ".net": "NuGet",
  packagist: "Packagist", php: "Packagist", composer: "Packagist", pub: "Pub", dart: "Pub", hex: "Hex", elixir: "Hex",
};

export function osvEcosystem(input: string): string {
  const e = ECOSYSTEMS[input.trim().toLowerCase()];
  if (!e) throw new ToolError(`Unknown ecosystem "${input}". Use one of: npm, PyPI, Go, crates.io, Maven, RubyGems, NuGet, Packagist, Pub, Hex.`, "INVALID_INPUT", 400);
  return e;
}

interface OsvVuln {
  id: string;
  aliases?: string[];
  summary?: string;
  details?: string;
  published?: string;
  severity?: { type: string; score: string }[];
  database_specific?: { severity?: string };
  affected?: { package?: { name?: string }; ranges?: { events: Record<string, string>[] }[] }[];
  references?: { url: string }[];
}

/** Compact, agent-friendly view of one OSV advisory. */
export function summarizeVuln(v: OsvVuln, pkg: string) {
  const fixed = new Set<string>();
  for (const a of v.affected ?? []) {
    if (a.package?.name && a.package.name.toLowerCase() !== pkg.toLowerCase()) continue;
    for (const r of a.ranges ?? []) for (const ev of r.events) if (ev.fixed) fixed.add(ev.fixed);
  }
  return {
    id: v.id,
    cve: v.aliases?.find((a) => a.startsWith("CVE-")) ?? null,
    summary: v.summary ?? v.details?.slice(0, 200) ?? null,
    severity: v.database_specific?.severity ?? null,
    cvss: v.severity?.find((s) => s.type.startsWith("CVSS"))?.score ?? null,
    fixed_in: [...fixed],
    published: v.published ?? null,
    link: `https://osv.dev/vulnerability/${v.id}`,
  };
}

export const packageVulns = defineTool({
  name: "package_vulns",
  title: "Package vulnerability check",
  description:
    "Check an open-source package version for known security vulnerabilities (CVEs, GitHub advisories) across npm, PyPI, Go, Rust, Maven, RubyGems, NuGet, PHP and more. Returns each issue's severity and the version that fixes it.",
  priceMicro: 2000,
  cacheTtl: 3600,
  input: z.object({
    ecosystem: z.string().min(2).max(20).describe('Package ecosystem: "npm", "PyPI", "Go", "crates.io", "Maven", "RubyGems", "NuGet", "Packagist".'),
    name: z.string().min(1).max(214).describe('Package name, e.g. "lodash" or "django".'),
    version: z.string().max(100).optional().describe('Version to check, e.g. "4.17.15". Leave out to list every known advisory.'),
  }),
  example: { ecosystem: "npm", name: "lodash", version: "4.17.15" },
  async run({ ecosystem, name, version }) {
    const eco = osvEcosystem(ecosystem);
    let res: Response;
    try {
      res = await fetch("https://api.osv.dev/v1/query", {
        method: "POST",
        headers: { "content-type": "application/json", "user-agent": USER_AGENT },
        body: JSON.stringify({ package: { name: name.trim(), ecosystem: eco }, ...(version ? { version: version.trim() } : {}) }),
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      throw new ToolError("The vulnerability database is unreachable right now.", "UPSTREAM_UNREACHABLE", 502);
    }
    if (!res.ok) throw new ToolError(`The vulnerability database didn't answer (status ${res.status}).`, "UPSTREAM_ERROR", 502);
    const data = (await res.json()) as { vulns?: OsvVuln[] };
    const vulns = (data.vulns ?? []).map((v) => summarizeVuln(v, name.trim()));
    const order = ["CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW"];
    vulns.sort((a, b) => (order.indexOf(a.severity ?? "") + 9) % 9 - (order.indexOf(b.severity ?? "") + 9) % 9);
    return {
      ecosystem: eco,
      name: name.trim(),
      version: version ?? null,
      vulnerable: vulns.length > 0,
      count: vulns.length,
      worst_severity: vulns.find((v) => v.severity)?.severity ?? null,
      vulnerabilities: vulns.slice(0, 50),
      credit: "OSV.dev open source vulnerability database.",
    };
  },
});

export const packageInfo = defineTool({
  name: "package_info",
  title: "Package registry info",
  description:
    "Latest version, description, license, repository, homepage, release date and weekly downloads for any npm, PyPI or Rust (crates.io) package. Good for picking dependencies and checking they're maintained.",
  priceMicro: 1000,
  cacheTtl: 3600,
  input: z.object({
    ecosystem: z.enum(["npm", "pypi", "crates"]).describe('"npm", "pypi" or "crates".'),
    name: z.string().min(1).max(214).describe('Package name, e.g. "zod", "requests", "serde".'),
  }),
  example: { ecosystem: "npm", name: "zod" },
  async run({ ecosystem, name }) {
    const n = name.trim();
    if (!/^(@[a-z0-9._~-]+\/)?[A-Za-z0-9._~-]+$/.test(n)) throw new ToolError(`"${name}" is not a valid package name.`, "INVALID_INPUT", 400);
    const notFound = () => new ToolError(`No ${ecosystem} package called "${n}".`, "NOT_FOUND", 404);

    if (ecosystem === "npm") {
      // The "latest" manifest is small; the full package document can be megabytes.
      const [{ data: doc }, { data: dl }] = await Promise.all([
        fetchJson<{
          name: string; version: string; description?: string; license?: string | { type?: string }; homepage?: string;
          repository?: { url?: string } | string; maintainers?: unknown[]; deprecated?: string; engines?: Record<string, string>;
          dependencies?: Record<string, string>;
        }>(`https://registry.npmjs.org/${n}/latest`),
        fetchJson<{ downloads?: number }>(`https://api.npmjs.org/downloads/point/last-week/${n}`),
      ]);
      if (!doc?.version) throw notFound();
      const repo = typeof doc.repository === "string" ? doc.repository : doc.repository?.url;
      return {
        ecosystem, name: doc.name, latest_version: doc.version, description: doc.description ?? null,
        license: (typeof doc.license === "string" ? doc.license : doc.license?.type) ?? null,
        homepage: doc.homepage ?? null, repository: repo?.replace(/^git\+/, "").replace(/\.git$/, "") ?? null,
        deprecated: doc.deprecated ?? null, dependencies: Object.keys(doc.dependencies ?? {}).length, engines: doc.engines ?? null,
        weekly_downloads: dl?.downloads ?? null, maintainers: doc.maintainers?.length ?? null,
        url: `https://www.npmjs.com/package/${n}`,
      };
    }

    if (ecosystem === "pypi") {
      const { data } = await fetchJson<{
        info: { name: string; version: string; summary?: string; license?: string; license_expression?: string; home_page?: string; project_urls?: Record<string, string>; requires_python?: string; author?: string };
        urls?: { upload_time_iso_8601?: string }[];
      }>(`https://pypi.org/pypi/${encodeURIComponent(n)}/json`);
      if (!data?.info) throw notFound();
      const i = data.info;
      const urls = i.project_urls ?? {};
      const repo = Object.entries(urls).find(([k, v]) => /source|repo|code|github/i.test(k) || /github\.com|gitlab\.com/.test(v))?.[1] ?? null;
      return {
        ecosystem, name: i.name, latest_version: i.version, description: i.summary ?? null,
        license: i.license_expression ?? (i.license && i.license.length < 80 ? i.license : null),
        homepage: i.home_page ?? urls.Homepage ?? urls.homepage ?? null, repository: repo,
        latest_release: data.urls?.[0]?.upload_time_iso_8601 ?? null, requires_python: i.requires_python ?? null,
        weekly_downloads: null, url: `https://pypi.org/project/${i.name}/`,
      };
    }

    const { data } = await fetchJson<{
      crate: { name: string; max_stable_version?: string; newest_version?: string; description?: string; homepage?: string; repository?: string; updated_at?: string; created_at?: string; recent_downloads?: number; downloads?: number };
      versions?: { num: string; license?: string; created_at?: string }[];
    }>(`https://crates.io/api/v1/crates/${encodeURIComponent(n)}`);
    if (!data?.crate) throw notFound();
    const c = data.crate;
    const latest = c.max_stable_version ?? c.newest_version ?? null;
    const v = data.versions?.find((x) => x.num === latest);
    return {
      ecosystem, name: c.name, latest_version: latest, description: c.description?.trim() ?? null, license: v?.license ?? null,
      homepage: c.homepage ?? null, repository: c.repository ?? null, latest_release: v?.created_at ?? c.updated_at ?? null,
      created: c.created_at ?? null, downloads_90_days: c.recent_downloads ?? null, total_downloads: c.downloads ?? null,
      url: `https://crates.io/crates/${c.name}`,
    };
  },
});

/** Full 8-group form of an IPv6 address ("2001:db8::1" -> 2001:0db8:0000:...:0001), or null. */
export function expandIPv6(ip: string): string | null {
  if (!/^[0-9a-f:]+$/i.test(ip) || (ip.match(/::/g) ?? []).length > 1) return null;
  const [head, tail] = ip.split("::") as [string, string | undefined];
  const h = head ? head.split(":") : [];
  const t = tail ? tail.split(":") : [];
  const missing = 8 - h.length - t.length;
  if (tail === undefined ? h.length !== 8 : missing < 1) return null;
  const groups = [...h, ...Array(tail === undefined ? 0 : missing).fill("0"), ...t];
  if (groups.some((g) => !/^[0-9a-f]{1,4}$/i.test(g))) return null;
  return groups.map((g) => g.toLowerCase().padStart(4, "0")).join(":");
}

/** The in-addr.arpa / ip6.arpa name for a reverse-DNS (PTR) lookup. */
export function reverseName(ip: string): string | null {
  if (isIPv4(ip)) return `${ip.split(".").reverse().join(".")}.in-addr.arpa`;
  const full = expandIPv6(ip);
  return full ? `${full.replace(/:/g, "").split("").reverse().join(".")}.ip6.arpa` : null;
}

interface RdapEntity { roles?: string[]; vcardArray?: [string, [string, unknown, string, unknown][]]; entities?: RdapEntity[] }
const vcard = (e: RdapEntity, field: string) => e.vcardArray?.[1]?.find((x) => x[0] === field)?.[3];
function findRole(list: RdapEntity[] | undefined, role: string): RdapEntity | undefined {
  for (const e of list ?? []) {
    if (e.roles?.includes(role)) return e;
    const inner = findRole(e.entities, role);
    if (inner) return inner;
  }
  return undefined;
}

export const ipLookup = defineTool({
  name: "ip_lookup",
  title: "IP address owner lookup",
  description:
    "Who owns an IP address: the network name, organization, country, address range (CIDR), abuse contact and reverse-DNS hostname, from the regional internet registries (RDAP). IPv4 and IPv6.",
  priceMicro: 1000,
  cacheTtl: 86_400,
  input: z.object({ ip: z.string().min(2).max(45).describe('IPv4 or IPv6 address, e.g. "8.8.8.8".') }),
  example: { ip: "8.8.8.8" },
  async run({ ip }) {
    const addr = ip.trim().toLowerCase();
    const v4 = isIPv4(addr);
    if (!v4 && !expandIPv6(addr)) throw new ToolError(`"${ip}" is not a valid IP address.`, "INVALID_INPUT", 400);
    if (v4 ? isPrivateIPv4(addr) : isPrivateIPv6(addr)) throw new ToolError("That is a private or reserved address; it has no public owner.", "BLOCKED_HOST", 400);

    const ptrName = reverseName(addr)!;
    const [rdap, ptr] = await Promise.all([
      fetchJson<{
        name?: string; handle?: string; startAddress?: string; endAddress?: string; country?: string; type?: string;
        cidr0_cidrs?: { v4prefix?: string; v6prefix?: string; length: number }[]; entities?: RdapEntity[];
        events?: { eventAction: string; eventDate: string }[]; port43?: string;
      }>(`https://rdap.org/ip/${addr}`, { timeoutMs: 8000, headers: { accept: "application/rdap+json" } }),
      fetchJson<{ Answer?: { type: number; data: string }[] }>(`https://cloudflare-dns.com/dns-query?name=${ptrName}&type=PTR`, {
        timeoutMs: 4000,
        headers: { accept: "application/dns-json" },
      }).catch(() => ({ data: null })),
    ]);
    const d = rdap.data;
    if (!d) throw new ToolError(`The internet registries didn't answer for ${addr} (status ${rdap.status}).`, "UPSTREAM_ERROR", 502);
    const org = findRole(d.entities, "registrant") ?? findRole(d.entities, "administrative");
    const abuse = findRole(d.entities, "abuse");
    const adrLabel = (org?.vcardArray?.[1]?.find((x) => x[0] === "adr")?.[1] as { label?: string } | undefined)?.label;
    return {
      ip: addr,
      hostname: ptr.data?.Answer?.find((a) => a.type === 12)?.data.replace(/\.$/, "") ?? null,
      network_name: d.name ?? null,
      organization: (org && (vcard(org, "fn") as string)) || null,
      country: d.country ?? null,
      address: adrLabel ? adrLabel.replace(/\n+/g, ", ") : null,
      range: d.startAddress && d.endAddress ? `${d.startAddress} - ${d.endAddress}` : null,
      cidr: (d.cidr0_cidrs ?? []).map((c) => `${c.v4prefix ?? c.v6prefix}/${c.length}`),
      allocation: d.type ?? null,
      abuse_email: abuse ? ((vcard(abuse, "email") as string) ?? null) : null,
      registered: d.events?.find((e) => e.eventAction === "registration")?.eventDate ?? null,
      registry: d.port43 ?? null,
      handle: d.handle ?? null,
    };
  },
});

export const redirectCheck = defineTool({
  name: "redirect_check",
  title: "Link unshortener and redirect checker",
  description:
    "Follow a link through every redirect (bit.ly, t.co, tracking links, http-to-https) and show each hop and where it really ends up, with the final status code. Use it to unshorten links or check them before visiting.",
  priceMicro: 1000,
  cacheTtl: 3600,
  input: z.object({ url: z.string().min(4).max(2000).describe('The link to follow, e.g. "https://bit.ly/3abc".') }),
  example: { url: "http://github.com" },
  async run({ url }) {
    const page = await fetchPage(url, { timeoutMs: 10_000 });
    const start = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url.trim()) ? url.trim() : `https://${url.trim()}`);
    const final = new URL(page.url);
    const notes: string[] = [];
    if (start.hostname.replace(/^www\./, "") !== final.hostname.replace(/^www\./, "")) notes.push(`Ends on a different site: ${final.hostname}.`);
    if (final.protocol === "http:") notes.push("Final page is plain HTTP (not encrypted).");
    if (page.status >= 400) notes.push(`Final page returns an error (${page.status}).`);
    const tracking = [...final.searchParams.keys()].filter((k) => /^(utm_|fbclid|gclid|mc_|ref$|igshid)/i.test(k));
    if (tracking.length) notes.push(`Final URL carries tracking parameters: ${tracking.join(", ")}.`);
    return {
      start_url: start.toString(),
      final_url: page.url,
      final_status: page.status,
      hops: page.redirects.length,
      chain: [start.toString(), ...page.redirects],
      final_domain: final.hostname,
      notes,
      ms: page.ms,
    };
  },
});
