#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${INFOWATCHTOWER_ENV_FILE:-/srv/infowatchtower/.env.production}"
compose_file="${INFOWATCHTOWER_COMPOSE_FILE:-$repo_root/deploy/docker-compose.prod.yml}"
backup_dir="${BACKUP_DIR:-/srv/infowatchtower/backups}"
keep_count="${BACKUP_KEEP:-14}"

if [[ "$env_file" != /* ]]; then
  env_file="$repo_root/$env_file"
fi
if [[ "$compose_file" != /* ]]; then
  compose_file="$repo_root/$compose_file"
fi

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

mkdir -p "$backup_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/infowatchtower_${timestamp}.sql"
backup_gz="${backup_file}.gz"

normalize_database_url() {
  local database_url="$1"
  case "$database_url" in
    postgresql+psycopg://*) printf 'postgresql://%s\n' "${database_url#postgresql+psycopg://}" ;;
    postgresql+psycopg2://*) printf 'postgresql://%s\n' "${database_url#postgresql+psycopg2://}" ;;
    *) printf '%s\n' "$database_url" ;;
  esac
}

compose_args() {
  if [[ -f "$env_file" ]]; then
    printf '%s\0' --env-file "$env_file"
  fi
  printf '%s\0' -f "$compose_file"
}

dump_with_host_tool() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    return 1
  fi
  local database_url
  database_url="$(normalize_database_url "$DATABASE_URL")"
  pg_dump --clean --if-exists --no-owner --no-privileges "$database_url"
}

dump_with_compose() {
  local postgres_user="${POSTGRES_USER:-infowatchtower}"
  local postgres_db="${POSTGRES_DB:-infowatchtower}"
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(compose_args)
  (
    cd "$repo_root"
    INFOWATCHTOWER_ENV_FILE="$env_file" docker compose "${args[@]}" exec -T postgres \
      pg_dump --clean --if-exists --no-owner --no-privileges -U "$postgres_user" "$postgres_db"
  )
}

if command -v pg_dump >/dev/null 2>&1 && dump_with_host_tool >"$backup_file"; then
  :
else
  dump_with_compose >"$backup_file"
fi

gzip -f "$backup_file"

backups=()
while IFS= read -r backup; do
  backups+=("$backup")
done < <(find "$backup_dir" -type f -name "infowatchtower_*.sql.gz" | sort -r)
for ((index = keep_count; index < ${#backups[@]}; index++)); do
  rm -f "${backups[$index]}"
done

echo "Backup written: $backup_gz"
