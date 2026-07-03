COMPOSE = docker compose --env-file deploy/.env -p infowatchtower -f deploy/docker-compose.local.yml

.PHONY: up down restart ps logs backend-logs frontend-logs test build migrate migration-check

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
	cd backend && . .venv/bin/activate && DATABASE_URL="" pytest
	cd frontend && npm run build

migrate:
	$(COMPOSE) build backend
	$(COMPOSE) run --rm backend alembic upgrade head

migration-check:
	cd backend && rm -f .migration_check.sqlite && . .venv/bin/activate && DATABASE_URL="sqlite:///./.migration_check.sqlite" alembic upgrade head
	cd backend && . .venv/bin/activate && DATABASE_URL="sqlite:///./.migration_check.sqlite" alembic check
	cd backend && rm -f .migration_check.sqlite
