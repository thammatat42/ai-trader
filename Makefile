# ==========================================
# AI Trader v2 – Command Runner
# ==========================================
# Usage:  make <command>
# Run in Git Bash or any terminal with make
# ==========================================

COMPOSE_DEV    = docker compose -f docker/docker-compose.dev.yml
COMPOSE_STAGE  = docker compose -f docker/docker-compose.staging.yml
COMPOSE_PROD   = docker compose -f docker/docker-compose.prod.yml

.PHONY: help dev up down build logs status \
        backend frontend db redis worker \
        shell-back shell-front shell-db \
        lint test migrate clean nuke

# ---- Help (default) ----
help: ## Show this help
	@echo ""
	@echo "  AI Trader v2 - Command Runner"
	@echo "  ============================="
	@echo ""
	@echo "  DEVELOPMENT"
	@echo "    make dev            Start full dev environment (all services)"
	@echo "    make backend        Start backend + db + redis only"
	@echo "    make frontend       Start frontend only"
	@echo "    make db             Start database only"
	@echo "    make redis          Start redis only"
	@echo "    make worker         Start celery worker only"
	@echo ""
	@echo "  CONTROL"
	@echo "    make down           Stop all services"
	@echo "    make restart        Restart all services"
	@echo "    make build          Rebuild all images (no cache)"
	@echo "    make logs           Tail logs (all services)"
	@echo "    make logs-back      Tail backend logs"
	@echo "    make logs-front     Tail frontend logs"
	@echo "    make status         Show running containers"
	@echo ""
	@echo "  SHELL ACCESS"
	@echo "    make shell-back     Shell into backend container"
	@echo "    make shell-front    Shell into frontend container"
	@echo "    make shell-db       Open psql in database container"
	@echo ""
	@echo "  CODE QUALITY"
	@echo "    make lint           Run ruff linter on backend"
	@echo "    make format         Format backend code with ruff"
	@echo "    make test           Run backend tests"
	@echo "    make type-check     Run mypy type check on backend"
	@echo ""
	@echo "  DATABASE"
	@echo "    make migrate        Run alembic migrations"
	@echo "    make migrate-new    Create new migration (usage: make migrate-new msg='add users')"
	@echo ""
	@echo "  CLEANUP"
	@echo "    make clean          Stop and remove containers"
	@echo "    make nuke           Stop, remove containers + volumes (DELETES DATA)"
	@echo ""

# ---- Development ----
dev: ## Start full dev environment
	$(COMPOSE_DEV) up --build

backend: ## Start backend + db + redis
	$(COMPOSE_DEV) up --build db redis backend

frontend: ## Start frontend only (needs backend running)
	$(COMPOSE_DEV) up --build frontend

db: ## Start database only
	$(COMPOSE_DEV) up --build db

redis: ## Start redis only
	$(COMPOSE_DEV) up --build redis

worker: ## Start celery worker (needs db + redis running)
	$(COMPOSE_DEV) up --build db redis worker

# ---- Control ----
up: ## Start services in background (detached)
	$(COMPOSE_DEV) up --build -d

down: ## Stop all services
	$(COMPOSE_DEV) down

restart: ## Restart all services
	$(COMPOSE_DEV) down
	$(COMPOSE_DEV) up --build -d

build: ## Rebuild all images without cache
	$(COMPOSE_DEV) build --no-cache

logs: ## Tail all logs
	$(COMPOSE_DEV) logs -f

logs-back: ## Tail backend logs
	$(COMPOSE_DEV) logs -f backend

logs-front: ## Tail frontend logs
	$(COMPOSE_DEV) logs -f frontend

status: ## Show running containers
	$(COMPOSE_DEV) ps

# ---- Shell Access ----
shell-back: ## Shell into backend container
	$(COMPOSE_DEV) exec backend bash

shell-front: ## Shell into frontend container
	$(COMPOSE_DEV) exec frontend sh

shell-db: ## Open psql in database container
	$(COMPOSE_DEV) exec db psql -U admin -d trading_log

# ---- Code Quality ----
lint: ## Run ruff linter
	$(COMPOSE_DEV) exec backend ruff check app/

format: ## Format backend code
	$(COMPOSE_DEV) exec backend ruff format app/

test: ## Run backend tests
	$(COMPOSE_DEV) exec backend python -m pytest tests/ -v --tb=short

type-check: ## Run mypy type check
	$(COMPOSE_DEV) exec backend mypy app/

# ---- Database ----
migrate: ## Run alembic migrations
	$(COMPOSE_DEV) exec backend alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new msg="add users")
	$(COMPOSE_DEV) exec backend alembic revision --autogenerate -m "$(msg)"

# ---- Cleanup ----
clean: ## Stop and remove containers
	$(COMPOSE_DEV) down --remove-orphans

nuke: ## Stop, remove containers + volumes (DELETES DATA!)
	$(COMPOSE_DEV) down -v --remove-orphans
