#!/usr/bin/env bash
set -euo pipefail

# intranet 离线升级：在内网主机执行，配套 scripts/export_offline_bundle.sh 的产物。
# 流程：校验 sha256 -> docker load 镜像 -> compose up（backend 以 RUN_MIGRATIONS=true
# 启动，入口脚本自动执行 alembic upgrade，与 install.sh 在线路径一致）。
# 数据库数据在 /srv/infowatchtower/postgres_data，跨版本保留；回滚先恢复备份再导入旧包。

BUNDLE_DIR=""
ENV_FILE="/srv/infowatchtower/.env.intranet"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/upgrade_offline.sh --bundle <extracted-bundle-dir> [--env-file <path>]

Options:
  --bundle <dir>       Extracted offline bundle directory (contains images.tar/manifest.txt)
  --env-file <path>    Intranet env file (default: /srv/infowatchtower/.env.intranet)
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle)
      BUNDLE_DIR="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
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

if [ -z "$BUNDLE_DIR" ]; then
  echo "--bundle is required" >&2
  usage >&2
  exit 2
fi
BUNDLE_DIR="$(cd "$BUNDLE_DIR" && pwd)"

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose is required" >&2; exit 1; }

for required in images.tar manifest.txt checksums.sha256 deploy/docker-compose.intranet.yml; do
  if [ ! -f "$BUNDLE_DIR/$required" ]; then
    echo "Bundle is missing $required: $BUNDLE_DIR" >&2
    exit 1
  fi
done

if [ ! -f "$ENV_FILE" ]; then
  echo "Environment file not found: $ENV_FILE" >&2
  echo "First install: copy $BUNDLE_DIR/deploy/env.intranet.example there and fill it in." >&2
  exit 1
fi

echo "Verifying bundle checksums"
(
  cd "$BUNDLE_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c checksums.sha256 >/dev/null
  else
    shasum -a 256 -c checksums.sha256 >/dev/null
  fi
)

VERSION="$(sed -n 's/^version=//p' "$BUNDLE_DIR/manifest.txt")"
if [ -z "$VERSION" ]; then
  echo "manifest.txt has no version field" >&2
  exit 1
fi

echo "Loading images from bundle (version: $VERSION)"
docker load -i "$BUNDLE_DIR/images.tar"

COMPOSE_FILE="$BUNDLE_DIR/deploy/docker-compose.intranet.yml"

compose() {
  # APP_VERSION 决定 compose 选用的镜像 tag；--no-build 确保只用离线导入的镜像。
  APP_VERSION="$VERSION" INFOWATCHTOWER_ENV_FILE="$ENV_FILE" \
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose up -d --no-build

echo "Waiting for API health inside backend container"
for _ in $(seq 1 60); do
  if compose exec -T backend python - <<'PY' >/dev/null 2>&1
import urllib.request

urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3).read()
PY
  then
    echo "Offline upgrade complete (version: $VERSION)."
    echo "Migration manifest: $BUNDLE_DIR/alembic_versions.txt"
    exit 0
  fi
  sleep 5
done

echo "Timed out waiting for API health. Inspect logs with:" >&2
echo "APP_VERSION=\"$VERSION\" INFOWATCHTOWER_ENV_FILE=\"$ENV_FILE\" docker compose --env-file \"$ENV_FILE\" -f \"$COMPOSE_FILE\" logs backend" >&2
exit 1
