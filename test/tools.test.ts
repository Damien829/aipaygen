import { describe, expect, it } from "vitest";
import { detectDnsProvider, detectMailProvider, unquoteTxt } from "../src/tools/dns";
import { gradeEmailSecurity } from "../src/tools/emailsec";
import { gradeHeaders } from "../src/tools/headers";
import { detectTech, isCloudflareIp } from "../src/tools/tech";
import { summarizeCerts } from "../src/tools/certs";
import { summarizeRdap } from "../src/tools/whois";
import { extractMetadata, htmlToMarkdown } from "../src/tools/page";
import { deriveSignals } from "../src/tools/composite";
import { TOOLS } from "../src/tools";

describe("dns helpers", () => {
  it("joins split TXT strings", () => expect(unquoteTxt('"v=spf1 include:a.com " "-all"')).toBe("v=spf1 include:a.com -all"));
  it("detects providers", () => {
    expect(detectMailProvider(["aspmx.l.google.com"])).toBe("Google Workspace");
    expect(detectMailProvider(["contoso-com.mail.protection.outlook.com"])).toBe("Microsoft 365");
    expect(detectMailProvider([])).toBeNull();
    expect(detectDnsProvider(["ns1.cloudflare.com"])).toBe("Cloudflare");
    expect(detectDnsProvider(["ns-1.awsdns-01.org"])).toBe("Amazon Route 53");
  });
});

describe("email security grading", () => {
  const base = { mx: ["aspmx.l.google.com"], txt: [], dmarc: [], dkimSelectors: [], mtaSts: [], tlsRpt: [], bimi: [] };

  it("fails an unprotected domain", () => {
    const r = gradeEmailSecurity("x.com", base);
    expect(r.grade).toBe("F");
    expect(r.spoofable).toBe(true);
    expect(r.email_provider).toBe("Google Workspace");
  });

  it("gives A to a fully protected domain", () => {
    const r = gradeEmailSecurity("x.com", {
      ...base,
      txt: ["v=spf1 include:_spf.google.com -all"],
      dmarc: ["v=DMARC1; p=reject; rua=mailto:d@x.com"],
      dkimSelectors: ["google"],
      mtaSts: ["v=STSv1; id=1"],
      tlsRpt: ["v=TLSRPTv1; rua=mailto:t@x.com"],
    });
    expect(r.grade).toBe("A");
    expect(r.spoofable).toBe(false);
    expect(r.dmarc?.policy).toBe("reject");
  });

  it("flags p=none and multiple SPF records", () => {
    const r = gradeEmailSecurity("x.com", { ...base, txt: ["v=spf1 -all", "v=spf1 ~all"], dmarc: ["v=DMARC1; p=none"] });
    expect(r.spoofable).toBe(true);
    expect(r.issues.join(" ")).toMatch(/Multiple SPF/);
    expect(r.issues.join(" ")).toMatch(/"none"/);
  });
});

describe("security headers grading", () => {
  it("grades a hardened site highly", () => {
    const h = new Headers({
      "strict-transport-security": "max-age=31536000; includeSubDomains",
      "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
      "x-content-type-options": "nosniff",
      "referrer-policy": "strict-origin",
      "permissions-policy": "camera=()",
      "cross-origin-opener-policy": "same-origin",
    });
    const r = gradeHeaders(h, "https://x.com/");
    expect(r.grade).toBe("A");
    expect(r.headers["x-frame-options"]).toMatch(/frame-ancestors/);
  });
  it("caps plain-http sites", () => {
    const r = gradeHeaders(new Headers({ server: "Apache/2.4.1" }), "http://x.com/");
    expect(r.grade).toBe("F");
    expect(r.issues.join(" ")).toMatch(/Version information/);
  });
});

describe("tech detection", () => {
  it("finds frameworks, implied libraries, hosting and analytics", () => {
    const html = `<html><head><meta name="generator" content="WordPress 6.6"><script src="https://www.googletagmanager.com/gtag/js?id=G-1"></script>
      <script src="https://js.stripe.com/v3"></script></head><body><div id="__next"></div><script id="__NEXT_DATA__">{}</script>
      <link href="/wp-content/themes/x.css"></body></html>`;
    const names = detectTech(html, new Headers({ server: "nginx/1.25", "x-vercel-id": "1" })).map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["Next.js", "React", "WordPress", "PHP", "Google Analytics", "Stripe", "Nginx", "Vercel"]));
  });
  it("only flags WooCommerce from its plugin files", () => {
    expect(detectTech('<a data-label="hero_carousel__woocommerce">Woo</a>', new Headers()).map((t) => t.name)).not.toContain("WooCommerce");
    expect(detectTech('<link href="/wp-content/plugins/woocommerce/style.css">', new Headers()).map((t) => t.name)).toContain("WooCommerce");
  });
  it("recognizes Cloudflare IP ranges", () => {
    expect(isCloudflareIp("104.21.41.248")).toBe(true);
    expect(isCloudflareIp("172.67.167.212")).toBe(true);
    expect(isCloudflareIp("2606:4700:3032::6815:29f8")).toBe(true);
    expect(isCloudflareIp("140.82.112.3")).toBe(false);
    expect(isCloudflareIp("8.8.8.8")).toBe(false);
  });
  it("returns nothing for a bare page", () => expect(detectTech("<html><body>hi</body></html>", new Headers())).toEqual([]));
  it("does not mistake an embedded Shopify image for a store", () => {
    const names = detectTech('<img src="https://cdn.shopify.com/static/logo.png">', new Headers()).map((t) => t.name);
    expect(names).not.toContain("Shopify");
    expect(detectTech('<div class="shopify-section"></div>', new Headers()).map((t) => t.name)).toContain("Shopify");
  });
});

describe("certificate summary", () => {
  it("collects subdomains and the current cert", () => {
    const future = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 19);
    const past = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 19);
    const r = summarizeCerts("x.com", [
      { issuer: "Let's Encrypt", names: ["x.com", "*.x.com", "api.x.com"], not_before: past, not_after: future },
      { issuer: "Let's Encrypt", names: ["mail.x.com", "evil.com"], not_before: past, not_after: future },
    ]);
    expect(r.subdomains).toEqual(["api.x.com", "mail.x.com", "x.com"]);
    expect(r.current_certificate?.days_remaining).toBeGreaterThanOrEqual(29);
    expect(r.issuers[0]).toEqual({ name: "Let's Encrypt", count: 2 });
  });
});

describe("RDAP summary", () => {
  it("extracts registrar and dates", () => {
    const r = summarizeRdap("x.com", {
      status: ["client transfer prohibited"],
      events: [
        { eventAction: "registration", eventDate: "2010-01-01T00:00:00Z" },
        { eventAction: "expiration", eventDate: "2099-01-01T00:00:00Z" },
      ],
      nameservers: [{ ldhName: "NS1.EXAMPLE.COM" }],
      entities: [{ roles: ["registrar"], vcardArray: ["vcard", [["fn", {}, "text", "Example Registrar"]]], publicIds: [{ type: "IANA Registrar ID", identifier: "9999" }] }],
    });
    expect(r.registrar).toBe("Example Registrar");
    expect(r.registrar_iana_id).toBe("9999");
    expect(r.nameservers).toEqual(["ns1.example.com"]);
    expect(r.age_days).toBeGreaterThan(5000);
  });
});

describe("page parsing", () => {
  const html = `<html lang="en"><head><title>Acme | Rockets</title><meta name="description" content="We build rockets.">
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme Inc","sameAs":["https://github.com/acme"],"address":{"addressLocality":"Austin","addressCountry":"US"}}</script></head>
    <body><nav><a href="/">Home</a></nav><main><h1>Rockets</h1><p>Fast <strong>rockets</strong>. Email sales@acme.com</p><a href="/pricing">Pricing</a><a href="/careers">Jobs</a>
    <a href="https://twitter.com/acme">X</a><a href="https://twitter.com/intent/tweet?text=x">share</a><a href="mailto:hi@acme.com">mail</a></main><footer>footer junk</footer></body></html>`;

  it("extracts metadata", () => {
    const m = extractMetadata(html, "https://acme.com/");
    expect(m.title).toBe("Acme | Rockets");
    expect(m.language).toBe("en");
    expect(m.social_profiles).toEqual({ x: "https://twitter.com/acme", github: "https://github.com/acme" });
    expect(m.emails).toEqual(expect.arrayContaining(["hi@acme.com", "sales@acme.com"]));
    expect(m.key_pages.pricing).toBe("https://acme.com/pricing");
    expect(m.key_pages.careers).toBe("https://acme.com/careers");
    expect(m.organization?.name).toBe("Acme Inc");
    expect(m.organization?.address).toBe("Austin, US");
  });

  it("converts main content to markdown without nav/footer", () => {
    const r = htmlToMarkdown(html, "https://acme.com/", 10_000);
    expect(r.markdown).toContain("# Rockets");
    expect(r.markdown).toContain("**rockets**");
    expect(r.markdown).toContain("(https://acme.com/pricing)");
    expect(r.markdown).not.toContain("footer junk");
    expect(r.markdown).not.toContain("Home");
  });

  it("truncates", () => expect(htmlToMarkdown(`<main><p>${"word ".repeat(2000)}</p></main>`, "https://a.com/", 1000).truncated).toBe(true));
});

describe("signals", () => {
  it("derives business signals", () => {
    const s = deriveSignals({ techNames: ["Stripe", "Intercom"], keyPages: { pricing: "x", careers: "y" }, domainAgeDays: 100, emailProvider: "Google Workspace", socials: {} });
    expect(s).toEqual(expect.arrayContaining(["Takes online payments", "Offers live chat support", "Has a careers page (may be hiring)"]));
    expect(s.join(" ")).toMatch(/under a year/);
  });
});

describe("tool registry", () => {
  it("has unique names, prices and valid examples", () => {
    expect(new Set(TOOLS.map((t) => t.name)).size).toBe(TOOLS.length);
    for (const t of TOOLS) {
      // Free on purpose: discovery helps agents find the paid tools.
      if (["search_marketplace", "register_agent", "find_tool"].includes(t.name)) expect(t.priceMicro).toBe(0);
      else expect(t.priceMicro).toBeGreaterThan(0);
      expect(t.description.length).toBeGreaterThan(40);
      expect(t.input.safeParse(t.example).success).toBe(true);
    }
  });
});

describe("admin auth", () => {
  it("accepts only the exact bearer token", async () => {
    const { isAdmin } = await import("../src/admin");
    const env = { ADMIN_TOKEN: "s3cret-token" };
    expect(await isAdmin(env, "Bearer s3cret-token")).toBe(true);
    expect(await isAdmin(env, "Bearer s3cret-toke")).toBe(false);
    expect(await isAdmin(env, "s3cret-token")).toBe(false);
    expect(await isAdmin(env, undefined)).toBe(false);
    expect(await isAdmin({ ADMIN_TOKEN: undefined }, "Bearer undefined")).toBe(false);
    expect(await isAdmin({ ADMIN_TOKEN: "" }, "Bearer ")).toBe(false);
  }, 30_000); // first import of the admin module is slow on older Macs
});

import { describeSymbol, summarizeForecast, type MetForecast } from "../src/tools/weather";
import { cleanTranslation } from "../src/tools/translate";

describe("weather", () => {
  it("describes MET symbol codes", () => {
    expect(describeSymbol("clearsky_day")).toBe("Clear");
    expect(describeSymbol("partlycloudy_night")).toBe("Partly cloudy");
    expect(describeSymbol("lightrainshowersandthunder_day")).toBe("Light rain showers and thunder");
    expect(describeSymbol("lightssleetshowersandthunder_day")).toBe("Light sleet showers and thunder");
    expect(describeSymbol("heavysnow")).toBe("Heavy snow");
    expect(describeSymbol(undefined)).toBeNull();
  });
  it("summarizes a forecast", () => {
    const step = (time: string, t: number, sym: string, mm: number) => ({
      time, data: { instant: { details: { air_temperature: t, wind_speed: 4, wind_from_direction: 270, relative_humidity: 60 } }, next_1_hours: { summary: { symbol_code: sym }, details: { precipitation_amount: mm } } },
    });
    const f: MetForecast = { properties: { meta: { updated_at: "2026-11-13T12:00:00Z" }, timeseries: [
      step("2026-11-13T12:00:00Z", 20, "rain", 1.2), step("2026-11-13T13:00:00Z", 22, "rain", 0.8), step("2026-11-14T12:00:00Z", 15, "clearsky_day", 0),
    ] } };
    const s = summarizeForecast(f, 0);
    expect(s.current).toMatchObject({ conditions: "Rain", temperature_c: 20, temperature_f: 68, wind_from: "W", wind_mph: 9 });
    expect(s.next_hours).toHaveLength(3);
    expect(s.daily[0]).toMatchObject({ date: "2026-11-13", min_c: 20, max_c: 22, precipitation_mm: 2, conditions: "Rain" });
    expect(s.daily[1]).toMatchObject({ date: "2026-11-14", conditions: "Clear" });
  });
});

describe("translate", () => {
  it("strips wrappers models add", () => {
    expect(cleanTranslation("<think>hmm</think>Hola")).toBe("Hola");
    expect(cleanTranslation("Here is the translation: ¿Dónde está?")).toBe("¿Dónde está?");
    expect(cleanTranslation("<text>Bonjour</text>")).toBe("Bonjour");
    expect(cleanTranslation("¿Dónde está la estación de tren!", "Where is the train station?")).toBe("¿Dónde está la estación de tren?");
    expect(cleanTranslation("Hola.", "Hello.")).toBe("Hola.");
    expect(cleanTranslation("こんにちは。", "Hello.")).toBe("こんにちは。");
  });
});

import { matchScore, ownItem, ownMatches } from "../src/owntools";

describe("own tools in marketplace search", () => {
  const env = { PUBLIC_URL: "https://aipaygen.com" };
  it("finds our tools by name and synonyms", () => {
    expect(ownMatches(env, "weather")[0]?.url).toBe("https://aipaygen.com/v1/weather");
    expect(ownMatches(env, "weather forecast api")[0]?.meta.tool).toBe("weather");
    expect(ownMatches(env, "translation")[0]?.meta.tool).toBe("translate");
    expect(ownMatches(env, "translate text between languages")[0]?.meta.tool).toBe("translate");
    expect(ownMatches(env, "dmarc spf")[0]?.meta.tool).toBe("email_security");
    expect(ownMatches(env, "whois")[0]?.meta.tool).toBe("domain_whois");
    expect(ownMatches(env, "translate text").map((i) => i.meta.tool)).toEqual(["translate"]);
    expect(ownMatches(env, "dns whois").map((i) => i.meta.tool).sort()).toEqual(["dns_lookup", "domain_whois"]);
  });
  it("stays out of unrelated searches and skips free helpers", () => {
    expect(ownMatches(env, "postgres mcp server")).toEqual([]);
    expect(ownMatches(env, "car rental")).toEqual([]);
    expect(ownMatches(env, "image generation")[0]?.meta.tool).toBe("generate_image");
    expect(ownMatches(env, "search marketplace").some((i) => i.meta.tool === "search_marketplace")).toBe(false);
    expect(matchScore("the api", "anything")).toBe(0);
  });
  it("resolves market page ids", () => {
    expect(ownItem(env, "aipaygen-dns-lookup")?.name).toBe("DNS lookup (AIPayGen)");
    expect(ownItem(env, "aipaygen-search-marketplace")).toBeNull();
    expect(ownItem(env, "aipaygen-nope")).toBeNull();
  });
});

describe("find_tool ranking", () => {
  const base = { id: "api:x", kind: "api" as const, name: "x", description: "", url: "https://x", meta: "{}", x402: 1, checks_total: 0, checks_ok: 0, latency_ms: null, verified: 0, price_micro: null };
  it("prefers verified, healthy, cheap options over raw relevance", async () => {
    const { scoreCandidate } = await import("../src/router");
    const flaky = scoreCandidate({ ...base, checks_total: 10, checks_ok: 3, latency_ms: 4000, price_micro: 50_000 }, 0, 1_000);
    const solid = scoreCandidate({ ...base, verified: 1, checks_total: 10, checks_ok: 10, latency_ms: 200, price_micro: 1_000 }, 5, 1_000);
    expect(solid.score).toBeGreaterThan(flaky.score);
    expect(solid.reasons).toContain("cheapest published price among matches");
  });
  it("keeps unchecked options in the middle", async () => {
    const { scoreCandidate } = await import("../src/router");
    const unchecked = scoreCandidate(base, 0, null).score;
    const down = scoreCandidate({ ...base, checks_total: 10, checks_ok: 0 }, 0, null).score;
    const up = scoreCandidate({ ...base, verified: 1, checks_total: 10, checks_ok: 10 }, 0, null).score;
    expect(unchecked).toBeGreaterThan(down);
    expect(up).toBeGreaterThan(unchecked);
  });
});

import { parseJsonObject } from "../src/lib/llm";
import { classifyText, extractData, parseFields, summarize } from "../src/tools/ai";
import { parseArxiv } from "../src/tools/data";
import { expandIPv6, osvEcosystem, reverseName, summarizeVuln } from "../src/tools/devtools";

const fakeAi = (reply: string) => ({ AI: { run: async () => ({ response: reply }) } }) as never;

describe("AI text tools", () => {
  it("pulls JSON out of chatty replies", () => {
    expect(parseJsonObject('Sure! ```json\n{"a": "x}", "b": {"c": 1}}\n``` done')).toEqual({ a: "x}", b: { c: 1 } });
    expect(parseJsonObject("no json here")).toBeNull();
    expect(parseJsonObject("[1,2]")).toBeNull();
  });
  it("normalizes field specs", () => {
    expect(parseFields(["Company Name", "price: in USD", " :x"])).toEqual([
      { key: "company_name", hint: null },
      { key: "price", hint: "in USD" },
    ]);
  });
  it("extracts only the requested keys", async () => {
    const r = await extractData.run({ text: "Acme raised $5M", fields: ["company", "amount"] }, { env: fakeAi('{"company":"Acme","amount":"$5M","extra":1}') });
    expect(r.data).toEqual({ company: "Acme", amount: "$5M" });
    expect(r.fields_found).toBe(2);
  });
  it("keeps classify labels to the allowed set", async () => {
    const r = await classifyText.run({ text: "charged twice", labels: ["Billing", "Bug"] }, { env: fakeAi('{"labels":["billing"],"confidence":0.93,"reason":"payment"}') });
    expect(r.label).toBe("Billing");
    expect(r.confidence).toBe(0.93);
    await expect(classifyText.run({ text: "x" }, { env: fakeAi('{"labels":["angry"]}') })).rejects.toThrow(/valid label/);
  });
  it("summarizes into bullets", async () => {
    const r = await summarize.run({ text: "long text" }, { env: fakeAi("Here is the summary:\n- one\n- two") });
    expect(r.bullets).toEqual(["one", "two"]);
    await expect(summarize.run({}, { env: fakeAi("x") })).rejects.toThrow(/text or url/);
  });
});

describe("data and dev tool helpers", () => {
  it("parses arXiv feeds", () => {
    const xml = `<feed><opensearch:totalResults>42</opensearch:totalResults><entry><id>http://arxiv.org/abs/2601.1v1</id><title>A &amp; B
      paper</title><published>2026-01-01T00:00:00Z</published><summary> Abs </summary><author><name>Ann Lee</name></author><author><name>Bo</name></author>
      <link href="https://arxiv.org/pdf/2601.1v1" rel="related" type="application/pdf" title="pdf"/><category term="cs.AI" scheme="x"/></entry></feed>`;
    const { total, papers } = parseArxiv(xml);
    expect(total).toBe(42);
    expect(papers[0]).toMatchObject({ title: "A & B paper", authors: ["Ann Lee", "Bo"], abstract: "Abs", url: "https://arxiv.org/abs/2601.1v1", pdf: "https://arxiv.org/pdf/2601.1v1", categories: ["cs.AI"] });
  });
  it("maps package ecosystems", () => {
    expect(osvEcosystem("python")).toBe("PyPI");
    expect(osvEcosystem("Cargo")).toBe("crates.io");
    expect(() => osvEcosystem("cobol")).toThrow(/Unknown ecosystem/);
  });
  it("summarizes OSV advisories", () => {
    const v = summarizeVuln(
      { id: "GHSA-1", aliases: ["CVE-2020-1"], summary: "ReDoS", database_specific: { severity: "MODERATE" }, affected: [{ package: { name: "lodash" }, ranges: [{ events: [{ introduced: "4.0.0" }, { fixed: "4.17.21" }] }] }] },
      "lodash",
    );
    expect(v).toMatchObject({ cve: "CVE-2020-1", severity: "MODERATE", fixed_in: ["4.17.21"] });
  });
  it("builds reverse-DNS names", () => {
    expect(reverseName("8.8.8.8")).toBe("8.8.8.8.in-addr.arpa");
    expect(expandIPv6("2001:db8::1")).toBe("2001:0db8:0000:0000:0000:0000:0000:0001");
    expect(reverseName("2001:db8::1")?.startsWith("1.0.0.0.0.0.0.0")).toBe(true);
    expect(expandIPv6("1::2::3")).toBeNull();
    expect(expandIPv6("hello")).toBeNull();
  });
  it("finds the new tools in marketplace search", () => {
    const env = { PUBLIC_URL: "https://aipaygen.com" };
    expect(ownMatches(env, "exchange rates")[0]?.meta.tool).toBe("currency_convert");
    expect(ownMatches(env, "npm vulnerability")[0]?.meta.tool).toBe("package_vulns");
    expect(ownMatches(env, "sentiment analysis")[0]?.meta.tool).toBe("classify_text");
    expect(ownMatches(env, "unshorten url")[0]?.meta.tool).toBe("redirect_check");
    expect(ownMatches(env, "arxiv papers")[0]?.meta.tool).toBe("paper_search");
  });
});

import { chainOf, decodeAbiString, formatUnits, tokenRisks } from "../src/tools/crypto";

describe("crypto helpers", () => {
  it("formats token units", () => {
    expect(formatUnits(1_234_500n, 6)).toBe("1.2345");
    expect(formatUnits(10n ** 18n, 18)).toBe("1");
    expect(formatUnits(0n, 6)).toBe("0");
  });
  it("resolves chains by name, alias and id", () => {
    expect(chainOf("Base").id).toBe(8453);
    expect(chainOf("eth").key).toBe("ethereum");
    expect(chainOf("137").key).toBe("polygon");
    expect(() => chainOf("dogechain")).toThrow(/Unknown chain/);
  });
  it("decodes ABI strings and bytes32 symbols", () => {
    const abi = "0x" + "20".padStart(64, "0") + "4".padStart(64, "0") + Buffer.from("USDC").toString("hex").padEnd(64, "0");
    expect(decodeAbiString(abi)).toBe("USDC");
    expect(decodeAbiString("0x" + Buffer.from("MKR").toString("hex").padEnd(64, "0"))).toBe("MKR");
  });
  it("scores token risks", () => {
    expect(tokenRisks({ is_honeypot: "1", sell_tax: "0.99", is_open_source: "1" }).verdict).toBe("dangerous");
    expect(tokenRisks({ is_open_source: "1", buy_tax: "0", sell_tax: "0" })).toMatchObject({ verdict: "no red flags", score: 0 });
    expect(tokenRisks({ is_open_source: "1", is_mintable: "1" }).verdict).toBe("caution");
  });
  it("finds the new tools in search", () => {
    const env = { PUBLIC_URL: "https://aipaygen.com" };
    expect(ownMatches(env, "bitcoin price")[0]?.meta.tool).toBe("crypto_price");
    expect(ownMatches(env, "honeypot check")[0]?.meta.tool).toBe("token_security");
    expect(ownMatches(env, "speech to text").map((i) => i.meta.tool)).toContain("transcribe_audio");
    expect(ownMatches(env, "transcribe podcast")[0]?.meta.tool).toBe("transcribe_audio");
    expect(ownMatches(env, "ocr")[0]?.meta.tool).toBe("describe_image");
    expect(ownMatches(env, "domain availability")[0]?.meta.tool).toBe("domain_available");
  });
});

import { refFromRequest, shareBlock, shareLine } from "../src/share";
import { emailSyntax, textUtils } from "../src/tools/reference";

describe("referrals everywhere", () => {
  const env = { PUBLIC_URL: "https://aipaygen.com" } as never;
  it("reads ref from the URL or a header and rejects junk", () => {
    expect(refFromRequest(new Request("https://aipaygen.com/v1/weather?ref=AbC123xy"))).toBe("AbC123xy");
    expect(refFromRequest(new Request("https://aipaygen.com/mcp", { headers: { "x-aipaygen-ref": "Zz99Zz99" } }))).toBe("Zz99Zz99");
    expect(refFromRequest(new Request("https://aipaygen.com/?ref=<script>"))).toBeUndefined();
    expect(refFromRequest(undefined)).toBeUndefined();
  });
  it("puts the caller's own code in results, else the code they arrived with", () => {
    const mine = shareBlock(env, { yourCode: "MYCODE12", ref: "OTHER123" }) as Record<string, unknown>;
    expect(mine.get_a_key).toContain('"ref":"MYCODE12"');
    expect((mine.your_referral as { invite_link: string }).invite_link).toBe("https://aipaygen.com/?ref=MYCODE12");
    const passed = shareBlock(env, { ref: "OTHER123" }) as Record<string, unknown>;
    expect((passed.connect as { mcp: string }).mcp).toBe("https://aipaygen.com/mcp?ref=OTHER123");
    expect(passed.your_referral).toBeUndefined();
    expect(shareBlock(env).get_a_key).toContain("{}");
    expect(shareLine(env, { yourCode: "MYCODE12" })).toContain("MYCODE12");
  });
});

describe("reference helpers", () => {
  it("checks email syntax", () => {
    expect(emailSyntax("a.b+c@example.co.uk").ok).toBe(true);
    expect(emailSyntax("a..b@example.com").ok).toBe(false);
    expect(emailSyntax("nobody@").ok).toBe(false);
    expect(emailSyntax("x@localhost").ok).toBe(false);
  });
  it("runs text utilities offline", async () => {
    const env = {} as never;
    expect((await textUtils.run({ op: "sha256", text: "abc" }, { env })).hex).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect((await textUtils.run({ op: "base64_decode", text: (await textUtils.run({ op: "base64_encode", text: "héllo ✓" }, { env })).result as string }, { env })).result).toBe("héllo ✓");
    expect((await textUtils.run({ op: "slugify", text: "Crème Brûlée & Co!" }, { env })).result).toBe("creme-brulee-co");
    expect((await textUtils.run({ op: "json_format", text: "{bad" }, { env })).valid).toBe(false);
    expect((await textUtils.run({ op: "uuid", count: 3 }, { env })).uuids).toHaveLength(3);
  });
});

import { rowToDiscovery } from "../src/x402discovery";

describe("x402 discovery API", () => {
  it("maps a catalog row to the Bazaar item shape with payment terms and health", () => {
    const item = rowToDiscovery({
      id: "api:x402-abc", name: "example.com/paid", description: "Paid thing", url: "https://example.com/paid", price_micro: 2500,
      meta: JSON.stringify({ network: "eip155:8453", scheme: "exact", pay_to: "0x1111111111111111111111111111111111111111", method: "POST" }),
      checks_total: 4, checks_ok: 3, latency_ms: 210, verified: 1, checked_at: Date.UTC(2026, 10, 1), source: "x402-bazaar",
    });
    expect(item).toMatchObject({ resource: "https://example.com/paid", type: "http", x402Version: 2, lastUpdated: "2026-11-01T00:00:00.000Z" });
    expect(item.accepts[0]).toMatchObject({ amount: "2500", payTo: "0x1111111111111111111111111111111111111111", network: "eip155:8453" });
    expect(item.metadata).toMatchObject({ method: "POST", trust: { verified: true, uptime_pct: 75, checks: 4 } });
  });
  it("omits payment terms it doesn't know", () => {
    const item = rowToDiscovery({ id: "x", name: "n", description: "d", url: "https://e.com", price_micro: null, meta: "{}", checks_total: 0, checks_ok: 0, latency_ms: null, verified: 0, checked_at: 0, source: "seed" });
    expect(item.accepts).toEqual([]);
  });
});

import { convertUnits, countBusinessDays, decodeJwt, evalMath, findCountry, isoWeek, offsetMinutes, parseCsv, stats, toCsv, toXml, toYaml, zoneOf } from "../src/tools/utils";
import { readability } from "../src/tools/reference";

describe("utility tools", () => {
  it("decodes JWTs and flags risks", () => {
    const enc = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    const t = `${enc({ alg: "none" })}.${enc({ sub: "1", exp: 1000 })}.`;
    const r = decodeJwt(t, 2_000_000);
    expect(r.payload.sub).toBe("1");
    expect(r.expired).toBe(true);
    expect(r.warnings.join(" ")).toMatch(/unsigned/);
    expect(() => decodeJwt("nope")).toThrow(/isn't a JWT/);
  });
  it("parses and writes CSV, YAML and XML", () => {
    expect(parseCsv('a,b\n"x, y","he said ""hi"""\n')).toEqual([["a", "b"], ["x, y", 'he said "hi"']]);
    expect(toCsv([{ a: 1, b: "x,y" }, { a: 2, c: true }])).toBe('a,b,c\n1,"x,y",\n2,,true');
    expect(toYaml({ name: "Ada", tags: ["x", "y"], n: 3, flag: "yes" })).toBe('name: Ada\ntags:\n  - x\n  - y\nn: 3\nflag: "yes"');
    expect(toXml({ a: 1, list: [1, 2] })).toContain("<list>1</list>");
  });
  it("does date math", () => {
    const d = (s: string) => new Date(`${s}T00:00:00Z`);
    expect(countBusinessDays(d("2026-11-13"), d("2026-11-20"), new Set())).toBe(5); // Fri -> next Fri
    expect(countBusinessDays(d("2026-11-25"), d("2026-11-27"), new Set(["2026-11-26"]))).toBe(1);
    expect(isoWeek(d("2026-01-01"))).toBe(1);
  });
  it("handles time zones with DST", () => {
    expect(zoneOf("pst")).toBe("America/Los_Angeles");
    expect(offsetMinutes("America/New_York", new Date("2026-07-01T12:00:00Z"))).toBe(-240);
    expect(offsetMinutes("America/New_York", new Date("2026-12-01T12:00:00Z"))).toBe(-300);
    expect(() => zoneOf("Mars/Base")).toThrow(/Unknown time zone/);
  });
  it("finds countries", () => {
    expect(findCountry("jp")?.[2]).toBe("Japan");
    expect(findCountry("Germany")?.[0]).toBe("DE");
    expect(findCountry("BRA")?.[2]).toBe("Brazil");
  });
  it("evaluates math safely", () => {
    expect(evalMath("2+3*4")).toBe(14);
    expect(evalMath("2^3^2")).toBe(512);
    expect(evalMath("-(1+2)*sqrt(16)")).toBe(-12);
    expect(evalMath("max(1, 5, 3) + 10%")).toBeCloseTo(5.1);
    expect(() => evalMath("constructor.constructor('x')()")).toThrow();
    expect(() => evalMath("2+")).toThrow();
  });
  it("computes stats and converts units", () => {
    expect(stats([1, 2, 3, 4, 100])).toMatchObject({ count: 5, median: 3, mean: 22, min: 1, max: 100 });
    expect(convertUnits(100, "c", "f")).toBeCloseTo(212);
    expect(convertUnits(1, "mi", "km")).toBeCloseTo(1.609344);
    expect(() => convertUnits(1, "kg", "km")).toThrow(/Can't convert/);
  });
  it("scores readability", () => {
    const easy = readability("The cat sat on the mat. It was a good cat.");
    const hard = readability("Notwithstanding considerable organizational complexity, interdisciplinary collaboration necessitates comprehensive documentation.");
    expect(easy.flesch_reading_ease).toBeGreaterThan(hard.flesch_reading_ease);
  });
});

import { spreadHosts } from "../src/catalog";

describe("search diversity", () => {
  it("moves a host's 3rd+ results to the end of the page without dropping any", () => {
    const items = ["https://a.com/1", "https://a.com/2", "https://www.a.com/3", "https://b.com/1", null, "https://a.com/4"].map((url) => ({ url }));
    const out = spreadHosts(items, 2).map((i) => i.url);
    expect(out).toEqual(["https://a.com/1", "https://a.com/2", "https://b.com/1", null, "https://www.a.com/3", "https://a.com/4"]);
    expect(out).toHaveLength(items.length);
  });
});

describe("own-tool ranking prefers full name matches", () => {
  const env = { PUBLIC_URL: "https://aipaygen.com" };
  it("weather vs weather_alerts", () => {
    expect(ownMatches(env, "weather in paris")[0]?.meta.tool).toBe("weather");
    expect(ownMatches(env, "weather alerts in texas")[0]?.meta.tool).toBe("weather_alerts");
  });
});

describe("word-order phrases", () => {
  const env = { PUBLIC_URL: "https://aipaygen.com" };
  it("tells speech-to-text from text-to-speech", () => {
    expect(ownMatches(env, "speech to text")[0]?.meta.tool).toBe("transcribe_audio");
    expect(ownMatches(env, "text to speech")[0]?.meta.tool).toBe("text_to_speech");
    expect(ownMatches(env, "text to image")[0]?.meta.tool).toBe("generate_image");
  });
});
