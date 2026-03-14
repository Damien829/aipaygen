#!/usr/bin/env bash
cd /home/damien809/agent-service
LOG="wal-checkpoint.log"
echo "[$(date -Iseconds)] WAL checkpoint start" >> "$LOG"
for db in *.db; do
  [ -f "$db" ] || continue
  /home/damien809/agent-service/venv/bin/python3 -c "import sqlite3; c=sqlite3.connect('$db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" 2>>"$LOG"
  echo "  checkpointed: $db" >> "$LOG"
done
echo "[$(date -Iseconds)] WAL checkpoint done" >> "$LOG"
