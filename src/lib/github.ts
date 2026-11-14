import type { Env } from "../env";

/**
 * Opens an issue on GITHUB_ALERT_REPO (owner alerts). Needs GITHUB_ALERT_TOKEN
 * (fine-grained, Issues: write). Returns null on success, else why it didn't.
 */
export async function openIssue(env: Env, title: string, body: string, label: string): Promise<string | null> {
  if (!env.GITHUB_ALERT_TOKEN || !env.GITHUB_ALERT_REPO) return "no GITHUB_ALERT_TOKEN";
  const post = (b: object) => fetch(`https://api.github.com/repos/${env.GITHUB_ALERT_REPO}/issues`, {
    method: "POST",
    headers: { authorization: `Bearer ${env.GITHUB_ALERT_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "AIPayGenBot", "content-type": "application/json" },
    body: JSON.stringify(b),
    signal: AbortSignal.timeout(10_000),
  });
  let res = await post({ title, body, labels: [label] });
  // Fine-grained tokens with only Issues: write may not be allowed to create a new label; retry without it.
  if (res.status === 403 || res.status === 422) res = await post({ title, body });
  if (res.ok) return null;
  const why = ((await res.json().catch(() => ({}))) as { message?: string }).message ?? "";
  return `github ${res.status} ${why}`.trim().slice(0, 200);
}
