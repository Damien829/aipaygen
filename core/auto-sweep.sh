#!/bin/bash
# AiPayGen Auto-Sweep — runs every 10 minutes
# Checks for stale references, broken endpoints, and service health
# Logs issues to sweep.log, sends wall alert on critical failures

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
LOG="$SCRIPT_DIR/sweep.log"
TS=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

# Rotate log if > 500KB
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 524288 ]; then
    mv "$LOG" "${LOG}.old"
fi

ISSUES=0

# 1. Health check — local first (fast), then public (tunnel verification)
API_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:5001/health 2>/dev/null || echo "000")
API_PUBLIC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://api.aipaygen.com/health 2>/dev/null || echo "000")

if [ "$API_LOCAL" != "200" ]; then
    echo "[$TS] CRITICAL: API process down (local=$API_LOCAL)" >> "$LOG"
    wall "AiPayGen ALERT: API process down ($API_LOCAL)" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
    # Restart gunicorn daemon
    pkill -9 -f "gunicorn.*app:app" 2>/dev/null || true
    sleep 2
    "$SCRIPT_DIR/venv/bin/gunicorn" -c "$SCRIPT_DIR/gunicorn.conf.py" app:app --daemon 2>/dev/null || true
    echo "[$TS] Attempted gunicorn restart" >> "$LOG"
elif [ "$API_PUBLIC" != "200" ]; then
    echo "[$TS] WARNING: API local OK but tunnel returned $API_PUBLIC" >> "$LOG"
    ISSUES=$((ISSUES + 1))
    # Tunnel down — restart cloudflared
    # Restart cloudflared tunnel
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    sleep 2
    nohup cloudflared tunnel --config /home/damien809/.cloudflared/config.yml run >> /home/damien809/agent-service/cloudflared.log 2>&1 &
    echo "[$TS] Attempted tunnel restart" >> "$LOG"
else
    echo "[$TS] API health OK (local+tunnel)" >> "$LOG"
fi

# 2. MCP health check — local first, then public
MCP_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:5002/health 2>/dev/null || echo "000")
MCP_PUBLIC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://mcp.aipaygen.com/health 2>/dev/null || echo "000")

if [ "$MCP_LOCAL" != "200" ]; then
    echo "[$TS] CRITICAL: MCP process down (local=$MCP_LOCAL)" >> "$LOG"
    wall "AiPayGen ALERT: MCP process down ($MCP_LOCAL)" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
    # Restart MCP server
    pkill -f "mcp_server.py" 2>/dev/null || true
    sleep 1
    cd "$SCRIPT_DIR" && ./venv/bin/python3 mcp_server.py >> /home/damien809/agent-service/mcp_server.log 2>&1 &
    echo "[$TS] Attempted MCP restart" >> "$LOG"
elif [ "$MCP_PUBLIC" != "200" ]; then
    echo "[$TS] WARNING: MCP local OK but tunnel returned $MCP_PUBLIC" >> "$LOG"
    ISSUES=$((ISSUES + 1))
else
    echo "[$TS] MCP health OK (local+tunnel)" >> "$LOG"
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
    "$SCRIPT_DIR" 2>/dev/null | grep -v 'docs/.*/plans/' | grep -v app.py.bak | grep -v __pycache__ | grep -v '.pyc' | grep -v node_modules | grep -v auto-sweep.sh | wc -l)
if [ "$STALE_COUNT" -gt 0 ]; then
    echo "[$TS] WARNING: $STALE_COUNT stale brand references found" >> "$LOG"
    ISSUES=$((ISSUES + 1))
fi

# 5. Disk space check
DISK_FREE_MB=$(df -m "$SCRIPT_DIR" | tail -1 | awk '{print $4}')
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

# 8. DB integrity check — catch corruption before it causes data loss
for db in *.db routes/*.db; do
    if [ -f "$db" ]; then
        INTEGRITY=$(python3 -c "
import sqlite3, sys
try:
    conn = sqlite3.connect('$db')
    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    conn.close()
    print(result)
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)
        if [ "$INTEGRITY" != "ok" ]; then
            echo "[$TS] CRITICAL: DB corruption in $db: $INTEGRITY" >> "$LOG"
            wall "AiPayGen ALERT: DB corruption in $db" 2>/dev/null || true
            ISSUES=$((ISSUES + 1))
            # Create backup before it gets worse
            cp "$db" "${db}.corrupt.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
        fi
    fi
done

# 9. DB permissions check — ensure all .db files are 600
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

# 10. App-level error check — scan for 500s and Python exceptions in recent logs
if [ -f "agent.log" ]; then
    RECENT_ERRORS=$(tail -200 agent.log 2>/dev/null | grep -ci 'ERROR\|Traceback\|Exception' || true)
    if [ "$RECENT_ERRORS" -gt 5 ]; then
        echo "[$TS] WARNING: $RECENT_ERRORS errors in recent agent.log" >> "$LOG"
        ISSUES=$((ISSUES + 1))
    fi
fi

# 11. Web app check — use local endpoint since Pi can't resolve own domain
APP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:5001/app/" 2>/dev/null || echo "000")
if [ "$APP_STATUS" != "200" ]; then
    echo "[$TS] WARNING: Web app returned $APP_STATUS" >> "$LOG"
    ISSUES=$((ISSUES + 1))
fi

# 12. Key endpoint smoke test — verify pages return proper responses
for endpoint in /health /discover /pricing /support /docs; do
    EP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:5001${endpoint}" 2>/dev/null || echo "000")
    if [ "$EP_STATUS" != "200" ]; then
        echo "[$TS] WARNING: Endpoint ${endpoint} returned $EP_STATUS" >> "$LOG"
        ISSUES=$((ISSUES + 1))
    fi
done

# 13. Process count check — ensure gunicorn has expected workers
WORKER_COUNT=$(pgrep -cf "gunicorn.*app:app" 2>/dev/null || echo 0)
WORKER_COUNT=$(echo "$WORKER_COUNT" | tr -d '[:space:]')
if [ "${WORKER_COUNT:-0}" -lt 3 ] 2>/dev/null; then
    echo "[$TS] WARNING: Only $WORKER_COUNT gunicorn workers (expected 4+)" >> "$LOG"
    ISSUES=$((ISSUES + 1))
fi

# 14. Cloudflared tunnel check
TUNNEL_RUNNING=$(pgrep -f "cloudflared tunnel" >/dev/null 2>&1 && echo "yes" || echo "no")
if [ "$TUNNEL_RUNNING" = "no" ]; then
    echo "[$TS] CRITICAL: Cloudflared tunnel not running" >> "$LOG"
    wall "AiPayGen ALERT: Tunnel down" 2>/dev/null || true
    ISSUES=$((ISSUES + 1))
fi

# 15. Temperature check — warn if Pi is throttling
TEMP=$(vcgencmd measure_temp 2>/dev/null | sed 's/[^0-9.]//g' || echo "0")
TEMP_INT=${TEMP%%.*}
if [ "${TEMP_INT:-0}" -gt 75 ] 2>/dev/null; then
    echo "[$TS] WARNING: CPU temperature ${TEMP}C (throttle risk)" >> "$LOG"
    ISSUES=$((ISSUES + 1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo "[$TS] Sweep clean — no issues" >> "$LOG"
else
    echo "[$TS] Sweep found $ISSUES issue(s)" >> "$LOG"
fi
