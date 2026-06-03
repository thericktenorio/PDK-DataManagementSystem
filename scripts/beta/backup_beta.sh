#!/usr/bin/env bash
# Nightly backup: pg_dump (×3) + optional media → local dir → B2 upload.
# Install on VPS: chmod 700 scripts/beta/backup_beta.sh
# Cron: 30 2 * * * /opt/pdk/pdk_crm_postgresql/scripts/beta/backup_beta.sh >> /var/log/pdk-backup.log 2>&1
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/pdk/pdk_crm_postgresql}"
STAMP=$(date +%Y%m%d_%H%M)
DIR=/var/backups/pdk/$STAMP
B2_BUCKET="${B2_BUCKET:-godelta-beta-backups}"
B2_ENDPOINT="${B2_ENDPOINT:-https://s3.us-west-004.backblazeb2.com}"

# Load CRM DB creds from .env.docker if present
ENV_FILE="$INSTALL_DIR/pdk_crm/.env.docker"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' "$ENV_FILE" | sed 's/\r$//')
  set +a
fi
DB_NAME="${DB_NAME:-tax_operations}"
DB_USER="${DB_USER:-pdkcrm}"

mkdir -p "$DIR"
cd "$INSTALL_DIR"

echo "[$STAMP] pg_dump tax_operations"
docker compose exec -T crm_db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$DIR/tax_operations.sql.gz"

echo "[$STAMP] pg_dump parser"
docker compose exec -T pdf_db pg_dump -U pdfmgr pdf_manager | gzip > "$DIR/parser.sql.gz"

echo "[$STAMP] pg_dump analytics"
docker compose exec -T analytics_db pg_dump -U analytics analytics | gzip > "$DIR/analytics.sql.gz"

# Media volume — adjust name after: docker volume ls | grep crm_media
MEDIA_VOL=$(docker volume ls -q | grep crm_media | head -1 || true)
if [ -n "$MEDIA_VOL" ]; then
  echo "[$STAMP] tar crm_media ($MEDIA_VOL)"
  docker run --rm -v "${MEDIA_VOL}:/data:ro" -v "$DIR:/out" alpine \
    tar -czf "/out/crm_media.tar.gz" -C /data . 2>/dev/null || true
fi

if command -v aws >/dev/null 2>&1 && [ -n "${AWS_ACCESS_KEY_ID:-}" ] || [ -f "$HOME/.aws/credentials" ]; then
  echo "[$STAMP] upload to s3://$B2_BUCKET/$STAMP/"
  aws s3 sync "$DIR" "s3://${B2_BUCKET}/${STAMP}/" --endpoint-url "$B2_ENDPOINT"
else
  echo "[$STAMP] B2 upload skipped — set AWS credentials (B2 application key) or ~/.aws/credentials"
fi

find /var/backups/pdk -maxdepth 1 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null || true
echo "[$STAMP] done"
