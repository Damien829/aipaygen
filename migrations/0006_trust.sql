-- Trust signals from real test calls (src/refresh.ts healthCheck).
ALTER TABLE catalog ADD COLUMN checks_total INTEGER NOT NULL DEFAULT 0;
ALTER TABLE catalog ADD COLUMN checks_ok INTEGER NOT NULL DEFAULT 0;
ALTER TABLE catalog ADD COLUMN latency_ms INTEGER;              -- smoothed response time
ALTER TABLE catalog ADD COLUMN verified INTEGER NOT NULL DEFAULT 0; -- 1 = proven callable (MCP tools/list or a valid x402 quote)
ALTER TABLE catalog ADD COLUMN verified_at INTEGER;
