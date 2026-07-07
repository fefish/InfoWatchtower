#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="prod"
DOMAIN=""
PRESET="full"

usage() {
  cat <<'USAGE'
Usage:
  ./install.sh --local [--preset rss-only|full|mirror]
  ./install.sh --domain example.internal [--preset rss-only|full|mirror]

Options:
  --local              Use docker-compose.local.yml and write deploy/.env
  --domain <domain>    Use docker-compose.prod.yml and write /srv/infowatchtower/.env.production
  --preset <preset>    Startup preset (default: full):
                         rss-only  平台只抓 RSS 类信息源（INGESTION_SOURCE_TYPES=rss,paper_rss）
                         full      全量能力（不写允许清单）
                         mirror    本地不采集，只从外部部署拉取成果
                                   （CAPABILITY_INGESTION=false + sync consumer pull，
                                    需要 SYNC_REMOTE_BASE_URL/SYNC_REMOTE_TOKEN）
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
    --preset)
      PRESET="${2:-}"
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

case "$PRESET" in
  rss-only|full|mirror)
    ;;
  *)
    echo "--preset must be one of: rss-only, full, mirror (got: ${PRESET:-<empty>})" >&2
    usage >&2
    exit 2
    ;;
esac

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
  # 本地一键起对应 standalone 形态：CSRF 默认关，方便调试。
  DEPLOY_MODE_VALUE="standalone"
  AUTH_CSRF_ENABLED_VALUE="false"
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
  # --domain 官方安装路径对应 cloud 形态：安全基线要求 CSRF 开启。
  # intranet / extranet 形态不走本脚本默认路径，请按 deploy/env.intranet.example
  # 或 deploy/env.extranet.example 手工准备 env 后使用对应 compose 文件。
  DEPLOY_MODE_VALUE="cloud"
  AUTH_CSRF_ENABLED_VALUE="true"
fi

random_hex() {
  openssl rand -hex "$1"
}

# --preset 生成的 env 组合（三预设说明见 deploy/env.production.example 顶部注释块）。
INGESTION_SCHEDULER_ENABLED_VALUE="true"
PRESET_ENV_BLOCK=""
MIRROR_PLACEHOLDER=0
if [ "$PRESET" = "rss-only" ]; then
  PRESET_ENV_BLOCK="
# --preset rss-only：平台只抓 RSS 类信息源。
# 抓取 run 内按允许清单过滤启用源，不在清单的源计入 run 摘要 skipped_type_disabled。
INGESTION_SOURCE_TYPES=rss,paper_rss"
elif [ "$PRESET" = "mirror" ]; then
  INGESTION_SCHEDULER_ENABLED_VALUE="false"
  SYNC_REMOTE_BASE_URL_VALUE="${SYNC_REMOTE_BASE_URL:-}"
  SYNC_REMOTE_TOKEN_VALUE="${SYNC_REMOTE_TOKEN:-}"
  if [ ! -f "$ENV_FILE" ] && [ -t 0 ]; then
    if [ -z "$SYNC_REMOTE_BASE_URL_VALUE" ]; then
      read -r -p "SYNC_REMOTE_BASE_URL（外部部署地址，如 https://extranet.example.com）: " SYNC_REMOTE_BASE_URL_VALUE
    fi
    if [ -z "$SYNC_REMOTE_TOKEN_VALUE" ]; then
      read -r -p "SYNC_REMOTE_TOKEN（外部部署签发的 Bearer token）: " SYNC_REMOTE_TOKEN_VALUE
    fi
  fi
  if [ -z "$SYNC_REMOTE_BASE_URL_VALUE" ]; then
    SYNC_REMOTE_BASE_URL_VALUE="REPLACE_WITH_SYNC_REMOTE_BASE_URL"
    MIRROR_PLACEHOLDER=1
  fi
  if [ -z "$SYNC_REMOTE_TOKEN_VALUE" ]; then
    SYNC_REMOTE_TOKEN_VALUE="REPLACE_WITH_SYNC_REMOTE_TOKEN"
    MIRROR_PLACEHOLDER=1
  fi
  PRESET_ENV_BLOCK="
# --preset mirror：本地不采集，只从我们的外部部署拉取成果（完整样例见 deploy/env.mirror.example）。
CAPABILITY_INGESTION=false
CAPABILITY_SYNC_CONSUMER=true
SYNC_PULL_ENABLED=true
SYNC_PULL_INTERVAL_SECONDS=900
SYNC_REMOTE_BASE_URL=$SYNC_REMOTE_BASE_URL_VALUE
SYNC_REMOTE_TOKEN=$SYNC_REMOTE_TOKEN_VALUE"
fi

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

# 部署拓扑（四形态 env 矩阵见 docs/deployment/deployment-ops.md §1.1）。
DEPLOY_MODE=$DEPLOY_MODE_VALUE
INSTANCE_ID=$DEPLOY_MODE_VALUE-main
AUTH_CSRF_ENABLED=$AUTH_CSRF_ENABLED_VALUE
# CSP frame-ancestors 白名单，默认仅允许同源 iframe。
EMBED_FRAME_ANCESTORS="'self'"
AUTH_TRUSTED_PROXY_CIDRS=
# 同步链路仅 intranet/extranet 使用（样例见 deploy/env.intranet.example / env.extranet.example）：
# SYNC_SERVICE_TOKENS=
# SYNC_REMOTE_BASE_URL=
# SYNC_REMOTE_TOKEN=
# SYNC_PULL_ENABLED=true
# SYNC_PULL_INTERVAL_SECONDS=900
# OIDC 登录（AUTH_MODE=oidc 时启用）：
# OIDC_ISSUER=
# OIDC_CLIENT_ID=
# OIDC_CLIENT_SECRET=
# OIDC_REDIRECT_URL=$APP_BASE_URL/api/auth/oidc/callback

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

INGESTION_SCHEDULER_ENABLED=$INGESTION_SCHEDULER_ENABLED_VALUE
INGESTION_SCHEDULER_DAILY_TIME=09:00
INGESTION_SCHEDULER_TIMEZONE=Asia/Shanghai
INGESTION_SCHEDULER_WORKSPACE_CODE=planning_intel
INGESTION_SCHEDULER_SOURCE_TYPES=rss,paper_rss,page_manual,page_monitor,wiseflow
INGESTION_CONCURRENCY=8
INGESTION_SOURCE_TIMEOUT_SECONDS=25
INGESTION_MAX_ITEMS_PER_SOURCE=100
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
$PRESET_ENV_BLOCK
EOF
  chmod 600 "$ENV_FILE"
  echo "Created environment file: $ENV_FILE (preset: $PRESET)"
  if [ "$MIRROR_PLACEHOLDER" = "1" ]; then
    echo "mirror preset: SYNC_REMOTE_BASE_URL / SYNC_REMOTE_TOKEN 未提供，已写入 REPLACE_WITH_* 占位值。"
    echo "请编辑 $ENV_FILE 填入外部部署的真实地址与 token 后，重新执行本脚本完成启动。"
    exit 0
  fi
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
