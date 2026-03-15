#!/usr/bin/env bash
# WAL checkpoint — path-agnostic (works on both Pi and Oracle)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
LOG="wal-checkpoint.log"
echo "[$(date -Iseconds)] WAL checkpoint start" >> "$LOG"
for db in *.db; do
  [ -f "$db" ] || continue
  python3 -c "import sqlite3; c=sqlite3.connect('$db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" 2>>"$LOG"
  echo "  checkpointed: $db" >> "$LOG"
done
echo "[$(date -Iseconds)] WAL checkpoint done" >> "$LOG"
