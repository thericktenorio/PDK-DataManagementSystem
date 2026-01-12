#!/usr/bin/env bash
set -euo pipefail

# cd to the directory of this script
cd "$(dirname "$0")/.."

# Start/refresh container services
docker compose up -d --build

# Best-effor wait for web to answer HTTP (up to ~60s)
URL="http://localhost:8000/"
echo "Waiting for ${URL} ..."
for i in {1..60}; do
    if curl -s -o /dev/null -w "%{http_code}" "$URL" | grep -qE '200|302'; then
        echo "Service is up."
        break
    fi
    sleep 1
    if [[ $i -eq 60 ]]; then
        echo "Timed out waiting for ${URL}. You can check logs with: docker compose logs -f web"
    fi
done

# Open browser (macOS / Linux)
if command -v open >/dev/null 2>&1; then
    open "$URL"
fi

echo "App starting at ${URL}"
