#!/usr/bin/env python3
"""Comprehensive health monitor. Run via cron every 5 minutes.
Alerts via wall if anything is wrong."""
import os, sys, subprocess, time, json
from datetime import datetime

issues = []
BASE = os.path.dirname(os.path.abspath(__file__))

# 1. Check if API responds
try:
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:5000/health", headers={"Host": "api.aipaygen.com"})
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())
    if data.get("status") != "healthy":
        issues.append(f"API unhealthy: {data.get('status')}")
    # Check disk
    disk_free = data.get("checks", {}).get("disk_free_mb", 999999)
    if disk_free < 1000:
        issues.append(f"LOW DISK: {disk_free}MB free")
    # Check memory
    mem_pct = data.get("checks", {}).get("memory_used_pct", 0)
    if mem_pct > 85:
        issues.append(f"HIGH MEMORY: {mem_pct}%")
except Exception as e:
    issues.append(f"API DOWN: {e}")

# 2. Check tunnel is running
try:
    result = subprocess.run(["pgrep", "-f", "cloudflared"], capture_output=True, timeout=5)
    if result.returncode != 0:
        issues.append("TUNNEL DOWN: cloudflared not running")
except:
    pass

# 3. Check gunicorn workers
try:
    result = subprocess.run(["pgrep", "-c", "-f", "gunicorn"], capture_output=True, timeout=5, text=True)
    workers = int(result.stdout.strip() or "0")
    if workers < 2:
        issues.append(f"LOW WORKERS: only {workers} gunicorn processes")
except:
    pass

# 4. Check for successful Stripe payments
try:
    import stripe
    env_path = os.path.join(BASE, ".env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("STRIPE_SECRET_KEY="):
                stripe.api_key = line.strip().split("=", 1)[1]
                break
    if stripe.api_key:
        charges = stripe.Charge.list(limit=1)
        succeeded = [c for c in charges.data if c.status == "succeeded"]
        if succeeded:
            # MONEY! Alert immediately
            c = succeeded[0]
            try:
                subprocess.run(["wall", f"$$$ FIRST PAYMENT: ${c.amount/100:.2f} $$$"], timeout=3, capture_output=True)
            except:
                pass
except:
    pass

# Report issues
if issues:
    msg = f"[{datetime.utcnow().strftime('%H:%M')} UTC] HEALTH ALERT: " + " | ".join(issues)
    try:
        subprocess.run(["wall", msg], timeout=3, capture_output=True)
    except:
        pass
    # Log to file
    with open(os.path.join(BASE, "health.log"), "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} {msg}\n")
