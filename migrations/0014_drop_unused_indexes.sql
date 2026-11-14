-- Every catalog write also writes each index, and the free plan allows 100k rows
-- written a day. Nothing queries these any more: the health check uses
-- idx_catalog_health (0011), and only the rare owner report groups by source.
DROP INDEX IF EXISTS idx_catalog_checked;
DROP INDEX IF EXISTS idx_catalog_source;
