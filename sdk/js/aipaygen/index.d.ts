/**
 * AiPayGen JavaScript/TypeScript SDK v1.9.0
 *
 * 250 AI tools in one API. Pay per call via x402 or prepaid API key.
 */

export class AiPayGenError extends Error {
  /** HTTP status code (0 for network errors). */
  statusCode: number;
  /** Unique request ID for debugging. */
  requestId: string | null;
  /** Raw response body. */
  body: any;
  constructor(message: string, statusCode?: number, requestId?: string | null, body?: any);
}

export class SessionClient {
  /** The session ID. */
  readonly sessionId: string;
  /** Call a tool within this session. */
  call(tool: string, input?: Record<string, any>): Promise<any>;
  /** Get conversation history for this session. */
  history(): Promise<any>;
  /** End this session and release resources. */
  end(): Promise<any>;
}

export class AiPayGen {
  /** The API key used for authentication. */
  apiKey: string;
  /** The base URL for API requests. */
  baseUrl: string;

  /**
   * Create a new AiPayGen client.
   * @param apiKey - Prepaid API key (apk_xxx) or set AIPAYGEN_API_KEY env var
   * @param baseUrl - Override base URL (default: https://aipaygen.com)
   */
  constructor(apiKey?: string, baseUrl?: string);

  // ── Core Methods ──────────────────────────────────────────────────────

  /** Call any tool by name. */
  call(tool: string, input?: Record<string, any>): Promise<any>;

  /** Execute a multi-step chain of tool calls sequentially. */
  chain(steps: Array<{ tool: string; input?: Record<string, any> }>): Promise<any>;

  /** Execute multiple tool calls in parallel. */
  batch(calls: Array<{ tool: string; input?: Record<string, any> }>): Promise<any>;

  /** Create a stateful session for multi-turn conversations. */
  session(): Promise<SessionClient>;

  /** Get usage statistics for this API key. */
  usage(): Promise<any>;

  /** Cached balance (call refreshBalance() to update). */
  readonly balance: number | null;

  /** Force-refresh the balance from the server. */
  refreshBalance(): Promise<number>;

  // ── Convenience Methods ───────────────────────────────────────────────

  /** Research any topic. $0.01 */
  research(topic: string, depth?: string): Promise<any>;

  /** Write content. $0.05 */
  write(prompt: string, style?: string): Promise<any>;

  /** Generate code. $0.05 */
  code(description: string, language?: string): Promise<any>;

  /** Analyze content. $0.02 */
  analyze(content: string): Promise<any>;

  /** Summarize text. $0.01 */
  summarize(text: string, maxLength?: number): Promise<any>;

  /** Translate text. $0.02 */
  translate(text: string, target: string): Promise<any>;

  /** Sentiment analysis. $0.01 */
  sentiment(text: string): Promise<any>;

  /** Extract keywords. $0.01 */
  keywords(text: string): Promise<any>;

  /** Web search. $0.02 */
  search(query: string, n?: number): Promise<any>;

  /** Scrape website. $0.05 */
  scrape(url: string): Promise<any>;

  /** Vision: analyze image. $0.05 */
  vision(imageUrl: string, question?: string): Promise<any>;

  /** Weather (free). */
  weather(city: string): Promise<any>;

  /** Crypto prices (free). */
  crypto(symbol?: string): Promise<any>;

  /** Random joke (free). */
  joke(): Promise<any>;

  /** Inspirational quote (free). */
  quote(): Promise<any>;
}
