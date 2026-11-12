#!/usr/bin/env bash
# Дамп Postgres в backups/ со сжатием; хранит последние KEEP копий.
# Cron на сервере: 0 3 * * * /opt/ai-tutor/scripts/backup.sh >> /var/log/ai-tutor-backup.log 2>&1
# Восстановление: gunzip -c backups/<файл>.sql.gz | docker compose exec -T db psql -U tutor -d tutor
set -euo pipefail

cd "$(dirname "$0")/.."
backup_dir="${BACKUP_DIR:-backups}"
keep="${KEEP:-7}"
mkdir -p "$backup_dir"

file="$backup_dir/tutor-$(date -u +%Y%m%d-%H%M%S).sql.gz"
# Пишем во временный файл: оборванный дамп не должен выглядеть как готовый
docker compose exec -T db pg_dump -U tutor -d tutor --clean --if-exists | gzip > "$file.tmp"
mv "$file.tmp" "$file"

ls -1t "$backup_dir"/tutor-*.sql.gz | tail -n +"$((keep + 1))" | xargs -r rm --
echo "$(date -u +%FT%TZ) backup ok: $file ($(du -h "$file" | cut -f1))"
