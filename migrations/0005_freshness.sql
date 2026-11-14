-- Keep the catalog fresh: health checks, where each item came from, sync cursors.
ALTER TABLE catalog ADD COLUMN source TEXT NOT NULL DEFAULT 'seed';   -- seed | registered | mcp-registry | x402-bazaar
ALTER TABLE catalog ADD COLUMN checked_at INTEGER NOT NULL DEFAULT 0; -- last health check (ms)
ALTER TABLE catalog ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0; -- consecutive failed checks; hidden at 3+
CREATE INDEX IF NOT EXISTS idx_catalog_checked ON catalog (checked_at);
CREATE INDEX IF NOT EXISTS idx_catalog_source ON catalog (source);

CREATE TABLE IF NOT EXISTS sync_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

ALTER TABLE agent_registrations ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0;
