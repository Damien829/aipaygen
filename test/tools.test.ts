import { describe, expect, it } from "vitest";
import { detectDnsProvider, detectMailProvider, unquoteTxt } from "../src/tools/dns";
import { gradeEmailSecurity } from "../src/tools/emailsec";
import { gradeHeaders } from "../src/tools/headers";
import { detectTech } from "../src/tools/tech";
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
    const names = detectTech(html, new Headers({ server: "cloudflare", "cf-ray": "1" })).map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["Next.js", "React", "WordPress", "PHP", "Google Analytics", "Stripe", "Cloudflare"]));
  });
  it("returns nothing for a bare page", () => expect(detectTech("<html><body>hi</body></html>", new Headers())).toEqual([]));
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
      expect(t.priceMicro).toBeGreaterThan(0);
      expect(t.description.length).toBeGreaterThan(40);
      expect(t.input.safeParse(t.example).success).toBe(true);
    }
  });
});
