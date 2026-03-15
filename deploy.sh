#!/bin/bash
# Deploy AiPayGen from Pi to Oracle Cloud
# Usage: ./deploy.sh [--restart]
set -e

REMOTE="oracle"  # Uses ~/.ssh/config alias
REMOTE_DIR="/home/ubuntu/agent-service"
LOCAL_DIR="/home/damien809/agent-service"

echo "=== AiPayGen Deploy ==="

# 1. Run tests locally first
echo "[1/4] Running tests..."
cd "$LOCAL_DIR"
python -m pytest tests/ -q --tb=line 2>&1 | tail -3
echo ""

# 2. Sync code (preserving directory structure)
echo "[2/4] Syncing to Oracle..."
rsync -avz --checksum \
  --exclude='.git' \
  --exclude='venv/' \
  --exclude='*.db' \
  --exclude='*.db-shm' \
  --exclude='*.db-wal' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='dist/' \
  --exclude='node_modules/' \
  --exclude='.env' \
  --exclude='*.log' \
  --exclude='*.log.old' \
  --exclude='.claude/' \
  --exclude='payments.jsonl' \
  "$LOCAL_DIR/" "$REMOTE:$REMOTE_DIR/" 2>&1 | grep -E "^(sending|sent|total|[a-z])" | tail -10
echo ""

# 3. Install deps if requirements changed
echo "[3/4] Checking dependencies..."
ssh "$REMOTE" "cd $REMOTE_DIR && source venv/bin/activate && pip install -q -r requirements.txt 2>&1 | grep -v 'already satisfied' | tail -5"
echo ""

# 4. Restart services if --restart flag
if [ "$1" = "--restart" ]; then
  echo "[4/4] Restarting services..."
  ssh "$REMOTE" "sudo systemctl restart aipaygent.service && sudo systemctl restart aipaygen-mcp.service && sleep 2 && systemctl status aipaygent.service | head -5 && echo '---' && systemctl status aipaygen-mcp.service | head -5"
else
  echo "[4/4] Skipping restart (use --restart to restart services)"
fi

echo ""
echo "=== Deploy complete ==="
# Verify health
curl -s --max-time 10 https://api.aipaygen.com/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Health: {d[\"status\"]}, Uptime: {int(d[\"checks\"][\"uptime_seconds\"])}s')" 2>/dev/null || echo "Health check failed"
