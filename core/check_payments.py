#!/usr/bin/env python3
"""Check Stripe for real payments. Run manually or via cron.
Usage: python3 check_payments.py
Cron:  0 * * * * cd /home/damien809/agent-service && python3 check_payments.py >> payments.log 2>&1
"""
import os, sys, subprocess
from datetime import datetime

try:
    import stripe
except ImportError:
    print("pip install stripe"); sys.exit(1)

# Load key
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
if not stripe.api_key:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("STRIPE_SECRET_KEY="):
                    stripe.api_key = line.strip().split("=", 1)[1]; break

if not stripe.api_key:
    print("ERROR: No STRIPE_SECRET_KEY"); sys.exit(1)

now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
print(f"\n{'='*50}")
print(f"  PAYMENT CHECK — {now}")
print(f"{'='*50}")

# All charges
charges = stripe.Charge.list(limit=20)
succeeded = [c for c in charges.data if c.status == "succeeded"]
failed = [c for c in charges.data if c.status == "failed"]

print(f"\nSuccessful payments: {len(succeeded)}")
for c in succeeded:
    dt = datetime.fromtimestamp(c.created)
    print(f"  $$$ {dt} | ${c.amount/100:.2f} | {c.receipt_email or c.customer or 'unknown'}")
if not succeeded:
    print("  None yet.")

print(f"Failed charges (recent): {len(failed)}")

# Balance
bal = stripe.Balance.retrieve()
avail = sum(b.amount for b in bal.available) / 100
pending = sum(b.amount for b in bal.pending) / 100
print(f"\nStripe balance: ${avail:.2f} available, ${pending:.2f} pending")

# Completed checkouts
sessions = stripe.checkout.Session.list(limit=10, status="complete")
print(f"\nCompleted checkouts: {len(sessions.data)}")
for s in sessions.data:
    dt = datetime.fromtimestamp(s.created)
    email = s.customer_email or ""
    if not email and s.customer_details:
        email = getattr(s.customer_details, "email", "")
    print(f"  {dt} | ${(s.amount_total or 0)/100:.2f} | {email or 'no-email'}")

# Open sessions
open_sessions = stripe.checkout.Session.list(limit=5, status="open")
print(f"Open checkouts: {len(open_sessions.data)}")

# Alert if money
if avail + pending > 0:
    try:
        subprocess.run(["wall", f"$$$ STRIPE HAS ${avail+pending:.2f} $$$"], timeout=3, capture_output=True)
    except Exception:
        pass

print(f"{'='*50}\n")
