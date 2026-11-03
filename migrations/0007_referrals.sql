-- Referrals: a key's code, and who referred it. The referrer is rewarded once,
-- on the referred key's first paid top-up (ledger ref "referral:<referred key id>").
ALTER TABLE api_keys ADD COLUMN referral_code TEXT;
ALTER TABLE api_keys ADD COLUMN referred_by TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_referral_code ON api_keys (referral_code);
