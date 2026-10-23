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
}

export const APP_VERSION = "2.0.0";
export const SERVICE_NAME = "AIPayGen Site Intel";
