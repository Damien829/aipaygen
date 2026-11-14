-- Which network carried each facilitator settlement: "self" (our fee wallet) or the
-- upstream facilitator it was routed to ("payai", "cdp") when ours can't pay gas.
ALTER TABLE facilitator_settlements ADD COLUMN via TEXT;
