-- API keys. Only a SHA-256 hash of each key is stored.
CREATE TABLE api_keys (
  id            TEXT PRIMARY KEY,
  key_hash      TEXT NOT NULL UNIQUE,
  key_prefix    TEXT NOT NULL,
  label         TEXT,
  balance_micro INTEGER NOT NULL DEFAULT 0 CHECK (balance_micro >= 0),
  created_at    INTEGER NOT NULL,
  creator_hash  TEXT,
  disabled      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_api_keys_creator ON api_keys (creator_hash, created_at);

-- Every credit movement: trial grants, top-ups, charges, refunds.
CREATE TABLE ledger (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  key_id       TEXT NOT NULL REFERENCES api_keys (id),
  delta_micro  INTEGER NOT NULL,
  reason       TEXT NOT NULL,
  ref          TEXT UNIQUE,
  created_at   INTEGER NOT NULL
);
CREATE INDEX idx_ledger_key ON ledger (key_id, created_at);

-- One row per paid tool call, however it was paid.
CREATE TABLE usage (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tool         TEXT NOT NULL,
  channel      TEXT NOT NULL,          -- mcp | http
  payment      TEXT NOT NULL,          -- credits | x402
  payer        TEXT,                   -- key id or wallet address
  price_micro  INTEGER NOT NULL,
  ok           INTEGER NOT NULL,
  ms           INTEGER NOT NULL,
  tx           TEXT,
  created_at   INTEGER NOT NULL
);
CREATE INDEX idx_usage_time ON usage (created_at);
CREATE INDEX idx_usage_tool ON usage (tool, created_at);
