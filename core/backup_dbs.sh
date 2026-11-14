#!/bin/bash
# Daily database backup
BACKUP_DIR="/home/damien809/agent-service/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d)

for db in api_keys.db funnel.db accounts.db tool_usage.db email_queue.db notifications.db seller_marketplace.db; do
    if [ -f "/home/damien809/agent-service/$db" ]; then
        sqlite3 "/home/damien809/agent-service/$db" ".backup '$BACKUP_DIR/${db%.db}_$DATE.db'" 2>/dev/null
    fi
done

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete 2>/dev/null

echo "[$(date)] Backup complete: $(ls $BACKUP_DIR/*_$DATE.db 2>/dev/null | wc -l) databases"
