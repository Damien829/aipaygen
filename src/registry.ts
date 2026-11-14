import type { ToolDef } from "./tools/types";

/**
 * The paid tool list, registered by src/tools/index.ts when it loads.
 * Modules that tools/index itself imports (catalog.ts) read it from here, so
 * there's no import cycle and no lazy import. Lazy imports changed module start
 * order in the Worker bundle and broke zod at startup (2026-11-14).
 */
let tools: readonly ToolDef[] = [];

export function registerTools(list: readonly ToolDef[]): void {
  tools = list;
}

export function registeredTools(): readonly ToolDef[] {
  return tools;
}
