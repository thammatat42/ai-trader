# AI XAUUSD Trader v1.0.0 (Demo)

An AI-powered automated trading bot for **XAUUSD (Gold)** using Claude AI analysis and MetaTrader 5 execution, with a real-time Streamlit admin dashboard.

> **v1.0.0** — Demo release supporting XAUUSD only.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Linux Server (Docker)                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  AI Trader   │  │  Dashboard   │  │  PostgreSQL  │  │
│  │  (Bot Loop)  │  │  (Streamlit) │  │  (Trade Log) │  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘  │
│         │ HTTP                                          │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────┐
│  Windows VPS        │
│  ┌───────────────┐  │
│  │ MT5 Bridge    │  │
│  │ (FastAPI)     │  │
│  └───────┬───────┘  │
│          │          │
│  ┌───────▼───────┐  │
│  │  MetaTrader 5 │  │
│  └───────────────┘  │
└─────────────────────┘
```

**Three main components:**

| Component | Tech | Description |
|-----------|------|-------------|
| **AI Trader Bot** | Python + Claude AI | Fetches price → AI analysis → executes trades |
| **MT5 Bridge API** | FastAPI + MetaTrader5 | Runs on Windows VPS, bridges HTTP to MT5 |
| **Admin Dashboard** | Streamlit + Plotly | Real-time monitoring, performance charts, bot control |

---

## Features

- **AI-Powered Analysis** — Uses Claude 3 Haiku via OpenRouter for BUY/SELL/HOLD decisions
- **Automated Execution** — Sends orders directly to MetaTrader 5
- **Risk Management** — Dynamic lot sizing based on account balance and configurable risk percentage
- **Market Hours Filter** — Trades only during Forex market hours (Sun–Fri UTC)
- **Admin Dashboard** — Equity curves, trade history, win rate, P/L tracking
- **Bot Control** — Pause/Resume trading from the dashboard
- **Trade Logging** — All AI analyses and trades logged to PostgreSQL
- **Docker Deployment** — Full stack containerized with docker-compose
- **Error Recovery** — Auto-reconnect to MT5, graceful shutdown

---

## Quick Start

### Prerequisites

- **Linux server** (or any Docker-capable machine) for the bot + dashboard
- **Windows VPS** with MetaTrader 5 installed and logged in
- **OpenRouter API key** for Claude AI access

### 1. Clone & Configure

```bash
git clone <your-repo-url>
cd Trade
cp env.example .env
```

Edit `.env` with your actual values:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
WINDOWS_IP=your-windows-vps-ip
ACCOUNT_BALANCE=1000.00
RISK_PERCENT=1.0
```

### 2. Start the Bot Stack (Linux/Docker)

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL** on port `5432`
- **AI Trader Bot** (auto-connects to MT5 Bridge)
- **Streamlit Dashboard** on port `8501`

### 3. Start the MT5 Bridge (Windows VPS)

```bash
pip install fastapi uvicorn MetaTrader5
cd server/ec2-windows
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. Access Dashboard

Open `http://<linux-server-ip>:8501` in your browser.

---

## API Endpoints (MT5 Bridge)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check & MT5 connection status |
| `GET` | `/price/{symbol}` | Get current bid/ask price |
| `POST` | `/trade` | Execute a BUY/SELL trade |
| `GET` | `/positions` | List open positions (AI Bot only) |
| `GET` | `/history?days=7` | Trade history (1–90 days) |
| `GET` | `/account` | Account balance, equity, margin info |

---

## Project Structure

```
Trade/
├── xauusd_analyzer.py        # Main AI trading bot (loop)
├── xauusd_analyzer_v1.py     # Analyzer v1 (reference)
├── dashboard.py               # Streamlit admin dashboard
├── docker-compose.yml         # Full stack orchestration
├── Dockerfile                 # Bot container image
├── requirements.txt           # Python dependencies
├── env.example                # Environment template
├── db/
│   ├── init.sql               # Database schema
│   └── migrate_add_bot_tables.sql  # Bot settings migration
├── server/
│   └── ec2-windows/
│       └── main.py            # MT5 Bridge API (FastAPI)
└── docs/                      # Documentation
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key for Claude AI |
| `MODEL` | `anthropic/claude-3-haiku` | AI model to use |
| `WINDOWS_IP` | — | IP of the Windows VPS running MT5 Bridge |
| `SYMBOL` | `XAUUSD` | Trading symbol |
| `ACCOUNT_BALANCE` | `1000.00` | Account balance for lot calculation |
| `RISK_PERCENT` | `1.0` | Risk per trade (% of balance) |
| `SL_POINTS` | `300` | Stop Loss in points |
| `TP_POINTS` | `600` | Take Profit in points |
| `DB_HOST` | `db` | PostgreSQL host |
| `DB_USER` | `admin` | PostgreSQL user |
| `DB_PASS` | `secretpassword` | PostgreSQL password |
| `DB_NAME` | `trading_log` | PostgreSQL database name |

---

## Roadmap

### v1.0.0 — Demo (Current Release)
- [x] XAUUSD automated trading with AI analysis
- [x] MetaTrader 5 integration via Windows VPS bridge
- [x] PostgreSQL trade logging
- [x] Streamlit admin dashboard
- [x] Docker deployment

### v2.0.0 — Multi-Platform Trading (Planned)
- [ ] Web-based dynamic configuration UI
- [ ] Multi-platform support:
  - [ ] **Bitkub** — Thai crypto exchange integration
  - [ ] **Binance** — Global crypto exchange integration
- [ ] 24-hour crypto trading (no market hours restriction)
- [ ] Platform-specific API adapters (pluggable architecture)
- [ ] Web dashboard for managing trading pairs & platform settings
- [ ] Per-platform risk management configuration

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Engine | Claude 3 Haiku (via OpenRouter) |
| Trading Bot | Python 3.11+ |
| MT5 Bridge | FastAPI + MetaTrader5 |
| Dashboard | Streamlit + Plotly |
| Database | PostgreSQL 15 |
| Deployment | Docker + Docker Compose |

---

## License

This project is proprietary. All rights reserved.

---

## Disclaimer

This software is for **demonstration and educational purposes only**. Trading financial instruments involves substantial risk of loss. Past performance does not guarantee future results. Use at your own risk.
