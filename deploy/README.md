# Deploying the AiPayGen core: free, on one server

Cost: **$0/month.**
- **Server:** Oracle Cloud Always Free.
- **Backups:** Cloudflare R2 free tier (10 GB; the data is a few hundred MB).
- **Way in from the internet:** Cloudflare Tunnel (free). The server opens **no** inbound ports.
- **Public front door:** the v2 Worker (Workers free tier).

```
internet ─▶ Cloudflare ─▶ Tunnel ─▶ web :5001 ─┐
                               └──▶ mcp :5002 ─┼─▶ /data (SQLite) ─▶ Litestream ─▶ R2 (7 days of history)
                                   scheduler ──┘
```

## One-time setup

1. **Server.** Use the existing Oracle instance, or create an Always Free one (Ampere A1 or AMD; Ubuntu). Then:
   - Add your Mac's key: `~/.ssh/aipaygen_oracle.pub` goes into `~/.ssh/authorized_keys`.
   - Install Docker: `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER`, then log out and back in.
   - In the Oracle security list, allow only SSH (22) inbound, ideally from your IP only.
2. **R2.** In the Cloudflare dashboard, go to R2, create the bucket `aipaygen-backups`, then create an API token with "Object Read & Write" on that bucket only.
3. **Tunnel.** In Zero Trust, go to Networks > Tunnels > Create (type: Cloudflared, Docker). Copy the token. Then add one public hostname: `core.aipaygen.com` → `http://web:5001`.
   - The Worker keeps `aipaygen.com`, `api.` and `mcp.`, charges for core routes, and forwards to `core.` with a signature.
   - Generate one secret: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Put it in `deploy/.env` as `AIPAYGEN_EDGE_SECRET`, and in the Worker with `npx wrangler secret put CORE_EDGE_SECRET`.
   - Set the Worker var `CORE_ORIGIN = "https://core.aipaygen.com"` in `wrangler.jsonc`.
4. **Code and settings** on the server:
   ```bash
   git clone https://github.com/Damien829/aipaygen.git && cd aipaygen && git checkout rebuild
   cp deploy/.env.example deploy/.env && chmod 600 deploy/.env   # fill in every value
   ```
5. **Data, first time only.** From the Mac, copy the cleaned snapshot into the server's data volume *before* the first start:
   ```bash
   scp -i ~/.ssh/aipaygen_oracle -r ~/AIPayGen-Backups/v1-data-cleaned-2026-10-30 ubuntu@SERVER:~/seed
   # on the server:
   docker volume create aipaygen_data
   docker run --rm -v aipaygen_data:/data -v ~/seed:/seed alpine sh -c 'cp /seed/*.db /data/ && chown -R 10001:10001 /data'
   rm -rf ~/seed
   ```
6. **Start:**
   ```bash
   cd deploy && docker compose --env-file .env up -d --build
   docker compose ps          # restore: exited 0; everything else: running / healthy
   docker compose logs -f litestream    # should show each database being replicated
   ```

## Everyday

| Task | Command (in `deploy/`) |
|---|---|
| Update to the latest code | `git pull && docker compose up -d --build` |
| Logs | `docker compose logs -f web` (or `scheduler`, `mcp`, `litestream`, `tunnel`) |
| Restart one part | `docker compose restart web` |
| Check backups | `docker compose exec litestream litestream databases -config /etc/litestream.yml` |

Run exactly **one** `scheduler`. Never scale it: it runs settlements and renewals.

## Restores

**Server or disk lost.** Do setup steps 1–4 on a new server and skip step 5. Then run `docker compose up -d`. The `restore` step pulls every database back from R2 before the app starts.

**Undo a bad change** (point in time, up to 7 days back):
```bash
docker compose stop web scheduler mcp litestream
docker compose run --rm --entrypoint litestream litestream \
  restore -config /etc/litestream.yml -timestamp 2026-11-01T12:00:00Z -o /data/api_keys.db.restored /data/api_keys.db
# inspect it, then swap it in:
docker compose run --rm --entrypoint sh litestream -c 'mv /data/api_keys.db.restored /data/api_keys.db && rm -f /data/api_keys.db-wal /data/api_keys.db-shm'
docker compose up -d
```

**Monthly restore test** (REBUILD_PLAN.md step 21): restore any one database with `-o` to a scratch path and compare row counts with the live one.
