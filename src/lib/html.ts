import { parse, type HTMLElement } from "node-html-parser";

export function parseHtml(html: string): HTMLElement {
  return parse(html, { comment: false, blockTextElements: { script: true, style: true, noscript: true, pre: true } });
}

export function clean(s: string | undefined | null, max = 500): string | null {
  if (!s) return null;
  const t = s.replace(/\s+/g, " ").trim();
  return t ? t.slice(0, max) : null;
}

export function absolute(href: string | undefined, base: string): string | null {
  if (!href) return null;
  try {
    const u = new URL(href.trim(), base);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function metaContent(root: HTMLElement, key: string): string | null {
  const el =
    root.querySelector(`meta[name="${key}"]`) ??
    root.querySelector(`meta[property="${key}"]`) ??
    root.querySelector(`meta[name="${key.toLowerCase()}"]`);
  return clean(el?.getAttribute("content"));
}

/** Parse every JSON-LD block, flattening @graph arrays. Invalid blocks are skipped. */
export function jsonLd(root: HTMLElement): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  for (const s of root.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data = JSON.parse(s.textContent);
      const items = Array.isArray(data) ? data : [data];
      for (const item of items) {
        if (item && typeof item === "object") {
          if (Array.isArray(item["@graph"])) out.push(...item["@graph"].filter((g: unknown) => g && typeof g === "object"));
          else out.push(item);
        }
      }
    } catch {
      // ignore malformed JSON-LD
    }
  }
  return out;
}
