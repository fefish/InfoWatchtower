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
    "DEPLOY_MODE",
    "AUTH_MODE",
    "AUTH_SESSION_SECRET",
    "INGESTION_SCHEDULER_TIMEZONE",
    "SCHEDULER_JOB_MODE",
)
SECRET_KEYS = ("POSTGRES_PASSWORD", "AUTH_SESSION_SECRET")

# 四种部署形态与各自的 compose 工件（契约：config/contracts/deployment_modes.json）。
VALID_DEPLOY_MODES = ("standalone", "cloud", "intranet", "extranet")
MODE_COMPOSE_FILES = {
    "standalone": "docker-compose.prod.yml",
    "cloud": "docker-compose.prod.yml",
    "intranet": "docker-compose.intranet.yml",
    "extranet": "docker-compose.extranet.yml",
}
# TLS 收口（C-6）由可选 caddy profile 承载的形态。
TLS_PROFILE_MODES = {"cloud", "extranet"}


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
    if not env_file.exists():
        return [f"missing file: {env_file}"]
    env = parse_env(env_file)

    deploy_mode = env.get("DEPLOY_MODE", "")
    if deploy_mode not in VALID_DEPLOY_MODES:
        errors.append(
            "DEPLOY_MODE must be one of standalone/cloud/intranet/extranet"
            f" (got: {deploy_mode or '<empty>'})"
        )
    compose_name = MODE_COMPOSE_FILES.get(deploy_mode, "docker-compose.prod.yml")
    compose_path = root / "deploy" / compose_name
    nginx_path = root / "frontend" / "nginx.conf"
    caddy_path = root / "deploy" / "Caddyfile"
    for path in (compose_path, nginx_path, caddy_path):
        if not path.exists():
            errors.append(f"missing file: {path}")
    if errors:
        return errors

    compose = compose_path.read_text(encoding="utf-8")
    nginx = nginx_path.read_text(encoding="utf-8")
    caddy = caddy_path.read_text(encoding="utf-8")

    for service in REQUIRED_SERVICES:
        if f"  {service}:" not in compose:
            errors.append(f"{compose_name} missing service: {service}")
    for forbidden_port in ('"5432:5432"', "'5432:5432'", "- 5432:5432", '"6379:6379"', "'6379:6379'", "- 6379:6379"):
        if forbidden_port in compose:
            errors.append(f"production compose must not expose internal port: {forbidden_port}")
    if "healthcheck:" not in compose or "/healthz" not in compose:
        errors.append("backend service must expose a /healthz healthcheck")
    if "condition: service_healthy" not in compose:
        errors.append("worker/scheduler/reverse_proxy should depend on backend service_healthy")
    if "EMBED_FRAME_ANCESTORS" not in compose:
        errors.append(f"{compose_name} must pass EMBED_FRAME_ANCESTORS to reverse_proxy")

    # 路由与嵌入安全底座在前端 nginx 模板（浏览器真正执行 CSP 的 HTML 响应处）。
    if "proxy_pass http://backend:8000/api/" not in nginx:
        errors.append("frontend/nginx.conf must route /api/ to backend:8000")
    if "try_files $uri $uri/ /index.html" not in nginx:
        errors.append("frontend/nginx.conf must serve Vue history fallback with try_files")
    if "frame-ancestors ${EMBED_FRAME_ANCESTORS}" not in nginx:
        errors.append("frontend/nginx.conf must emit Content-Security-Policy frame-ancestors from EMBED_FRAME_ANCESTORS")
    if 'proxy_set_header X-Employee-No ""' not in nginx:
        errors.append("frontend/nginx.conf must blank inbound identity headers on /api/ (X-Employee-No etc.)")

    # TLS 收口（C-6）：cloud/extranet 的 compose 必须带可选 caddy profile 并真正挂载 Caddyfile。
    if deploy_mode in TLS_PROFILE_MODES:
        if "  caddy:" not in compose or 'profiles: ["tls"]' not in compose:
            errors.append(f"{compose_name} must define an optional caddy service with profiles: [\"tls\"]")
        if "./Caddyfile:/etc/caddy/Caddyfile" not in compose:
            errors.append(f"{compose_name} caddy service must mount deploy/Caddyfile")
        if "{$CADDY_DOMAIN" not in caddy:
            errors.append("Caddyfile must read the TLS domain from env (CADDY_DOMAIN)")
        if "reverse_proxy reverse_proxy:80" not in caddy:
            errors.append("Caddyfile must terminate TLS and forward to the frontend nginx (reverse_proxy:80)")

    # intranet：backend/前端只绑回环，宿主机不得直接暴露 80。
    if deploy_mode == "intranet" and '"80:80"' in compose:
        errors.append("intranet compose must not bind port 80 on the host; only the portal gateway may reach it")

    for key in REQUIRED_ENV_KEYS:
        if not env.get(key):
            errors.append(f"env missing required key: {key}")
    if env.get("APP_ENV") != "production":
        errors.append("APP_ENV must be production")
    if env.get("ENABLE_DOCS", "").lower() != "false":
        errors.append("ENABLE_DOCS must be false in production")
    if env.get("AUTH_MODE") not in {"public_password", "intranet_header", "oidc", "intranet_oidc", "intranet_saml"}:
        errors.append("AUTH_MODE is not one of the supported production modes")
    for key in SECRET_KEYS:
        value = env.get(key, "")
        if not value or "change_me" in value.lower() or value.lower() in {"password", "secret"}:
            errors.append(f"{key} must not use a development default")
    if "localhost" in env.get("DATABASE_URL", ""):
        errors.append("DATABASE_URL should target the compose postgres service, not localhost")
    if env.get("INGESTION_SCHEDULER_TIMEZONE") != "Asia/Shanghai":
        errors.append("INGESTION_SCHEDULER_TIMEZONE should be Asia/Shanghai for the planning daily flow")

    # 拓扑条件校验（对齐契约 startup_failfast_rules，提前在部署工件层拦住非法组合）。
    if deploy_mode == "extranet" and not env.get("SYNC_SERVICE_TOKENS"):
        errors.append("extranet requires non-empty SYNC_SERVICE_TOKENS (startup fail-fast)")
    if deploy_mode == "intranet":
        if env.get("AUTH_MODE") != "intranet_header":
            errors.append("intranet requires AUTH_MODE=intranet_header (startup fail-fast)")
        for key in ("SYNC_REMOTE_BASE_URL", "SYNC_REMOTE_TOKEN"):
            if not env.get(key):
                errors.append(f"intranet requires {key} for sync pull")
    if deploy_mode in {"cloud", "extranet"} and env.get("AUTH_CSRF_ENABLED", "").lower() == "false":
        errors.append(f"{deploy_mode} must not disable CSRF (AUTH_CSRF_ENABLED=false)")
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
