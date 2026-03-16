"""
🎛️  AI Trader – Admin Dashboard (Streamlit)
=============================================
ใช้ควบคุม Bot, ดู Reports, ดู Event Log และปรับ Settings
รันด้วย:  streamlit run dashboard.py --server.port 8501
"""

import os
import time
import psycopg2
import psycopg2.extras
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="AI Gold Trader Dashboard",
    page_icon="🥇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================
# ENTERPRISE DARK THEME CSS
# ==========================================
st.markdown("""
<style>
/* ===== GLOBAL DARK THEME ===== */
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0a0e17 0%, #111827 50%, #0f172a 100%);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
    border-right: 1px solid #1e293b;
}
[data-testid="stHeader"] {
    background: transparent;
}

/* ===== METRIC CARDS ===== */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1e293b 0%, #162032 100%);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    transition: transform 0.2s, box-shadow 0.2s;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
[data-testid="stMetricLabel"] {
    color: #94a3b8 !important;
    font-size: 0.8rem !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
[data-testid="stMetricValue"] {
    color: #f1f5f9 !important;
    font-weight: 700 !important;
}

/* ===== BUTTONS ===== */
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
    letter-spacing: 0.3px;
    transition: all 0.2s;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
    border: none;
    color: #0f172a;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
    box-shadow: 0 4px 16px rgba(245,158,11,0.3);
}

/* ===== DATAFRAMES / TABLES ===== */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #1e293b;
}

/* ===== FORM CONTAINER ===== */
[data-testid="stForm"] {
    background: linear-gradient(135deg, #1e293b 0%, #162032 100%);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 24px;
}

/* ===== SECTION HEADERS ===== */
h1 {
    color: #f1f5f9 !important;
    font-weight: 800 !important;
    letter-spacing: -0.5px;
}
h2, h3 {
    color: #e2e8f0 !important;
    font-weight: 600 !important;
}

/* ===== DIVIDER ===== */
hr {
    border-color: #1e293b !important;
}

/* ===== CUSTOM CARD CLASS ===== */
.card-panel {
    background: linear-gradient(135deg, #1e293b 0%, #162032 100%);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.card-panel h4 {
    color: #f59e0b;
    margin-top: 0;
    font-weight: 700;
}
.gold-accent { color: #f59e0b; }
.green-accent { color: #22c55e; }
.red-accent { color: #ef4444; }
.text-muted { color: #94a3b8; font-size: 0.85rem; }

/* ===== STATUS BADGES ===== */
.status-running {
    display: inline-block;
    background: linear-gradient(135deg, #22c55e33, #16a34a33);
    border: 1px solid #22c55e;
    color: #22c55e;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.85rem;
}
.status-stopped {
    display: inline-block;
    background: linear-gradient(135deg, #ef444433, #dc262633);
    border: 1px solid #ef4444;
    color: #ef4444;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.85rem;
}

/* ===== SIDEBAR STYLING ===== */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {
    color: #f59e0b !important;
    font-size: 1.3rem !important;
}

/* ===== EXPANDER ===== */
[data-testid="stExpander"] {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
}

/* ===== INFO/SUCCESS/ERROR ===== */
[data-testid="stAlert"] {
    border-radius: 8px;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# DB HELPER
# ==========================================
@st.cache_resource
def get_conn():
    """Persistent DB connection (Streamlit cache)"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASS", "secretpassword"),
        dbname=os.getenv("DB_NAME", "trading_log"),
    )


def run_query(sql, params=None, fetchall=True):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetchall:
                return cur.fetchall()
            conn.commit()
            return None
    except psycopg2.OperationalError:
        # reconnect once
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "db"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASS", "secretpassword"),
            dbname=os.getenv("DB_NAME", "trading_log"),
        )
        st.cache_resource.clear()
        st.rerun()


def run_command(sql, params=None):
    """Execute INSERT / UPDATE / DELETE"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.OperationalError:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "db"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASS", "secretpassword"),
            dbname=os.getenv("DB_NAME", "trading_log"),
        )
        st.cache_resource.clear()
        st.rerun()


# ==========================================
# MT5 API HELPER – ดึงข้อมูลจาก Windows VPS
# ==========================================
import requests as req_lib

def mt5_api(endpoint: str, params: dict = None, timeout: int = 8):
    """เรียก MT5 Bridge API บน Windows VPS"""
    windows_ip = os.getenv("WINDOWS_IP", "")
    if not windows_ip:
        return None
    try:
        resp = req_lib.get(f"http://{windows_ip}:8000{endpoint}",
                           params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def sync_mt5_to_db():
    """
    ซิงค์ข้อมูลจาก MT5 → trades table ใน PostgreSQL
    - /positions → UPSERT เป็น OPEN trades
    - /history   → UPSERT เป็น CLOSED trades
    """
    synced = 0

    # --- Sync Open Positions ---
    pos_data = mt5_api("/positions")
    if pos_data and pos_data.get("positions"):
        for p in pos_data["positions"]:
            try:
                run_command(
                    """
                    INSERT INTO trades (order_id, symbol, action, lot, open_price,
                                        sl_price, tp_price, profit, status, opened_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'OPEN', to_timestamp(%s))
                    ON CONFLICT (order_id) DO UPDATE SET
                        profit = EXCLUDED.profit,
                        sl_price = EXCLUDED.sl_price,
                        tp_price = EXCLUDED.tp_price;
                    """,
                    (p["ticket"], p["symbol"], p["type"], p["lot"],
                     p["open_price"], p["sl"], p["tp"], p["profit"], p["time"]),
                )
                synced += 1
            except Exception:
                pass

    # --- Sync Closed Deals (last 30 days) ---
    hist_data = mt5_api("/history", params={"days": 30})
    if hist_data and hist_data.get("deals"):
        # Separate IN (open) and OUT (close) deals, pair by position_id
        in_deals = {}
        out_deals = {}
        for d in hist_data["deals"]:
            pos_id = d.get("position", d["order"])
            if d.get("entry") == "IN":
                in_deals[pos_id] = d
            elif d.get("entry") in ("OUT", "INOUT"):
                out_deals[pos_id] = d
            else:
                # Legacy format (no entry field) → treat as OUT
                out_deals[pos_id] = d

        # UPSERT paired trades — use IN deal's order as DB key
        for pos_id, out_deal in out_deals.items():
            in_deal = in_deals.get(pos_id, {})
            open_price = in_deal.get("price")
            open_time = in_deal.get("time", out_deal["time"])
            # DB order_id = opening order (IN deal's order)
            db_order_id = in_deal.get("order", out_deal["order"])
            # action = direction of the original open deal
            action = in_deal.get("type", out_deal["type"])
            try:
                run_command(
                    """
                    INSERT INTO trades (order_id, symbol, action, lot,
                                        open_price, close_price,
                                        profit, status, opened_at, closed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'CLOSED',
                            to_timestamp(%s), to_timestamp(%s))
                    ON CONFLICT (order_id) DO UPDATE SET
                        open_price = COALESCE(EXCLUDED.open_price, trades.open_price),
                        close_price = EXCLUDED.close_price,
                        profit = EXCLUDED.profit,
                        status = 'CLOSED',
                        closed_at = EXCLUDED.closed_at;
                    """,
                    (db_order_id, out_deal["symbol"], action, out_deal["lot"],
                     open_price, out_deal["price"],
                     out_deal["profit"], open_time, out_deal["time"]),
                )
                synced += 1
            except Exception:
                pass

    # --- Mark positions closed if they disappeared from MT5 ---
    # Only mark as closed; actual close_price/profit come from history sync above
    if pos_data is not None:
        open_tickets = [p["ticket"] for p in pos_data.get("positions", [])]
        if open_tickets:
            placeholders = ",".join(["%s"] * len(open_tickets))
            run_command(
                f"""
                UPDATE trades SET status = 'CLOSED', closed_at = COALESCE(closed_at, NOW())
                WHERE status = 'OPEN' AND order_id NOT IN ({placeholders})
                  AND close_price IS NOT NULL;
                """,
                tuple(open_tickets),
            )
        else:
            # No open positions at all → close only trades that already have close data
            run_command(
                """UPDATE trades SET status = 'CLOSED', closed_at = COALESCE(closed_at, NOW())
                   WHERE status = 'OPEN' AND close_price IS NOT NULL;"""
            )

    return synced


# ==========================================
# SIDEBAR – NAVIGATION
# ==========================================
st.sidebar.markdown("# 🥇 AI Gold Trader")
st.sidebar.caption("Enterprise Dashboard v2.0")
st.sidebar.divider()
page = st.sidebar.radio(
    "Navigation",
    ["🏠 Overview", "📊 Trade Reports", "📈 Analysis Log", "🎛️ Bot Control", "📋 Event Log", "🔑 API Usage"],
    label_visibility="collapsed",
)

# Auto-refresh toggle
auto_refresh = st.sidebar.toggle("🔄 Auto-Refresh (10s)", value=False)
if auto_refresh:
    time.sleep(10)
    st.rerun()


# ==========================================
# PAGE: OVERVIEW
# ==========================================
if page == "🏠 Overview":
    st.markdown("## 🥇 AI Gold Trader — Dashboard")

    # ── System Status Bar ──
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()
    h = now_utc.hour
    market_open = True
    market_msg = "🟢 OPEN"
    if wd == 5:
        market_open = False
        market_msg = "🔴 CLOSED (Sat)"
    elif wd == 6 and h < 23:
        market_open = False
        market_msg = "🔴 CLOSED (Sun)"
    elif wd == 4 and h >= 22:
        market_open = False
        market_msg = "🔴 CLOSED (Weekend)"
    elif h == 22:
        market_open = False
        market_msg = "⏸️ Break (22-23 UTC)"

    settings = run_query("SELECT * FROM bot_settings LIMIT 1;")
    bot_running = settings[0]["is_running"] if settings else False

    # ── Account Overview Cards ──
    account_info = mt5_api("/account")

    # Top status row
    st.markdown('<div class="card-panel">', unsafe_allow_html=True)
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("Market", market_msg)
    s2.metric("Bot", "🟢 RUNNING" if bot_running else "🔴 STOPPED")
    if settings:
        s3.metric("Interval", f"{settings[0]['interval_seconds']}s")
        s4.metric("Scalp TF", settings[0].get("scalp_timeframe", "M15"))
        s5.metric("Max Trades", settings[0]["max_trades_per_day"])
    s6.metric("UTC", now_utc.strftime("%H:%M:%S"))
    st.markdown('</div>', unsafe_allow_html=True)

    # Account overview row
    if account_info and "balance" in account_info:
        ac1, ac2, ac3, ac4 = st.columns(4)
        ac1.metric("💰 Balance", f"${account_info['balance']:,.2f}")
        ac2.metric("📊 Equity", f"${account_info['equity']:,.2f}")
        unrealized = account_info.get("profit", 0)
        ac3.metric("📈 Unrealized P/L",
                    f"${unrealized:+,.2f}",
                    delta=f"${unrealized:+,.2f}",
                    delta_color="normal")
        ac4.metric("🏦 Free Margin", f"${account_info['free_margin']:,.2f}")

    st.divider()

    # ── Active Positions ──
    st.markdown("### 📌 Active Positions")
    pos_data = mt5_api("/positions")
    if pos_data and pos_data.get("positions"):
        positions = pos_data["positions"]
        total_unrealized = sum(p.get("profit", 0) for p in positions)
        pc1, pc2 = st.columns(2)
        pc1.metric("Open Trades", len(positions))
        pc2.metric("Unrealized P/L", f"${total_unrealized:+,.2f}",
                    delta=f"${total_unrealized:+,.2f}",
                    delta_color="normal")
        df_pos = pd.DataFrame(positions)
        display_cols = ["ticket", "symbol", "type", "lot", "open_price",
                        "current_price", "sl", "tp", "profit", "swap"]
        existing_cols = [c for c in display_cols if c in df_pos.columns]
        st.dataframe(
            df_pos[existing_cols],
            use_container_width=True,
            column_config={
                "profit": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "open_price": st.column_config.NumberColumn("Entry", format="%.2f"),
                "current_price": st.column_config.NumberColumn("Current", format="%.2f"),
            },
        )
    else:
        st.info("No active positions")

    st.divider()

    # ── Live AI Insight ──
    st.markdown("### 🧠 Live AI Insight")
    latest = run_query(
        """
        SELECT trade_action, ai_recommendation, bid, ask, lot_size,
               sl_price, tp_price, created_at
        FROM ai_analysis_log
        ORDER BY created_at DESC LIMIT 1;
        """
    )
    if latest and latest[0]:
        ai = latest[0]
        action_color = "#22c55e" if ai["trade_action"] == "BUY" else (
            "#ef4444" if ai["trade_action"] == "SELL" else "#94a3b8"
        )
        ai_col1, ai_col2, ai_col3, ai_col4 = st.columns(4)
        ai_col1.metric("Signal", ai["trade_action"])
        ai_col2.metric("Bid / Ask", f"{ai['bid']:.2f} / {ai['ask']:.2f}")
        ai_col3.metric("Lot Size", f"{ai['lot_size']}")
        ai_col4.metric("Time", ai["created_at"].strftime("%H:%M:%S") if ai["created_at"] else "N/A")
        with st.expander("📝 Full AI Analysis", expanded=False):
            st.text(ai["ai_recommendation"] or "No recommendation")

    st.divider()

    # ── Quick Stats (24h) ──
    st.markdown("### 📊 Quick Stats (Last 24h)")

    rows = run_query(
        """
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%bullish%%') AS bullish,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%bearish%%') AS bearish,
               COUNT(*) FILTER (WHERE ai_recommendation ILIKE '%%neutral%%') AS neutral,
               ROUND(AVG(bid)::numeric, 2) AS avg_bid,
               ROUND(AVG(ask)::numeric, 2) AS avg_ask,
               ROUND(AVG(lot_size)::numeric, 2) AS avg_lot
        FROM ai_analysis_log
        WHERE created_at >= NOW() - INTERVAL '24 hours';
        """
    )
    if rows and rows[0]:
        r = rows[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Analyses", r["total"])
        c2.metric("🟢 Bullish", r["bullish"])
        c3.metric("🔴 Bearish", r["bearish"])
        c4.metric("⚪ Neutral", r["neutral"])

    # ── Recent Trade History (last 5) ──
    st.markdown("### 📜 Recent Trades")
    recent_trades = run_query(
        """
        SELECT order_id, action, lot, open_price, close_price, profit,
               opened_at, closed_at, status
        FROM trades
        ORDER BY COALESCE(closed_at, opened_at) DESC
        LIMIT 5;
        """
    )
    if recent_trades:
        df_recent = pd.DataFrame(recent_trades)
        st.dataframe(
            df_recent,
            use_container_width=True,
            column_config={
                "profit": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "open_price": st.column_config.NumberColumn("Entry", format="%.2f"),
                "close_price": st.column_config.NumberColumn("Exit", format="%.2f"),
            },
        )
    else:
        st.info("No trade history yet")

    # ── Price Chart ──
    st.markdown("### 💹 Price Chart (24h)")
    price_rows = run_query(
        """
        SELECT created_at, bid, ask
        FROM ai_analysis_log
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY created_at;
        """
    )
    if price_rows:
        df = pd.DataFrame(price_rows)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["bid"], name="Bid",
                                  line=dict(color="#22c55e", width=2)))
        fig.add_trace(go.Scatter(x=df["created_at"], y=df["ask"], name="Ask",
                                  line=dict(color="#ef4444", width=2)))
        fig.update_layout(
            height=400,
            xaxis_title="Time",
            yaxis_title="Price (USD)",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.8)",
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No price data in last 24 hours")

    # ── Sentiment Pie ──
    if rows and rows[0] and rows[0]["total"] > 0:
        st.markdown("### 🧠 Sentiment Distribution (24h)")
        r = rows[0]
        fig_pie = px.pie(
            names=["Bullish", "Bearish", "Neutral"],
            values=[r["bullish"], r["bearish"], r["neutral"]],
            color_discrete_sequence=["#22c55e", "#ef4444", "#64748b"],
        )
        fig_pie.update_layout(
            template="plotly_dark",
            height=350,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.8)",
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig_pie, use_container_width=True)


# ==========================================
# PAGE: TRADE REPORTS  (Pro Trader Dashboard)
# ==========================================
elif page == "📊 Trade Reports":
    st.markdown("## 📊 Trade Reports")

    # ----- SYNC MT5 → DB on page load -----
    with st.spinner("🔄 Syncing trades from MT5..."):
        synced_count = sync_mt5_to_db()

    # ----- ACCOUNT INFO (Live from MT5) -----
    st.markdown("### 💰 Account Overview")
    account_info = mt5_api("/account")

    if account_info and "balance" in account_info:
        ac1, ac2, ac3, ac4, ac5 = st.columns(5)
        ac1.metric("Balance", f"${account_info['balance']:,.2f}")
        ac2.metric("Equity", f"${account_info['equity']:,.2f}")
        ac3.metric("Margin", f"${account_info['margin']:,.2f}")
        ac4.metric("Free Margin", f"${account_info['free_margin']:,.2f}")
        ac5.metric("Unrealized P/L",
                    f"${account_info['profit']:+,.2f}",
                    delta=f"${account_info['profit']:+,.2f}",
                    delta_color="normal")
    else:
        st.info("⚠️ Cannot connect to MT5 — showing DB data only")

    st.divider()

    # ----- OPEN POSITIONS (Live from MT5 API) -----
    st.markdown("### 📌 Open Positions")
    pos_data = mt5_api("/positions")
    if pos_data and pos_data.get("positions"):
        positions = pos_data["positions"]
        total_unrealized = sum(p.get("profit", 0) for p in positions)
        oc1, oc2 = st.columns(2)
        oc1.metric("Open Trades", len(positions))
        oc2.metric("Unrealized P/L", f"${total_unrealized:+,.2f}",
                    delta=f"${total_unrealized:+,.2f}",
                    delta_color="normal")
        df_pos = pd.DataFrame(positions)
        display_cols = ["ticket", "symbol", "type", "lot", "open_price",
                        "current_price", "sl", "tp", "profit", "swap"]
        existing_cols = [c for c in display_cols if c in df_pos.columns]
        st.dataframe(df_pos[existing_cols], use_container_width=True)
    else:
        # Fallback to DB
        open_trades = run_query(
            "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY opened_at DESC;"
        )
        if open_trades:
            df_open = pd.DataFrame(open_trades)
            total_unrealized = sum(float(t.get("profit") or 0) for t in open_trades)
            oc1, oc2 = st.columns(2)
            oc1.metric("Open Trades", len(open_trades))
            oc2.metric("Unrealized P/L", f"${total_unrealized:+,.2f}",
                        delta_color="normal")
            st.dataframe(df_open, use_container_width=True)
        else:
            st.info("No active positions")

    st.divider()

    # ----- PERIOD SELECTOR -----
    st.markdown("### 📆 Performance Summary")
    period = st.radio(
        "Select Period",
        ["Today", "Yesterday", "This Week", "This Month", "Last 7 Days", "Last 30 Days", "All Time"],
        horizontal=True,
    )

    period_map = {
        "Today": "date_trunc('day', NOW())",
        "Yesterday": "date_trunc('day', NOW()) - INTERVAL '1 day'",
        "This Week": "date_trunc('week', NOW())",
        "This Month": "date_trunc('month', NOW())",
        "Last 7 Days": "NOW() - INTERVAL '7 days'",
        "Last 30 Days": "NOW() - INTERVAL '30 days'",
        "All Time": "'2000-01-01'::timestamp",
    }
    # For Yesterday, also need an end
    if period == "Yesterday":
        date_filter = "closed_at >= date_trunc('day', NOW()) - INTERVAL '1 day' AND closed_at < date_trunc('day', NOW())"
    else:
        date_filter = f"closed_at >= {period_map[period]}"

    # ----- SUMMARY STATS -----
    summary = run_query(
        f"""
        SELECT
            COUNT(*) AS total_trades,
            COUNT(*) FILTER (WHERE profit > 0) AS wins,
            COUNT(*) FILTER (WHERE profit < 0) AS losses,
            COUNT(*) FILTER (WHERE profit = 0) AS breakeven,
            COALESCE(SUM(profit), 0) AS net_profit,
            COALESCE(AVG(profit), 0) AS avg_profit,
            COALESCE(MAX(profit), 0) AS best_trade,
            COALESCE(MIN(profit), 0) AS worst_trade,
            COALESCE(AVG(profit) FILTER (WHERE profit > 0), 0) AS avg_win,
            COALESCE(AVG(profit) FILTER (WHERE profit < 0), 0) AS avg_loss,
            COALESCE(SUM(lot), 0) AS total_lots
        FROM trades
        WHERE status = 'CLOSED' AND {date_filter};
        """
    )

    if summary and summary[0]:
        s = summary[0]
        total = int(s["total_trades"])
        wins = int(s["wins"])
        losses = int(s["losses"])
        net = float(s["net_profit"])
        win_rate = (wins / total * 100) if total > 0 else 0

        # Row 1: Key Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Closed Trades", total)
        m2.metric("Net Profit/Loss",
                   f"${net:+,.2f}",
                   delta=f"${net:+,.2f}",
                   delta_color="normal")
        m3.metric("Win Rate", f"{win_rate:.1f}%")
        m4.metric("Avg Profit/Trade", f"${float(s['avg_profit']):+,.2f}")

        # Row 2: Detail Metrics
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("🟢 Wins", wins)
        m6.metric("🔴 Losses", losses)
        m7.metric("Best Trade", f"${float(s['best_trade']):+,.2f}")
        m8.metric("Worst Trade", f"${float(s['worst_trade']):+,.2f}")

        # Row 3: Advanced Metrics
        avg_win = float(s["avg_win"])
        avg_loss = abs(float(s["avg_loss"])) if float(s["avg_loss"]) != 0 else 1
        rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        profit_factor = (wins * avg_win) / (losses * avg_loss) if losses > 0 and avg_loss > 0 else 0
        expectancy = (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss) if total > 0 else 0

        m9, m10, m11, m12 = st.columns(4)
        m9.metric("Avg Win", f"${avg_win:+,.2f}")
        m10.metric("Avg Loss", f"${float(s['avg_loss']):+,.2f}")
        m11.metric("Risk:Reward", f"1:{rr_ratio:.2f}" if rr_ratio > 0 else "N/A")
        m12.metric("Profit Factor", f"{profit_factor:.2f}" if profit_factor > 0 else "N/A")

        st.caption(f"📐 Expectancy per trade: **${expectancy:+,.2f}**  |  Total Lots: **{float(s['total_lots']):.2f}**")
    else:
        st.info("No closed trades in this period")

    st.divider()

    # ----- EQUITY CURVE -----
    st.markdown("### 📈 Equity Curve")
    equity_rows = run_query(
        """
        SELECT closed_at, profit,
               SUM(profit) OVER (ORDER BY closed_at) AS cumulative_pnl
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        ORDER BY closed_at;
        """
    )
    if equity_rows:
        df_eq = pd.DataFrame(equity_rows)
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=df_eq["closed_at"],
            y=df_eq["cumulative_pnl"],
            mode="lines+markers",
            name="Cumulative P/L",
            line=dict(color="#26a69a", width=2),
            fill="tozeroy",
            fillcolor="rgba(38,166,154,0.1)",
        ))
        fig_eq.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig_eq.update_layout(
            height=400,
            xaxis_title="Date",
            yaxis_title="Cumulative P/L ($)",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.8)",
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig_eq, use_container_width=True)
    else:
        st.info("No equity data yet")

    # ----- DAILY P&L BAR CHART -----
    st.markdown("### 📊 Daily P&L")
    daily_pnl = run_query(
        """
        SELECT DATE(closed_at) AS trade_date,
               COUNT(*) AS trades,
               SUM(profit) AS daily_pnl,
               COUNT(*) FILTER (WHERE profit > 0) AS wins,
               COUNT(*) FILTER (WHERE profit < 0) AS losses
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY DATE(closed_at)
        ORDER BY trade_date DESC
        LIMIT 30;
        """
    )
    if daily_pnl:
        df_daily = pd.DataFrame(daily_pnl)
        df_daily = df_daily.sort_values("trade_date")

        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df_daily["daily_pnl"]]
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=df_daily["trade_date"],
            y=df_daily["daily_pnl"],
            marker_color=colors,
            text=[f"${v:+,.2f}" for v in df_daily["daily_pnl"]],
            textposition="outside",
        ))
        fig_bar.update_layout(
            height=400,
            xaxis_title="Date",
            yaxis_title="P/L ($)",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.8)",
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # Daily P&L Table
        st.dataframe(
            df_daily.sort_values("trade_date", ascending=False),
            use_container_width=True,
            column_config={
                "trade_date": "Date",
                "trades": "# Trades",
                "daily_pnl": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "wins": "Wins",
                "losses": "Losses",
            },
        )
    else:
        st.info("No daily P&L data")

    st.divider()

    # ----- WEEKLY SUMMARY -----
    st.markdown("### 📅 Weekly Summary")
    weekly_pnl = run_query(
        """
        SELECT date_trunc('week', closed_at)::date AS week_start,
               COUNT(*) AS trades,
               SUM(profit) AS weekly_pnl,
               COUNT(*) FILTER (WHERE profit > 0) AS wins,
               COUNT(*) FILTER (WHERE profit < 0) AS losses,
               ROUND(AVG(profit)::numeric, 2) AS avg_pnl
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY date_trunc('week', closed_at)
        ORDER BY week_start DESC
        LIMIT 12;
        """
    )
    if weekly_pnl:
        df_weekly = pd.DataFrame(weekly_pnl)
        st.dataframe(
            df_weekly,
            use_container_width=True,
            column_config={
                "week_start": "Week Starting",
                "trades": "# Trades",
                "weekly_pnl": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "wins": "Wins",
                "losses": "Losses",
                "avg_pnl": st.column_config.NumberColumn("Avg P/L", format="$%.2f"),
            },
        )
    else:
        st.info("No weekly data")

    # ----- MONTHLY SUMMARY -----
    st.markdown("### 📅 Monthly Summary")
    monthly_pnl = run_query(
        """
        SELECT to_char(closed_at, 'YYYY-MM') AS month,
               COUNT(*) AS trades,
               SUM(profit) AS monthly_pnl,
               COUNT(*) FILTER (WHERE profit > 0) AS wins,
               COUNT(*) FILTER (WHERE profit < 0) AS losses,
               ROUND(AVG(profit)::numeric, 2) AS avg_pnl,
               ROUND((COUNT(*) FILTER (WHERE profit > 0))::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS win_rate
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY to_char(closed_at, 'YYYY-MM')
        ORDER BY month DESC
        LIMIT 12;
        """
    )
    if monthly_pnl:
        df_monthly = pd.DataFrame(monthly_pnl)
        st.dataframe(
            df_monthly,
            use_container_width=True,
            column_config={
                "month": "Month",
                "trades": "# Trades",
                "monthly_pnl": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "wins": "Wins",
                "losses": "Losses",
                "avg_pnl": st.column_config.NumberColumn("Avg P/L", format="$%.2f"),
                "win_rate": st.column_config.NumberColumn("Win Rate %", format="%.1f%%"),
            },
        )
    else:
        st.info("No monthly data")

    st.divider()

    # ----- TRADE HISTORY TABLE -----
    st.markdown("### 📜 Trade History")
    history_limit = st.number_input("Max rows", 10, 1000, 100, key="hist_limit")
    history_rows = run_query(
        """
        SELECT order_id, symbol, action, lot, open_price, close_price,
               sl_price, tp_price, profit, opened_at, closed_at
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY closed_at DESC
        LIMIT %s;
        """,
        (history_limit,),
    )
    if history_rows:
        df_hist = pd.DataFrame(history_rows)
        st.dataframe(
            df_hist,
            use_container_width=True,
            height=500,
            column_config={
                "profit": st.column_config.NumberColumn("Profit ($)", format="$%.2f"),
                "open_price": st.column_config.NumberColumn("Entry", format="%.2f"),
                "close_price": st.column_config.NumberColumn("Exit", format="%.2f"),
            },
        )

        csv_hist = df_hist.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export Trade History CSV", csv_hist, "trade_history.csv", "text/csv")
    else:
        st.info("No closed trades")

    # ----- WIN/LOSS DISTRIBUTION -----
    st.markdown("### 📊 Profit Distribution")
    dist_rows = run_query(
        """
        SELECT profit FROM trades
        WHERE status = 'CLOSED' AND profit IS NOT NULL;
        """
    )
    if dist_rows and len(dist_rows) > 1:
        df_dist = pd.DataFrame(dist_rows)
        fig_dist = px.histogram(
            df_dist, x="profit", nbins=30,
            color_discrete_sequence=["#26a69a"],
            labels={"profit": "Profit ($)", "count": "Count"},
        )
        fig_dist.add_vline(x=0, line_dash="dash", line_color="red", opacity=0.7)
        fig_dist.update_layout(
            template="plotly_dark", height=350,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.8)",
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig_dist, use_container_width=True)


# ==========================================
# PAGE: ANALYSIS LOG
# ==========================================
elif page == "📈 Analysis Log":
    st.markdown("## 📈 Analysis Log")

    # Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        hours = st.slider("Lookback (hours)", 1, 168, 24)
    with col_f2:
        limit = st.number_input("Max rows", 10, 5000, 200)

    log_rows = run_query(
        """
        SELECT id, symbol, bid, ask, trade_action, ai_recommendation,
               lot_size, sl_price, tp_price, created_at
        FROM ai_analysis_log
        WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
        ORDER BY created_at DESC
        LIMIT %s;
        """,
        (hours, limit),
    )

    if log_rows:
        df = pd.DataFrame(log_rows)

        # Color-code trade_action
        def color_action(val):
            if val == "BUY":
                return "color: #26a69a; font-weight: bold"
            elif val == "SELL":
                return "color: #ef5350; font-weight: bold"
            return "color: #78909c"

        # Summary counts
        if "trade_action" in df.columns:
            ac1, ac2, ac3, ac4 = st.columns(4)
            ac1.metric("Total", len(df))
            ac2.metric("🟢 BUY", len(df[df["trade_action"] == "BUY"]))
            ac3.metric("🔴 SELL", len(df[df["trade_action"] == "SELL"]))
            ac4.metric("⏸️ WAIT", len(df[df["trade_action"] == "WAIT"]))

        styled_df = df.style.applymap(
            color_action, subset=["trade_action"]
        ) if "trade_action" in df.columns else df

        st.dataframe(styled_df, use_container_width=True, height=500)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export CSV", csv, "analysis_log.csv", "text/csv")
    else:
        st.info("No analysis data found")


# ==========================================
# PAGE: BOT CONTROL
# ==========================================
elif page == "🎛️ Bot Control":
    st.markdown("## 🎛️ Control Panel")

    settings = run_query("SELECT * FROM bot_settings LIMIT 1;")
    if not settings:
        st.error("No bot_settings found — run db/init.sql first")
        st.stop()

    s = settings[0]

    # --- System Status + Kill Switch ---
    st.markdown("### ⚡ System Status")
    col_status, col_action, col_emergency = st.columns(3)

    with col_status:
        if s["is_running"]:
            st.markdown('<span class="status-running">● SYSTEM ACTIVE</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-stopped">● SYSTEM OFFLINE</span>', unsafe_allow_html=True)

    with col_action:
        if s["is_running"]:
            if st.button("⏹️  STOP BOT", type="primary", use_container_width=True):
                run_command("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
                run_command(
                    "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                    ("STOP", "Bot stopped from Dashboard"),
                )
                st.rerun()
        else:
            if st.button("▶️  START BOT", type="primary", use_container_width=True):
                run_command("UPDATE bot_settings SET is_running = TRUE, updated_at = NOW();")
                run_command(
                    "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                    ("START", "Bot started from Dashboard"),
                )
                st.rerun()

    with col_emergency:
        if st.button("🚨 EMERGENCY CLOSE ALL", type="secondary", use_container_width=True):
            # Close all open positions via MT5
            pos_data = mt5_api("/positions")
            closed = 0
            if pos_data and pos_data.get("positions"):
                import requests
                windows_ip = os.getenv("WINDOWS_IP", "")
                for p in pos_data["positions"]:
                    try:
                        requests.post(
                            f"http://{windows_ip}:8000/close",
                            json={"ticket": p["ticket"]},
                            timeout=10,
                        )
                        closed += 1
                    except Exception:
                        pass
            run_command("UPDATE bot_settings SET is_running = FALSE, updated_at = NOW();")
            run_command(
                "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                ("KILL_SWITCH", f"Emergency close all — closed {closed} positions"),
            )
            st.warning(f"🚨 Emergency executed — closed {closed} positions, bot stopped")
            st.rerun()

    st.divider()

    # --- Settings ---
    st.markdown("### ⚙️ Configuration")

    # ดึงค่าปัจจุบัน (รองรับ column ใหม่)
    current_max_retries = s.get("pause_max_retries", 5)
    current_retry_sec = s.get("pause_retry_sec", 10)

    with st.form("settings_form"):
        st.markdown("##### ⏱️ Trading Interval")
        new_interval = st.selectbox(
            "Interval",
            options=[60, 120, 300, 600, 900, 1800, 3600],
            index=[60, 120, 300, 600, 900, 1800, 3600].index(s["interval_seconds"])
            if s["interval_seconds"] in [60, 120, 300, 600, 900, 1800, 3600]
            else 2,
            format_func=lambda x: {
                60: "1 min",
                120: "2 min",
                300: "5 min",
                600: "10 min",
                900: "15 min",
                1800: "30 min",
                3600: "1 hour",
            }.get(x, f"{x}s"),
        )

        st.markdown("##### 📊 Scalp Timeframe")
        scalp_tf_options = ["M1", "M5", "M15", "M30"]
        current_scalp_tf = s.get("scalp_timeframe", "M15")
        new_scalp_tf = st.selectbox(
            "Scalp Timeframe (short-term analysis + AI prompt)",
            options=scalp_tf_options,
            index=scalp_tf_options.index(current_scalp_tf)
            if current_scalp_tf in scalp_tf_options
            else 2,
            help="Timeframe for scalp analysis (M1/M5/M15/M30) — changes take effect immediately without restart",
        )

        new_max_trades = st.number_input(
            "Max Trades / Day", min_value=1, max_value=100, value=s["max_trades_per_day"]
        )

        st.markdown("##### ⏸️ Pause Settings")
        bp_col1, bp_col2 = st.columns(2)
        with bp_col1:
            new_max_retries = st.number_input(
                "Max Pause Retries",
                min_value=0, max_value=100, value=current_max_retries,
                help="Number of retries while bot is STOPPED before auto shutdown (0 = unlimited)",
            )
        with bp_col2:
            new_retry_sec = st.number_input(
                "Pause Retry Interval (sec)",
                min_value=5, max_value=300, value=current_retry_sec,
                help="Wait time (seconds) between retries while STOPPED",
            )

        submitted = st.form_submit_button("💾 Save Settings")
        if submitted:
            run_command(
                """
                UPDATE bot_settings
                SET interval_seconds = %s, max_trades_per_day = %s,
                    pause_max_retries = %s, pause_retry_sec = %s,
                    scalp_timeframe = %s,
                    updated_at = NOW();
                """,
                (new_interval, new_max_trades, new_max_retries, new_retry_sec, new_scalp_tf),
            )
            run_command(
                "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                ("CONFIG_CHANGE", f"interval={new_interval}s, max_trades={new_max_trades}, scalp_tf={new_scalp_tf}, pause_retries={new_max_retries}, retry_sec={new_retry_sec}s"),
            )
            st.success("✅ Settings saved!")
            st.rerun()

    st.divider()
    st.subheader("💡 Interval & Timeframe Guide")
    st.markdown(
        """
        | Scalp TF | Recommended Interval | Strategy |
        |----------|---------------------|--------|
        | **M5** | 1-2 min (60-120s) | Ultra-short scalp |
        | **M15** | 5 min (300s) | Standard scalp (recommended) |
        | **M30** | 10 min (600s) | Short swing |
        | **H1** | 15-30 min | Swing / Position |
        """
    )


# ==========================================
# PAGE: EVENT LOG
# ==========================================
elif page == "📋 Event Log":
    st.markdown("## 📋 Event Log")

    events = run_query(
        """
        SELECT id, event_type, message, created_at
        FROM bot_events
        ORDER BY created_at DESC
        LIMIT 200;
        """
    )
    if events:
        df = pd.DataFrame(events)

        # Color-code event types
        def color_event(val):
            colors = {
                "START": "background-color: #166534; color: #86efac",
                "STOP": "background-color: #991b1b; color: #fca5a5",
                "ERROR": "background-color: #9a3412; color: #fdba74",
                "KILL_SWITCH": "background-color: #9f1239; color: #fda4af",
                "CONFIG_CHANGE": "background-color: #1e3a5f; color: #93c5fd",
                "RESTART": "background-color: #854d0e; color: #fde68a",
            }
            return colors.get(val, "")

        st.dataframe(
            df.style.map(color_event, subset=["event_type"]),
            use_container_width=True,
            height=600,
        )
    else:
        st.info("No events yet")


# ==========================================
# PAGE: API USAGE
# ==========================================
elif page == "🔑 API Usage":
    st.markdown("## 🔑 AI API Usage Monitor")

    # --- Period Selector ---
    api_period = st.radio(
        "Period",
        ["Today", "Last 7 Days", "Last 30 Days", "All Time"],
        horizontal=True,
        key="api_period",
    )
    api_period_map = {
        "Today": "date_trunc('day', NOW())",
        "Last 7 Days": "NOW() - INTERVAL '7 days'",
        "Last 30 Days": "NOW() - INTERVAL '30 days'",
        "All Time": "'2000-01-01'::timestamp",
    }
    api_date_filter = f"created_at >= {api_period_map[api_period]}"

    # --- Overall Summary ---
    st.subheader("📊 Overall Summary")
    api_summary = run_query(
        f"""
        SELECT
            COUNT(*) AS total_calls,
            COUNT(*) FILTER (WHERE status = 'OK') AS success,
            COUNT(*) FILTER (WHERE status = 'ERROR') AS errors,
            COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            ROUND(AVG(response_time_ms)::numeric, 0) AS avg_latency_ms,
            ROUND(AVG(total_tokens)::numeric, 0) AS avg_tokens_per_call,
            MAX(response_time_ms) AS max_latency_ms,
            MIN(created_at) AS first_call,
            MAX(created_at) AS last_call
        FROM api_usage_log
        WHERE {api_date_filter};
        """
    )

    if api_summary and api_summary[0] and api_summary[0]["total_calls"] > 0:
        s = api_summary[0]
        error_rate = (int(s["errors"]) / int(s["total_calls"]) * 100) if int(s["total_calls"]) > 0 else 0

        ac1, ac2, ac3, ac4 = st.columns(4)
        ac1.metric("Total API Calls", f"{s['total_calls']:,}")
        ac2.metric("✅ Success", f"{s['success']:,}")
        ac3.metric("❌ Errors", f"{s['errors']:,}")
        ac4.metric("Error Rate", f"{error_rate:.1f}%")

        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("Total Tokens", f"{int(s['total_tokens']):,}")
        tc2.metric("Prompt Tokens", f"{int(s['total_prompt_tokens']):,}")
        tc3.metric("Completion Tokens", f"{int(s['total_completion_tokens']):,}")
        tc4.metric("Avg Tokens/Call", f"{int(s['avg_tokens_per_call']):,}")

        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("Avg Latency", f"{int(s['avg_latency_ms']):,} ms")
        lc2.metric("Max Latency", f"{int(s['max_latency_ms']):,} ms")
        lc3.metric("Last Call", s["last_call"].strftime("%Y-%m-%d %H:%M") if s["last_call"] else "N/A")
    else:
        st.info("No API usage data in this period")

    st.divider()

    # --- Per-Provider Breakdown ---
    st.subheader("🏢 Usage by Provider")
    provider_stats = run_query(
        f"""
        SELECT
            provider,
            COUNT(*) AS calls,
            COUNT(*) FILTER (WHERE status = 'OK') AS success,
            COUNT(*) FILTER (WHERE status = 'ERROR') AS errors,
            COALESCE(SUM(total_tokens), 0) AS tokens,
            ROUND(AVG(response_time_ms)::numeric, 0) AS avg_latency,
            ROUND(AVG(total_tokens)::numeric, 0) AS avg_tokens
        FROM api_usage_log
        WHERE {api_date_filter}
        GROUP BY provider
        ORDER BY calls DESC;
        """
    )
    if provider_stats:
        df_prov = pd.DataFrame(provider_stats)
        st.dataframe(
            df_prov,
            use_container_width=True,
            column_config={
                "provider": "Provider",
                "calls": "API Calls",
                "success": "✅ Success",
                "errors": "❌ Errors",
                "tokens": st.column_config.NumberColumn("Total Tokens", format="%d"),
                "avg_latency": st.column_config.NumberColumn("Avg Latency (ms)", format="%d"),
                "avg_tokens": st.column_config.NumberColumn("Avg Tokens/Call", format="%d"),
            },
        )

        # Provider pie chart
        fig_prov = px.pie(
            df_prov, names="provider", values="calls",
            title="API Calls by Provider",
            color_discrete_sequence=["#26a69a", "#7c4dff"],
        )
        fig_prov.update_layout(template="plotly_dark", height=300)
        st.plotly_chart(fig_prov, use_container_width=True)

    st.divider()

    # --- Per-Model Breakdown ---
    st.subheader("🤖 Usage by Model")
    model_stats = run_query(
        f"""
        SELECT
            provider,
            model,
            COUNT(*) AS calls,
            COALESCE(SUM(total_tokens), 0) AS tokens,
            ROUND(AVG(response_time_ms)::numeric, 0) AS avg_latency,
            ROUND(AVG(total_tokens)::numeric, 0) AS avg_tokens,
            COUNT(*) FILTER (WHERE status = 'ERROR') AS errors
        FROM api_usage_log
        WHERE {api_date_filter}
        GROUP BY provider, model
        ORDER BY calls DESC;
        """
    )
    if model_stats:
        df_model = pd.DataFrame(model_stats)
        st.dataframe(
            df_model,
            use_container_width=True,
            column_config={
                "provider": "Provider",
                "model": "Model",
                "calls": "API Calls",
                "tokens": st.column_config.NumberColumn("Total Tokens", format="%d"),
                "avg_latency": st.column_config.NumberColumn("Avg Latency (ms)", format="%d"),
                "avg_tokens": st.column_config.NumberColumn("Avg Tokens/Call", format="%d"),
                "errors": "Errors",
            },
        )

    st.divider()

    # --- Daily API Usage Trend ---
    st.subheader("📈 Daily API Usage Trend")
    daily_api = run_query(
        f"""
        SELECT
            DATE(created_at) AS date,
            provider,
            COUNT(*) AS calls,
            COALESCE(SUM(total_tokens), 0) AS tokens,
            ROUND(AVG(response_time_ms)::numeric, 0) AS avg_latency
        FROM api_usage_log
        WHERE {api_date_filter}
        GROUP BY DATE(created_at), provider
        ORDER BY date;
        """
    )
    if daily_api:
        df_daily_api = pd.DataFrame(daily_api)

        # Calls per day (stacked by provider)
        fig_calls = px.bar(
            df_daily_api, x="date", y="calls", color="provider",
            title="API Calls per Day",
            color_discrete_map={"openrouter": "#26a69a", "nvidia": "#7c4dff"},
            barmode="stack",
        )
        fig_calls.update_layout(template="plotly_dark", height=350, xaxis_title="Date", yaxis_title="Calls")
        st.plotly_chart(fig_calls, use_container_width=True)

        # Tokens per day
        fig_tokens = px.bar(
            df_daily_api, x="date", y="tokens", color="provider",
            title="Tokens Used per Day",
            color_discrete_map={"openrouter": "#26a69a", "nvidia": "#7c4dff"},
            barmode="stack",
        )
        fig_tokens.update_layout(template="plotly_dark", height=350, xaxis_title="Date", yaxis_title="Tokens")
        st.plotly_chart(fig_tokens, use_container_width=True)

        # Latency trend
        daily_latency = run_query(
            f"""
            SELECT
                DATE(created_at) AS date,
                provider,
                ROUND(AVG(response_time_ms)::numeric, 0) AS avg_latency,
                MAX(response_time_ms) AS max_latency
            FROM api_usage_log
            WHERE {api_date_filter}
            GROUP BY DATE(created_at), provider
            ORDER BY date;
            """
        )
        if daily_latency:
            df_lat = pd.DataFrame(daily_latency)
            fig_lat = px.line(
                df_lat, x="date", y="avg_latency", color="provider",
                title="Average Response Latency (ms)",
                color_discrete_map={"openrouter": "#26a69a", "nvidia": "#7c4dff"},
                markers=True,
            )
            fig_lat.update_layout(template="plotly_dark", height=350, xaxis_title="Date", yaxis_title="Latency (ms)")
            st.plotly_chart(fig_lat, use_container_width=True)
    else:
        st.info("No daily API usage data")

    st.divider()

    # --- Hourly Heatmap (Today) ---
    st.subheader("🕐 Hourly Usage (Today)")
    hourly_api = run_query(
        """
        SELECT
            EXTRACT(HOUR FROM created_at)::int AS hour,
            COUNT(*) AS calls,
            COALESCE(SUM(total_tokens), 0) AS tokens
        FROM api_usage_log
        WHERE created_at >= date_trunc('day', NOW())
        GROUP BY EXTRACT(HOUR FROM created_at)
        ORDER BY hour;
        """
    )
    if hourly_api:
        df_hourly = pd.DataFrame(hourly_api)
        fig_hourly = go.Figure()
        fig_hourly.add_trace(go.Bar(
            x=df_hourly["hour"],
            y=df_hourly["calls"],
            name="Calls",
            marker_color="#26a69a",
        ))
        fig_hourly.update_layout(
            template="plotly_dark", height=300,
            xaxis_title="Hour (UTC)", yaxis_title="API Calls",
            xaxis=dict(dtick=1),
        )
        st.plotly_chart(fig_hourly, use_container_width=True)
    else:
        st.info("No data for today")

    st.divider()

    # --- Recent API Calls (Raw Log) ---
    st.subheader("📝 Recent API Calls")
    recent_limit = st.number_input("Rows", 10, 500, 50, key="api_log_limit")
    recent_api = run_query(
        """
        SELECT id, provider, model, prompt_tokens, completion_tokens,
               total_tokens, response_time_ms, status, created_at
        FROM api_usage_log
        ORDER BY created_at DESC
        LIMIT %s;
        """,
        (recent_limit,),
    )
    if recent_api:
        df_recent = pd.DataFrame(recent_api)
        st.dataframe(
            df_recent,
            use_container_width=True,
            height=400,
            column_config={
                "provider": "Provider",
                "model": "Model",
                "prompt_tokens": "Prompt Tokens",
                "completion_tokens": "Completion Tokens",
                "total_tokens": "Total Tokens",
                "response_time_ms": st.column_config.NumberColumn("Latency (ms)", format="%d"),
                "status": "Status",
                "created_at": "Time",
            },
        )

        csv_api = df_recent.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export API Usage CSV", csv_api, "api_usage.csv", "text/csv")
    else:
        st.info("No API calls yet")


# ==========================================
# SIDEBAR FOOTER
# ==========================================
st.sidebar.divider()

# Show AI provider info
ai_provider = os.getenv("AI_PROVIDER", "openrouter").lower()
ai_model = os.getenv("MODEL", os.getenv("NVIDIA_MODEL", "N/A"))
st.sidebar.markdown(f"""
<div class="text-muted">
<b class="gold-accent">Engine:</b> {ai_model}<br>
<b class="gold-accent">Symbol:</b> XAUUSD<br>
<b class="gold-accent">Provider:</b> {ai_provider.title()}
</div>
""", unsafe_allow_html=True)
st.sidebar.caption(f"AI Gold Trader v2.0 Enterprise • {datetime.now().strftime('%Y-%m-%d %H:%M')}")
