#!/usr/bin/env bash

set -e

TASK=$1
ARGS=${@:2}

COMPOSE_DEV="docker compose -f docker/docker-compose.dev.yml"
COMPOSE_STAGE="docker compose -f docker/docker-compose.staging.yml"
COMPOSE_PROD="docker compose -f docker/docker-compose.prod.yml"

# ==========================================
# Development
# ==========================================

help__dev="Start full dev environment (all services)"
task_dev() {
  $COMPOSE_DEV up --build
}

help__backend="Start backend + db + redis only"
task_backend() {
  $COMPOSE_DEV up --build db redis backend
}

help__frontend="Start frontend only (needs backend running)"
task_frontend() {
  $COMPOSE_DEV up --build frontend
}

help__db="Start database only"
task_db() {
  $COMPOSE_DEV up --build db
}

help__redis="Start redis only"
task_redis() {
  $COMPOSE_DEV up --build redis
}

help__worker="Start celery worker (needs db + redis)"
task_worker() {
  $COMPOSE_DEV up --build db redis worker
}

# ==========================================
# Control
# ==========================================

help__up="Start all services in background (detached)"
task_up() {
  $COMPOSE_DEV up --build -d
}

help__down="Stop all services"
task_down() {
  $COMPOSE_DEV down
}

help__restart="Restart all services"
task_restart() {
  $COMPOSE_DEV down
  $COMPOSE_DEV up --build -d
}

help__build="Rebuild all images (no cache)"
task_build() {
  $COMPOSE_DEV build --no-cache
}

help__logs="Tail logs [service] (default: all)"
task_logs() {
  if [[ -n "$1" ]]; then
    $COMPOSE_DEV logs -f "$1"
  else
    $COMPOSE_DEV logs -f
  fi
}

help__status="Show running containers"
task_status() {
  $COMPOSE_DEV ps
}

# ==========================================
# Shell Access
# ==========================================

help__shell="Shell into container [back, front, db]"
task_shell() {
  case "$1" in
    back)  $COMPOSE_DEV exec backend bash ;;
    front) $COMPOSE_DEV exec frontend sh ;;
    db)    $COMPOSE_DEV exec db psql -U admin -d trading_log ;;
    *)     echo "Usage: ./go shell [back|front|db]" ;;
  esac
}

# ==========================================
# Code Quality
# ==========================================

help__lint="Run ruff linter on backend"
task_lint() {
  $COMPOSE_DEV exec backend ruff check app/
}

help__format="Format backend code with ruff"
task_format() {
  $COMPOSE_DEV exec backend ruff format app/
}

help__test="Run backend tests"
task_test() {
  $COMPOSE_DEV exec backend python -m pytest tests/ -v --tb=short
}

help__typecheck="Run mypy type check on backend"
task_typecheck() {
  $COMPOSE_DEV exec backend mypy app/
}

# ==========================================
# Database
# ==========================================

help__migrate="Run alembic migrations"
task_migrate() {
  $COMPOSE_DEV exec backend alembic upgrade head
}

help__migrate_new="Create new migration (usage: ./go migrate_new 'add users')"
task_migrate_new() {
  local msg="${*:-auto}"
  $COMPOSE_DEV exec backend alembic revision --autogenerate -m "$msg"
}

# ==========================================
# Cleanup
# ==========================================

help__clean="Stop and remove containers"
task_clean() {
  $COMPOSE_DEV down --remove-orphans
}

help__nuke="Stop + remove containers + volumes (DELETES DATA!)"
task_nuke() {
  echo -e "\033[31mWARNING: This will delete all data volumes!\033[0m"
  read -rp "Type 'yes' to confirm: " confirm
  if [[ "$confirm" == "yes" ]]; then
    $COMPOSE_DEV down -v --remove-orphans
  else
    echo "Cancelled."
  fi
}

# ==========================================
## Main
# ==========================================

list_all_helps() {
  compgen -v | egrep "^help__.*" | while read -r var; do
    task_name="${var#help__}"
    printf "  %-18s %s\n" "./go $task_name" "${!var}"
  done
}

list_all_tasks() {
  compgen -A function | egrep "^task_.*" | sed 's/task_//g'
}

task_help() {
  echo ""
  echo "  AI Trader v2 - Command Runner"
  echo "  ============================="
  echo ""
  list_all_helps
  echo ""
}

if [[ -z "$TASK" ]] || [[ "$TASK" == "help" ]]; then
  task_help
elif type "task_$TASK" &>/dev/null; then
  "task_$TASK" $ARGS
else
  echo "Unknown command: $TASK"
  task_help
  exit 1
fi
