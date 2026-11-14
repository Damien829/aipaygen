-- Owner key lookups in the Mac app read one key's usage; without this they scan the whole usage table.
CREATE INDEX IF NOT EXISTS idx_usage_payer ON usage (payer, created_at);
