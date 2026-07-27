#!/usr/bin/env bash
# Backup script: dumps the postgres database to a gzipped SQL file.
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-/var/lib/nationcraft/backups}"
mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/nationcraft-$TIMESTAMP.sql.gz"

docker-compose exec -T postgres pg_dump -U nationcraft nationcraft | gzip > "$OUT"

# Prune old backups (keep last 14 days)
find "$BACKUP_DIR" -name 'nationcraft-*.sql.gz' -mtime +14 -delete

echo "Backup written to $OUT"
