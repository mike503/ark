#!/bin/bash
# Restart the ark server (Docker preferred when container exists)
#
# Usage:
#   .helpers/restart-app-server.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

compose() {
  docker compose -f "$ROOT/compose.yml" "$@"
}

docker_ark_exists() {
  command -v docker >/dev/null 2>&1 || return 1
  [ -f "$ROOT/compose.yml" ] || return 1
  compose ps -a --status created --status running --status paused --status restarting --status exited --format '{{.Name}}' 2>/dev/null \
    | grep -qx 'ark'
}

if [ "${ARK_RUNTIME:-}" = "docker" ] || docker_ark_exists; then
  if compose ps -a --format '{{.Name}}' 2>/dev/null | grep -qx 'ark'; then
    compose up -d --build --force-recreate ark
  else
    compose up -d --build ark
  fi
  exit $?
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
PORT="${APP_PORT:-3010}"

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
elif command -v lsof >/dev/null 2>&1; then
  pid=$(lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pid" ]; then kill $pid 2>/dev/null || true; fi
fi

mkdir -p "$ROOT/server/tmp" "$ROOT/server/logs" "$ROOT/tmp" "$ROOT/logs"
(
  cd "$ROOT/server"
  nohup node server.js >> "$ROOT/server/logs/server.log" 2>&1 &
  echo $! > "$ROOT/server/tmp/server.pid"
)
sleep 1
echo "Started ark on port $PORT (pid $(cat "$ROOT/server/tmp/server.pid"))"
