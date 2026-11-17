#!/usr/bin/env bash
# Redeploy LaunchScout on the VPS: pull the latest code, rebuild, restart, then wait for the health check.
# Run from the repo folder on the server (e.g. /opt/launchscout):   ./deploy.sh
# Releases still go through local testing and the approval step first.
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
HEALTH_URL="http://127.0.0.1:8612/_stcore/health"

if [ ! -f .env ]; then
  echo "Missing .env (copy .env.example and add the keys). Aborting." >&2
  exit 1
fi

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building and restarting"
$COMPOSE up -d --build

echo "==> Waiting for the health check"
for i in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "OK: LaunchScout is healthy (after ~$((i * 3))s)"
    $COMPOSE ps
    exit 0
  fi
  sleep 3
done

echo "Health check failed after 90s. Recent logs:" >&2
$COMPOSE logs --tail=60 >&2
exit 1
