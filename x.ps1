<#
.SYNOPSIS
    AI Trader v2 - Command Runner (PowerShell)
.DESCRIPTION
    Centralized command runner for development, testing, and deployment.
    Usage: .\x.ps1 <command> [args]
.EXAMPLE
    .\x.ps1 dev          # Start full dev environment
    .\x.ps1 backend      # Start backend + db + redis
    .\x.ps1 down         # Stop everything
    .\x.ps1 logs         # Tail logs
    .\x.ps1 help         # Show all commands
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments)]
    [string[]]$Args
)

$ComposeDev   = "docker compose -f docker/docker-compose.dev.yml"
$ComposeStage = "docker compose -f docker/docker-compose.staging.yml"
$ComposeProd  = "docker compose -f docker/docker-compose.prod.yml"

function Show-Help {
    Write-Host ""
    Write-Host "  AI Trader v2 - Command Runner" -ForegroundColor Cyan
    Write-Host "  =============================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  DEVELOPMENT" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 dev            Start full dev environment (all services)"
    Write-Host "    .\x.ps1 backend        Start backend + db + redis only"
    Write-Host "    .\x.ps1 frontend       Start frontend only"
    Write-Host "    .\x.ps1 db             Start database only"
    Write-Host "    .\x.ps1 redis          Start redis only"
    Write-Host "    .\x.ps1 worker         Start celery worker only"
    Write-Host ""
    Write-Host "  CONTROL" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 up             Start all in background (detached)"
    Write-Host "    .\x.ps1 down           Stop all services"
    Write-Host "    .\x.ps1 restart        Restart all services"
    Write-Host "    .\x.ps1 build          Rebuild all images (no cache)"
    Write-Host "    .\x.ps1 logs           Tail logs (all services)"
    Write-Host "    .\x.ps1 logs-back      Tail backend logs"
    Write-Host "    .\x.ps1 logs-front     Tail frontend logs"
    Write-Host "    .\x.ps1 status         Show running containers"
    Write-Host ""
    Write-Host "  SHELL ACCESS" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 shell-back     Shell into backend container"
    Write-Host "    .\x.ps1 shell-front    Shell into frontend container"
    Write-Host "    .\x.ps1 shell-db       Open psql in database container"
    Write-Host ""
    Write-Host "  CODE QUALITY" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 lint           Run ruff linter on backend"
    Write-Host "    .\x.ps1 format         Format backend code with ruff"
    Write-Host "    .\x.ps1 test           Run backend tests"
    Write-Host "    .\x.ps1 type-check     Run mypy type check"
    Write-Host ""
    Write-Host "  DATABASE" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 migrate        Run alembic migrations"
    Write-Host "    .\x.ps1 migrate-new 'add users'   Create new migration"
    Write-Host ""
    Write-Host "  CLEANUP" -ForegroundColor Yellow
    Write-Host "    .\x.ps1 clean          Stop and remove containers"
    Write-Host "    .\x.ps1 nuke           Stop + remove containers + volumes (DELETES DATA)"
    Write-Host ""
}

function Invoke-Compose {
    param([string]$Arguments)
    Invoke-Expression "$ComposeDev $Arguments"
}

switch ($Command) {
    # ---- Development ----
    "dev"         { Invoke-Compose "up --build" }
    "backend"     { Invoke-Compose "up --build db redis backend" }
    "frontend"    { Invoke-Compose "up --build frontend" }
    "db"          { Invoke-Compose "up --build db" }
    "redis"       { Invoke-Compose "up --build redis" }
    "worker"      { Invoke-Compose "up --build db redis worker" }

    # ---- Control ----
    "up"          { Invoke-Compose "up --build -d" }
    "down"        { Invoke-Compose "down" }
    "restart"     { Invoke-Compose "down"; Invoke-Compose "up --build -d" }
    "build"       { Invoke-Compose "build --no-cache" }
    "logs"        { Invoke-Compose "logs -f" }
    "logs-back"   { Invoke-Compose "logs -f backend" }
    "logs-front"  { Invoke-Compose "logs -f frontend" }
    "status"      { Invoke-Compose "ps" }

    # ---- Shell Access ----
    "shell-back"  { Invoke-Compose "exec backend bash" }
    "shell-front" { Invoke-Compose "exec frontend sh" }
    "shell-db"    { Invoke-Compose "exec db psql -U admin -d trading_log" }

    # ---- Code Quality ----
    "lint"        { Invoke-Compose "exec backend ruff check app/" }
    "format"      { Invoke-Compose "exec backend ruff format app/" }
    "test"        { Invoke-Compose "exec backend python -m pytest tests/ -v --tb=short" }
    "type-check"  { Invoke-Compose "exec backend mypy app/" }

    # ---- Database ----
    "migrate"     { Invoke-Compose "exec backend alembic upgrade head" }
    "migrate-new" {
        $msg = if ($Args) { $Args -join " " } else { "auto" }
        Invoke-Compose "exec backend alembic revision --autogenerate -m `"$msg`""
    }

    # ---- Cleanup ----
    "clean"       { Invoke-Compose "down --remove-orphans" }
    "nuke"        {
        Write-Host "WARNING: This will delete all data volumes!" -ForegroundColor Red
        $confirm = Read-Host "Type 'yes' to confirm"
        if ($confirm -eq "yes") {
            Invoke-Compose "down -v --remove-orphans"
        } else {
            Write-Host "Cancelled."
        }
    }

    # ---- Help ----
    "help"        { Show-Help }
    default       { Write-Host "Unknown command: $Command" -ForegroundColor Red; Show-Help }
}
