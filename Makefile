COMPOSE = docker compose -p infowatchtower -f deploy/docker-compose.local.yml

.PHONY: up down restart ps logs backend-logs frontend-logs test e2e build migrate migration-check docs-check frontend-controls-check

up:
	$(COMPOSE) up -d

build:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

backend-logs:
	$(COMPOSE) logs -f --tail=100 backend

frontend-logs:
	$(COMPOSE) logs -f --tail=100 frontend

test:
	python3 scripts/validate_docs_governance.py
	python3 scripts/validate_frontend_controls.py
	cd backend && . .venv/bin/activate && DATABASE_URL="" pytest
	cd frontend && npx vitest run
	cd frontend && npm run build

# 浏览器级 e2e（Playwright smoke，可选 target，不进 make test/CI 门禁：
# chromium 首次需 ~100MB 下载且耗时，门禁保持快速确定性；本地/发版前手动跑）。
e2e:
	cd frontend && npx playwright install chromium
	cd frontend && npx playwright test

docs-check:
	python3 scripts/validate_docs_governance.py

frontend-controls-check:
	python3 scripts/validate_frontend_controls.py

migrate:
	$(COMPOSE) build backend
	$(COMPOSE) run --rm backend alembic upgrade head

migration-check:
	cd backend && rm -f .migration_check.sqlite && . .venv/bin/activate && DATABASE_URL="sqlite:///./.migration_check.sqlite" alembic upgrade head
	cd backend && . .venv/bin/activate && DATABASE_URL="sqlite:///./.migration_check.sqlite" alembic check
	cd backend && rm -f .migration_check.sqlite
