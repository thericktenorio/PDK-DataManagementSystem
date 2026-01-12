#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# stop services but keep volumes (DB data)
docker compose down

echo "Stopped."