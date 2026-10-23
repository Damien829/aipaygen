import { ToolError } from "./errors";

const USER_AGENT = "AIPayGenBot/2.0 (+https://aipaygen.com/bot)";
const MAX_BYTES = 2_000_000;
const DEFAULT_TIMEOUT_MS = 10_000;
const MAX_REDIRECTS = 5;

const BLOCKED_SUFFIXES = [".localhost", ".local", ".internal", ".home.arpa", ".lan", ".intranet", ".corp"];

/** Lowercase, strip scheme/path/port/trailing dot, and validate a domain name. */
export function normalizeDomain(input: string): string {
  let s = input.trim().toLowerCase();
  if (!s) throw new ToolError("A domain is required.", "INVALID_DOMAIN");
  if (s.includes("://")) {
    try {
      s = new URL(s).hostname;
    } catch {
      throw new ToolError(`"${input}" is not a valid domain.`, "INVALID_DOMAIN");
    }
  }
  s = s.split("/")[0]!.split("?")[0]!.split("#")[0]!;
  s = s.replace(/:\d+$/, "").replace(/\.$/, "");
  if (s.startsWith("www.")) s = s.slice(4);
  s = toAscii(s);
  if (!/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/.test(s)) {
    throw new ToolError(`"${input}" is not a valid public domain.`, "INVALID_DOMAIN");
  }
  assertPublicHostname(s);
  return s;
}

/** Normalize a URL, defaulting to https, and reject non-public targets. */
export function normalizeUrl(input: string): URL {
  let s = input.trim();
  if (!s) throw new ToolError("A URL is required.", "INVALID_URL");
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `https://${s}`;
  let url: URL;
  try {
    url = new URL(s);
  } catch {
    throw new ToolError(`"${input}" is not a valid URL.`, "INVALID_URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new ToolError("Only http and https URLs are supported.", "INVALID_URL");
  }
  if (url.username || url.password) throw new ToolError("URLs with credentials are not allowed.", "INVALID_URL");
  if (url.port && url.port !== "80" && url.port !== "443") {
    throw new ToolError("Only standard ports (80, 443) are allowed.", "INVALID_URL");
  }
  assertPublicHostname(url.hostname);
  url.hash = "";
  return url;
}

function toAscii(host: string): string {
  try {
    return new URL(`http://${host}`).hostname;
  } catch {
    return host;
  }
}

/** Reject localhost, private/reserved IP literals and internal-only names. */
export function assertPublicHostname(hostname: string): void {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (h === "localhost" || BLOCKED_SUFFIXES.some((s) => h.endsWith(s)) || !h.includes(".") && !h.includes(":")) {
    throw new ToolError("That host is not publicly reachable.", "BLOCKED_HOST");
  }
  if (isIPv4(h) && isPrivateIPv4(h)) throw new ToolError("Private or reserved IP addresses are not allowed.", "BLOCKED_HOST");
  if (h.includes(":") && isPrivateIPv6(h)) throw new ToolError("Private or reserved IP addresses are not allowed.", "BLOCKED_HOST");
}

export function isIPv4(h: string): boolean {
  return /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.test(h) && h.split(".").every((p) => Number(p) <= 255);
}

export function isPrivateIPv4(ip: string): boolean {
  const [a, b] = ip.split(".").map(Number) as [number, number, number, number];
  return (
    a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && (b === 168 || b === 0)) ||
    (a === 198 && (b === 18 || b === 19))
  );
}

export function isPrivateIPv6(ip: string): boolean {
  const h = ip.toLowerCase();
  if (h === "::" || h === "::1") return true;
  if (h.startsWith("::ffff:")) {
    const v4 = h.slice(7);
    return isIPv4(v4) ? isPrivateIPv4(v4) : true;
  }
  return /^(fc|fd|fe8|fe9|fea|feb|ff)/.test(h);
}

export interface FetchedPage {
  url: string;
  status: number;
  headers: Headers;
  body: string;
  redirects: string[];
  ms: number;
}

/**
 * Fetch a public web page with a timeout, a size cap and manual redirect
 * handling so every hop is re-checked against the public-host rules.
 */
export async function fetchPage(input: string | URL, opts: { timeoutMs?: number; method?: "GET" | "HEAD" } = {}): Promise<FetchedPage> {
  let url = typeof input === "string" ? normalizeUrl(input) : input;
  const redirects: string[] = [];
  const started = Date.now();
  const signal = AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
    let res: Response;
    try {
      res = await fetch(url.toString(), {
        method: opts.method ?? "GET",
        redirect: "manual",
        signal,
        headers: {
          "user-agent": USER_AGENT,
          accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "accept-language": "en-US,en;q=0.9",
        },
      });
    } catch (err) {
      if (err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError")) {
        throw new ToolError(`Timed out fetching ${url.hostname}.`, "UPSTREAM_TIMEOUT", 504);
      }
      throw new ToolError(`Could not connect to ${url.hostname}.`, "UPSTREAM_UNREACHABLE", 502);
    }

    if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
      await res.body?.cancel();
      const next = new URL(res.headers.get("location")!, url);
      redirects.push(next.toString());
      url = normalizeUrl(next.toString());
      continue;
    }

    const body = opts.method === "HEAD" ? "" : await readCapped(res, MAX_BYTES);
    return { url: url.toString(), status: res.status, headers: res.headers, body, redirects, ms: Date.now() - started };
  }
  throw new ToolError("Too many redirects.", "TOO_MANY_REDIRECTS", 502);
}

async function readCapped(res: Response, maxBytes: number): Promise<string> {
  if (!res.body) return "";
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      chunks.push(value.subarray(0, value.byteLength - (total - maxBytes)));
      break;
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(Math.min(total, maxBytes));
  let offset = 0;
  for (const c of chunks) {
    buf.set(c, offset);
    offset += c.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: false, ignoreBOM: false }).decode(buf);
}

/** Fetch JSON from a fixed, trusted upstream API (not user-controlled URLs). */
export async function fetchJson<T>(url: string, opts: { timeoutMs?: number; headers?: Record<string, string> } = {}): Promise<{ status: number; data: T | null }> {
  let res: Response;
  try {
    res = await fetch(url, {
      signal: AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS),
      headers: { "user-agent": USER_AGENT, accept: "application/json", ...opts.headers },
    });
  } catch (err) {
    if (err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new ToolError("An upstream data source timed out.", "UPSTREAM_TIMEOUT", 504);
    }
    throw new ToolError("An upstream data source is unreachable.", "UPSTREAM_UNREACHABLE", 502);
  }
  if (!res.ok) {
    await res.body?.cancel();
    return { status: res.status, data: null };
  }
  try {
    return { status: res.status, data: (await res.json()) as T };
  } catch {
    return { status: res.status, data: null };
  }
}
