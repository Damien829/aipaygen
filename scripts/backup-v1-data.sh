#!/usr/bin/env bash
# Phase 0 backup: run ON the v1 server (Pi or Oracle) from the agent-service folder.
# Makes consistent copies of every SQLite database plus secrets, records row counts,
# and packs it all into one archive to copy off the machine.
#
#   cd ~/agent-service && bash backup-v1-data.sh
#
set -euo pipefail

SRC="${1:-$PWD}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$HOME/aipaygen-v1-backup-$STAMP"
mkdir -p "$OUT/db" "$OUT/secrets"

command -v sqlite3 >/dev/null || { echo "sqlite3 is not installed (sudo apt install sqlite3)"; exit 1; }

shopt -s nullglob
for db in "$SRC"/*.db; do
  name="$(basename "$db")"
  # .backup is safe while the app is running, unlike cp, and folds in the -wal file.
  sqlite3 "$db" ".backup '$OUT/db/$name'"
  for table in $(sqlite3 "$OUT/db/$name" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"); do
    echo "$name	$table	$(sqlite3 "$OUT/db/$name" "SELECT COUNT(*) FROM \"$table\"")"
  done >> "$OUT/row-counts.tsv"
  echo "backed up $name"
done

for f in "$SRC/.env" "$SRC/.env.enc" "$HOME/.agent_key"; do
  [ -f "$f" ] && cp -p "$f" "$OUT/secrets/" && echo "copied $(basename "$f")"
done

chmod -R go-rwx "$OUT"
tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
chmod 600 "$OUT.tar.gz"
( cd "$OUT" && find . -type f -exec shasum -a 256 {} + ) > "$OUT.sha256"

echo
echo "Done: $OUT.tar.gz"
echo "$(ls "$OUT/db" | wc -l | tr -d ' ') databases, $(wc -l < "$OUT/row-counts.tsv" | tr -d ' ') tables."
echo "It contains secrets. Copy it off this machine, then delete it here."
