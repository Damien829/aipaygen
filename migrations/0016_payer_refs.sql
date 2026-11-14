-- Referrals for wallet payers (x402 buyers usually never create an API key).
-- A wallet's first paid call that carries ?ref=CODE links that wallet to the code's key.
-- The referrer earns a share of the wallet's spend for 90 days (src/billing/refshare.ts).
-- One row written per newly referred wallet; earnings are summed from `usage` (idx_usage_payer).
CREATE TABLE IF NOT EXISTS payer_refs (
  payer       TEXT PRIMARY KEY,   -- wallet address, lowercase
  ref_key_id  TEXT NOT NULL,      -- api_keys.id of the referrer
  first_at    INTEGER NOT NULL    -- ms; the share window starts here
);
CREATE INDEX IF NOT EXISTS idx_payer_refs_key ON payer_refs (ref_key_id);

-- Wallet case: PayAI-settled usage rows hold lowercase wallets, CDP-settled ones EIP-55 checksummed.
-- recordUsage now lowercases on write (normalizePayer in keys.ts); this backfills older rows so
-- exact-match lookups (idx_usage_payer) see a wallet's whole history.
UPDATE usage SET payer = lower(payer)
WHERE payment = 'x402' AND payer LIKE '0x%' AND length(payer) = 42 AND payer <> lower(payer);
