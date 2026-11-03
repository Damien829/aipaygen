import { type CatalogItem, KINDS, type Kind, getCatalogItem, searchCatalog } from "./catalog";
import { CORE_ROUTES } from "./core/proxy";
import { APP_VERSION, type Env } from "./env";
import { esc, layout } from "./pages";
import { TOOLS } from "./tools";
import { formatPrice } from "./tools/types";

/**
 * Discovery for agents that never visit the homepage: indexable catalog pages and
 * sitemaps (search and AI answer engines), the A2A agent card, an x402 resource
 * list, llms-full.txt, and a robots.txt that welcomes AI crawlers.
 */

const KIND_LABEL: Record<Kind, string> = { listing: "AIPayGen tool", api: "API", skill: "Skill", agent: "Agent", service: "Agent service", mcp: "MCP server" };

/** Search engines get one indexable page per catalog item. */
export function catalogItemPage(env: Env, item: CatalogItem): string {
  const [kind, id] = item.id.split(/:(.*)/s) as [Kind, string];
  const url = `${env.PUBLIC_URL}/market/${kind}/${encodeURIComponent(id)}`;
  const desc = item.description || `${KIND_LABEL[kind]} for AI agents: ${item.name}`;
  const ld = {
    "@context": "https://schema.org",
    "@type": kind === "api" ? "WebAPI" : "SoftwareApplication",
    name: item.name,
    description: desc,
    url,
    applicationCategory: item.category || undefined,
    ...(item.url ? { sameAs: item.url } : {}),
    ...(item.price ? { offers: { "@type": "Offer", price: item.price.replace("$", ""), priceCurrency: "USD" } } : {}),
  };
  const meta = Object.entries(item.meta)
    .filter(([, v]) => typeof v === "string" || (Array.isArray(v) && v.length))
    .map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td>${esc(Array.isArray(v) ? v.join(", ") : String(v))}</td></tr>`)
    .join("");
  const body = `<main><p class="muted"><a href="/market">Marketplace</a> · ${esc(KIND_LABEL[kind])}${item.category ? ` · ${esc(item.category)}` : ""}</p>
<h1>${esc(item.name)}</h1><p>${esc(desc)}</p>
<table>${item.url ? `<tr><td>Endpoint</td><td><code>${esc(item.url)}</code></td></tr>` : ""}${item.price ? `<tr><td>Price</td><td class="price">${esc(item.price)} per call</td></tr>` : ""}<tr><td>x402 (pay per call, no account)</td><td>${item.x402 ? "yes" : "no"}</td></tr>${meta}</table>
<h2>Use it from an agent</h2><p>Machine-readable: <code>GET ${esc(env.PUBLIC_URL)}/v1/catalog/${esc(kind)}/${esc(id)}</code>. Find more with the free <code>search_marketplace</code> MCP tool at <code>${esc(env.PUBLIC_URL)}/mcp</code>.</p></main>`;
  return layout(env, `${item.name} · ${KIND_LABEL[kind]} for AI agents · AIPayGen`, body, desc.slice(0, 300),
    `<link rel="canonical" href="${esc(url)}"><link rel="alternate" type="application/json" href="/v1/catalog/${esc(kind)}/${esc(id)}"><script type="application/ld+json">${JSON.stringify(ld).replace(/</g, "\\u003c")}</script>${webMcpScript()}`);
}

export async function marketItem(env: Env, kind: string, id: string): Promise<CatalogItem | null> {
  return KINDS.includes(kind as Kind) ? getCatalogItem(env, `${kind}:${id}`) : null;
}

/** Marketplace home: search box plus a server-rendered first page, so it works without JS. */
export async function marketPage(env: Env, q: string, kind?: Kind): Promise<string> {
  const r = await searchCatalog(env, { q: q || undefined, kind, limit: 30 });
  const rows = r.items
    .map((i) => {
      const [k, id] = i.id.split(/:(.*)/s);
      return `<tr><td><a href="/market/${esc(k!)}/${encodeURIComponent(id!)}">${esc(i.name)}</a><br><span class="muted">${esc((i.description || "").slice(0, 160))}</span></td><td>${esc(KIND_LABEL[i.kind])}</td><td class="price">${i.price ? esc(i.price) : ""}</td></tr>`;
    })
    .join("");
  const tabs = ["", ...KINDS].map((k) => `<a href="/market?${new URLSearchParams({ q, ...(k ? { kind: k } : {}) })}">${k ? esc(KIND_LABEL[k as Kind]) + "s" : "All"}</a>`).join(" · ");
  const body = `<main><h1>Marketplace</h1><p>11,000+ resources for AI agents: AIPayGen tools, third-party APIs, skills, agents and agent services. Searching is free.</p>
<form action="/market" role="search" aria-label="Search the marketplace"><input name="q" aria-label="Search query" value="${esc(q)}" placeholder="What does your agent need? e.g. weather API, summarize PDF" style="width:100%;padding:10px"></form>
<p>${tabs}</p><p class="muted">${r.total.toLocaleString("en-US")} results</p><table>${rows}</table></main>`;
  return layout(env, q ? `${q} · AIPayGen Marketplace` : "AIPayGen Marketplace · tools, APIs and skills for AI agents", body,
    "Search 11,000+ APIs, skills, agents and pay-per-call tools for AI agents. Free to search; pay per call with x402 or credits.", webMcpScript());
}

/** Sitemap index plus one sitemap per kind (each well under the 50,000-URL limit). */
export function sitemapIndex(env: Env): string {
  const maps = ["pages", ...KINDS].map((k) => `<sitemap><loc>${env.PUBLIC_URL}/sitemaps/${k}.xml</loc></sitemap>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${maps}</sitemapindex>`;
}

export async function sitemapFor(env: Env, name: string): Promise<string | null> {
  let locs: string[];
  if (name === "pages") {
    locs = ["/", "/market", "/docs", "/billing", "/llms.txt", "/llms-full.txt"].map((p) => env.PUBLIC_URL + p);
  } else if (KINDS.includes(name as Kind)) {
    const { results } = await env.DB.prepare("SELECT id FROM catalog WHERE kind = ? ORDER BY id LIMIT 50000").bind(name).all<{ id: string }>();
    locs = results.map((r) => `${env.PUBLIC_URL}/market/${name}/${encodeURIComponent(r.id.slice(name.length + 1))}`);
  } else {
    return null;
  }
  const urls = locs.map((l) => `<url><loc>${esc(l)}</loc></url>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`;
}

/** Search and AI crawlers are all welcome; there is nothing private on public pages. */
export function robotsTxt(env: Env): string {
  const ai = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Amazonbot", "meta-externalagent", "Bytespider", "cohere-ai", "DuckAssistBot", "MistralAI-User"];
  return `${ai.map((a) => `User-agent: ${a}\nAllow: /\n`).join("\n")}\nUser-agent: *\nAllow: /\nDisallow: /admin\n\nSitemap: ${env.PUBLIC_URL}/sitemap.xml\n`;
}

/** A2A agent card (/.well-known/agent-card.json; also served at the pre-0.3 agent.json path). */
export function agentCard(env: Env): Record<string, unknown> {
  return {
    protocolVersion: "0.3.0",
    name: "AIPayGen",
    description: "Pay-per-call tools for AI agents: website and company intelligence, plus a free searchable marketplace of 11,000+ APIs, skills, agents and services. Pay with x402 (USDC on Base) or prepaid credits; no account needed for x402.",
    url: `${env.PUBLIC_URL}/mcp`,
    preferredTransport: "JSONRPC",
    additionalInterfaces: [{ url: `${env.PUBLIC_URL}/v1`, transport: "HTTP+JSON" }],
    version: APP_VERSION,
    documentationUrl: `${env.PUBLIC_URL}/docs`,
    provider: { organization: "AIPayGen", url: env.PUBLIC_URL },
    capabilities: { streaming: false, pushNotifications: false },
    defaultInputModes: ["application/json", "text/plain"],
    defaultOutputModes: ["application/json"],
    securitySchemes: { apiKey: { type: "http", scheme: "bearer", description: "Optional apg_ key for prepaid credits. Without one, paid calls use x402." } },
    skills: TOOLS.map((t) => ({
      id: t.name,
      name: t.title,
      description: `${t.description} Price: ${formatPrice(t.priceMicro)} per call.`,
      tags: [t.priceMicro === 0 ? "free" : "x402", "pay-per-call"],
      examples: [JSON.stringify(t.example)],
    })),
  };
}

/** Every payable resource, for x402 crawlers and wallets. */
export function x402Discovery(env: Env): Record<string, unknown> {
  const tools = TOOLS.filter((t) => t.priceMicro > 0).map((t) => ({
    resource: `${env.PUBLIC_URL}/v1/${t.name}`, method: t.httpMethod ?? "GET", price_usd: t.priceMicro / 1_000_000, description: t.description,
  }));
  const core = env.CORE_ORIGIN && env.CORE_EDGE_SECRET
    ? CORE_ROUTES.map((r) => ({ resource: `${env.PUBLIC_URL}${r.path}`, method: r.method, price_usd: r.price_micro / 1_000_000, description: r.description }))
    : [];
  return {
    x402Version: 2,
    payTo: env.PAY_TO || null,
    network: env.X402_NETWORK,
    asset: "USDC",
    facilitator: env.FACILITATOR_URL,
    howToPay: "Call the resource; a 402 response carries PAYMENT-REQUIRED. Sign it with an x402 client and retry with PAYMENT-SIGNATURE. Failed calls are never settled.",
    resources: [...tools, ...core],
    free: [`${env.PUBLIC_URL}/v1/search_marketplace`, `${env.PUBLIC_URL}/v1/catalog/search`],
  };
}

/** Everything an LLM needs in one fetch. */
export function llmsFullTxt(env: Env, base: string): string {
  const tools = TOOLS.map((t) => `### ${t.name} (${formatPrice(t.priceMicro)})\n${t.description}\nHTTP: ${t.httpMethod ?? "GET"} ${env.PUBLIC_URL}/v1/${t.name}\nExample input: ${JSON.stringify(t.example)}\n`).join("\n");
  return `${base}\n\n## Paying\n\n- x402: call any paid endpoint; the 402 reply says what to sign (USDC on ${env.X402_NETWORK}). No account, no API key.\n- Credits: POST ${env.PUBLIC_URL}/v1/keys for a key with free trial credits, then send Authorization: Bearer apg_...\n- Failed calls are never charged.\n\n## Discovery files\n\n- ${env.PUBLIC_URL}/.well-known/agent-card.json (A2A)\n- ${env.PUBLIC_URL}/.well-known/x402 (payable resources)\n- ${env.PUBLIC_URL}/.well-known/mcp/server-card.json (MCP)\n- ${env.PUBLIC_URL}/openapi.json\n\n## Tools\n\n${tools}`;
}

/**
 * WebMCP: AI browsers that support navigator.modelContext get real tools on our
 * pages instead of guessing at buttons. Feature-detected; ordinary browsers ignore it.
 */
export function webMcpScript(): string {
  const js = `(()=>{const mc=navigator.modelContext;if(!mc)return;
const j=async(u)=>{const r=await fetch(u,{headers:{accept:"application/json"}});return{content:[{type:"text",text:await r.text()}]};};
const tools=[
{name:"search_marketplace",description:"Search 11,000+ APIs, skills, agents, services and AIPayGen pay-per-call tools. Free.",
inputSchema:{type:"object",properties:{query:{type:"string"},kind:{type:"string",enum:["listing","api","skill","agent","service"]},limit:{type:"number"}},required:["query"]},
execute:(a)=>j("/v1/catalog/search?"+new URLSearchParams({q:a.query,...(a.kind?{kind:a.kind}:{}),limit:String(a.limit||10)}))},
{name:"get_catalog_item",description:"Full details for one marketplace item by kind and id (from search results, id is 'kind:id').",
inputSchema:{type:"object",properties:{id:{type:"string"}},required:["id"]},
execute:(a)=>{const i=String(a.id).indexOf(":");return j("/v1/catalog/"+encodeURIComponent(a.id.slice(0,i))+"/"+encodeURIComponent(a.id.slice(i+1)));}},
{name:"list_paid_tools",description:"AIPayGen's pay-per-call tools with prices and how to pay (x402 or credits).",
inputSchema:{type:"object",properties:{}},execute:()=>j("/.well-known/x402")}];
try{if(mc.registerTool){tools.forEach(t=>mc.registerTool(t));}else if(mc.provideContext){mc.provideContext({tools});}}catch(e){}})();`;
  return `<script>${js}</script>`;
}

/** Markdown for agents that ask for it (Accept: text/markdown). */
export function catalogItemMarkdown(env: Env, item: CatalogItem): string {
  const [kind, id] = item.id.split(/:(.*)/s) as [Kind, string];
  const extras = Object.entries(item.meta).filter(([, v]) => typeof v === "string" || (Array.isArray(v) && v.length))
    .map(([k, v]) => `- ${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : v}`).join("\n");
  return `# ${item.name}\n\n${KIND_LABEL[kind]}${item.category ? ` · ${item.category}` : ""}\n\n${item.description}\n\n${item.url ? `- Endpoint: ${item.url}\n` : ""}${item.price ? `- Price: ${item.price} per call\n` : ""}- x402 pay-per-call: ${item.x402 ? "yes" : "no"}\n${extras ? extras + "\n" : ""}\nJSON: ${env.PUBLIC_URL}/v1/catalog/${kind}/${id}\nMore: search_marketplace tool at ${env.PUBLIC_URL}/mcp\n`;
}

export async function marketMarkdown(env: Env, q: string, kind?: Kind): Promise<string> {
  const r = await searchCatalog(env, { q: q || undefined, kind, limit: 30 });
  const lines = r.items.map((i) => {
    const [k, id] = i.id.split(/:(.*)/s);
    return `- [${i.name}](${env.PUBLIC_URL}/market/${k}/${encodeURIComponent(id!)}) (${KIND_LABEL[i.kind]}${i.price ? `, ${i.price}` : ""}): ${(i.description || "").slice(0, 160)}`;
  });
  return `# AIPayGen Marketplace${q ? `: ${q}` : ""}\n\n${r.total} results. Search by URL: ${env.PUBLIC_URL}/market?q=<words>&kind=<listing|api|skill|agent|service>\n\n${lines.join("\n")}\n`;
}

/** Points every agent that fetches any page at the machine-readable entry points. */
export const DISCOVERY_LINK_HEADER =
  '</.well-known/agent-card.json>; rel="describedby"; type="application/json", </llms.txt>; rel="describedby"; type="text/plain", </mcp>; rel="service", </openapi.json>; rel="service-desc"; type="application/json"';
