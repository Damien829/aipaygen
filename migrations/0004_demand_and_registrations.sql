-- What agents look for: search words and result counts only. No IP, key or payer.
CREATE TABLE IF NOT EXISTS search_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,          -- normalized, lowercased, max 200 chars
  kind TEXT,
  results INTEGER NOT NULL,
  channel TEXT NOT NULL,        -- http | mcp | web
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_log_created ON search_log (created_at);

-- Agents that listed themselves by submitting their public agent card URL.
CREATE TABLE IF NOT EXISTS agent_registrations (
  card_url TEXT PRIMARY KEY,
  catalog_id TEXT NOT NULL,
  status TEXT NOT NULL,         -- listed | rejected
  reason TEXT,
  created_at INTEGER NOT NULL,
  refreshed_at INTEGER NOT NULL
);
