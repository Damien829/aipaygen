/**
 * AiPayGen JavaScript SDK v1.9.0
 *
 * 250 AI tools in one API. Pay per call via x402 (USDC on Base) or prepaid API key.
 *
 * npm install aipaygen
 *
 * Usage:
 *   const { AiPayGen } = require('aipaygen');
 *   const client = new AiPayGen('apk_your_key');
 *   const result = await client.call('research', { topic: 'quantum computing' });
 */

const https = require('https');
const http = require('http');
const { randomUUID } = require('crypto');

const DEFAULT_BASE_URL = 'https://aipaygen.com';
const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

// ── Custom Error ────────────────────────────────────────────────────────────

class AiPayGenError extends Error {
  /**
   * @param {string} message
   * @param {number} statusCode
   * @param {string} requestId
   * @param {*} body
   */
  constructor(message, statusCode = 0, requestId = null, body = null) {
    super(message);
    this.name = 'AiPayGenError';
    this.statusCode = statusCode;
    this.requestId = requestId;
    this.body = body;
  }
}

// ── Session Client ──────────────────────────────────────────────────────────

class SessionClient {
  /**
   * @param {AiPayGen} client
   * @param {string} sessionId
   */
  constructor(client, sessionId) {
    this._client = client;
    this.sessionId = sessionId;
  }

  /**
   * Call a tool within this session context.
   * @param {string} tool
   * @param {Object} input
   * @returns {Promise<Object>}
   */
  async call(tool, input = {}) {
    return this._client._post(`/session/${this.sessionId}/call`, { tool, input });
  }

  /**
   * Get the conversation history for this session.
   * @returns {Promise<Object>}
   */
  async history() {
    return this._client._get(`/session/${this.sessionId}/history`);
  }

  /**
   * End this session and release resources.
   * @returns {Promise<Object>}
   */
  async end() {
    return this._client._post(`/session/${this.sessionId}/end`, {});
  }
}

// ── Main Client ─────────────────────────────────────────────────────────────

class AiPayGen {
  /**
   * @param {string} apiKey - Prepaid API key (apk_xxx) or set AIPAYGEN_API_KEY env var
   * @param {string} [baseUrl] - Override base URL (default: https://aipaygen.com)
   */
  constructor(apiKey, baseUrl) {
    this.apiKey = apiKey || process.env.AIPAYGEN_API_KEY;
    this.baseUrl = (baseUrl || process.env.AIPAYGEN_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, '');
    this._cachedBalance = null;
    this._balanceFetchedAt = 0;
  }

  // ── Core Methods ────────────────────────────────────────────────────────

  /**
   * Call any tool by name.
   * @param {string} tool - Tool name (e.g. 'research', 'summarize', 'web_search')
   * @param {Object} input - Tool-specific input parameters
   * @returns {Promise<Object>}
   */
  async call(tool, input = {}) {
    // Map tool names to known endpoints
    const endpoint = this._resolveEndpoint(tool);
    return this._post(endpoint, input);
  }

  /**
   * Execute a multi-step chain of tool calls sequentially.
   * @param {Array<{tool: string, input: Object}>} steps
   * @returns {Promise<Object>}
   */
  async chain(steps) {
    return this._post('/chain', { steps });
  }

  /**
   * Execute multiple tool calls in parallel.
   * @param {Array<{tool: string, input: Object}>} calls
   * @returns {Promise<Object>}
   */
  async batch(calls) {
    return this._post('/batch', { calls });
  }

  /**
   * Create a stateful session for multi-turn conversations.
   * @returns {Promise<SessionClient>}
   */
  async session() {
    const result = await this._post('/session/create', {});
    return new SessionClient(this, result.session_id);
  }

  /**
   * Get usage statistics for this API key.
   * @returns {Promise<Object>}
   */
  async usage() {
    return this._get('/auth/status', { key: this.apiKey });
  }

  /**
   * Get cached balance (refreshes every 60s).
   * @returns {Promise<number|null>}
   */
  get balance() {
    return this._cachedBalance;
  }

  /**
   * Force-refresh the balance from the server.
   * @returns {Promise<number>}
   */
  async refreshBalance() {
    const status = await this.usage();
    this._cachedBalance = status.balance_usd ?? status.balance ?? null;
    this._balanceFetchedAt = Date.now();
    return this._cachedBalance;
  }

  // ── Convenience Methods ─────────────────────────────────────────────────

  /** Research any topic. $0.01 */
  research(topic, depth = 'standard') { return this.call('research', { topic, depth }); }

  /** Write content. $0.05 */
  write(prompt, style = 'professional') { return this.call('write', { prompt, style }); }

  /** Generate code. $0.05 */
  code(description, language = 'python') { return this.call('code', { description, language }); }

  /** Analyze content. $0.02 */
  analyze(content) { return this.call('analyze', { content }); }

  /** Summarize text. $0.01 */
  summarize(text, maxLength) { return this.call('summarize', { text, max_length: maxLength }); }

  /** Translate text. $0.02 */
  translate(text, target) { return this.call('translate', { text, target }); }

  /** Sentiment analysis. $0.01 */
  sentiment(text) { return this.call('sentiment', { text }); }

  /** Extract keywords. $0.01 */
  keywords(text) { return this.call('keywords', { text }); }

  /** Web search. $0.02 */
  search(query, n = 10) { return this.call('web_search', { query, n }); }

  /** Scrape website. $0.05 */
  scrape(url) { return this.call('scrape_web', { url }); }

  /** Vision: analyze image. $0.05 */
  vision(imageUrl, question) { return this.call('vision', { image_url: imageUrl, question }); }

  /** Weather (free). */
  weather(city) { return this._get('/data/weather', { city }); }

  /** Crypto prices (free). */
  crypto(symbol = 'bitcoin') { return this._get('/data/crypto', { symbol }); }

  /** Random joke (free). */
  joke() { return this._get('/data/joke'); }

  /** Inspirational quote (free). */
  quote() { return this._get('/data/quote'); }

  // ── Internal ────────────────────────────────────────────────────────────

  _resolveEndpoint(tool) {
    const map = {
      research: '/research',
      write: '/write',
      code: '/code',
      analyze: '/analyze',
      summarize: '/summarize',
      translate: '/translate',
      sentiment: '/sentiment',
      keywords: '/keywords',
      explain: '/explain',
      rewrite: '/rewrite',
      classify: '/classify',
      extract: '/extract',
      rag: '/rag',
      vision: '/vision',
      web_search: '/web/search',
      scrape_web: '/scrape/web',
      scrape_tweets: '/scrape/tweets',
      scrape_google_maps: '/scrape/google-maps',
      scrape_youtube: '/scrape/youtube',
      scrape_instagram: '/scrape/instagram',
      scrape_tiktok: '/scrape/tiktok',
      enrich: '/enrich',
      run_code: '/code/run',
      workflow: '/workflow',
      batch: '/batch',
      chain: '/chain',
    };
    return map[tool] || `/${tool}`;
  }

  _headers(requestId) {
    const h = {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
      'User-Agent': 'aipaygen-js/1.9.0',
    };
    if (this.apiKey) h['Authorization'] = `Bearer ${this.apiKey}`;
    return h;
  }

  /**
   * Make an HTTP request with auto-retry on 429.
   * @param {string} method
   * @param {string} path
   * @param {Object|null} body
   * @param {Object} [queryParams]
   * @param {number} [attempt]
   * @returns {Promise<Object>}
   */
  _request(method, path, body, queryParams, attempt = 0) {
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      if (queryParams) {
        Object.entries(queryParams).forEach(([k, v]) => {
          if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
        });
      }

      const isHttps = url.protocol === 'https:';
      const lib = isHttps ? https : http;
      const payload = body ? JSON.stringify(body) : null;
      const headers = this._headers(requestId);
      if (payload) headers['Content-Length'] = Buffer.byteLength(payload);

      const options = {
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + url.search,
        method,
        headers,
      };

      const req = lib.request(options, (res) => {
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          let parsed;
          try {
            parsed = JSON.parse(data);
          } catch {
            parsed = data;
          }

          // Auto-retry on 429 with exponential backoff
          if (res.statusCode === 429 && attempt < MAX_RETRIES) {
            const retryAfter = res.headers['retry-after'];
            const delay = retryAfter
              ? parseInt(retryAfter, 10) * 1000
              : BASE_DELAY_MS * Math.pow(2, attempt);
            setTimeout(() => {
              this._request(method, path, body, queryParams, attempt + 1)
                .then(resolve)
                .catch(reject);
            }, delay);
            return;
          }

          if (res.statusCode === 402) {
            reject(new AiPayGenError(
              'Payment required — add credits at https://aipaygen.com/buy-credits',
              402, requestId, parsed
            ));
          } else if (res.statusCode >= 400) {
            const msg = (parsed && parsed.error) || `HTTP ${res.statusCode}`;
            reject(new AiPayGenError(msg, res.statusCode, requestId, parsed));
          } else {
            resolve(parsed);
          }
        });
      });

      req.on('error', (err) => {
        reject(new AiPayGenError(err.message, 0, requestId));
      });

      req.setTimeout(30000, () => {
        req.destroy();
        reject(new AiPayGenError('Request timed out', 0, requestId));
      });

      if (payload) req.write(payload);
      req.end();
    });
  }

  _post(path, body) {
    return this._request('POST', path, body);
  }

  _get(path, queryParams) {
    return this._request('GET', path, null, queryParams);
  }
}

module.exports = { AiPayGen, AiPayGenError, SessionClient };
