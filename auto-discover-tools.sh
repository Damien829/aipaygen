#!/bin/bash
# AiPayGen Auto Tool Discovery
# Runs every hour via cron. Discovers new APIs and absorbs them as skills.
# Safe: logs everything, never breaks existing tools.

set -e
cd /home/damien809/agent-service

LOG="/home/damien809/agent-service/discovery.log"
TS=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
BASE="http://127.0.0.1:5001"

# Rotate log if > 1MB
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 1048576 ]; then
    mv "$LOG" "${LOG}.old"
fi

echo "[$TS] Auto-discovery starting..." >> "$LOG"

# 1. Check health first
HEALTH=$(curl -s -m 5 "$BASE/health" 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status',''))" 2>/dev/null || echo "down")
if [ "$HEALTH" != "healthy" ]; then
    echo "[$TS] Server not healthy ($HEALTH), skipping." >> "$LOG"
    exit 0
fi

# 2. Discover and absorb APIs
source venv/bin/activate
set -a; source .env 2>/dev/null; set +a
python3 << 'PYEOF' >> "$LOG" 2>&1
import json, urllib.request, time, random, os

BASE = "http://127.0.0.1:5001"
ADMIN_KEY = os.environ.get("ADMIN_SECRET", "")

def api_call(endpoint, data):
    try:
        headers = {"Content-Type": "application/json"}
        if ADMIN_KEY:
            headers["Authorization"] = f"Bearer {ADMIN_KEY}"
        req = urllib.request.Request(
            f"{BASE}/{endpoint}",
            data=json.dumps(data).encode(),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}

def safe_fetch(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AiPayGen-Discovery/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

# Source 1: apis.guru — public API directory
print("  [1/3] Scanning apis.guru...")
apis = safe_fetch("https://api.apis.guru/v2/list.json")
absorbed = 0
if apis:
    # Pick 10 random APIs to absorb this run (avoid hammering)
    api_list = list(apis.items())
    random.shuffle(api_list)
    for name, info in api_list[:10]:
        preferred = info.get("preferred", "")
        versions = info.get("versions", {})
        if preferred and preferred in versions:
            v = versions[preferred]
            title = v.get("info", {}).get("title", name)
            desc = v.get("info", {}).get("description", "")[:300]
            spec_url = v.get("swaggerUrl", "")
            if title and desc:
                result = api_call("skills/absorb", {
                    "text": f"API: {title}\nDescription: {desc}\nSpec: {spec_url}\nSource: apis.guru/{name}"
                })
                if result.get("absorbed") or result.get("skill_name"):
                    absorbed += 1
                time.sleep(0.5)  # Be gentle
    print(f"  apis.guru: absorbed {absorbed} skills")

# Source 2: Process queued messages
print("  [2/3] Processing agent inbox...")
try:
    inbox_req = urllib.request.Request(
        f"{BASE}/message/inbox/aipaygen-system?unread_only=1",
        headers={"Authorization": f"Bearer {ADMIN_KEY}"} if ADMIN_KEY else {},
    )
    with urllib.request.urlopen(inbox_req, timeout=10) as r:
        inbox = json.loads(r.read().decode())
    messages = inbox.get("messages", [])
    if messages:
        print(f"  Found {len(messages)} queued messages")
        for msg in messages[:5]:
            body = msg.get("body", "")
            subject = msg.get("subject", "")
            if any(kw in (subject + body).lower() for kw in ["skill", "tool", "api", "add", "create"]):
                result = api_call("skills/absorb", {"text": f"{subject}: {body}"})
                if result.get("absorbed"):
                    print(f"    Absorbed skill from message: {subject}")
    else:
        print("  No queued messages")
except Exception as e:
    print(f"  Inbox check failed: {e}")

# Source 3: Check open tasks
print("  [3/3] Checking task board...")
try:
    tasks_req = urllib.request.Request(f"{BASE}/task/browse?status=open&limit=5")
    with urllib.request.urlopen(tasks_req, timeout=10) as r:
        tasks = json.loads(r.read().decode())
    task_list = tasks.get("tasks", [])
    if task_list:
        print(f"  Found {len(task_list)} open tasks")
except Exception as e:
    print(f"  Task board check failed: {e}")

# Log stats
print(f"  Discovery complete: {absorbed} new skills absorbed")
PYEOF

echo "[$TS] Auto-discovery finished." >> "$LOG"
