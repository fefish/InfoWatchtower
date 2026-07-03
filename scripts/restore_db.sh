#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/restore_db.sh <backup.sql|backup.sql.gz>" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${INFOWATCHTOWER_ENV_FILE:-/srv/infowatchtower/.env.production}"
compose_file="${INFOWATCHTOWER_COMPOSE_FILE:-$repo_root/deploy/docker-compose.prod.yml}"
backup_file="$1"

if [[ "$env_file" != /* ]]; then
  env_file="$repo_root/$env_file"
fi
if [[ "$compose_file" != /* ]]; then
  compose_file="$repo_root/$compose_file"
fi

if [[ ! -f "$backup_file" ]]; then
  echo "Backup file not found: $backup_file" >&2
  exit 2
fi

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

if [[ "${RESTORE_CONFIRM:-}" != "yes" ]]; then
  echo "This will restore InfoWatchtower PostgreSQL data from: $backup_file" >&2
  read -r -p "Type RESTORE to continue: " answer
  if [[ "$answer" != "RESTORE" ]]; then
    echo "Restore cancelled." >&2
    exit 1
  fi
fi

stream_backup() {
  if [[ "$backup_file" == *.gz ]]; then
    gzip -dc "$backup_file"
  else
    cat "$backup_file"
  fi
}

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

restore_with_host_tool() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    return 1
  fi
  local database_url
  database_url="$(normalize_database_url "$DATABASE_URL")"
  stream_backup | psql "$database_url"
}

restore_with_compose() {
  local postgres_user="${POSTGRES_USER:-infowatchtower}"
  local postgres_db="${POSTGRES_DB:-infowatchtower}"
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(compose_args)
  stream_backup | (
    cd "$repo_root"
    INFOWATCHTOWER_ENV_FILE="$env_file" docker compose "${args[@]}" exec -T postgres \
      psql -U "$postgres_user" "$postgres_db"
  )
}

if command -v psql >/dev/null 2>&1 && [[ -n "${DATABASE_URL:-}" ]]; then
  if restore_with_host_tool; then
    echo "Restore completed. Restart API, worker and scheduler containers before accepting traffic."
    exit 0
  fi
fi

restore_with_compose
echo "Restore completed. Restart API, worker and scheduler containers before accepting traffic."
