-- Marketplace catalog served by the Worker: listings, third-party APIs, skills,
-- agents and services from v1's research data. Public fields only; usage stats,
-- ratings and reviews start empty and come from real usage.
CREATE TABLE IF NOT EXISTS catalog (
  id TEXT PRIMARY KEY,          -- "<kind>:<source id>"
  kind TEXT NOT NULL,           -- listing | api | skill | agent | service
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  url TEXT,                     -- what an agent calls or reads
  price_micro INTEGER,          -- AIPayGen price when we sell it; NULL for third-party
  x402 INTEGER NOT NULL DEFAULT 0,
  meta TEXT NOT NULL DEFAULT '{}', -- JSON, public extras
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_kind_category ON catalog (kind, category);

CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(
  name, description, category,
  content = 'catalog', content_rowid = 'rowid',
  tokenize = 'porter unicode61'
);

-- Private: how a skill runs. Never returned by public endpoints.
CREATE TABLE IF NOT EXISTS skill_prompts (
  id TEXT PRIMARY KEY REFERENCES catalog (id),
  prompt_template TEXT NOT NULL,
  input_schema TEXT,
  output_hint TEXT
);
