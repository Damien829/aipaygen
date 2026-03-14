# AiPayGen Oracle Cloud Migration

**Date**: 2026-03-12
**Status**: Approved

## Goal

Migrate AiPayGen from Raspberry Pi 5 to Oracle Cloud Free Tier (ARM Ampere A1) with zero downtime, keeping Pi as fallback.

## Architecture

```
User → Cloudflare CDN → Cloudflare Tunnel → Oracle VM (gunicorn:5001) → SQLite DBs
```

Same stack, bigger box. No code changes.

## Oracle Cloud Instance

- **Shape**: VM.Standard.A1.Flex (ARM)
- **OCPU**: 4
- **RAM**: 24GB
- **Boot Volume**: 100GB
- **OS**: Ubuntu 22.04 LTS (aarch64)
- **Cost**: $0 (Always Free tier)

## Migration Steps

### Phase 1: Provision & Setup
1. Create Oracle Cloud account + ARM instance
2. Configure security list (block all inbound except SSH from your IP)
3. Install: Python 3.11, git, cloudflared, system deps (libffi, libssl)
4. Create user, venv, install pip packages from requirements.txt

### Phase 2: Transfer
5. rsync codebase: `agent-service/` (code, templates, static, tests)
6. scp secrets: `.env`, `.agent_key`, `.env.enc`
7. rsync SQLite DBs (19 files, ~10MB total)
8. Copy cron scripts: `auto-discover-tools.sh`, `auto-update.sh`, `auto-sweep.sh`

### Phase 3: Configure
9. Install systemd units: `aipaygent.service` (update workers 2→4)
10. Create new Cloudflare Tunnel on Oracle VM (or migrate existing credentials)
11. Install systemd unit: `aipaygent-tunnel.service`
12. Set up cron jobs (3 active)
13. Create 2GB swap (safety net, shouldn't need with 24GB)

### Phase 4: Validate
14. Start service, check `/health` endpoint
15. Run test suite on Oracle VM
16. Test all critical paths: auth, payments, crypto, MCP
17. Verify Cloudflare Tunnel connectivity

### Phase 5: Cutover
18. Stop Pi tunnel service
19. Start Oracle tunnel service (or update Cloudflare DNS routing)
20. Verify `aipaygen.com` and `api.aipaygen.com` resolve to Oracle
21. Monitor for 24 hours

### Phase 6: Steady State
22. Pi stays as cold standby (tunnel stopped, service stopped)
23. Monitor Oracle VM performance for 1 week
24. If stable, Pi becomes backup only

## Configuration Changes

| Setting | Pi (current) | Oracle (new) |
|---------|-------------|--------------|
| Gunicorn workers | 2 | 4 |
| Swap | 2GB | 2GB (safety) |
| Worker class | sync | sync |
| Timeout | 120s | 120s |
| Cron jobs | 3 | 3 (same) |

## Rollback

Stop Oracle tunnel → Start Pi tunnel. Takes ~10 seconds. Zero data loss (SQLite DBs are on both machines at cutover time).

## Security

- No public ports exposed (Cloudflare Tunnel only)
- SSH restricted to known IP via Oracle security list
- `.env` transferred via scp (encrypted in transit)
- Firewall: iptables deny all inbound except SSH
- Same auth/rate-limiting as current setup

## What Does NOT Change

- All application code, routes, templates
- Domain, DNS, SSL certificates (Cloudflare managed)
- API keys, wallet address, Stripe config
- MCP server, PyPI packages, Smithery/Glama listings
