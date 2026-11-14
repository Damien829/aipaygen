-- One row per x402 payment in flight or settled. Claimed after verify, before the
-- tool runs, so the same signed payment can't run a paid call twice in parallel.
CREATE TABLE IF NOT EXISTS payment_claims (
  token_hash TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
);
