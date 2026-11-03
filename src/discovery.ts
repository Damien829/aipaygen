import { type CatalogItem, catalogStats, KINDS, type Kind, getCatalogItem, searchCatalog } from "./catalog";
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
export interface RelatedItem { name: string; kind: string; price: string | null; url: string }

function snippets(env: Env, item: CatalogItem, kind: Kind, id: string): { label: string; code: string }[] {
  const out: { label: string; code: string }[] = [];
  const remote = typeof item.meta.remote === "string" ? item.meta.remote : null;
  if (kind === "mcp" && remote) {
    out.push({ label: "Add to an MCP client", code: JSON.stringify({ mcpServers: { [item.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()]: { url: remote } } }, null, 2) });
  } else if (item.x402 && item.url) {
    out.push({ label: "Call it (an x402 client pays automatically)", code: `curl -i ${item.url}\n# 402 reply -> sign PAYMENT-REQUIRED with an x402 client (e.g. @x402/fetch) -> retry with PAYMENT-SIGNATURE` });
  } else if (item.url) {
    out.push({ label: "Endpoint", code: item.url });
  }
  out.push({ label: "This listing as JSON", code: `curl ${env.PUBLIC_URL}/v1/catalog/${kind}/${id}` });
  out.push({ label: "Search the whole marketplace from your agent (MCP)", code: JSON.stringify({ mcpServers: { aipaygen: { url: `${env.PUBLIC_URL}/mcp` } } }, null, 2) });
  return out;
}

const COPY_JS = `<script>document.querySelectorAll(".copy").forEach(b=>b.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(b.nextElementSibling.textContent);b.textContent="Copied";setTimeout(()=>b.textContent="Copy",1500);}catch(e){}}));</script>`;

export function catalogItemPage(env: Env, item: CatalogItem, related: RelatedItem[] = []): string {
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
<table>${item.url ? `<tr><td>Endpoint</td><td><code>${esc(item.url)}</code></td></tr>` : ""}${item.price ? `<tr><td>Price</td><td class="price">${esc(item.price)} per call</td></tr>` : ""}${item.trust ? `<tr><td>Trust</td><td>${item.trust.verified ? "✓ Verified callable · " : ""}${item.trust.uptime_pct}% uptime over ${item.trust.checks} checks${item.trust.latency_ms != null ? ` · ~${item.trust.latency_ms} ms` : ""}</td></tr>` : `<tr><td>Trust</td><td>Not checked yet</td></tr>`}<tr><td>Pricing</td><td>${item.x402 ? "Pay per call with x402, no account. Call it to get an exact quote before paying." : "See the provider"}</td></tr>${meta}</table>
<h2>Use it</h2>${snippets(env, item, kind, id).map((sn) => `<p class="muted">${esc(sn.label)}</p><div class="snip"><button class="copy" type="button" aria-label="Copy ${esc(sn.label)}">Copy</button><pre><code>${esc(sn.code)}</code></pre></div>`).join("")}
${related.length ? `<h2>Related</h2><ul class="cards">${related.map((r) => `<li class="card"><a class="t" href="${esc(r.url)}">${esc(r.name)}</a><div class="badges"><span class="b">${esc(KIND_LABEL[r.kind as Kind] ?? r.kind)}</span>${r.price ? `<span class="b pay">${esc(r.price)}/call</span>` : ""}</div></li>`).join("")}</ul>` : ""}</main>${COPY_JS}`;
  return layout(env, `${item.name} · ${KIND_LABEL[kind]} for AI agents · AIPayGen`, body, desc.slice(0, 300),
    `<link rel="canonical" href="${esc(url)}"><link rel="alternate" type="application/json" href="/v1/catalog/${esc(kind)}/${esc(id)}"><script type="application/ld+json">${JSON.stringify(ld).replace(/</g, "\\u003c")}</script>${MARKET_CSS}${webMcpScript()}`);
}

export async function marketItem(env: Env, kind: string, id: string): Promise<CatalogItem | null> {
  return KINDS.includes(kind as Kind) ? getCatalogItem(env, `${kind}:${id}`) : null;
}

const MARKET_CSS = `<style>
.mk-search{display:flex;gap:8px;margin:12px 0}.mk-search input{flex:1;min-width:0;padding:12px 14px;font:inherit;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg)}
.mk-search input:focus{outline:2px solid var(--accent);outline-offset:1px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chip{padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);font:inherit;font-size:.9rem;cursor:pointer;text-decoration:none}
.chip[aria-pressed=true]{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}.chip .n{opacity:.7;margin-left:4px;font-variant-numeric:tabular-nums}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:12px;margin:12px 0;padding:0;list-style:none}
.card{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:14px;display:flex;flex-direction:column;gap:6px;min-width:0}
.card a.t{font-weight:600;color:var(--fg);text-decoration:none;overflow-wrap:anywhere}.card a.t:hover{text-decoration:underline}
.card p{margin:0;color:var(--muted);font-size:.92rem;overflow-wrap:anywhere}.badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto}
.b{font-size:.75rem;padding:2px 8px;border-radius:999px;background:var(--code);color:var(--muted)}.b.ok{color:#1a7f37;font-weight:600}@media (prefers-color-scheme:dark){.b.ok{color:#56d364}}.b.pay{color:var(--fg)}
.mk-status{color:var(--muted);font-size:.9rem;min-height:1.4em}.more{margin:8px auto 24px;display:block}
.snip{position:relative}.snip pre{background:var(--code);padding:12px;border-radius:10px;overflow-x:auto;font-size:.85rem}
.copy{position:absolute;top:6px;right:6px;font:inherit;font-size:.8rem;padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
</style>`;

function card(env: Env, i: CatalogItem): string {
  const [k, id] = i.id.split(/:(.*)/s);
  const badges = [`<span class="b">${esc(KIND_LABEL[i.kind])}</span>`, i.trust?.verified ? `<span class="b ok">✓ Verified</span>` : "", i.trust ? `<span class="b">${i.trust.uptime_pct}% up</span>` : "", i.price ? `<span class="b pay">${esc(i.price)}/call</span>` : "", i.x402 ? `<span class="b">x402</span>` : ""].join("");
  return `<li class="card"><a class="t" href="/market/${esc(k!)}/${encodeURIComponent(id!)}">${esc(i.name)}</a><p>${esc((i.description || "").slice(0, 180))}</p><div class="badges">${badges}</div></li>`;
}

/** Marketplace home. Server-rendered first page (works without JS for agents and crawlers);
 * in a browser, search updates as you type, chips filter by kind, and "Load more" pages on. */
export async function marketPage(env: Env, q: string, kind?: Kind): Promise<string> {
  const [r, stats] = await Promise.all([searchCatalog(env, { q: q || undefined, kind, limit: 24 }), catalogStats(env)]);
  const total = Object.values(stats.counts).reduce((a, b) => a + (b as number), 0);
  const chip = (k: Kind | "", label: string, n: number) =>
    `<a class="chip" data-kind="${k}" aria-pressed="${(kind ?? "") === k}" href="/market?${new URLSearchParams({ ...(q ? { q } : {}), ...(k ? { kind: k } : {}) })}">${esc(label)}<span class="n">${n.toLocaleString("en-US")}</span></a>`;
  const chips = [chip("", "All", total), ...KINDS.filter((k) => stats.counts[k]).map((k) => chip(k, `${KIND_LABEL[k]}s`, stats.counts[k] as number))].join("");
  const body = `<main><h1>Marketplace</h1><p>${total.toLocaleString("en-US")} resources for AI agents: AIPayGen tools, APIs, skills, agents, MCP servers and agent services. Searching is free and the catalog refreshes itself every 10 minutes.</p>
<form class="mk-search" action="/market" role="search" aria-label="Search the marketplace"><input id="q" name="q" type="search" value="${esc(q)}" placeholder="What does your agent need? e.g. weather API, summarize PDF" aria-label="Search query" autocomplete="off">${kind ? `<input type="hidden" name="kind" value="${esc(kind)}">` : ""}</form>
<nav class="chips" aria-label="Filter by kind">${chips}</nav>
<p class="muted"><a href="/market/wanted">Most wanted by agents →</a></p><p class="mk-status" id="status" aria-live="polite">${r.total.toLocaleString("en-US")} results</p>
<ul class="cards" id="results">${r.items.map((i) => card(env, i)).join("")}</ul>
<button class="chip more" id="more" type="button" ${r.total > 24 ? "" : "hidden"}>Load more</button></main>
<script>(()=>{const q=document.getElementById("q"),res=document.getElementById("results"),st=document.getElementById("status"),more=document.getElementById("more");
const L=${JSON.stringify(KIND_LABEL)};let kind=${JSON.stringify(kind ?? "")},off=24,total=${r.total},t,seq=0;
const e=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const card=i=>{const x=i.id.indexOf(":"),k=i.id.slice(0,x),id=i.id.slice(x+1);return '<li class="card"><a class="t" href="/market/'+e(k)+'/'+encodeURIComponent(id)+'">'+e(i.name)+'</a><p>'+e((i.description||"").slice(0,180))+'</p><div class="badges"><span class="b">'+e(L[i.kind])+'</span>'+(i.trust&&i.trust.verified?'<span class="b ok">✓ Verified</span>':'')+(i.trust?'<span class="b">'+i.trust.uptime_pct+'% up</span>':'')+(i.price?'<span class="b pay">'+e(i.price)+'/call</span>':'')+(i.x402?'<span class="b">x402</span>':'')+'</div></li>';};
async function load(reset){const n=++seq;const p=new URLSearchParams({limit:"24",offset:String(reset?0:off)});if(q.value.trim())p.set("q",q.value.trim());if(kind)p.set("kind",kind);
st.textContent="Searching…";const d=await (await fetch("/v1/catalog/search?"+p)).json();if(n!==seq)return;
if(reset){res.innerHTML="";off=0;}res.insertAdjacentHTML("beforeend",d.items.map(card).join(""));off+=d.items.length;total=d.total;
st.textContent=total.toLocaleString("en-US")+" results";more.hidden=off>=total;
const u=new URLSearchParams();if(q.value.trim())u.set("q",q.value.trim());if(kind)u.set("kind",kind);history.replaceState(null,"","/market"+(u.toString()?"?"+u:""));}
q.addEventListener("input",()=>{clearTimeout(t);t=setTimeout(()=>load(true),220);});
document.querySelector(".mk-search").addEventListener("submit",ev=>{ev.preventDefault();load(true);});
document.querySelectorAll(".chip[data-kind]").forEach(c=>c.addEventListener("click",ev=>{ev.preventDefault();kind=c.dataset.kind;document.querySelectorAll(".chip[data-kind]").forEach(x=>x.setAttribute("aria-pressed",String(x===c)));load(true);}));
more.addEventListener("click",()=>load(false));})();</script>`;
  return layout(env, q ? `${q} · AIPayGen Marketplace` : "AIPayGen Marketplace · tools, APIs and skills for AI agents", body,
    "Search 11,000+ APIs, skills, agents, MCP servers and pay-per-call tools for AI agents. Free to search; pay per call with x402 or credits.", MARKET_CSS + webMcpScript());
}

/** Sitemap index plus one sitemap per kind (each well under the 50,000-URL limit). */
export function sitemapIndex(env: Env): string {
  const maps = ["pages", ...KINDS].map((k) => `<sitemap><loc>${env.PUBLIC_URL}/sitemaps/${k}.xml</loc></sitemap>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${maps}</sitemapindex>`;
}

export async function sitemapFor(env: Env, name: string): Promise<string | null> {
  let locs: string[];
  if (name === "pages") {
    locs = ["/", "/market", "/market/wanted", "/docs", "/billing", "/llms.txt", "/llms-full.txt"].map((p) => env.PUBLIC_URL + p);
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
      description: t.priceMicro === 0 ? `${t.description} Free.` : `${t.description} Pay per call; quote on request.`,
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
  const tools = TOOLS.map((t) => `### ${t.name}${t.priceMicro === 0 ? " (free)" : ""}\n${t.description}\nHTTP: ${t.httpMethod ?? "GET"} ${env.PUBLIC_URL}/v1/${t.name}\nExample input: ${JSON.stringify(t.example)}\n`).join("\n");
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

/**
 * What agents search for and can't find. Only queries searched 3+ times, short and
 * plain (letters, digits, spaces, dashes), so nothing one person typed is exposed.
 */
export async function wantedList(env: Env, days = 30) {
  const since = Date.now() - days * 86_400_000;
  const q = (zero: boolean) => env.DB.prepare(
    `SELECT query, COUNT(*) AS searches FROM search_log WHERE created_at > ? ${zero ? "AND results = 0" : ""}
     AND length(query) <= 60 AND query NOT GLOB '*[^a-z0-9 -]*' GROUP BY query HAVING COUNT(*) >= 3 ORDER BY searches DESC LIMIT 40`,
  ).bind(since);
  const [unmet, popular] = await env.DB.batch([q(true), q(false)]);
  return { window_days: days, unmet: unmet?.results ?? [], popular: popular?.results ?? [] };
}

export async function wantedPage(env: Env): Promise<string> {
  const w = await wantedList(env);
  const li = (rows: unknown[]) => (rows as { query: string; searches: number }[])
    .map((r) => `<li><a href="/market?q=${encodeURIComponent(r.query)}">${esc(r.query)}</a> <span class="muted">· ${r.searches} searches</span></li>`).join("") || `<li class="muted">Not enough searches yet. Check back soon.</li>`;
  const body = `<main><h1>Most wanted</h1><p>What AI agents are searching this marketplace for. If you build or run one of these, list it for free: send your agent card to <code>POST ${esc(env.PUBLIC_URL)}/v1/agents/register</code> or use the <code>register_agent</code> MCP tool.</p>
<h2>Searched for, not found yet</h2><ul>${li(w.unmet)}</ul><h2>Popular searches</h2><ul>${li(w.popular)}</ul>
<p class="muted">Last ${w.window_days} days. Only searches made at least 3 times are shown.</p></main>`;
  return layout(env, "Most wanted by AI agents · AIPayGen", body, "What AI agents search for in the AIPayGen marketplace, and what they can't find yet.");
}
