/** An error whose message is safe to show to the caller. */
export class ToolError extends Error {
  constructor(
    message: string,
    readonly code: string = "TOOL_ERROR",
    readonly status: number = 400,
  ) {
    super(message);
    this.name = "ToolError";
  }
}

export function errorMessage(err: unknown): string {
  if (err instanceof ToolError) return err.message;
  if (err instanceof Error && err.name === "TimeoutError") return "The upstream source timed out.";
  return "Internal error.";
}
