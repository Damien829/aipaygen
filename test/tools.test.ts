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
    expect(ownMatches(env, "dns whois").map((i) => i.meta.tool).sort()).toEqual(["dns_lookup", "domain_report", "domain_whois"]); // domain_report does both
  });
  it("stays out of unrelated searches and skips free helpers", () => {
    expect(ownMatches(env, "postgres mcp server")).toEqual([]);
    expect(ownMatches(env, "image generation")).toEqual([]);
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
