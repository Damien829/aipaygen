#!/bin/bash
# AiPayGen Auto-Sweep — runs every 10 minutes
# Checks for stale references, broken endpoints, and service health
# Logs issues to sweep.log, sends wall alert on critical failures

set -e
cd /home/damien809/agent-service
LOG="/home/damien809/agent-service/sweep.log"
TS=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

# Rotate log if > 500KB
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 524288 ]; then
    mv "$LOG" "${LOG}.old"
fi

ISSUES=0

# 1. Health check
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://api.aipaygen.com/health 2>/dev/null || echo "000")
if [ "$API_STATUS" != "200" ]; then
    echo "[$TS] CRITICAL: API health returned $API_STATUS" >> "$LOG"
    wall "AiPayGen ALERT: API health check failed ($API_STATUS)" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
    # Try to restart
    source venv/bin/activate 2>/dev/null
    gunicorn --workers 4 --worker-class sync --bind 127.0.0.1:5001 --timeout 120 --daemon app:app 2>/dev/null || true
    echo "[$TS] Attempted auto-restart" >> "$LOG"
else
    echo "[$TS] API health OK" >> "$LOG"
fi

# 2. MCP health check
MCP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://mcp.aipaygen.com/health 2>/dev/null || echo "000")
if [ "$MCP_STATUS" != "200" ]; then
    echo "[$TS] CRITICAL: MCP health returned $MCP_STATUS" >> "$LOG"
    wall "AiPayGen ALERT: MCP health check failed ($MCP_STATUS)" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
    systemctl --user restart aipaygen-mcp.service 2>/dev/null || true
    echo "[$TS] Attempted MCP restart" >> "$LOG"
else
    echo "[$TS] MCP health OK" >> "$LOG"
fi

# 3. Key pages check
for path in / /try /buy-credits /docs /security /sdk /discover /builder; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://api.aipaygen.com${path}" 2>/dev/null || echo "000")
    if [ "$STATUS" != "200" ]; then
        echo "[$TS] WARNING: ${path} returned $STATUS" >> "$LOG"
        ISSUES=$((ISSUES + 1))
    fi
done

# 4. Stale reference check (code-level)
STALE_COUNT=$(grep -r --include='*.py' --include='*.js' --include='*.json' --include='*.md' --include='*.sh' --include='*.toml' \
    -E 'AiPayGent|aipaygent\.xyz|djautomd-lab|fallback-change-me' \
    /home/damien809/agent-service 2>/dev/null | grep -v docs/plans/ | grep -v app.py.bak | grep -v __pycache__ | grep -v '.pyc' | grep -v node_modules | grep -v auto-sweep.sh | wc -l)
if [ "$STALE_COUNT" -gt 0 ]; then
    echo "[$TS] WARNING: $STALE_COUNT stale brand references found" >> "$LOG"
    ISSUES=$((ISSUES + 1))
fi

# 5. Disk space check
DISK_FREE_MB=$(df -m /home/damien809 | tail -1 | awk '{print $4}')
if [ "$DISK_FREE_MB" -lt 1000 ]; then
    echo "[$TS] WARNING: Low disk space: ${DISK_FREE_MB}MB free" >> "$LOG"
    wall "AiPayGen ALERT: Low disk space (${DISK_FREE_MB}MB)" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
fi

# 6. Log file permissions — ensure all .log and .jsonl are 600
for logfile in *.log *.jsonl; do
    if [ -f "$logfile" ]; then
        perms=$(stat -c%a "$logfile" 2>/dev/null)
        if [ "$perms" != "600" ]; then
            chmod 600 "$logfile"
            echo "[$TS] Fixed permissions on $logfile ($perms -> 600)" >> "$LOG"
        fi
    fi
done

# 7. Log size check — trim if over 5MB
for logfile in agent.log update.log sweep.log access.log cloudflared.log mcp_server.log; do
    if [ -f "$logfile" ] && [ $(stat -c%s "$logfile" 2>/dev/null || echo 0) -gt 5242880 ]; then
        tail -500 "$logfile" > "${logfile}.tmp" && mv "${logfile}.tmp" "$logfile"
        echo "[$TS] Trimmed $logfile (was >5MB)" >> "$LOG"
    fi
done

# 8. DB permissions check — ensure all .db files are 600
for db in *.db routes/*.db; do
    if [ -f "$db" ]; then
        perms=$(stat -c%a "$db" 2>/dev/null)
        if [ "$perms" != "600" ]; then
            chmod 600 "$db"
            echo "[$TS] Fixed permissions on $db ($perms -> 600)" >> "$LOG"
            ISSUES=$((ISSUES + 1))
        fi
    fi
done

if [ "$ISSUES" -eq 0 ]; then
    echo "[$TS] Sweep clean — no issues" >> "$LOG"
else
    echo "[$TS] Sweep found $ISSUES issue(s)" >> "$LOG"
fi
