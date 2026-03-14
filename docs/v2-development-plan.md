# AI Trader v2.0.0 — Development Master Plan

> **Project**: Multi-Platform AI Trading System
> **Current**: v1.0.0 (XAUUSD only, MT5, Streamlit dashboard)
> **Target**: v2.0.0 (Multi-platform, Multi-AI, Web UI, Auth, Real-time)
> **Created**: 2026-03-14

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [Tech Stack Selection](#2-tech-stack-selection)
3. [Project Structure](#3-project-structure)
4. [Architecture Overview](#4-architecture-overview)
5. [Epic Breakdown & Sprint Stories](#5-epic-breakdown--sprint-stories)
6. [Database Schema v2](#6-database-schema-v2)
7. [API Design & Auth](#7-api-design--auth)
8. [AI Provider Adapter System](#8-ai-provider-adapter-system)
9. [Platform Adapter System](#9-platform-adapter-system)
10. [Real-time System (WebSocket)](#10-real-time-system-websocket)
11. [Environment Strategy](#11-environment-strategy)
12. [Security Checklist](#12-security-checklist)
13. [Performance Criteria](#13-performance-criteria)
14. [MCP Integration Strategy](#14-mcp-integration-strategy)
15. [Developer Instructions](#15-developer-instructions)

---

## 1. Vision & Goals

### What We're Building
A **production-grade, multi-platform AI trading system** with:
- **Multi-AI** — Switch between OpenRouter (Claude), NVIDIA NIM (Llama 3.1 70B), and future providers from a web UI
- **Multi-Platform** — Trade on MT5 (Forex), Bitkub (Thai crypto), Binance (Global crypto) with pluggable adapters
- **Modern Web Dashboard** — Replace Streamlit with a full React dashboard (real-time, auth, dark theme)
- **Enterprise Auth** — JWT login, API key management, RBAC
- **Real-time** — WebSocket/Socket.IO for live price feeds, trade updates, logs
- **Observability** — Full traceability: structured logs, metrics, audit trail visible in UI
- **MCP Ready** — Extensible via Model Context Protocol for third-party tool integrations

### Non-Negotiable Requirements
- 100% functional — every feature works end-to-end
- Instant responsiveness — sub-200ms API responses, <50ms WebSocket updates
- Continuous high-quality code — typed, tested, linted, reviewed
- Robust security — OWASP Top 10 compliant, encrypted secrets, auth everywhere
- Modern UX/UI — dark theme, fluid animations, future-proof design system

---

## 2. Tech Stack Selection

### Backend (Python — FastAPI)
| Layer | Technology | Why |
|-------|-----------|-----|
| **Framework** | FastAPI 0.115+ | Async, OpenAPI auto-docs, dependency injection, already in use |
| **ORM** | SQLAlchemy 2.0 + Alembic | Async ORM, migration management, type safety |
| **Auth** | python-jose (JWT) + passlib (bcrypt) | Industry standard, secure password hashing |
| **Validation** | Pydantic v2 | Fast, strict schema validation (already in use) |
| **WebSocket** | FastAPI WebSocket + redis pub/sub | Native async WS, scalable via Redis |
| **Task Queue** | Celery + Redis | Background jobs (trade sync, AI analysis) |
| **Cache** | Redis 7 | Session store, rate limiting, pub/sub, cache |
| **Database** | PostgreSQL 16 | Already in use, battle-tested, JSONB for flexible config |
| **Logging** | structlog + python-json-logger | Structured JSON logs, correlation IDs |
| **Testing** | pytest + httpx + pytest-asyncio | Async test support, API testing |

### Frontend (TypeScript — Next.js)
| Layer | Technology | Why |
|-------|-----------|-----|
| **Framework** | Next.js 15 (App Router) | SSR/SSG, API routes, file-based routing |
| **Language** | TypeScript 5.x | Type safety, better DX, catch errors at compile |
| **UI Library** | shadcn/ui + Radix UI | Accessible, beautiful, customizable components |
| **Styling** | Tailwind CSS 4 | Utility-first, dark mode built-in, fast |
| **State** | Zustand | Lightweight, no boilerplate, React 19 compatible |
| **Data Fetching** | TanStack Query (React Query) | Cache, retry, optimistic updates, stale-while-revalidate |
| **Charts** | Recharts + Lightweight Charts (TradingView) | Trading charts, performance graphs |
| **Real-time** | socket.io-client | Bi-directional real-time communication |
| **Forms** | React Hook Form + Zod | Performant forms with schema validation |
| **Theme** | next-themes | Dark/light toggle, system preference detection |
| **Icons** | Lucide React | Modern, consistent icon set |

### Infrastructure
| Layer | Technology | Why |
|-------|-----------|-----|
| **Containers** | Docker + Docker Compose | Multi-environment, reproducible |
| **Reverse Proxy** | Nginx (or Traefik) | SSL termination, load balancing, static files |
| **CI/CD** | GitHub Actions | Automated testing, building, deployment |
| **Monitoring** | Prometheus + Grafana (optional) | Metrics, alerting |

---

## 3. Project Structure

```
Trade/
├── README.md
├── .github/
│   └── workflows/
│       ├── ci.yml                    # Lint + test on PR
│       └── deploy.yml                # Build + deploy
│
├── docker/
│   ├── docker-compose.dev.yml        # Dev environment
│   ├── docker-compose.staging.yml    # Staging environment
│   ├── docker-compose.prod.yml       # Production environment
│   ├── nginx/
│   │   ├── nginx.dev.conf
│   │   └── nginx.prod.conf
│   └── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                 # DB migrations
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app factory
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py             # Pydantic Settings (env-based)
│   │   │   ├── security.py           # JWT, password hashing, API key utils
│   │   │   ├── database.py           # Async SQLAlchemy engine + session
│   │   │   ├── redis.py              # Redis connection pool
│   │   │   ├── dependencies.py       # FastAPI Depends (get_db, get_current_user)
│   │   │   └── exceptions.py         # Custom exception handlers
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               # Bearer token / API key middleware
│   │   │   ├── cors.py               # CORS configuration
│   │   │   ├── logging.py            # Request/response logging + correlation ID
│   │   │   ├── rate_limit.py         # Rate limiting (Redis-backed)
│   │   │   └── latency.py            # Response time tracking header
│   │   ├── models/                   # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── api_key.py
│   │   │   ├── trade.py
│   │   │   ├── ai_analysis.py
│   │   │   ├── ai_provider.py
│   │   │   ├── platform.py
│   │   │   ├── bot_settings.py
│   │   │   └── bot_event.py
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── user.py
│   │   │   ├── trade.py
│   │   │   ├── ai_provider.py
│   │   │   ├── platform.py
│   │   │   ├── bot.py
│   │   │   └── common.py             # Pagination, error response schemas
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py         # Aggregate all v1 routers
│   │   │       ├── auth.py           # POST /login, /register, /refresh
│   │   │       ├── users.py          # GET/PUT /users/me
│   │   │       ├── api_keys.py       # CRUD /api-keys (generate, revoke, list)
│   │   │       ├── trades.py         # GET /trades, /positions, /history
│   │   │       ├── ai_providers.py   # CRUD /ai-providers (switch, test)
│   │   │       ├── platforms.py      # CRUD /platforms (MT5, Bitkub, Binance)
│   │   │       ├── bot.py            # GET/PUT /bot/status, /bot/settings, /bot/events
│   │   │       ├── analytics.py      # GET /analytics/summary, /equity-curve
│   │   │       ├── logs.py           # GET /logs (analysis, events, system)
│   │   │       └── ws.py             # WebSocket endpoint /ws
│   │   ├── services/                 # Business logic (no HTTP knowledge)
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py
│   │   │   ├── trade_service.py
│   │   │   ├── risk_manager.py
│   │   │   ├── bot_service.py
│   │   │   ├── analytics_service.py
│   │   │   ├── websocket_manager.py  # WS connection manager + Redis pub/sub
│   │   │   ├── ai/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py           # Abstract AI provider interface
│   │   │   │   ├── openrouter.py     # OpenRouter adapter (Claude, etc.)
│   │   │   │   ├── nvidia_nim.py     # NVIDIA NIM adapter (Llama 3.1 70B)
│   │   │   │   └── registry.py       # Provider registry (factory pattern)
│   │   │   └── platforms/
│   │   │       ├── __init__.py
│   │   │       ├── base.py           # Abstract platform interface
│   │   │       ├── mt5_bridge.py     # MT5 via Windows VPS HTTP bridge
│   │   │       ├── bitkub.py         # Bitkub REST API adapter
│   │   │       ├── binance.py        # Binance REST + WS adapter
│   │   │       └── registry.py       # Platform registry (factory pattern)
│   │   └── workers/
│   │       ├── __init__.py
│   │       ├── celery_app.py         # Celery configuration
│   │       ├── trade_loop.py         # Main trading loop (refactored from xauusd_analyzer)
│   │       └── sync_worker.py        # Trade sync background task
│   └── tests/
│       ├── conftest.py
│       ├── test_auth.py
│       ├── test_trades.py
│       ├── test_ai_providers.py
│       └── test_platforms.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.ts
│   ├── .env.local.example
│   ├── public/
│   │   └── logo.svg
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx            # Root layout (providers, theme, sidebar)
│   │   │   ├── page.tsx              # Dashboard home
│   │   │   ├── login/
│   │   │   │   └── page.tsx
│   │   │   ├── dashboard/
│   │   │   │   ├── page.tsx          # Overview (replaces Streamlit overview)
│   │   │   │   ├── trades/
│   │   │   │   │   └── page.tsx      # Trade history, open positions
│   │   │   │   ├── analytics/
│   │   │   │   │   └── page.tsx      # Equity curve, daily P&L, win rate
│   │   │   │   ├── ai-providers/
│   │   │   │   │   └── page.tsx      # AI provider management (switch, test)
│   │   │   │   ├── platforms/
│   │   │   │   │   └── page.tsx      # Trading platform config (MT5, Bitkub, Binance)
│   │   │   │   ├── bot-control/
│   │   │   │   │   └── page.tsx      # Start/stop, interval, risk settings
│   │   │   │   ├── api-keys/
│   │   │   │   │   └── page.tsx      # Generate, revoke API keys
│   │   │   │   ├── logs/
│   │   │   │   │   └── page.tsx      # Real-time log viewer (WS-powered)
│   │   │   │   └── settings/
│   │   │   │       └── page.tsx      # User profile, theme, notification prefs
│   │   │   └── api/                  # Next.js API routes (BFF proxy if needed)
│   │   ├── components/
│   │   │   ├── ui/                   # shadcn/ui components (button, card, dialog...)
│   │   │   ├── layout/
│   │   │   │   ├── sidebar.tsx
│   │   │   │   ├── header.tsx
│   │   │   │   └── breadcrumb.tsx
│   │   │   ├── charts/
│   │   │   │   ├── equity-curve.tsx
│   │   │   │   ├── daily-pnl-bar.tsx
│   │   │   │   ├── sentiment-pie.tsx
│   │   │   │   └── price-chart.tsx   # TradingView lightweight chart
│   │   │   ├── trade/
│   │   │   │   ├── position-table.tsx
│   │   │   │   ├── history-table.tsx
│   │   │   │   └── trade-card.tsx
│   │   │   ├── bot/
│   │   │   │   ├── status-badge.tsx
│   │   │   │   └── control-panel.tsx
│   │   │   └── common/
│   │   │       ├── data-table.tsx    # Generic sortable/filterable table
│   │   │       ├── stat-card.tsx
│   │   │       ├── loading.tsx
│   │   │       └── error-boundary.tsx
│   │   ├── hooks/
│   │   │   ├── use-auth.ts
│   │   │   ├── use-socket.ts         # Socket.IO hook
│   │   │   ├── use-trades.ts
│   │   │   └── use-bot-status.ts
│   │   ├── lib/
│   │   │   ├── api-client.ts         # Axios/fetch wrapper with auth interceptor
│   │   │   ├── socket.ts             # Socket.IO client singleton
│   │   │   ├── utils.ts
│   │   │   └── constants.ts
│   │   ├── stores/
│   │   │   ├── auth-store.ts         # Zustand: user, tokens
│   │   │   └── app-store.ts          # Zustand: theme, sidebar state
│   │   └── types/
│   │       ├── api.ts                # API response types (mirrors backend schemas)
│   │       ├── trade.ts
│   │       └── user.ts
│   └── tests/
│       └── ...
│
├── mt5-bridge/                       # Runs on Windows VPS (unchanged from v1)
│   ├── main.py
│   └── requirements.txt
│
├── docs/
│   └── v2-development-plan.md        # THIS FILE
│
└── legacy/                           # v1 code preserved for reference
    ├── xauusd_analyzer.py
    ├── xauusd_analyzer_v1.py
    └── dashboard.py
```

---

## 4. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         NGINX REVERSE PROXY                         │
│                    (SSL, Load Balance, Static)                       │
│         :80/:443 → frontend:3000 | /api/* → backend:8000            │
└────────┬──────────────────────────────────────┬──────────────────────┘
         │                                      │
         ▼                                      ▼
┌─────────────────┐                  ┌──────────────────────┐
│   FRONTEND      │   WebSocket/     │     BACKEND          │
│   Next.js 15    │◄────────────────►│     FastAPI          │
│                 │   Socket.IO      │                      │
│  • Dashboard    │                  │  • REST API v1       │
│  • Charts       │                  │  • WebSocket Hub     │
│  • Bot Control  │                  │  • Auth (JWT/APIKey) │
│  • AI Config    │                  │  • Rate Limiting     │
│  • Log Viewer   │                  │  • Correlation IDs   │
└─────────────────┘                  └───────┬──────────────┘
                                             │
                    ┌────────────────────────┬┴──────────────────┐
                    │                        │                   │
              ┌─────▼─────┐          ┌───────▼──────┐   ┌───────▼──────┐
              │ PostgreSQL │          │    Redis     │   │   Celery     │
              │    16      │          │     7        │   │   Workers    │
              │            │          │              │   │              │
              │ • Users    │          │ • JWT Block  │   │ • Trade Loop │
              │ • Trades   │          │ • Rate Limit │   │ • Sync Jobs  │
              │ • AI Logs  │          │ • WS Pub/Sub │   │ • AI Queue   │
              │ • Settings │          │ • Cache      │   │              │
              └────────────┘          └──────────────┘   └──────┬───────┘
                                                                │
                    ┌───────────────────────────────────────────┐│
                    │          TRADING ADAPTERS                  ││
                    │                                           ▼│
                    │  ┌───────────┐  ┌────────┐  ┌─────────┐   │
                    │  │ MT5 Bridge│  │ Bitkub │  │ Binance │   │
                    │  │ (Win VPS) │  │  API   │  │  API    │   │
                    │  └───────────┘  └────────┘  └─────────┘   │
                    └───────────────────────────────────────────┘
                    ┌───────────────────────────────────────────┐
                    │            AI ADAPTERS                     │
                    │  ┌───────────┐  ┌────────────────────┐    │
                    │  │OpenRouter │  │ NVIDIA NIM         │    │
                    │  │(Claude)   │  │ (Llama 3.1 70B)    │    │
                    │  └───────────┘  └────────────────────┘    │
                    │  ┌───────────┐  ┌────────────────────┐    │
                    │  │ Future    │  │ Future             │    │
                    │  │ Provider  │  │ Provider           │    │
                    │  └───────────┘  └────────────────────┘    │
                    └───────────────────────────────────────────┘
```

---

## 5. Epic Breakdown & Sprint Stories

### EPIC 0: Foundation & Infrastructure (Sprint 1-2)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 0.1 | Set up monorepo structure (backend/, frontend/, docker/) | P0 | 3 |
| 0.2 | Backend: FastAPI app factory + Pydantic Settings + env config | P0 | 3 |
| 0.3 | Backend: Async SQLAlchemy 2.0 + Alembic migration setup | P0 | 5 |
| 0.4 | Backend: Redis connection pool + health check | P0 | 2 |
| 0.5 | Docker Compose: dev/staging/prod with Nginx + hot-reload | P0 | 5 |
| 0.6 | Backend: Structured logging (structlog) + correlation IDs | P1 | 3 |
| 0.7 | Backend: Error handling + custom exception classes | P1 | 2 |
| 0.8 | Frontend: Next.js 15 scaffold + Tailwind + shadcn/ui setup | P0 | 3 |
| 0.9 | Frontend: Dark theme system + design tokens + layout shell | P0 | 5 |
| 0.10 | CI: GitHub Actions lint + test pipeline | P1 | 3 |

### EPIC 1: Authentication & Authorization (Sprint 2-3)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 1.1 | DB: users table (id, email, hashed_password, role, created_at) | P0 | 2 |
| 1.2 | Backend: Register + Login endpoints (JWT access + refresh tokens) | P0 | 5 |
| 1.3 | Backend: Token refresh, logout (Redis blocklist) | P0 | 3 |
| 1.4 | Backend: Auth middleware (Bearer token + API key dual mode) | P0 | 5 |
| 1.5 | Backend: API key CRUD (generate, list, revoke, hash storage) | P0 | 5 |
| 1.6 | Backend: Role-based access control (admin, trader, viewer) | P1 | 3 |
| 1.7 | Backend: Rate limiting middleware (Redis, per-user/IP) | P1 | 3 |
| 1.8 | Frontend: Login page (email/password form, JWT storage) | P0 | 3 |
| 1.9 | Frontend: Auth context + protected route middleware | P0 | 3 |
| 1.10 | Frontend: API Key management page (generate, copy, revoke) | P0 | 5 |

### EPIC 2: Core Trading Engine (Sprint 3-4)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 2.1 | Backend: Abstract Platform interface (get_price, execute_trade, get_positions, get_history) | P0 | 5 |
| 2.2 | Backend: MT5 Bridge adapter (refactor from v1 main.py HTTP calls) | P0 | 3 |
| 2.3 | Backend: Platform registry (factory pattern, DB-configured) | P0 | 3 |
| 2.4 | Backend: Trade service (risk calc, lot sizing, SL/TP) | P0 | 5 |
| 2.5 | Backend: Trades API endpoints (positions, history, manual trade) | P0 | 3 |
| 2.6 | Backend: Trade sync worker (Celery: sync open/closed from platforms) | P0 | 5 |
| 2.7 | DB: Migrate trades table (add platform_id, pair columns) | P0 | 2 |
| 2.8 | Frontend: Dashboard overview page (account balance, positions, P&L) | P0 | 5 |
| 2.9 | Frontend: Trade history table (sortable, filterable, export CSV) | P0 | 5 |
| 2.10 | Frontend: Open positions panel (live updates via WS) | P0 | 5 |

### EPIC 3: AI Provider System (Sprint 4-5)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 3.1 | Backend: Abstract AI provider interface (analyze, health_check) | P0 | 3 |
| 3.2 | Backend: OpenRouter adapter (refactor from v1) | P0 | 3 |
| 3.3 | Backend: NVIDIA NIM adapter (Llama 3.1 70B via build.nvidia.com) | P0 | 5 |
| 3.4 | Backend: AI provider registry (switch active provider, DB config) | P0 | 3 |
| 3.5 | Backend: AI provider CRUD API (add, edit, test connection, switch) | P0 | 5 |
| 3.6 | DB: ai_providers table (name, type, api_key_encrypted, endpoint, model, is_active, config_json) | P0 | 3 |
| 3.7 | Backend: AI provider health check + latency measurement | P1 | 3 |
| 3.8 | Frontend: AI Providers management page (list, add, edit, test, switch active) | P0 | 8 |
| 3.9 | Frontend: AI response viewer (show analysis results in real-time) | P1 | 3 |
| 3.10 | Backend: AI analysis logging with provider traceability | P0 | 2 |

### EPIC 4: Real-time System (Sprint 5-6)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 4.1 | Backend: WebSocket manager (connection registry, rooms, broadcast) | P0 | 5 |
| 4.2 | Backend: Redis pub/sub bridge (WS ↔ Redis for multi-worker) | P0 | 5 |
| 4.3 | Backend: WS events — price_update, trade_executed, bot_status, log_entry | P0 | 5 |
| 4.4 | Frontend: Socket.IO client hook (auto-connect, reconnect, auth) | P0 | 3 |
| 4.5 | Frontend: Real-time price ticker (WS-powered) | P0 | 3 |
| 4.6 | Frontend: Live log viewer (streaming, filterable, color-coded) | P0 | 5 |
| 4.7 | Frontend: Toast notifications for trade events | P1 | 2 |
| 4.8 | Backend: WS authentication (JWT token in handshake) | P0 | 3 |

### EPIC 5: Bot Control & Settings (Sprint 6-7)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 5.1 | Backend: Bot control API (start/stop/restart, status, settings CRUD) | P0 | 5 |
| 5.2 | Backend: Bot main trading loop (refactored as Celery worker, multi-platform) | P0 | 8 |
| 5.3 | Backend: Bot events API (list, filter by type, date range) | P0 | 3 |
| 5.4 | Frontend: Bot control panel (start/stop, status badge, settings form) | P0 | 5 |
| 5.5 | Frontend: Bot event log (color-coded, filterable, auto-scroll) | P0 | 3 |
| 5.6 | Backend: Per-platform bot configuration (symbols, risk per platform) | P1 | 5 |

### EPIC 6: Analytics & Reporting (Sprint 7-8)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 6.1 | Backend: Analytics API (summary stats, equity curve, daily/weekly/monthly P&L) | P0 | 5 |
| 6.2 | Frontend: Equity curve chart (TradingView lightweight charts) | P0 | 5 |
| 6.3 | Frontend: Daily P&L bar chart (green/red, hover details) | P0 | 3 |
| 6.4 | Frontend: Performance metrics cards (win rate, R:R, profit factor, expectancy) | P0 | 3 |
| 6.5 | Frontend: Sentiment distribution pie chart | P1 | 2 |
| 6.6 | Frontend: Weekly/Monthly summary tables | P1 | 3 |
| 6.7 | Frontend: CSV/PDF export | P2 | 3 |

### EPIC 7: Multi-Platform Expansion (Sprint 8-10)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 7.1 | Backend: Bitkub adapter (REST API: price, order, positions, history) | P0 | 8 |
| 7.2 | Backend: Binance adapter (REST + WS: price, order, positions, history) | P0 | 8 |
| 7.3 | Backend: Platform CRUD API (add, configure, test connection, enable/disable) | P0 | 5 |
| 7.4 | DB: platforms table (name, type, api_key_encrypted, api_secret_encrypted, config_json, is_active) | P0 | 3 |
| 7.5 | Frontend: Platform management page (add, config form per type, test, toggle) | P0 | 8 |
| 7.6 | Backend: 24h trading support (crypto has no market hours) | P1 | 3 |
| 7.7 | Frontend: Multi-platform dashboard filter (dropdown: All, MT5, Bitkub, Binance) | P1 | 3 |

### EPIC 8: MCP & Extensibility (Sprint 10-11)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 8.1 | Backend: MCP client integration (connect to third-party MCP servers) | P1 | 8 |
| 8.2 | Backend: MCP tool registry (list available tools, invoke) | P1 | 5 |
| 8.3 | Frontend: MCP configuration page (add server, auth, test) | P2 | 5 |
| 8.4 | Backend: Webhook system (outgoing: trade events → n8n, Zapier) | P2 | 5 |
| 8.5 | Frontend: Webhook management (add URL, select events, test) | P2 | 3 |

### EPIC 9: Polish & Production Hardening (Sprint 11-12)

| # | Story | Priority | Points |
|---|-------|----------|--------|
| 9.1 | Backend: Comprehensive test suite (≥80% coverage) | P0 | 8 |
| 9.2 | Frontend: E2E tests (Playwright) | P1 | 5 |
| 9.3 | Security audit (OWASP checklist, penetration testing) | P0 | 5 |
| 9.4 | Performance profiling + optimization | P0 | 5 |
| 9.5 | Documentation (API docs, deployment guide, user guide) | P1 | 5 |
| 9.6 | Production Docker Compose (resource limits, restart policies, secrets) | P0 | 3 |

---

## 6. Database Schema v2

```sql
-- ===================== USERS =====================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100),
    role            VARCHAR(20) NOT NULL DEFAULT 'trader',  -- admin, trader, viewer
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== API KEYS =====================
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,              -- friendly name
    key_prefix      VARCHAR(8) NOT NULL,                -- first 8 chars (for display)
    key_hash        VARCHAR(255) NOT NULL,              -- bcrypt hash of full key
    scopes          TEXT[] DEFAULT '{}',                 -- future: granular permissions
    is_active       BOOLEAN DEFAULT TRUE,
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== AI PROVIDERS =====================
CREATE TABLE ai_providers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,              -- "OpenRouter Claude", "NVIDIA Llama"
    provider_type   VARCHAR(50) NOT NULL,               -- "openrouter", "nvidia_nim", "openai"
    endpoint_url    VARCHAR(500) NOT NULL,
    model           VARCHAR(200) NOT NULL,
    api_key_enc     BYTEA,                              -- encrypted API key (AES-256)
    max_tokens      INTEGER DEFAULT 100,
    temperature     NUMERIC(3,2) DEFAULT 0.1,
    config_json     JSONB DEFAULT '{}',                 -- provider-specific extra config
    is_active       BOOLEAN DEFAULT FALSE,              -- only 1 active at a time
    last_health_at  TIMESTAMPTZ,
    avg_latency_ms  INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== TRADING PLATFORMS =====================
CREATE TABLE trading_platforms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,              -- "MT5 Live", "Binance Spot"
    platform_type   VARCHAR(50) NOT NULL,               -- "mt5", "bitkub", "binance"
    endpoint_url    VARCHAR(500),                       -- connection URL/IP
    api_key_enc     BYTEA,                              -- encrypted (Bitkub/Binance)
    api_secret_enc  BYTEA,                              -- encrypted
    config_json     JSONB DEFAULT '{}',                 -- e.g. {"symbols": ["XAUUSD"], "magic": 888888}
    is_active       BOOLEAN DEFAULT FALSE,
    market_hours    VARCHAR(50) DEFAULT '24h',          -- "forex" or "24h"
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== TRADES (enhanced) =====================
CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID REFERENCES trading_platforms(id),
    order_id        VARCHAR(100),                       -- external order ID (MT5 ticket, exchange order ID)
    symbol          VARCHAR(30) NOT NULL,
    action          VARCHAR(10) NOT NULL,               -- BUY / SELL
    lot             NUMERIC(12,6) NOT NULL,             -- crypto can have 6 decimals
    open_price      NUMERIC(16,8),
    close_price     NUMERIC(16,8),
    sl_price        NUMERIC(16,8),
    tp_price        NUMERIC(16,8),
    profit          NUMERIC(16,4),
    commission      NUMERIC(12,4),
    swap            NUMERIC(12,4),
    status          VARCHAR(20) DEFAULT 'OPEN',
    ai_provider_id  UUID REFERENCES ai_providers(id),   -- which AI made the decision
    ai_analysis_id  UUID,                               -- link to analysis log
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    UNIQUE(platform_id, order_id)
);

-- ===================== AI ANALYSIS LOG (enhanced) =====================
CREATE TABLE ai_analysis_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_provider_id      UUID REFERENCES ai_providers(id),
    platform_id         UUID REFERENCES trading_platforms(id),
    symbol              VARCHAR(30) NOT NULL,
    bid                 NUMERIC(16,8),
    ask                 NUMERIC(16,8),
    ai_recommendation   TEXT,
    sentiment           VARCHAR(20),                    -- BULLISH / BEARISH / NEUTRAL
    trade_action        VARCHAR(10) DEFAULT 'WAIT',
    lot_size            NUMERIC(12,6),
    sl_price            NUMERIC(16,8),
    tp_price            NUMERIC(16,8),
    latency_ms          INTEGER,                        -- AI response time
    correlation_id      VARCHAR(50),                    -- trace across services
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== BOT SETTINGS (enhanced) =====================
CREATE TABLE bot_settings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id         UUID REFERENCES trading_platforms(id),
    is_running          BOOLEAN DEFAULT TRUE,
    interval_seconds    INTEGER DEFAULT 300,
    max_trades_per_day  INTEGER DEFAULT 10,
    risk_percent        NUMERIC(5,2) DEFAULT 1.0,
    sl_points           NUMERIC(10,2) DEFAULT 300,
    tp_points           NUMERIC(10,2) DEFAULT 600,
    pause_max_retries   INTEGER DEFAULT 5,
    pause_retry_sec     INTEGER DEFAULT 10,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== BOT EVENTS =====================
CREATE TABLE bot_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID REFERENCES trading_platforms(id),
    event_type      VARCHAR(50) NOT NULL,
    message         TEXT,
    severity        VARCHAR(10) DEFAULT 'INFO',        -- INFO, WARN, ERROR, CRITICAL
    correlation_id  VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== AUDIT LOG =====================
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(100),
    details         JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== MCP CONNECTIONS =====================
CREATE TABLE mcp_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    server_url      VARCHAR(500) NOT NULL,
    transport_type  VARCHAR(20) DEFAULT 'stdio',       -- "stdio", "sse", "streamable_http"
    auth_config     JSONB DEFAULT '{}',                 -- encrypted auth details
    is_active       BOOLEAN DEFAULT FALSE,
    tools_json      JSONB DEFAULT '[]',                 -- cached available tools list
    last_connected  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ===================== INDEXES =====================
CREATE INDEX idx_trades_platform_status ON trades (platform_id, status);
CREATE INDEX idx_trades_opened ON trades (opened_at DESC);
CREATE INDEX idx_trades_closed ON trades (closed_at DESC NULLS LAST);
CREATE INDEX idx_ai_log_created ON ai_analysis_log (created_at DESC);
CREATE INDEX idx_ai_log_provider ON ai_analysis_log (ai_provider_id);
CREATE INDEX idx_bot_events_created ON bot_events (created_at DESC);
CREATE INDEX idx_bot_events_type ON bot_events (event_type);
CREATE INDEX idx_audit_user ON audit_log (user_id, created_at DESC);
CREATE INDEX idx_api_keys_hash ON api_keys (key_hash);
```

---

## 7. API Design & Auth

### Authentication Flow

```
┌──────────┐         ┌──────────┐         ┌──────────┐
│  Client   │──POST──►│  /login   │──verify─►│  Users   │
│           │         │          │◄─────────│   DB     │
│           │◄─JWT────┤          │          └──────────┘
│           │ access  └──────────┘
│           │ +refresh
│           │
│           │──GET────► /api/v1/* ─── Bearer {access_token}
│           │──GET────► /api/v1/* ─── X-API-Key: {api_key}
└──────────┘
```

### Auth Modes (dual support on every endpoint)
1. **Bearer Token (JWT)** — For web UI sessions
   - Access token: 15 min expiry, in memory (not localStorage)
   - Refresh token: 7 days, httpOnly secure cookie
2. **API Key** — For programmatic access / external integrations
   - Header: `X-API-Key: atk_xxxxxxxxxxxxxxxxxxxxxxxx`
   - Stored as bcrypt hash in DB (never plain text)
   - Prefix `atk_` + 32 random chars

### API Endpoints (v1)

```
POST   /api/v1/auth/register          # Create account
POST   /api/v1/auth/login             # Get JWT tokens
POST   /api/v1/auth/refresh           # Refresh access token
POST   /api/v1/auth/logout            # Revoke refresh token
GET    /api/v1/users/me               # Get current user profile
PUT    /api/v1/users/me               # Update profile

GET    /api/v1/api-keys               # List user's API keys
POST   /api/v1/api-keys               # Generate new API key
DELETE /api/v1/api-keys/{id}          # Revoke API key

GET    /api/v1/trades                 # List trades (filter: status, platform, date)
GET    /api/v1/trades/positions       # Open positions (live)
GET    /api/v1/trades/history         # Closed trades
POST   /api/v1/trades                 # Manual trade execution

GET    /api/v1/ai-providers           # List all providers
POST   /api/v1/ai-providers           # Add new provider
PUT    /api/v1/ai-providers/{id}      # Update provider config
DELETE /api/v1/ai-providers/{id}      # Remove provider
POST   /api/v1/ai-providers/{id}/test # Test connection + latency
PUT    /api/v1/ai-providers/{id}/activate  # Set as active provider

GET    /api/v1/platforms              # List trading platforms
POST   /api/v1/platforms              # Add platform
PUT    /api/v1/platforms/{id}         # Update platform config
DELETE /api/v1/platforms/{id}         # Remove platform
POST   /api/v1/platforms/{id}/test    # Test connection

GET    /api/v1/bot/status             # Bot running status
PUT    /api/v1/bot/start              # Start bot
PUT    /api/v1/bot/stop               # Stop bot
PUT    /api/v1/bot/restart            # Restart bot
GET    /api/v1/bot/settings           # Get bot settings
PUT    /api/v1/bot/settings           # Update bot settings
GET    /api/v1/bot/events             # Event log (paginated)

GET    /api/v1/analytics/summary      # Performance summary (period filter)
GET    /api/v1/analytics/equity-curve # Equity curve data
GET    /api/v1/analytics/daily-pnl    # Daily P&L data

GET    /api/v1/logs                   # AI analysis logs (paginated)

WS     /api/v1/ws                     # WebSocket (auth via query token)

GET    /api/v1/health                 # Health check (no auth)
```

### Response Time Headers
Every response includes:
```
X-Request-ID: abc-123-def       # Correlation ID
X-Response-Time: 45ms           # Server processing time
```

---

## 8. AI Provider Adapter System

```python
# backend/app/services/ai/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class AIAnalysisResult(BaseModel):
    sentiment: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    action: str             # "BUY" | "SELL" | "WAIT"
    reason: str
    raw_response: str
    latency_ms: int
    provider_name: str
    model: str

class BaseAIProvider(ABC):
    """Abstract base class for all AI providers"""

    @abstractmethod
    async def analyze(self, symbol: str, bid: float, ask: float,
                      context: dict | None = None) -> AIAnalysisResult:
        """Send market data to AI and get trading recommendation"""
        ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, int]:
        """Check if provider is reachable. Returns (is_healthy, latency_ms)"""
        ...

    @abstractmethod
    def provider_type(self) -> str:
        """Return provider type identifier"""
        ...
```

### Supported Providers (v2.0.0)

| Provider | Type | Models | Endpoint |
|----------|------|--------|----------|
| **OpenRouter** | `openrouter` | Claude 3 Haiku, GPT-4o, etc. | `https://openrouter.ai/api/v1/chat/completions` |
| **NVIDIA NIM** | `nvidia_nim` | Llama 3.1 70B Instruct | `https://integrate.api.nvidia.com/v1/chat/completions` |

### Adding a New Provider
1. Create adapter class extending `BaseAIProvider`
2. Register in `registry.py`
3. Add to DB via API/UI — no code changes needed for config

---

## 9. Platform Adapter System

```python
# backend/app/services/platforms/base.py
from abc import ABC, abstractmethod

class PriceData(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: int

class TradeResult(BaseModel):
    success: bool
    order_id: str | None
    price: float | None
    error: str | None

class BasePlatform(ABC):
    """Abstract base class for all trading platforms"""

    @abstractmethod
    async def get_price(self, symbol: str) -> PriceData | None: ...

    @abstractmethod
    async def execute_trade(self, action: str, symbol: str, lot: float,
                            sl: float, tp: float) -> TradeResult: ...

    @abstractmethod
    async def get_positions(self) -> list[dict]: ...

    @abstractmethod
    async def get_history(self, days: int = 7) -> list[dict]: ...

    @abstractmethod
    async def get_account(self) -> dict: ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, int]: ...

    @abstractmethod
    def platform_type(self) -> str: ...

    @abstractmethod
    def market_hours_type(self) -> str:
        """Return 'forex' (with market hours check) or '24h' (crypto)"""
        ...
```

| Platform | Type | Market | Notes |
|----------|------|--------|-------|
| **MT5** | `mt5` | Forex hours | Via Windows VPS HTTP bridge (unchanged) |
| **Bitkub** | `bitkub` | 24h | REST API, Thai Baht pairs |
| **Binance** | `binance` | 24h | REST + WebSocket, global pairs |

---

## 10. Real-time System (WebSocket)

### WebSocket Events

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `price:update` | Server→Client | `{symbol, bid, ask, platform}` | Live price feed |
| `trade:opened` | Server→Client | `{trade object}` | New trade executed |
| `trade:closed` | Server→Client | `{trade object}` | Trade closed |
| `trade:updated` | Server→Client | `{trade object}` | P/L updated |
| `bot:status` | Server→Client | `{is_running, platform}` | Bot status change |
| `bot:event` | Server→Client | `{event_type, message}` | Bot event log entry |
| `ai:analysis` | Server→Client | `{analysis result}` | AI analysis completed |
| `log:entry` | Server→Client | `{level, message, timestamp}` | System log entry |

### Architecture
```
Workers/Bot ──publish──► Redis Pub/Sub ──subscribe──► WS Manager ──broadcast──► Clients
```

---

## 11. Environment Strategy

### Three Environments

| Env | Purpose | DB | External APIs | Debug |
|-----|---------|-----|--------------|-------|
| **dev** | Local development | PostgreSQL (Docker, port 5432) | Mocked or sandbox | Full debug, hot-reload |
| **staging** | Pre-release testing | PostgreSQL (Docker, port 5433) | Sandbox keys | Partial debug |
| **prod** | Live trading | PostgreSQL (Docker, port 5434) | Real keys | No debug, structured logs only |

### Docker Compose Files

```bash
# Development (hot-reload, debug, exposed ports)
docker compose -f docker/docker-compose.dev.yml up

# Staging (production-like, sandbox APIs)
docker compose -f docker/docker-compose.staging.yml up

# Production (optimized, no exposed DB ports, resource limits)
docker compose -f docker/docker-compose.prod.yml up -d
```

### Environment Variables (per-env .env files)

```bash
# docker/.env.dev
APP_ENV=development
DEBUG=true
LOG_LEVEL=DEBUG
SECRET_KEY=dev-secret-not-for-production
DB_HOST=db
DB_PORT=5432
CORS_ORIGINS=http://localhost:3000
...

# docker/.env.prod
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
SECRET_KEY=<random-64-char-generated>
DB_HOST=db
DB_PORT=5432
CORS_ORIGINS=https://yourdomain.com
...
```

---

## 12. Security Checklist

- [x] **A01 Broken Access Control** → JWT + RBAC on every endpoint, API key scoping
- [x] **A02 Cryptographic Failures** → AES-256 encrypted API keys in DB, bcrypt passwords, TLS termination
- [x] **A03 Injection** → SQLAlchemy ORM (parameterized), Pydantic validation, no raw SQL
- [x] **A04 Insecure Design** → Rate limiting, input validation, fail-secure defaults
- [x] **A05 Security Misconfiguration** → Env-based config, no defaults in prod, security headers
- [x] **A06 Vulnerable Components** → Dependabot alerts, pinned versions, regular updates
- [x] **A07 Auth Failures** → bcrypt(12), short-lived JWT, refresh token rotation, blocklist
- [x] **A08 Data Integrity** → Signed JWTs, schema validation, CSP headers
- [x] **A09 Logging Failures** → Structured logging with correlation IDs, audit trail, no secrets in logs
- [x] **A10 SSRF** → Allowlist for external URLs, no user-controlled redirects

### Additional Security Measures
- CORS restricted per environment
- CSRF protection via SameSite cookies
- Request body size limits
- SQL query timeout limits
- API key hashed (never stored in plain text)
- Secrets encrypted at rest in DB (AES-256-GCM)
- Helmet-equivalent security headers via Nginx

---

## 13. Performance Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| API Response (p50) | < 100ms | X-Response-Time header |
| API Response (p95) | < 200ms | Structured log aggregation |
| API Response (p99) | < 500ms | Structured log aggregation |
| WebSocket Latency | < 50ms | Client-side ping measurement |
| AI Analysis Round-trip | < 3s | Measured per provider, shown in UI |
| Trade Execution E2E | < 2s | From decision to order confirmation |
| Dashboard Initial Load | < 2s | Lighthouse / Web Vitals |
| Dashboard Interaction | < 100ms (INP) | Core Web Vitals |
| DB Query (p95) | < 50ms | SQLAlchemy event hooks |
| Concurrent Users | 50+ | Load testing |
| Concurrent WS Connections | 200+ | Redis pub/sub scaling |

### How We Measure
- Every API response includes `X-Response-Time` header
- Structured logs include `latency_ms` field
- Frontend: React Query devtools + Web Vitals reporting
- Backend: middleware auto-measures and logs slow queries (>100ms)

---

## 14. MCP Integration Strategy

### What is MCP for This Project?
MCP (Model Context Protocol) allows the AI trading bot to access external **tools** (data sources, calculators, news feeds) via standardized protocol.

### Use Cases
1. **Market News Feed** — MCP server providing real-time news affecting XAUUSD / crypto
2. **Technical Indicators** — MCP server computing RSI, MACD, Bollinger from price history
3. **Economic Calendar** — MCP server for upcoming events (FOMC, NFP)
4. **Custom Signals** — Third-party signal providers exposed as MCP tools

### Architecture
```
AI Provider ← prompt includes tool results ← MCP Client ← MCP Server(s)
```

### UI Management
- Add/remove MCP server connections (URL, auth type)
- View available tools per server
- Enable/disable specific tools
- Test connection
- View tool invocation history

### n8n Integration
- Optional: n8n as automation layer alongside MCP
- Backend exposes webhooks for trade events → n8n workflows
- n8n can trigger custom actions (send Telegram alerts, update spreadsheets)
- Configured via UI webhook management page

---

## 15. Developer Instructions

### Senior Fullstack Developer Guidelines

#### Code Quality Standards
- **Python Backend**: PEP 8, type hints everywhere, async/await consistently
- **TypeScript Frontend**: Strict mode, no `any`, exhaustive switch cases
- **Both**: Single responsibility, dependency injection, interface-first design

#### Git Workflow
```
main               ← production (tagged releases only)
├── develop        ← integration branch
│   ├── epic/0-foundation
│   ├── epic/1-auth
│   ├── epic/2-trading-engine
│   ├── epic/3-ai-providers
│   ├── epic/4-realtime
│   ├── epic/5-bot-control
│   ├── epic/6-analytics
│   ├── epic/7-multi-platform
│   ├── epic/8-mcp
│   └── epic/9-hardening
```

#### Branch Naming
- `epic/<number>-<name>` — Epic branches
- `feature/<epic>/<story>` — Feature branches (e.g., `feature/1/login-endpoint`)
- `fix/<ticket>-<description>` — Bug fixes
- `hotfix/<description>` — Production hotfix

#### Commit Messages (Conventional Commits)
```
feat(auth): add JWT login endpoint
fix(trade): handle null price in MT5 response
refactor(ai): extract provider registry pattern
test(auth): add API key generation tests
docs(api): update endpoint documentation
chore(docker): add Redis to dev compose
```

#### PR Requirements
- All checks pass (lint + test)
- At least 1 approval
- No `TODO` or `FIXME` in new code (use issues instead)
- No secrets, no hardcoded URLs

#### Testing Requirements
- Backend: ≥80% coverage, integration tests for every endpoint
- Frontend: Component tests for key flows, E2E for auth + trade execution
- All tests must pass before merge

---

## Appendix: Quick Reference Commands

```bash
# Start development environment
docker compose -f docker/docker-compose.dev.yml up --build

# Run backend tests
docker compose -f docker/docker-compose.dev.yml exec backend pytest -v

# Run Alembic migration
docker compose -f docker/docker-compose.dev.yml exec backend alembic upgrade head

# Create new migration
docker compose -f docker/docker-compose.dev.yml exec backend alembic revision --autogenerate -m "description"

# Frontend dev (outside Docker for fast HMR)
cd frontend && npm run dev

# Build frontend
cd frontend && npm run build

# Lint all
cd backend && ruff check . && cd ../frontend && npm run lint
```

---

*This plan is the single source of truth for v2.0.0 development. Update this document as decisions evolve.*
