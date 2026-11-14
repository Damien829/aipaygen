-- Try before paying: a few free calls a day per caller (hashed IP) on low-cost tools.
CREATE TABLE IF NOT EXISTS free_calls (
  day TEXT NOT NULL,   -- YYYY-MM-DD (UTC)
  who TEXT NOT NULL,   -- sha256 of the caller IP, never the IP itself
  n INTEGER NOT NULL,
  PRIMARY KEY (day, who)
);
