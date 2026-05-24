#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT/web"
export VITE_APP_BASE_PATH="${STD_WEB_BASE_PATH:-/crawler/}"
export VITE_API_BASE_PATH="${STD_WEB_API_BASE_PATH:-/crawler/api}"
npm run build

cd "$REPO_ROOT"
sudo docker compose -p std-worker-prod -f docker-compose.yml -f docker-compose.server.override.yml --env-file .env.prod up -d --build
