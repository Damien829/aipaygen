#!/bin/bash
# AiPayGen Auto-Update Script
# 1. Pulls latest app code from GitHub, tests, deploys
# 2. Updates Python dependencies (security patches)
# 3. Rotates logs
# Safe: only deploys if tests pass.

set -e
cd /home/damien809/agent-service
LOG="/home/damien809/agent-service/update.log"
TS=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

# Rotate log if > 1MB
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 1048576 ]; then
    mv "$LOG" "${LOG}.old"
fi

echo "[$TS] Checking for updates..." >> "$LOG"

# Pull latest
git fetch origin master 2>> "$LOG"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[$TS] Already up to date." >> "$LOG"
    exit 0
fi

echo "[$TS] Update found: $LOCAL -> $REMOTE" >> "$LOG"
git pull origin master >> "$LOG" 2>&1

# Activate venv and run tests
source venv/bin/activate
if python -m pytest tests/ -q --tb=line >> "$LOG" 2>&1; then
    echo "[$TS] Tests passed. Restarting server..." >> "$LOG"
    pkill -f "gunicorn.*app:app" || true
    sleep 3
    gunicorn --workers 4 --worker-class sync --bind 127.0.0.1:5001 --timeout 120 --daemon app:app
    echo "[$TS] Server restarted successfully." >> "$LOG"

    # Update MCP server too
    if systemctl --user is-active aipaygen-mcp.service > /dev/null 2>&1; then
        systemctl --user restart aipaygen-mcp.service
        echo "[$TS] MCP server restarted." >> "$LOG"
    fi

    # Run auto-discovery after successful deploy
    if [ -x /home/damien809/agent-service/auto-discover-tools.sh ]; then
        /home/damien809/agent-service/auto-discover-tools.sh &
        echo "[$TS] Auto-discovery triggered." >> "$LOG"
    fi

    # Restart message agent if running
    pkill -f "message_agent.py" 2>/dev/null || true
    source venv/bin/activate
    nohup python3 message_agent.py >> message_agent.log 2>&1 &
    echo "[$TS] Message agent restarted." >> "$LOG"
else
    echo "[$TS] Tests FAILED. Rolling back..." >> "$LOG"
    git checkout "$LOCAL"
    echo "[$TS] Rolled back to $LOCAL" >> "$LOG"
fi

# ── Security Updates (pip packages) ──────────────────────────────────────────
# Only run at the top of the hour (once per hour, not every 15 min)
MINUTE=$(date +%M)
if [ "$MINUTE" -lt 15 ]; then
    echo "[$TS] Checking pip security updates..." >> "$LOG"
    source venv/bin/activate

    # Upgrade pip itself
    pip install --upgrade pip >> "$LOG" 2>&1 || true

    # Security-critical packages — always keep latest
    pip install --upgrade \
        certifi \
        urllib3 \
        requests \
        cryptography \
        flask \
        gunicorn \
        stripe \
        werkzeug \
        jinja2 \
        markupsafe \
        >> "$LOG" 2>&1 || true

    # Check if upgrade broke tests
    if python -m pytest tests/ -q --tb=line >> "$LOG" 2>&1; then
        echo "[$TS] Security updates applied. Tests still passing." >> "$LOG"
        # Restart to pick up new packages
        pkill -f "gunicorn.*app:app" || true
        sleep 3
        gunicorn --workers 4 --worker-class sync --bind 127.0.0.1:5001 --timeout 120 --daemon app:app
        echo "[$TS] Server restarted after security updates." >> "$LOG"
    else
        echo "[$TS] WARNING: Tests failed after pip upgrade. Pinning back..." >> "$LOG"
        # Restore from requirements if available
        if [ -f requirements.txt ]; then
            pip install -r requirements.txt >> "$LOG" 2>&1 || true
        fi
        echo "[$TS] Restored previous package versions." >> "$LOG"
    fi

    # Freeze current working state
    pip freeze > requirements.lock 2>/dev/null || true
fi
