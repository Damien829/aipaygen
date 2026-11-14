#!/bin/sh
# Runs before the app starts. For each database in litestream.yml that is not on
# disk yet (new server, or the disk was lost), restore it from R2. Databases that
# already exist are left alone, and a database with no backup yet is skipped.
set -eu
CONFIG=/etc/litestream.yml
for db in $(sed -n 's/^  - path: //p' "$CONFIG"); do
  litestream restore -config "$CONFIG" -if-db-not-exists -if-replica-exists "$db"
done
# The app containers run as uid 10001 (see core/Dockerfile).
chown -R 10001:10001 /data
echo "restore: done"
