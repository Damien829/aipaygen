export interface Env {
  DB: D1Database;
  TOOL_LIMITER?: RateLimit;
  KEY_LIMITER?: RateLimit;

  PUBLIC_URL: string;
  X402_NETWORK: string;
  FACILITATOR_URL: string;
  PAY_TO: string;
  TRIAL_CREDITS_MICRO: string;

  ADMIN_TOKEN?: string;
  STRIPE_SECRET_KEY?: string;
  STRIPE_WEBHOOK_SECRET?: string;

  /** Core (v1 marketplace) origin behind the Cloudflare Tunnel, e.g. https://core.aipaygen.com. Unset: core routes are off. */
  CORE_ORIGIN?: string;
  /** Shared with the core's AIPAYGEN_EDGE_SECRET; signs every forwarded request. */
  CORE_EDGE_SECRET?: string;
}

export const APP_VERSION = "2.1.0";
export const SERVICE_NAME = "AIPayGen";
