-- The health check picks the least recently checked listings of each kind.
-- Without this index it reads the whole catalog every 10 minutes (about 1.3M
-- row reads a day, a quarter of D1's free daily quota). With it, about 40.
-- Partial: only https listings are ever checked.
CREATE INDEX IF NOT EXISTS idx_catalog_health ON catalog (kind, checked_at) WHERE url LIKE 'https://%';
