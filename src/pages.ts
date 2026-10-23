import { APP_VERSION, SERVICE_NAME, type Env } from "./env";
import { TOOLS } from "./tools";
import { formatPrice } from "./tools/types";
import { microToUsd, toolJsonSchema, x402Enabled } from "./billing/x402";
import { PACKS, stripeEnabled } from "./billing/stripe";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const STYLE = `
:root{--bg:#fbfaf8;--fg:#17171a;--muted:#5f6068;--line:#e6e3dd;--card:#fff;--accent:#2b59ff;--accent-fg:#fff;--code:#f2f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#0f0f12;--fg:#ecebe8;--muted:#a0a0a8;--line:#26262c;--card:#17171c;--accent:#7c9cff;--accent-fg:#0b0b0e;--code:#1d1d23}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:0 20px}
header.top{display:flex;justify-content:space-between;align-items:center;padding:18px 0}
.logo{font-weight:700;letter-spacing:-.02em;color:var(--fg);text-decoration:none}.logo span{color:var(--accent)}
nav a{color:var(--muted);text-decoration:none;margin-left:18px;font-size:15px}nav a:hover{color:var(--fg)}
h1{font-size:clamp(32px,6vw,52px);line-height:1.08;letter-spacing:-.03em;margin:48px 0 16px}
h2{font-size:26px;letter-spacing:-.02em;margin:56px 0 12px}h3{font-size:18px;margin:0 0 6px}
p.lead{font-size:19px;color:var(--muted);max-width:640px}
.btns{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0}
.btn{display:inline-block;padding:11px 18px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg);text-decoration:none;font-weight:600;font-size:15px;cursor:pointer}
.btn.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.card p{margin:0;color:var(--muted);font-size:15px}
table{width:100%;border-collapse:collapse;font-size:15px}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}td.price{white-space:nowrap;font-variant-numeric:tabular-nums}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px}
pre{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px;overflow-x:auto;margin:10px 0}
code{background:var(--code);padding:1px 5px;border-radius:5px}pre code{background:none;padding:0}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.tabs button{font:inherit;font-size:14px;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}.tabs button[aria-selected=true]{background:var(--fg);color:var(--bg)}
.muted{color:var(--muted)}.small{font-size:14px}
#keybox{display:none;margin-top:14px}
input,select{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg);width:100%}
label{display:block;font-weight:600;margin:14px 0 6px}
footer{margin:72px 0 40px;color:var(--muted);font-size:14px;border-top:1px solid var(--line);padding-top:20px}
.scroll{overflow-x:auto}
`;

function layout(env: Env, title: string, body: string, description: string): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><meta name="description" content="${esc(description)}">
<meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}"><meta property="og:url" content="${esc(env.PUBLIC_URL)}">
<link rel="alternate" type="text/plain" href="/llms.txt" title="llms.txt"><style>${STYLE}</style></head>
<body><div class="wrap"><header class="top"><a class="logo" href="/">AIPay<span>Gen</span></a>
<nav><a href="/#tools">Tools</a><a href="/#connect">Connect</a><a href="/billing">Billing</a><a href="/docs">Docs</a></nav></header>
${body}
<footer>${SERVICE_NAME} v${APP_VERSION} · Public data only · Failed calls are never charged · <a class="muted" href="/llms.txt">llms.txt</a> · <a class="muted" href="/openapi.json">OpenAPI</a></footer>
</div></body></html>`;
}

export function landingPage(env: Env): string {
  const mcpUrl = `${env.PUBLIC_URL}/mcp`;
  const rows = TOOLS.map(
    (t) => `<tr><td><code>${t.name}</code></td><td>${esc(t.description)}</td><td class="price">${formatPrice(t.priceMicro)}</td></tr>`,
  ).join("");
  const x402 = x402Enabled(env);
  const trial = microToUsd(Number(env.TRIAL_CREDITS_MICRO) || 0);

  const body = `
<h1>Website and company intelligence for AI agents.</h1>
<p class="lead">Give your agent ten tools for DNS, domain registration, certificates and subdomains, tech stack, email security, page content and full company profiles. Built on public data. Pay per call from ${formatPrice(TOOLS[0]!.priceMicro)}.</p>
<div class="btns"><button class="btn primary" id="getkey">Get a free API key</button><a class="btn" href="#connect">Connect via MCP</a></div>
<div id="keybox" class="card"><h3>Your API key</h3><p>Copy it now; it is shown only once. It comes with <strong>${trial}</strong> of free credits.</p><pre><code id="keyval"></code></pre></div>

<div class="grid" style="margin-top:36px">
<div class="card"><h3>One domain in, a full profile out</h3><p><code>company_profile</code> combines website metadata, registration, DNS, tech stack and business signals in one call.</p></div>
<div class="card"><h3>MCP and HTTP</h3><p>Use it from Claude, Cursor or any MCP client, or call the plain HTTP API from any agent or script.</p></div>
<div class="card"><h3>Pay how you like</h3><p>Prepaid credits with an API key${x402 ? ", or per-call USDC with x402. No signup needed" : ""}. A failed call is never charged.</p></div>
</div>

<h2 id="tools">Tools and prices</h2>
<div class="scroll"><table><thead><tr><th>Tool</th><th>What it does</th><th>Price</th></tr></thead><tbody>${rows}
<tr><td><code>pricing</code>, <code>create_api_key</code>, <code>account_balance</code></td><td>Account and pricing helpers.</td><td class="price">free</td></tr></tbody></table></div>

<h2 id="connect">Connect</h2>
<p class="muted">MCP endpoint: <code>${esc(mcpUrl)}</code> (Streamable HTTP). Add your key as a header.</p>
<div class="tabs" role="tablist"><button role="tab" aria-selected="true" data-tab="claude">Claude Code</button><button role="tab" aria-selected="false" data-tab="json">Cursor / JSON config</button><button role="tab" aria-selected="false" data-tab="http">HTTP API</button></div>
<pre data-panel="claude"><code>claude mcp add --transport http aipaygen ${esc(mcpUrl)} \\
  --header "Authorization: Bearer YOUR_API_KEY"</code></pre>
<pre data-panel="json" hidden><code>{
  "mcpServers": {
    "aipaygen": {
      "url": "${esc(mcpUrl)}",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}</code></pre>
<pre data-panel="http" hidden><code>curl "${esc(env.PUBLIC_URL)}/v1/company_profile?domain=figma.com" \\
  -H "Authorization: Bearer YOUR_API_KEY"</code></pre>
${x402 ? `<p class="small muted">No key? Call any paid endpoint without one: it answers <code>402</code> with x402 payment requirements (USDC, network <code>${esc(env.X402_NETWORK)}</code>). x402-enabled agents pay automatically.</p>` : ""}

<h2>FAQ</h2>
<div class="grid">
<div class="card"><h3>Where does the data come from?</h3><p>Public sources only: DNS over HTTPS, RDAP registries, Certificate Transparency logs and the public web pages of the site you ask about.</p></div>
<div class="card"><h3>What if a call fails?</h3><p>You are not charged. Credits are refunded and x402 payments are not settled.</p></div>
<div class="card"><h3>Is there caching?</h3><p>Yes. Repeat lookups are served fast from cache within each tool's freshness window, at the same price.</p></div>
</div>

<script>
document.querySelectorAll('[data-tab]').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('[data-tab]').forEach(function(x){x.setAttribute('aria-selected',x===b)});document.querySelectorAll('[data-panel]').forEach(function(p){p.hidden=p.dataset.panel!==b.dataset.tab})})});
document.getElementById('getkey').addEventListener('click',async function(){var btn=this;btn.disabled=true;btn.textContent='Creating…';try{var r=await fetch('/v1/keys',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});var d=await r.json();if(!r.ok)throw new Error(d.error&&d.error.message||'Failed');document.getElementById('keyval').textContent=d.api_key;document.getElementById('keybox').style.display='block';btn.textContent='Key created';}catch(e){btn.disabled=false;btn.textContent='Get a free API key';alert(e.message)}});
</script>`;
  return layout(env, "AIPayGen: website and company intelligence for AI agents", body, "Pay-per-call MCP and HTTP tools for DNS, WHOIS, certificates, tech stack, email security and company profiles.");
}

export function billingPage(env: Env, paid: boolean): string {
  const packs = Object.entries(PACKS)
    .map(([id, p]) => `<option value="${id}">Pay $${(p.cents / 100).toFixed(0)}: get ${esc(p.label)}</option>`)
    .join("");
  const body = `
<h1>Billing</h1>
${paid ? `<div class="card"><h3>Payment received</h3><p>Credits are added within a few seconds. Check your balance below.</p></div>` : ""}
<div class="grid" style="margin-top:24px">
<div class="card"><h3>Check balance</h3><label for="bkey">API key</label><input id="bkey" placeholder="apg_…" autocomplete="off"><div class="btns"><button class="btn" id="checkbal">Check</button></div><p id="balout"></p></div>
<div class="card"><h3>Add credits</h3>
${stripeEnabled(env) ? `<label for="tkey">API key</label><input id="tkey" placeholder="apg_…" autocomplete="off"><label for="pack">Pack</label><select id="pack">${packs}</select><div class="btns"><button class="btn primary" id="buy">Pay with card</button></div>` : `<p>Card top-ups are coming soon.${x402Enabled(env) ? " You can already pay per call with USDC over x402." : ""}</p>`}
</div></div>
<script>
async function bal(){var k=document.getElementById('bkey').value.trim();var o=document.getElementById('balout');var r=await fetch('/v1/balance',{headers:{authorization:'Bearer '+k}});var d=await r.json();o.textContent=r.ok?('Balance: '+d.balance):(d.error&&d.error.message||'Error');}
document.getElementById('checkbal').addEventListener('click',bal);
var buy=document.getElementById('buy');if(buy)buy.addEventListener('click',async function(){var k=document.getElementById('tkey').value.trim();var r=await fetch('/billing/checkout',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({api_key:k,pack:document.getElementById('pack').value})});var d=await r.json();if(d.url)location.href=d.url;else alert(d.error||'Could not start checkout');});
</script>`;
  return layout(env, "AIPayGen billing", body, "Check your AIPayGen credit balance and add credits.");
}

export function docsPage(env: Env): string {
  const sections = TOOLS.map(
    (t) => `<h2 id="${t.name}"><code>${t.name}</code></h2><p>${esc(t.description)}</p><p class="muted small">Price ${formatPrice(t.priceMicro)} · cached up to ${Math.round(t.cacheTtl / 60)} min</p>
<pre><code>GET ${esc(env.PUBLIC_URL)}/v1/${t.name}?${esc(new URLSearchParams(Object.entries(t.example).map(([k, v]) => [k, String(v)])).toString())}</code></pre>
<details><summary class="small">Input schema</summary><pre><code>${esc(JSON.stringify(toolJsonSchema(t), null, 2))}</code></pre></details>`,
  ).join("");
  const body = `<h1>API docs</h1>
<p class="lead">Every tool works over MCP (<code>${esc(env.PUBLIC_URL)}/mcp</code>) and HTTP (<code>GET</code> with query parameters or <code>POST</code> with a JSON body to <code>/v1/&lt;tool&gt;</code>).</p>
<h2>Authentication and payment</h2>
<p>Send <code>Authorization: Bearer apg_…</code> to pay from prepaid credits. Create a key with <code>POST /v1/keys</code>.${x402Enabled(env) ? " Without a key, paid endpoints answer <code>402 Payment Required</code> with a <code>PAYMENT-REQUIRED</code> header (x402 v2). Retry with a <code>PAYMENT-SIGNATURE</code> header; the receipt comes back in <code>PAYMENT-RESPONSE</code>. Over MCP, the payment goes in <code>_meta[\"x402/payment\"]</code>." : ""}</p>
<p>Successful responses look like <code>{"tool": "...", "data": {...}, "receipt": {...}}</code>. Errors look like <code>{"error": {"code": "...", "message": "..."}}</code>.</p>
${sections}`;
  return layout(env, "AIPayGen API docs", body, "API reference for AIPayGen Site Intel tools.");
}

export function llmsTxt(env: Env): string {
  return `# AIPayGen Site Intel

> Pay-per-call website and company intelligence for AI agents: DNS, domain registration (RDAP), certificates and subdomains, tech stack, email security, security headers, page-to-markdown, and combined company profiles. Public data only. Failed calls are never charged.

- MCP endpoint (Streamable HTTP): ${env.PUBLIC_URL}/mcp
- HTTP API: ${env.PUBLIC_URL}/v1/<tool> (GET query params or POST JSON)
- Tool catalog (JSON): ${env.PUBLIC_URL}/v1/tools
- OpenAPI: ${env.PUBLIC_URL}/openapi.json
- Free API key with trial credits: POST ${env.PUBLIC_URL}/v1/keys
- Auth: Authorization: Bearer apg_...${x402Enabled(env) ? `\n- x402: unauthenticated calls return 402 with x402 v2 requirements (USDC, ${env.X402_NETWORK})` : ""}

## Tools

${TOOLS.map((t) => `- ${t.name} (${formatPrice(t.priceMicro)}): ${t.description}`).join("\n")}
`;
}

export function openApi(env: Env): Record<string, unknown> {
  const paths: Record<string, unknown> = {};
  for (const t of TOOLS) {
    const schema = toolJsonSchema(t) as { properties?: Record<string, unknown>; required?: string[] };
    paths[`/v1/${t.name}`] = {
      get: {
        operationId: t.name,
        summary: t.title,
        description: `${t.description} Price: ${formatPrice(t.priceMicro)} per call.`,
        parameters: Object.entries(schema.properties ?? {}).map(([name, s]) => ({
          name,
          in: "query",
          required: schema.required?.includes(name) ?? false,
          schema: s,
        })),
        responses: {
          "200": { description: "Success", content: { "application/json": { schema: { type: "object" } } } },
          "402": { description: "Payment required (x402 v2 or insufficient credits)" },
          "400": { description: "Invalid input" },
        },
        "x-price-usd": t.priceMicro / 1_000_000,
      },
      post: {
        operationId: `${t.name}_post`,
        summary: t.title,
        requestBody: { required: true, content: { "application/json": { schema, example: t.example } } },
        responses: { "200": { description: "Success" }, "402": { description: "Payment required" } },
        "x-price-usd": t.priceMicro / 1_000_000,
      },
    };
  }
  return {
    openapi: "3.1.0",
    info: { title: SERVICE_NAME, version: APP_VERSION, description: "Pay-per-call website and company intelligence for AI agents." },
    servers: [{ url: env.PUBLIC_URL }],
    components: { securitySchemes: { apiKey: { type: "http", scheme: "bearer", bearerFormat: "apg_..." } } },
    security: [{ apiKey: [] }],
    paths,
  };
}

/** MCP server card (SEP-1649 style) for clients and registries that probe /.well-known. */
export function serverCard(env: Env): Record<string, unknown> {
  return {
    name: "com.aipaygen/site-intel",
    title: SERVICE_NAME,
    version: APP_VERSION,
    description: "Pay-per-call website and company intelligence: DNS, RDAP, certificates, tech stack, email security, company profiles.",
    websiteUrl: env.PUBLIC_URL,
    remotes: [{ type: "streamable-http", url: `${env.PUBLIC_URL}/mcp` }],
    authentication: { type: "bearer", description: "Optional API key (apg_...). Without one, paid tools use x402 when enabled." },
    tools: TOOLS.map((t) => ({ name: t.name, title: t.title, description: t.description, priceUSD: t.priceMicro / 1_000_000 })),
  };
}
