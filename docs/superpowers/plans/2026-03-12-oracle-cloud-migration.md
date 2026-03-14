# Oracle Cloud Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate AiPayGen from Raspberry Pi 5 to Oracle Cloud Free Tier ARM instance with zero downtime.

**Architecture:** Same Flask/Gunicorn/SQLite stack running on Oracle Cloud ARM VM behind Cloudflare Tunnel. Pi stays as cold standby. No code changes — infrastructure-only migration.

**Tech Stack:** Oracle Cloud (Ampere A1 ARM), Ubuntu 22.04, Python 3.11, Gunicorn, Cloudflared, SQLite, systemd

**Spec:** `docs/superpowers/specs/2026-03-12-oracle-cloud-migration-design.md`

---

## Chunk 1: Provision Oracle Cloud Instance

### Task 1: Create Oracle Cloud Account

- [ ] **Step 1: Sign up at cloud.oracle.com**

Go to https://cloud.oracle.com and create a free account. You'll need:
- Email address
- Credit card (for verification only — free tier resources are never charged)
- Home region: pick the closest to your users (e.g., US East Ashburn, US West Phoenix)

> **Important:** Choose your home region carefully — it cannot be changed later and free tier ARM instances are only available in your home region.

- [ ] **Step 2: Wait for account activation**

Oracle may take 1-30 minutes to activate. You'll get an email when ready.

### Task 2: Create ARM Compute Instance

- [ ] **Step 1: Navigate to Compute → Instances → Create Instance**

Set these parameters:
- **Name:** `aipaygen-prod`
- **Image:** Ubuntu 22.04 (aarch64)
- **Shape:** VM.Standard.A1.Flex
- **OCPU:** 4
- **RAM:** 24 GB
- **Boot volume:** 100 GB
- **SSH key:** Upload your public key from Pi: `cat ~/.ssh/id_rsa.pub`

If you don't have an SSH key on the Pi:
```bash
ssh-keygen -t ed25519 -C "aipaygen-oracle" -f ~/.ssh/oracle_key
cat ~/.ssh/oracle_key.pub
```

- [ ] **Step 2: Note the public IP**

After creation, note the public IP address. Save it:
```bash
echo "ORACLE_IP=<the-ip>" >> ~/.bashrc
source ~/.bashrc
```

- [ ] **Step 3: Test SSH access from Pi**

```bash
ssh -i ~/.ssh/oracle_key ubuntu@$ORACLE_IP "hostname && uname -m"
```
Expected: hostname prints, architecture shows `aarch64`

### Task 3: Lock Down Security

- [ ] **Step 1: Configure Oracle Security List**

In Oracle Console → Networking → VCN → Security Lists → Default:
- **Remove** the 0.0.0.0/0 rule for ports 80/443 (Cloudflare Tunnel means no inbound HTTP needed)
- **Keep** SSH (port 22) but restrict source to your home IP only
- Result: only SSH from your IP, everything else blocked

- [ ] **Step 2: Configure UFW on the VM**

```bash
ssh -i ~/.ssh/oracle_key ubuntu@$ORACLE_IP << 'REMOTE'
sudo apt update && sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from YOUR_HOME_IP to any port 22
sudo ufw --force enable
sudo ufw status
REMOTE
```
Expected: Status shows SSH allowed from your IP only.

---

## Chunk 2: Install Dependencies on Oracle VM

### Task 4: Install System Packages

- [ ] **Step 1: Install Python 3.11 and system deps**

```bash
ssh -i ~/.ssh/oracle_key ubuntu@$ORACLE_IP << 'REMOTE'
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    python3-pip libffi-dev libssl-dev build-essential \
    git curl wget sqlite3 libsqlite3-dev
python3.11 --version
REMOTE
```
Expected: `Python 3.11.x`

- [ ] **Step 2: Create app user**

```bash
ssh -i ~/.ssh/oracle_key ubuntu@$ORACLE_IP << 'REMOTE'
sudo useradd -m -s /bin/bash damien809
sudo mkdir -p /home/damien809/.ssh
sudo cp ~/.ssh/authorized_keys /home/damien809/.ssh/
sudo chown -R damien809:damien809 /home/damien809/.ssh
sudo chmod 700 /home/damien809/.ssh
sudo chmod 600 /home/damien809/.ssh/authorized_keys
REMOTE
```

- [ ] **Step 3: Test SSH as app user**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP "whoami && pwd"
```
Expected: `damien809` and `/home/damien809`

### Task 5: Install Cloudflared

- [ ] **Step 1: Install cloudflared (ARM64)**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version
REMOTE
```
Expected: `cloudflared version 2024.x.x` or newer

---

## Chunk 3: Transfer Codebase & Data

### Task 6: Transfer Application Code

- [ ] **Step 1: Rsync codebase from Pi to Oracle (excluding venv and logs)**

Run this **from the Pi**:
```bash
rsync -avz --progress \
    --exclude='venv/' \
    --exclude='*.log' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='requests.jsonl' \
    --exclude='tests/__init__.py' \
    -e "ssh -i ~/.ssh/oracle_key" \
    /home/damien809/agent-service/ \
    damien809@$ORACLE_IP:/home/damien809/agent-service/
```

- [ ] **Step 2: Transfer secrets securely**

```bash
scp -i ~/.ssh/oracle_key /home/damien809/agent-service/.env damien809@$ORACLE_IP:/home/damien809/agent-service/.env
scp -i ~/.ssh/oracle_key /home/damien809/.agent_key damien809@$ORACLE_IP:/home/damien809/.agent_key
scp -i ~/.ssh/oracle_key /home/damien809/agent-service/.env.enc damien809@$ORACLE_IP:/home/damien809/agent-service/.env.enc
```

- [ ] **Step 3: Lock down secret file permissions on Oracle**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
chmod 600 ~/agent-service/.env ~/agent-service/.env.enc ~/.agent_key
ls -la ~/agent-service/.env ~/agent-service/.env.enc ~/.agent_key
REMOTE
```
Expected: `-rw-------` on all three files

### Task 7: Create Venv & Install Packages

- [ ] **Step 1: Create venv and install requirements**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
cd ~/agent-service
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
python -c "from app import app; print('App imports OK')"
REMOTE
```
Expected: `App imports OK`

- [ ] **Step 2: Run tests on Oracle**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
cd ~/agent-service
rm -f tests/__init__.py
source venv/bin/activate
python -m pytest --tb=line -q 2>&1 | tail -5
REMOTE
```
Expected: 1400+ passed, ~9 failed (same crypto order-dependent ones)

---

## Chunk 4: Configure Services

### Task 8: Set Up Gunicorn Service

- [ ] **Step 1: Create systemd unit file**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
sudo tee /etc/systemd/system/aipaygent.service << 'EOF'
[Unit]
Description=AiPayGent Flask API
After=network.target

[Service]
User=damien809
WorkingDirectory=/home/damien809/agent-service
EnvironmentFile=/home/damien809/agent-service/.env
ExecStart=/home/damien809/agent-service/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --preload \
    --bind 127.0.0.1:5001 \
    --timeout 120 \
    --keep-alive 5 \
    --graceful-timeout 30 \
    --access-logfile /home/damien809/agent-service/access.log \
    --error-logfile /home/damien809/agent-service/agent.log \
    --log-level info \
    app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable aipaygent.service
sudo systemctl start aipaygent.service
sudo systemctl status aipaygent.service
REMOTE
```
Expected: `active (running)`

- [ ] **Step 2: Verify health endpoint locally on Oracle**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP \
    "curl -s http://localhost:5001/health | python3 -m json.tool"
```
Expected: `"status": "healthy"`

### Task 9: Set Up Cloudflare Tunnel

- [ ] **Step 1: Authenticate cloudflared on Oracle VM**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP "cloudflared tunnel login"
```
This opens a URL — paste it in your browser and authorize.

- [ ] **Step 2: Create a new tunnel**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
cloudflared tunnel create aipaygen-oracle
cloudflared tunnel list
REMOTE
```
Note the new tunnel ID.

- [ ] **Step 3: Configure tunnel**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /home/damien809/.cloudflared/$TUNNEL_ID.json

retries: 5
grace-period: 30s
protocol: quic

ingress:
  - hostname: aipaygen.com
    service: http://localhost:5001
    originRequest:
      keepAliveTimeout: 90s
      keepAliveConnections: 10
      connectTimeout: 30s
  - hostname: api.aipaygen.com
    service: http://localhost:5001
    originRequest:
      keepAliveTimeout: 90s
      keepAliveConnections: 10
      connectTimeout: 30s
  - hostname: mcp.aipaygen.com
    service: http://localhost:5001
    originRequest:
      keepAliveTimeout: 90s
      keepAliveConnections: 10
      connectTimeout: 30s
  - service: http_status:404
EOF
cat ~/.cloudflared/config.yml
REMOTE
```

- [ ] **Step 4: Create tunnel systemd service**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
sudo tee /etc/systemd/system/aipaygent-tunnel.service << 'EOF'
[Unit]
Description=AiPayGen Cloudflare Tunnel
After=network-online.target
Wants=network-online.target

[Service]
User=damien809
ExecStart=/usr/bin/cloudflared tunnel --config /home/damien809/.cloudflared/config.yml run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable aipaygent-tunnel.service
REMOTE
```

**Do NOT start the tunnel yet** — we start it during cutover.

### Task 10: Set Up Cron Jobs

- [ ] **Step 1: Copy and install cron jobs**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
crontab -l 2>/dev/null || true
(crontab -l 2>/dev/null; echo "0 * * * * /home/damien809/agent-service/auto-discover-tools.sh >> /home/damien809/agent-service/cron.log 2>&1") | crontab -
(crontab -l; echo "*/15 * * * * /home/damien809/agent-service/auto-update.sh >> /home/damien809/agent-service/cron.log 2>&1") | crontab -
(crontab -l; echo "*/10 * * * * /home/damien809/agent-service/auto-sweep.sh >> /home/damien809/agent-service/cron.log 2>&1") | crontab -
crontab -l
REMOTE
```
Expected: 3 cron entries listed

- [ ] **Step 2: Create swap (safety net)**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h | head -3
REMOTE
```
Expected: Shows 2GB swap

---

## Chunk 5: Cutover & Validate

### Task 11: Cutover Traffic

- [ ] **Step 1: Final data sync from Pi (catch any recent changes)**

Run from Pi:
```bash
rsync -avz --progress \
    --exclude='venv/' --exclude='*.log' --exclude='__pycache__/' \
    --exclude='.pytest_cache/' --exclude='requests.jsonl' \
    -e "ssh -i ~/.ssh/oracle_key" \
    /home/damien809/agent-service/*.db \
    damien809@$ORACLE_IP:/home/damien809/agent-service/
```

- [ ] **Step 2: Stop Pi tunnel**

On the Pi:
```bash
sudo systemctl stop aipaygent-tunnel.service
sudo systemctl disable aipaygent-tunnel.service
```

- [ ] **Step 3: Update Cloudflare DNS routes**

In Cloudflare dashboard → DNS → update CNAME records for `aipaygen.com`, `api.aipaygen.com`, `mcp.aipaygen.com` to point to the new Oracle tunnel ID:
```
cloudflared tunnel route dns aipaygen-oracle aipaygen.com
cloudflared tunnel route dns aipaygen-oracle api.aipaygen.com
cloudflared tunnel route dns aipaygen-oracle mcp.aipaygen.com
```

- [ ] **Step 4: Start Oracle tunnel**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
sudo systemctl start aipaygent-tunnel.service
sudo systemctl status aipaygent-tunnel.service
REMOTE
```
Expected: `active (running)`

- [ ] **Step 5: Verify public endpoints**

```bash
curl -s https://api.aipaygen.com/health | python3 -m json.tool
curl -s https://aipaygen.com/ | head -3
curl -s https://api.aipaygen.com/api/stats | python3 -m json.tool
```
Expected: All return valid responses

### Task 12: Post-Cutover Monitoring

- [ ] **Step 1: Check service logs for errors**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP << 'REMOTE'
sudo journalctl -u aipaygent.service --since "10 minutes ago" --no-pager | tail -20
sudo journalctl -u aipaygent-tunnel.service --since "10 minutes ago" --no-pager | tail -10
REMOTE
```
Expected: No errors (RPC rotation warnings are normal)

- [ ] **Step 2: Check resource usage**

```bash
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP "free -h && echo '---' && df -h / && echo '---' && uptime"
```
Expected: RAM well under 50%, disk under 20%, low load avg

- [ ] **Step 3: Verify Pi is stopped but ready for rollback**

On Pi:
```bash
systemctl status aipaygent-tunnel.service  # should be inactive
systemctl status aipaygent.service          # should still be running (for rollback)
```

## Rollback Procedure

If anything goes wrong after cutover:
```bash
# On Oracle — stop tunnel
ssh -i ~/.ssh/oracle_key damien809@$ORACLE_IP "sudo systemctl stop aipaygent-tunnel.service"

# On Pi — restart tunnel
sudo systemctl start aipaygent-tunnel.service

# Update DNS back to Pi tunnel
cloudflared tunnel route dns 3e7edc19-d896-47e6-8b61-0c2d0d593295 aipaygen.com
cloudflared tunnel route dns 3e7edc19-d896-47e6-8b61-0c2d0d593295 api.aipaygen.com
cloudflared tunnel route dns 3e7edc19-d896-47e6-8b61-0c2d0d593295 mcp.aipaygen.com
```
Takes ~10 seconds. Zero data loss.
