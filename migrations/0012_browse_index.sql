-- Browsing the catalog without a keyword sorts by trust (TRUST_SQL in src/catalog.ts).
-- Without these indexes each browse page read and sorted the whole catalog
-- (17k rows); with them a page reads about as many rows as it shows.
-- The expressions must stay identical to TRUST_SQL, or SQLite won't use them.
CREATE INDEX IF NOT EXISTS idx_catalog_browse ON catalog (
  (kind = 'listing') DESC,
  (verified * 2.0 + CASE WHEN checks_total > 0 THEN 1.0 * checks_ok / checks_total ELSE 0.5 END) DESC,
  name
);
CREATE INDEX IF NOT EXISTS idx_catalog_browse_kind ON catalog (
  kind,
  (verified * 2.0 + CASE WHEN checks_total > 0 THEN 1.0 * checks_ok / checks_total ELSE 0.5 END) DESC,
  name
);
