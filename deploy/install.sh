#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="prod"
DOMAIN=""

usage() {
  cat <<'USAGE'
Usage:
  ./install.sh --local
  ./install.sh --domain example.internal

Options:
  --local              Use docker-compose.local.yml and write deploy/.env
  --domain <domain>    Use docker-compose.prod.yml and write /srv/infowatchtower/.env.production
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --local)
      MODE="local"
      shift
      ;;
    --domain)
      DOMAIN="${2:-}"
      shift 2
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

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose is required" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }

if [ "$MODE" = "local" ]; then
  ENV_FILE="${INFOWATCHTOWER_ENV_FILE:-$SCRIPT_DIR/.env}"
  COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"
  FRONTEND_PORT="${FRONTEND_PORT:-5173}"
  BACKEND_PORT="${BACKEND_PORT:-8000}"
  POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  REDIS_PORT="${REDIS_PORT:-6379}"
  AUTH_SESSION_COOKIE_SECURE="${AUTH_SESSION_COOKIE_SECURE:-false}"
  APP_BASE_URL="http://localhost:$FRONTEND_PORT"
  CORS_ORIGINS="http://localhost:$FRONTEND_PORT"
  PUBLIC_URL="http://localhost:$FRONTEND_PORT"
else
  if [ -z "$DOMAIN" ]; then
    echo "--domain is required unless --local is used" >&2
    usage >&2
    exit 2
  fi
  INSTALL_ROOT="/srv/infowatchtower"
  mkdir -p "$INSTALL_ROOT"
  ENV_FILE="$INSTALL_ROOT/.env.production"
  COMPOSE_FILE="$SCRIPT_DIR/docker-compose.prod.yml"
  APP_BASE_URL="https://$DOMAIN"
  CORS_ORIGINS="https://$DOMAIN"
  PUBLIC_URL="https://$DOMAIN"
  AUTH_SESSION_COOKIE_SECURE="${AUTH_SESSION_COOKIE_SECURE:-true}"
fi

random_hex() {
  openssl rand -hex "$1"
}

if [ ! -f "$ENV_FILE" ]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  POSTGRES_PASSWORD="$(random_hex 24)"
  AUTH_SESSION_SECRET="$(random_hex 32)"
  cat >"$ENV_FILE" <<EOF
APP_ENV=production
APP_VERSION=0.1.0
APP_BASE_URL=$APP_BASE_URL
ENABLE_DOCS=false
CORS_ORIGINS=$CORS_ORIGINS

DATABASE_URL=postgresql+psycopg://infowatchtower:$POSTGRES_PASSWORD@postgres:5432/infowatchtower
REDIS_URL=redis://redis:6379/0

BACKUP_KEEP=14

POSTGRES_DB=infowatchtower
POSTGRES_USER=infowatchtower
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_PORT=${POSTGRES_PORT:-5432}
REDIS_PORT=${REDIS_PORT:-6379}
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-5173}

AUTH_MODE=public_password
AUTH_SESSION_SECRET=$AUTH_SESSION_SECRET
AUTH_SESSION_COOKIE=infowatchtower_session
AUTH_SESSION_COOKIE_SECURE=$AUTH_SESSION_COOKIE_SECURE
AUTH_SESSION_TTL_SECONDS=43200
AUTH_AUTO_PROVISION=false
AUTH_DEFAULT_ROLE=viewer
AUTH_BOOTSTRAP_ADMIN_USERNAME=admin
AUTH_BOOTSTRAP_ADMIN_PASSWORD=
AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME=系统管理员

AUTH_HEADER_EMPLOYEE_NO=X-Employee-No
AUTH_HEADER_DISPLAY_NAME=X-Employee-Name
AUTH_HEADER_DEPARTMENT=X-Department
AUTH_HEADER_EMAIL=X-Email

INGESTION_SCHEDULER_ENABLED=true
INGESTION_SCHEDULER_DAILY_TIME=09:00
INGESTION_SCHEDULER_TIMEZONE=Asia/Shanghai
INGESTION_SCHEDULER_WORKSPACE_CODE=planning_intel
INGESTION_SCHEDULER_SOURCE_TYPES=rss,paper_rss,page_manual,page_monitor,wiseflow
INGESTION_CONCURRENCY=8
INGESTION_SOURCE_TIMEOUT_SECONDS=25
SCHEDULER_JOB_MODE=daily_pipeline
DAILY_PIPELINE_RUN_INGESTION=true
DAILY_PIPELINE_CREATE_DAILY_DRAFT=true
DAILY_PIPELINE_RECOMMENDATION_LIMIT=15
DAILY_PIPELINE_SOURCE_DAILY_LIMIT=2
DAILY_PIPELINE_DAY_OFFSET_DAYS=-1

MINIMAX_GENERATION_ENABLED=false
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2.7-highspeed
MINIMAX_MAX_TOKENS=3200
MINIMAX_TEMPERATURE=0.4
MINIMAX_RETRY_TIMES=3
MINIMAX_RETRY_BACKOFF_SECONDS=8
EOF
  chmod 600 "$ENV_FILE"
  echo "Created environment file: $ENV_FILE"
else
  echo "Using existing environment file: $ENV_FILE"
fi

compose() {
  INFOWATCHTOWER_ENV_FILE="$ENV_FILE" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose up -d --build

echo "Waiting for API health inside backend container"
for _ in $(seq 1 60); do
  if compose exec -T backend python - <<'PY' >/dev/null 2>&1
import urllib.request

urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3).read()
PY
  then
    echo "InfoWatchtower is healthy."
    echo "Open: $PUBLIC_URL"
    echo "First run: complete /setup, then invite users and create workspaces."
    exit 0
  fi
  sleep 5
done

echo "Timed out waiting for API health. Inspect logs with:" >&2
echo "INFOWATCHTOWER_ENV_FILE=\"$ENV_FILE\" docker compose --env-file \"$ENV_FILE\" -f \"$COMPOSE_FILE\" logs backend" >&2
exit 1
