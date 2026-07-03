#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="prod"

usage() {
  cat <<'USAGE'
Usage:
  ./upgrade.sh [--local]

Options:
  --local    Use docker-compose.local.yml and deploy/.env
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --local)
      MODE="local"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$MODE" = "local" ]; then
  ENV_FILE="$SCRIPT_DIR/.env"
  COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"
else
  ENV_FILE="/srv/infowatchtower/.env.production"
  COMPOSE_FILE="$SCRIPT_DIR/docker-compose.prod.yml"
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

git -C "$SCRIPT_DIR/.." pull --ff-only
INFOWATCHTOWER_ENV_FILE="$ENV_FILE" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

echo "Upgrade complete. If rollback is needed, restore a database backup and checkout the previous tag."
