#!/usr/bin/env bash
# Runs on the server from ~/gridlock after CI has loaded the new image and written
# .env.new. Swaps it in, waits for the app's health check, and rolls back on failure.
set -euo pipefail
cd "$(dirname "$0")"

prev_tag=$(grep -s '^APP_TAG=' .env | cut -d= -f2- || true)
mv .env.new .env
chmod 600 .env
# Other apps on this server plug into Caddy through sites/ and the edge network.
mkdir -p sites
docker network inspect edge >/dev/null 2>&1 || docker network create edge >/dev/null
docker compose up -d --remove-orphans

healthy() {
  local id
  id=$(docker compose ps -q app)
  [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id")" = healthy ]
}

for _ in $(seq 60); do
  if healthy; then
    echo "app healthy"
    docker image prune -af --filter "until=168h" >/dev/null || true
    exit 0
  fi
  sleep 5
done

echo "::error::new version never became healthy; recent app logs:"
docker compose logs --tail 100 app || true
if [ -n "$prev_tag" ]; then
  echo "rolling back to $prev_tag"
  sed -i "s/^APP_TAG=.*/APP_TAG=$prev_tag/" .env
  docker compose up -d
fi
exit 1
