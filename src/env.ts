export interface Env {
  DB: D1Database;
  /** Workers AI: free skill runtime (wrangler.jsonc "ai" binding). */
  AI?: Ai;
  TOOL_LIMITER?: RateLimit;
  KEY_LIMITER?: RateLimit;

  PUBLIC_URL: string;
  X402_NETWORK: string;
  FACILITATOR_URL: string;
  PAY_TO: string;
  /** When PAY_TO took effect (ISO time); payment reconciliation checks sales from then on. */
  PAY_TO_SINCE?: string;
  /** CDP Secret API key (Ed25519). When both are set, x402 settles through Coinbase's facilitator. */
  CDP_API_KEY_ID?: string;
  CDP_API_KEY_SECRET?: string;
  TRIAL_CREDITS_MICRO: string;

  ADMIN_TOKEN?: string;
  STRIPE_SECRET_KEY?: string;
  STRIPE_WEBHOOK_SECRET?: string;

  /** Core (v1 marketplace) origin behind the Cloudflare Tunnel, e.g. https://core.aipaygen.com. Unset: core routes are off. */
  CORE_ORIGIN?: string;
  /** Shared with the core's AIPAYGEN_EDGE_SECRET; signs every forwarded request. */
  CORE_EDGE_SECRET?: string;

  /** Runs marketplace skills (run_skill) and drafts skills from unmet demand. Secret; unset = skills off. */
  ANTHROPIC_API_KEY?: string;

  /** Facilitator settlement wallet (pays gas only). Secret; unset = facilitator off. */
  FACILITATOR_PRIVATE_KEY?: string;
  /** Separate fee wallet for Base mainnet (secret). Mainnet is served only when this is set. */
  FACILITATOR_MAINNET_KEY?: string;
  /** Optional: fine-grained GitHub token (Issues: write) for owner alerts, and the "owner/repo" to open them in. */
  GITHUB_ALERT_TOKEN?: string;
  GITHUB_ALERT_REPO?: string;
  /** Comma-separated CAIP-2 networks, e.g. "eip155:84532" or "eip155:8453,eip155:84532". */
  FACILITATOR_NETWORKS?: string;
  FACILITATOR_RPC_BASE?: string;
  FACILITATOR_RPC_BASE_SEPOLIA?: string;
}

export const APP_VERSION = "2.2.0";
export const SERVICE_NAME = "AIPayGen";
