/**
 * AiPayGent JavaScript SDK
 *
 * AI agent marketplace with 123 endpoints. Pay per call via x402 or prepaid API key.
 *
 * npm install aipaygent
 *
 * Usage:
 *   const { AiPayGent } = require('aipaygent');
 *   const client = new AiPayGent({ apiKey: 'apk_your_key' });
 *   const result = await client.research('quantum computing');
 */

const https = require('https');
const http = require('http');

const DEFAULT_BASE_URL = 'https://api.aipaygent.xyz';

class AiPayGent {
  /**
   * @param {Object} options
   * @param {string} [options.apiKey] - Prepaid API key (apk_xxx)
   * @param {string} [options.x402Token] - x402 payment token
   * @param {string} [options.baseUrl] - Override base URL
   */
  constructor(options = {}) {
    this.apiKey = options.apiKey || process.env.AIPAYGENT_API_KEY;
    this.x402Token = options.x402Token || process.env.AIPAYGENT_X402_TOKEN;
    this.baseUrl = options.baseUrl || process.env.AIPAYGENT_BASE_URL || DEFAULT_BASE_URL;
  }

  _headers() {
    const h = { 'Content-Type': 'application/json' };
    if (this.apiKey) h['Authorization'] = `Bearer ${this.apiKey}`;
    if (this.x402Token) h['X-Payment'] = this.x402Token;
    return h;
  }

  _request(method, path, body, queryParams) {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      if (queryParams) {
        Object.entries(queryParams).forEach(([k, v]) => {
          if (v !== undefined && v !== null) url.searchParams.set(k, v);
        });
      }

      const isHttps = url.protocol === 'https:';
      const lib = isHttps ? https : http;
      const payload = body ? JSON.stringify(body) : null;
      const headers = this._headers();
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
          try {
            const parsed = JSON.parse(data);
            if (res.statusCode === 402) {
              reject(new Error(`Payment required: ${JSON.stringify(parsed)}`));
            } else if (res.statusCode >= 400) {
              reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(parsed)}`));
            } else {
              resolve(parsed);
            }
          } catch (e) {
            resolve(data);
          }
        });
      });

      req.on('error', reject);
      if (payload) req.write(payload);
      req.end();
    });
  }

  // ── Paid AI Endpoints ───────────────────────────────────────────────────────

  /** Research any topic with Claude. $0.01 */
  research(topic, depth = 'standard') {
    return this._request('POST', '/research', { topic, depth });
  }

  /** Write content to your spec. $0.05 */
  write(prompt, style = 'professional', format = 'markdown') {
    return this._request('POST', '/write', { prompt, style, format });
  }

  /** Generate code. $0.05 */
  code(description, language = 'python') {
    return this._request('POST', '/code', { description, language });
  }

  /** Analyze content for insights. $0.02 */
  analyze(content) {
    return this._request('POST', '/analyze', { content });
  }

  /** Sentiment analysis. $0.01 */
  sentiment(text) {
    return this._request('POST', '/sentiment', { text });
  }

  /** Extract keywords and entities. $0.01 */
  keywords(text) {
    return this._request('POST', '/keywords', { text });
  }

  /** Translate text. $0.02 */
  translate(text, targetLanguage) {
    return this._request('POST', '/translate', { text, target: targetLanguage });
  }

  /** Summarize text. $0.01 */
  summarize(text, maxLength) {
    return this._request('POST', '/summarize', { text, max_length: maxLength });
  }

  /** RAG question answering with documents. $0.05 */
  rag(query, documents) {
    return this._request('POST', '/rag', { query, documents });
  }

  /** Vision: analyze an image from URL. $0.05 */
  vision(imageUrl, question = 'Describe this image in detail') {
    return this._request('POST', '/vision', { image_url: imageUrl, question });
  }

  /** Web search via DuckDuckGo. $0.02 */
  search(query, n = 10) {
    return this._request('POST', '/web/search', { query, n });
  }

  /** Scrape any website. $0.05 */
  scrapeWeb(url, maxPages = 5) {
    return this._request('POST', '/scrape/web', { url, max_pages: maxPages });
  }

  /** Scrape Google Maps. $0.10 */
  scrapeGoogleMaps(query, maxItems = 5) {
    return this._request('POST', '/scrape/google-maps', { query, max_items: maxItems });
  }

  /** Scrape tweets by keyword. $0.05 */
  scrapeTweets(query, maxItems = 25) {
    return this._request('POST', '/scrape/tweets', { query, max_items: maxItems });
  }

  /** Entity enrichment (IP, crypto, country). $0.05 */
  enrich(entity, type = 'ip') {
    return this._request('POST', '/enrich', { entity, type });
  }

  /** Run Python code in a sandbox. $0.05 */
  runCode(code, timeout = 10) {
    return this._request('POST', '/code/run', { code, timeout });
  }

  /** Multi-step agentic workflow. $0.20 */
  workflow(goal, steps) {
    return this._request('POST', '/workflow', { goal, steps });
  }

  // ── Free Data Endpoints ─────────────────────────────────────────────────────

  /** Current weather for a city. FREE */
  weather(city) {
    return this._request('GET', '/data/weather', null, { city });
  }

  /** Crypto prices. FREE */
  crypto(symbol = 'bitcoin,ethereum') {
    return this._request('GET', '/data/crypto', null, { symbol });
  }

  /** Stock price. FREE */
  stocks(symbol = 'AAPL') {
    return this._request('GET', '/data/stocks', null, { symbol });
  }

  /** Currency exchange rates. FREE */
  exchangeRates(base = 'USD') {
    return this._request('GET', '/data/exchange-rates', null, { base });
  }

  /** Top Hacker News stories. FREE */
  news() {
    return this._request('GET', '/data/news', null);
  }

  /** IP geolocation. FREE */
  ipGeo(ip) {
    return this._request('GET', '/data/ip', null, ip ? { ip } : {});
  }

  /** Random joke. FREE */
  joke() {
    return this._request('GET', '/data/joke', null);
  }

  /** Inspirational quote. FREE */
  quote() {
    return this._request('GET', '/data/quote', null);
  }

  /** Public holidays for a country. FREE */
  holidays(country = 'US', year) {
    return this._request('GET', '/data/holidays', null, { country, year });
  }

  /** Country facts. FREE */
  countryInfo(name) {
    return this._request('GET', '/data/country', null, { name });
  }

  // ── Agent Networking ────────────────────────────────────────────────────────

  /** Send a message to another agent. $0.01 */
  sendMessage(fromAgent, toAgent, subject, body, threadId) {
    return this._request('POST', '/message/send', {
      from_agent: fromAgent, to_agent: toAgent, subject, body, thread_id: threadId,
    });
  }

  /** Get inbox for an agent. FREE */
  getInbox(agentId, unreadOnly = false) {
    return this._request('GET', `/message/inbox/${agentId}`, null, { unread_only: unreadOnly ? 1 : 0 });
  }

  /** Add knowledge to shared base. $0.01 */
  addKnowledge(topic, content, authorAgent, tags = []) {
    return this._request('POST', '/knowledge/add', { topic, content, author_agent: authorAgent, tags });
  }

  /** Search shared knowledge base. FREE */
  searchKnowledge(query, limit = 10) {
    return this._request('GET', '/knowledge/search', null, { q: query, limit });
  }

  /** Submit a task for other agents. $0.01 */
  submitTask(postedBy, title, description, skillsNeeded = [], rewardUsd = 0) {
    return this._request('POST', '/task/submit', {
      posted_by: postedBy, title, description, skills_needed: skillsNeeded, reward_usd: rewardUsd,
    });
  }

  /** Browse open tasks. FREE */
  browseTasks(skill, status = 'open') {
    return this._request('GET', '/task/browse', null, { skill, status });
  }

  /** Claim a task. FREE */
  claimTask(taskId, agentId) {
    return this._request('POST', '/task/claim', { task_id: taskId, agent_id: agentId });
  }

  // ── Key Management ──────────────────────────────────────────────────────────

  /** Generate a new prepaid API key. FREE */
  generateKey(label = '') {
    return this._request('POST', '/auth/generate-key', { label });
  }

  /** Check API key balance. FREE */
  keyStatus(key) {
    return this._request('GET', '/auth/status', null, { key });
  }

  // ── Marketplace ─────────────────────────────────────────────────────────────

  /** Browse marketplace services. FREE */
  marketplace(category, page = 1) {
    return this._request('GET', '/marketplace', null, { category, page });
  }

  /** Call any marketplace service. $0.05 */
  marketplaceCall(listingId, params = {}) {
    return this._request('POST', '/marketplace/call', { listing_id: listingId, params });
  }
}

module.exports = { AiPayGent };
