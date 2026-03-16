#!/bin/bash
# AiPayGen Health Monitor — runs every 5 minutes via cron
# Crontab: */5 * * * * /home/ubuntu/agent-service/health_monitor.sh
#
# Checks:
#   - Both services running (aipaygent, aipaygen-mcp)
#   - Auto-restart with 3-failure escalation
#   - Disk space warnings
#   - Log rotation

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/health_monitor.log"
ALERT_FILE="$LOG_DIR/alerts.log"
STATE_DIR="$LOG_DIR/.health_state"
MAX_RESTART_ATTEMPTS=3
DISK_WARN_MB=2048       # 2GB
LOG_MAX_BYTES=104857600  # 100MB

SERVICES=("aipaygent.service" "aipaygen-mcp.service")

# Ensure directories exist
mkdir -p "$LOG_DIR" "$STATE_DIR"

# --- Logging ---
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

alert() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: $*"
  echo "$msg" >> "$ALERT_FILE"
  log "ALERT: $*"
}

# ──────────────────────────────────────────────
# 1. Check and restart services
# ──────────────────────────────────────────────
for svc in "${SERVICES[@]}"; do
  STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
  FAIL_COUNT_FILE="$STATE_DIR/${svc}.fail_count"

  if [ "$STATUS" = "active" ]; then
    # Service is healthy — reset failure counter
    if [ -f "$FAIL_COUNT_FILE" ]; then
      rm -f "$FAIL_COUNT_FILE"
      log "$svc recovered — reset failure counter"
    fi
    continue
  fi

  # Service is down
  log "$svc is $STATUS — attempting restart"

  # Read current failure count
  FAIL_COUNT=0
  if [ -f "$FAIL_COUNT_FILE" ]; then
    FAIL_COUNT=$(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo "0")
  fi
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"

  if [ "$FAIL_COUNT" -gt "$MAX_RESTART_ATTEMPTS" ]; then
    alert "$svc has failed $FAIL_COUNT times (threshold: $MAX_RESTART_ATTEMPTS). Manual intervention required."
    continue
  fi

  # Attempt restart
  if sudo systemctl restart "$svc" 2>/dev/null; then
    sleep 2
    NEW_STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    if [ "$NEW_STATUS" = "active" ]; then
      log "$svc restarted successfully (attempt $FAIL_COUNT/$MAX_RESTART_ATTEMPTS)"
      rm -f "$FAIL_COUNT_FILE"
    else
      log "$svc restart attempt $FAIL_COUNT/$MAX_RESTART_ATTEMPTS — still $NEW_STATUS"
      if [ "$FAIL_COUNT" -ge "$MAX_RESTART_ATTEMPTS" ]; then
        alert "$svc failed to restart after $MAX_RESTART_ATTEMPTS attempts. Status: $NEW_STATUS"
      fi
    fi
  else
    log "$svc restart command failed (attempt $FAIL_COUNT/$MAX_RESTART_ATTEMPTS)"
    if [ "$FAIL_COUNT" -ge "$MAX_RESTART_ATTEMPTS" ]; then
      alert "$svc restart command failed $MAX_RESTART_ATTEMPTS times. Manual intervention required."
    fi
  fi
done

# ──────────────────────────────────────────────
# 2. Check disk space
# ──────────────────────────────────────────────
DISK_AVAIL_KB=$(df "$SCRIPT_DIR" --output=avail 2>/dev/null | tail -1 | tr -d ' ')
if [ -n "$DISK_AVAIL_KB" ] && [ "$DISK_AVAIL_KB" -gt 0 ] 2>/dev/null; then
  DISK_AVAIL_MB=$((DISK_AVAIL_KB / 1024))
  if [ "$DISK_AVAIL_MB" -lt "$DISK_WARN_MB" ]; then
    alert "Low disk space: ${DISK_AVAIL_MB}MB available (threshold: ${DISK_WARN_MB}MB)"
  fi
fi

# ──────────────────────────────────────────────
# 3. Rotate logs if over 100MB
# ──────────────────────────────────────────────
rotate_log() {
  local file="$1"
  if [ ! -f "$file" ]; then
    return
  fi
  local size
  size=$(stat -c%s "$file" 2>/dev/null || echo "0")
  if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
    # Keep one rotated copy
    mv "$file" "${file}.old"
    log "Rotated $file (was ${size} bytes)"
  fi
}

# Rotate our own logs
rotate_log "$LOG_FILE"
rotate_log "$ALERT_FILE"

# Rotate application logs
for logfile in "$SCRIPT_DIR"/*.log; do
  [ -f "$logfile" ] || continue
  [ "$logfile" = "$LOG_FILE" ] && continue  # already handled
  rotate_log "$logfile"
done

# Rotate gunicorn/service logs via journalctl vacuum (if applicable)
if command -v journalctl &>/dev/null; then
  JOURNAL_SIZE=$(journalctl --disk-usage 2>/dev/null | grep -oP '[\d.]+[MG]' || echo "0M")
  # Vacuum if over 500MB
  JOURNAL_MB=$(echo "$JOURNAL_SIZE" | python3 -c "
import sys
s = sys.stdin.read().strip()
if s.endswith('G'):
    print(int(float(s[:-1]) * 1024))
elif s.endswith('M'):
    print(int(float(s[:-1])))
else:
    print(0)
" 2>/dev/null || echo "0")
  if [ "$JOURNAL_MB" -gt 500 ]; then
    sudo journalctl --vacuum-size=200M 2>/dev/null
    log "Vacuumed journal logs (was ${JOURNAL_SIZE})"
  fi
fi

exit 0
