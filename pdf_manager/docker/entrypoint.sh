#!/usr/bin/env bash
set -euo pipefail

: "${DATA_ROOT:=/home/app/data}"

# If running as root, fix mounted volume perms then drop privileges
if [ "$(id -u)" -eq 0 ]; then
    mkdir -p "$DATA_ROOT/incoming" "$DATA_ROOT/outputs"
    chown -R app:app "$DATA_ROOT"
    exec gosu app "$@"
fi

# Now we are non-root app
python scripts/wait_for_db.py
python manage.py migrate --noinput

# Serve static files via WhiteNoise (3rd party app) for dev mode only
python manage.py collectstatic --noinput

# Hand off to the CMD (gunicorn)
exec "$@"