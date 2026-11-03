-- Every settlement our facilitator submits (who asked, for whom, result).
CREATE TABLE IF NOT EXISTS facilitator_settlements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key_id TEXT NOT NULL,          -- merchant's apg_ key id
  network TEXT NOT NULL,
  payer TEXT,
  pay_to TEXT,
  asset TEXT,
  amount TEXT,                   -- atomic units (USDC: micro-USD)
  tx TEXT NOT NULL,
  success INTEGER NOT NULL,
  error TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fac_settlements_key ON facilitator_settlements (key_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fac_settlements_payto ON facilitator_settlements (pay_to, created_at);
