# Lesson 08: Deploying on a Raspberry Pi 5

## What You Will Build

A production deployment: systemd services for your Flask app and MCP server, a Cloudflare tunnel for HTTPS without a static IP, a health monitoring script, a deploy pipeline with rsync and smoke tests, automatic WAL checkpointing, and a tunnel watchdog. Total monthly cost: $0.

## Why Raspberry Pi

A Raspberry Pi 5 with 8GB RAM costs $80 once. A comparable cloud VM costs $20-40/month. After 3 months, the Pi has paid for itself. For a pre-revenue startup, that runway difference matters.

The Pi 5 has a quad-core ARM Cortex-A76 at 2.4 GHz (overclockable to 2.7 GHz), which handles a Flask/Gunicorn app comfortably. SQLite performs well on its NVMe SSD. The only limitation is bandwidth, which Cloudflare handles.

## Systemd Service

Create a systemd service file so your app starts on boot, restarts on crash, and logs to journalctl:

```ini
# /etc/systemd/system/aipaygent.service
[Unit]
Description=AiPayGen API Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/damien809/agent-service
ExecStart=/home/damien809/agent-service/venv/bin/gunicorn app:app \
    --bind 0.0.0.0:5001 \
    --workers 2 \
    --timeout 120 \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log
Restart=always
RestartSec=5
Environment=PATH=/home/damien809/agent-service/venv/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

And a second service for the MCP server:

```ini
# ~/.config/systemd/user/aipaygen-mcp.service
[Unit]
Description=AiPayGen MCP Server (streamable-http on port 5002)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/damien809/agent-service
ExecStart=/home/damien809/agent-service/venv/bin/python mcp_server.py --http
Restart=always
RestartSec=5
Environment=PATH=/home/damien809/agent-service/venv/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
```

Enable and start:

```bash
sudo systemctl enable aipaygent.service
sudo systemctl start aipaygent.service
sudo systemctl status aipaygent.service
```

## Cloudflare Tunnel

A Cloudflare tunnel gives you HTTPS, DDoS protection, and a public URL — all without opening ports on your router or having a static IP.

```bash
# Install cloudflared
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb

# Authenticate and create tunnel
cloudflared tunnel login
cloudflared tunnel create aipaygen

# Configure the tunnel
# ~/.cloudflared/config.yml
tunnel: <your-tunnel-id>
credentials-file: /home/damien809/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: api.aipaygen.com
    service: http://localhost:5001
  - hostname: mcp.aipaygen.com
    service: http://localhost:5002
  - service: http_status:404

# Install as a service
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Point your DNS CNAME records to `<tunnel-id>.cfargotunnel.com` in the Cloudflare dashboard.

## Tunnel Watchdog

Tunnels sometimes die. A watchdog script checks every minute and restarts if needed:

```bash
#!/bin/bash
# tunnel-watchdog.sh — runs every minute via cron
TUNNEL_SERVICE="cloudflared"
APP_SERVICE="aipaygent"

# Check if tunnel process exists
if ! pgrep -f cloudflared > /dev/null 2>&1; then
    echo "$(date): Tunnel dead, restarting" >> watchdog.log
    sudo systemctl restart $TUNNEL_SERVICE
fi

# Check if app is responding locally
if ! curl -sf http://localhost:5001/health > /dev/null 2>&1; then
    echo "$(date): App not responding, restarting" >> watchdog.log
    sudo systemctl restart $APP_SERVICE
    sleep 5
    sudo systemctl restart $TUNNEL_SERVICE
fi
```

Add to crontab: `* * * * * /home/damien809/agent-service/tunnel-watchdog.sh`

## Health Monitor

A more comprehensive monitor that runs every 5 minutes with escalating restart logic:

```bash
#!/bin/bash
# health_monitor.sh — */5 * * * *
SERVICES=("aipaygent.service" "aipaygen-mcp.service")
MAX_RESTART_ATTEMPTS=3
DISK_WARN_MB=2048

for svc in "${SERVICES[@]}"; do
    STATUS=$(systemctl is-active "$svc")
    if [ "$STATUS" != "active" ]; then
        FAIL_COUNT=$(cat "/tmp/${svc}.fails" 2>/dev/null || echo 0)
        if [ "$FAIL_COUNT" -lt "$MAX_RESTART_ATTEMPTS" ]; then
            sudo systemctl restart "$svc"
            echo $((FAIL_COUNT + 1)) > "/tmp/${svc}.fails"
            echo "[$(date)] Restarted $svc (attempt $((FAIL_COUNT + 1)))" >> health.log
        else
            echo "[$(date)] ALERT: $svc failed $MAX_RESTART_ATTEMPTS times" >> alerts.log
        fi
    else
        echo 0 > "/tmp/${svc}.fails"
    fi
done

# Disk space check
AVAIL_MB=$(df -m / | awk 'NR==2{print $4}')
if [ "$AVAIL_MB" -lt "$DISK_WARN_MB" ]; then
    echo "[$(date)] DISK WARNING: ${AVAIL_MB}MB remaining" >> alerts.log
fi
```

## Deploy Pipeline

The real deploy script runs tests, rsyncs to the server, installs deps, restarts services, and runs smoke tests:

```bash
#!/bin/bash
set -euo pipefail

LOCAL_DIR="/home/damien809/agent-service"
REMOTE="ubuntu@150.136.124.81"
REMOTE_DIR="/home/ubuntu/agent-service"
LIVE_URL="https://api.aipaygen.com"

# Step 1: Run tests locally
echo "=== Running Tests ==="
cd "$LOCAL_DIR"
python -m pytest tests/ -q --tb=line -x

# Step 2: Rsync (exclude DBs, venv, secrets)
echo "=== Syncing Files ==="
rsync -avz --checksum --delete \
  --exclude='.git' --exclude='venv/' --exclude='*.db' \
  --exclude='__pycache__/' --exclude='.env' --exclude='*.log' \
  "$LOCAL_DIR/" "$REMOTE:$REMOTE_DIR/"

# Step 3: Install dependencies
ssh "$REMOTE" "cd $REMOTE_DIR && source venv/bin/activate && pip install -q -r requirements.txt"

# Step 4: Restart services
ssh "$REMOTE" "sudo systemctl restart aipaygent.service"
ssh "$REMOTE" "sudo systemctl restart aipaygen-mcp.service"

# Step 5: Wait and smoke test
sleep 5
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$LIVE_URL/health")
if [ "$HTTP_CODE" = "200" ]; then
    echo "Deploy SUCCESS — $LIVE_URL is live"
else
    echo "SMOKE TEST FAILED — health returned $HTTP_CODE"
    exit 1
fi
```

Key decisions: databases are excluded from rsync (production data stays on the server), the venv is rebuilt on the server, and the deploy fails fast if smoke tests don't pass.

## Database Maintenance

SQLite WAL mode accumulates write-ahead log files. Checkpoint them periodically:

```bash
#!/bin/bash
# wal-checkpoint.sh — runs daily via cron
for db in /home/damien809/agent-service/*.db; do
    sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null
done
```

## Backups

Back up all databases daily to a separate drive or cloud storage:

```bash
#!/bin/bash
# backup_dbs.sh — runs nightly
BACKUP_DIR="/home/damien809/backups/$(date +%Y-%m-%d)"
mkdir -p "$BACKUP_DIR"
for db in /home/damien809/agent-service/*.db; do
    sqlite3 "$db" ".backup '$BACKUP_DIR/$(basename $db)'"
done
# Keep only last 14 days
find /home/damien809/backups -maxdepth 1 -mtime +14 -exec rm -rf {} +
```

Use `sqlite3 .backup` instead of `cp` — it creates a consistent snapshot even while the app is writing.

## Exercise

1. Create a systemd service file for your Flask app.
2. Set up a Cloudflare tunnel to get a public HTTPS URL.
3. Write a watchdog script and add it to crontab.
4. Create a deploy script that rsyncs, restarts, and smoke tests.
5. Set up daily database backups with the `.backup` command.

Next lesson: growth strategies and what to build next.
