-- Idempotency-Key on credit calls: a retried request returns the first result
-- instead of charging again. Rows older than 24 hours are ignored.
CREATE TABLE IF NOT EXISTS idempotency (
  key_id TEXT NOT NULL,
  idem_key TEXT NOT NULL,
  tool TEXT NOT NULL,
  result TEXT,                  -- JSON of the first successful result; NULL while in progress
  created_at INTEGER NOT NULL,
  PRIMARY KEY (key_id, idem_key)
);
