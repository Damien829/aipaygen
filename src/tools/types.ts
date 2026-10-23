import type { z } from "zod";
import type { Env } from "../env";

export interface ToolContext {
  env: Env;
}

export interface ToolDef<I extends z.ZodObject = z.ZodObject> {
  name: string;
  title: string;
  description: string;
  /** Price per successful call in micro-USD (1_000_000 = $1). 0 = free. */
  priceMicro: number;
  /** Seconds a result may be served from cache. 0 disables caching. */
  cacheTtl: number;
  input: I;
  /** A realistic example input, used in docs and discovery metadata. */
  example: z.infer<I>;
  run(args: z.infer<I>, ctx: ToolContext): Promise<Record<string, unknown>>;
}

export function defineTool<I extends z.ZodObject>(def: ToolDef<I>): ToolDef<I> {
  return def;
}

export function formatPrice(micro: number): string {
  if (micro === 0) return "free";
  const usd = micro / 1_000_000;
  return `$${usd.toFixed(usd < 0.01 ? 3 : 2)}`;
}
