#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED_SERVICES = ("postgres", "redis", "backend", "worker", "scheduler", "reverse_proxy")
REQUIRED_ENV_KEYS = (
    "APP_ENV",
    "APP_BASE_URL",
    "ENABLE_DOCS",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "AUTH_MODE",
    "AUTH_SESSION_SECRET",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD",
    "INGESTION_SCHEDULER_TIMEZONE",
    "SCHEDULER_JOB_MODE",
)
SECRET_KEYS = ("POSTGRES_PASSWORD", "AUTH_SESSION_SECRET", "AUTH_BOOTSTRAP_ADMIN_PASSWORD")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def check_prod_deploy(root: Path, env_file: Path) -> list[str]:
    errors: list[str] = []
    compose_path = root / "deploy" / "docker-compose.prod.yml"
    caddy_path = root / "deploy" / "Caddyfile"
    for path in (compose_path, caddy_path, env_file):
        if not path.exists():
            errors.append(f"missing file: {path}")
    if errors:
        return errors

    compose = compose_path.read_text(encoding="utf-8")
    caddy = caddy_path.read_text(encoding="utf-8")
    env = parse_env(env_file)

    for service in REQUIRED_SERVICES:
        if f"  {service}:" not in compose:
            errors.append(f"docker-compose.prod.yml missing service: {service}")
    for forbidden_port in ('"5432:5432"', "'5432:5432'", "- 5432:5432", '"6379:6379"', "'6379:6379'", "- 6379:6379"):
        if forbidden_port in compose:
            errors.append(f"production compose must not expose internal port: {forbidden_port}")
    if "/api/*" not in caddy or "reverse_proxy backend:8000" not in caddy:
        errors.append("Caddyfile must route /api/* to backend:8000")
    if "try_files {path} /index.html" not in caddy:
        errors.append("Caddyfile must serve Vue history fallback with try_files")

    for key in REQUIRED_ENV_KEYS:
        if not env.get(key):
            errors.append(f"env missing required key: {key}")
    if env.get("APP_ENV") != "production":
        errors.append("APP_ENV must be production")
    if env.get("ENABLE_DOCS", "").lower() != "false":
        errors.append("ENABLE_DOCS must be false in production")
    if env.get("AUTH_MODE") not in {"public_password", "intranet_header", "oidc", "intranet_oidc", "saml"}:
        errors.append("AUTH_MODE is not one of the supported production modes")
    for key in SECRET_KEYS:
        value = env.get(key, "")
        if not value or "change_me" in value.lower() or value.lower() in {"password", "secret"}:
            errors.append(f"{key} must not use a development default")
    if "localhost" in env.get("DATABASE_URL", ""):
        errors.append("DATABASE_URL should target the compose postgres service, not localhost")
    if env.get("INGESTION_SCHEDULER_TIMEZONE") != "Asia/Shanghai":
        errors.append("INGESTION_SCHEDULER_TIMEZONE should be Asia/Shanghai for the planning daily flow")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check InfoWatchtower production deployment files.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument(
        "--env-file",
        default="deploy/env.production.example",
        help="production env file or template to check",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    env_file = (root / args.env_file).resolve() if not Path(args.env_file).is_absolute() else Path(args.env_file)
    errors = check_prod_deploy(root, env_file)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Production deployment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
