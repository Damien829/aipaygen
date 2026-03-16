# AiPayGen JavaScript SDK

Official JavaScript/TypeScript SDK for [AiPayGen](https://aipaygen.com) — 250 AI tools in one API.

## Install

```bash
npm install aipaygen
```

## Quick Start

```js
const { AiPayGen } = require('aipaygen');

const client = new AiPayGen('apk_your_key');

// Call any tool by name
const result = await client.call('research', { topic: 'quantum computing' });

// Use convenience methods
const summary = await client.summarize('Long text here...');
const weather = await client.weather('London');
```

## TypeScript

```ts
import { AiPayGen, AiPayGenError } from 'aipaygen';

const client = new AiPayGen('apk_your_key');

try {
  const result = await client.call('research', { topic: 'AI trends' });
} catch (err) {
  if (err instanceof AiPayGenError) {
    console.error(`Error ${err.statusCode}: ${err.message} (request: ${err.requestId})`);
  }
}
```

## Chain & Batch

```js
// Sequential chain
const chain = await client.chain([
  { tool: 'research', input: { topic: 'solar energy' } },
  { tool: 'summarize', input: { text: '{{prev.result}}' } },
]);

// Parallel batch
const batch = await client.batch([
  { tool: 'weather', input: { city: 'London' } },
  { tool: 'weather', input: { city: 'Tokyo' } },
]);
```

## Sessions

```js
const session = await client.session();
await session.call('research', { topic: 'machine learning' });
await session.call('summarize', { text: '{{prev.result}}' });
const log = await session.history();
await session.end();
```

## Usage & Balance

```js
const stats = await client.usage();
console.log(stats.balance_usd, stats.calls_today);

await client.refreshBalance();
console.log(client.balance);
```

## Error Handling

The SDK throws `AiPayGenError` with `statusCode`, `requestId`, and `body`. Rate-limited requests (429) are automatically retried with exponential backoff (up to 3 retries).

## Environment Variables

| Variable | Description |
|---|---|
| `AIPAYGEN_API_KEY` | Default API key |
| `AIPAYGEN_BASE_URL` | Override base URL |

## Links

- [Documentation](https://aipaygen.com/docs)
- [Get API Key](https://aipaygen.com/buy-credits)
- [Pricing](https://aipaygen.com/pricing)
- [Status](https://aipaygen.com/status)
