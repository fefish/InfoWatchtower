#!/usr/bin/env bash
set -euo pipefail

# intranet 离线升级包导出：在有外网与构建能力的机器上执行。
# 产出 tar.gz（docker save 全部镜像 + alembic 迁移清单 + compose/env 样例 +
# 门户反代样例 + 升级脚本 + sha256 校验和），拷入内网后用
# scripts/upgrade_offline.sh 导入并升级（内网无 git pull / 本机构建能力）。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION=""
OUTPUT_DIR="$REPO_ROOT/dist"
VITE_BASE_PATH="/watchtower/"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/export_offline_bundle.sh [--version <tag>] [--output <dir>] [--base-path <path>]

Options:
  --version <tag>      Image tag and bundle version (default: git describe or date)
  --output <dir>       Output directory for the bundle tarball (default: <repo>/dist)
  --base-path <path>   VITE_BASE_PATH for the frontend build (default: /watchtower/)
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --base-path)
      VITE_BASE_PATH="${2:-}"
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
command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }

if [ -z "$VERSION" ]; then
  VERSION="$(git -C "$REPO_ROOT" describe --tags --always 2>/dev/null || date +%Y%m%d%H%M)"
fi

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$1" && sha256sum "$2")
  else
    (cd "$1" && shasum -a 256 "$2")
  fi
}

BUNDLE_NAME="infowatchtower-offline-$VERSION"
STAGE_DIR="$(mktemp -d)"
BUNDLE_DIR="$STAGE_DIR/$BUNDLE_NAME"
mkdir -p "$BUNDLE_DIR/deploy" "$BUNDLE_DIR/scripts" "$OUTPUT_DIR"
trap 'rm -rf "$STAGE_DIR"' EXIT

echo "Building images (version: $VERSION)"
# 镜像名与 deploy/docker-compose.intranet.yml 的 image 字段一致，
# 内网侧 docker load 后 compose up --no-build 直接复用。
docker build -t "infowatchtower-backend:$VERSION" "$REPO_ROOT/backend"
docker build -t "infowatchtower-frontend:$VERSION" \
  --build-arg "VITE_BASE_PATH=$VITE_BASE_PATH" "$REPO_ROOT/frontend"
docker pull postgres:16-alpine
docker pull redis:7-alpine

echo "Saving images to images.tar"
docker save -o "$BUNDLE_DIR/images.tar" \
  "infowatchtower-backend:$VERSION" \
  "infowatchtower-frontend:$VERSION" \
  postgres:16-alpine \
  redis:7-alpine

echo "Collecting deploy artifacts and alembic manifest"
cp "$REPO_ROOT/deploy/docker-compose.intranet.yml" "$BUNDLE_DIR/deploy/"
cp "$REPO_ROOT/deploy/env.intranet.example" "$BUNDLE_DIR/deploy/"
cp "$REPO_ROOT/deploy/nginx.portal.example.conf" "$BUNDLE_DIR/deploy/"
cp "$SCRIPT_DIR/upgrade_offline.sh" "$BUNDLE_DIR/scripts/"
# backend/worker/scheduler 挂载 ../config，离线主机没有仓库，随包携带。
cp -R "$REPO_ROOT/config" "$BUNDLE_DIR/config"
# alembic 版本清单：升级排障时对照数据库 alembic_version 与包内迁移链。
(cd "$REPO_ROOT/backend/alembic/versions" && ls -1 -- *.py | sort) >"$BUNDLE_DIR/alembic_versions.txt"

cat >"$BUNDLE_DIR/manifest.txt" <<EOF
bundle=$BUNDLE_NAME
version=$VERSION
vite_base_path=$VITE_BASE_PATH
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
images=infowatchtower-backend:$VERSION,infowatchtower-frontend:$VERSION,postgres:16-alpine,redis:7-alpine
EOF

echo "Writing checksums"
(
  cd "$BUNDLE_DIR"
  : >checksums.sha256
  find . -type f ! -name checksums.sha256 | sort | while read -r file; do
    checksum "$BUNDLE_DIR" "${file#./}" >>checksums.sha256
  done
)

TARBALL="$OUTPUT_DIR/$BUNDLE_NAME.tar.gz"
tar -czf "$TARBALL" -C "$STAGE_DIR" "$BUNDLE_NAME"

echo "Offline bundle created: $TARBALL"
echo "Copy it into the intranet host, then run:"
echo "  tar -xzf $BUNDLE_NAME.tar.gz && $BUNDLE_NAME/scripts/upgrade_offline.sh --bundle $BUNDLE_NAME"
