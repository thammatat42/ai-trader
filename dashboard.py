"""
AI Trader - Admin Dashboard (Streamlit)
========================================
Control bot, view reports/events, manage AI models.
Run:  streamlit run dashboard.py --server.port 8501
"""

import os
import time
import psycopg2
import psycopg2.extras
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import requests as req_lib
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
# MT5 API HELPER
# ==========================================

def mt5_api(endpoint: str, params: dict = None, timeout: int = 8):
    """Call MT5 Bridge API on Windows VPS"""
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
    Sync data from MT5 to trades table in PostgreSQL.
    - /positions -> UPSERT as OPEN trades
    - /history   -> UPSERT as CLOSED trades
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
st.sidebar.caption("Enterprise Dashboard v2.1")
st.sidebar.divider()
page = st.sidebar.radio(
    "Navigation",
    ["🏠 Overview", "📊 Trade Reports", "📈 Analysis Log", "🤖 AI Models",
     "🎛️ Bot Control", "📋 Event Log", "🔑 API Usage"],
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

    # ── Trading Health Score ──
    st.markdown("### 🩺 Trading Health Score")
    health_data = run_query(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE profit > 0) AS wins,
            COUNT(*) FILTER (WHERE profit < 0) AS losses,
            COALESCE(SUM(profit), 0) AS net_pnl,
            COALESCE(AVG(profit), 0) AS avg_pnl,
            COUNT(*) FILTER (WHERE action = 'BUY') AS buys,
            COUNT(*) FILTER (WHERE action = 'SELL') AS sells
        FROM trades
        WHERE status = 'CLOSED'
          AND closed_at >= NOW() - INTERVAL '7 days';
        """
    )
    if health_data and health_data[0] and health_data[0]["total"] > 0:
        hd = health_data[0]
        total = int(hd["total"])
        wins = int(hd["wins"])
        losses = int(hd["losses"])
        net_pnl = float(hd["net_pnl"])
        buys = int(hd["buys"])
        sells = int(hd["sells"])
        win_rate = (wins / total * 100) if total > 0 else 0

        # Compute composite health score (0-100)
        # Components: win_rate (40%), profitability (30%), direction balance (30%)
        wr_score = min(win_rate / 60 * 40, 40)  # 60% win rate = full 40 pts
        profit_score = min(max(net_pnl / 50 * 30, 0), 30)  # $50 profit = full 30 pts
        balance_ratio = min(buys, sells) / max(buys, sells, 1)
        balance_score = balance_ratio * 30  # perfectly balanced = 30 pts
        health_score = int(wr_score + profit_score + balance_score)

        health_color = "#22c55e" if health_score >= 70 else ("#f59e0b" if health_score >= 40 else "#ef4444")
        health_label = "Excellent" if health_score >= 70 else ("Fair" if health_score >= 40 else "Needs Attention")

        h1, h2, h3, h4, h5 = st.columns(5)
        h1.metric("Health Score", f"{health_score}/100")
        h2.metric("Status", health_label)
        h3.metric("Win Rate (7d)", f"{win_rate:.1f}%")
        h4.metric("Net P/L (7d)", f"${net_pnl:+,.2f}")
        buy_pct = buys / max(total, 1) * 100
        h5.metric("BUY/SELL Ratio", f"{buys}B / {sells}S ({buy_pct:.0f}%)")

        # Health bar visualization
        st.markdown(
            f"""<div style="background:#1e293b; border-radius:8px; padding:4px; margin:8px 0;">
            <div style="background:{health_color}; width:{health_score}%; height:24px;
            border-radius:6px; display:flex; align-items:center; justify-content:center;
            font-weight:bold; color:#0f172a; font-size:0.8rem;">{health_score}%</div></div>""",
            unsafe_allow_html=True,
        )
    else:
        st.info("No closed trades in last 7 days to compute health score")

    st.divider()

    # ── Safety Filters Status ──
    st.markdown("### 🛡️ Active Safety Filters")
    bad_hours = os.getenv("BAD_HOURS_UTC", "2,3,4,5,6")
    loss_threshold = os.getenv("LOSS_PAUSE_THRESHOLD", "3")
    loss_pause_sec = os.getenv("LOSS_PAUSE_SEC", "1800")
    min_hold = os.getenv("MIN_HOLD_SEC", "60")
    max_hold = os.getenv("MAX_HOLD_SEC", "1800")
    max_tp = os.getenv("MAX_TP_POINTS", "600")

    sf1, sf2, sf3 = st.columns(3)
    with sf1:
        st.markdown('<div class="card-panel"><h4>⏰ Time Filter</h4>', unsafe_allow_html=True)
        current_hour_blocked = str(now_utc.hour) in [x.strip() for x in bad_hours.split(",")]
        if current_hour_blocked:
            st.markdown("Status: <b class='red-accent'>BLOCKED</b> (bad hour)", unsafe_allow_html=True)
        else:
            st.markdown("Status: <b class='green-accent'>ACTIVE</b>", unsafe_allow_html=True)
        st.markdown(f"<span class='text-muted'>Bad hours (UTC): {bad_hours}</span>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with sf2:
        st.markdown('<div class="card-panel"><h4>🔴 Loss Pause</h4>', unsafe_allow_html=True)
        # Check consecutive losses
        recent_trades_check = run_query(
            f"""
            SELECT profit FROM trades
            WHERE status = 'CLOSED'
            ORDER BY closed_at DESC
            LIMIT {int(loss_threshold)};
            """
        )
        consec_losses = 0
        if recent_trades_check:
            for t in recent_trades_check:
                if float(t["profit"] or 0) < 0:
                    consec_losses += 1
                else:
                    break
        paused = consec_losses >= int(loss_threshold)
        if paused:
            st.markdown(f"Status: <b class='red-accent'>PAUSED</b> ({consec_losses} consecutive losses)", unsafe_allow_html=True)
        else:
            st.markdown(f"Status: <b class='green-accent'>OK</b> ({consec_losses}/{loss_threshold} losses)", unsafe_allow_html=True)
        st.markdown(f"<span class='text-muted'>Pause: {int(loss_pause_sec)//60} min after {loss_threshold} losses</span>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with sf3:
        st.markdown('<div class="card-panel"><h4>📏 Position Limits</h4>', unsafe_allow_html=True)
        st.markdown(f"Hold: **{min_hold}s** – **{max_hold}s**", unsafe_allow_html=True)
        st.markdown(f"Max TP: **{max_tp} points**", unsafe_allow_html=True)
        st.markdown("Status: <b class='green-accent'>ENFORCED</b>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

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
        ai_col1, ai_col2, ai_col3, ai_col4 = st.columns(4)
        ai_col1.metric("Signal", ai["trade_action"])
        ai_col2.metric("Bid / Ask", f"{ai['bid']:.2f} / {ai['ask']:.2f}")
        ai_col3.metric("Lot Size", f"{ai['lot_size']}")
        ai_col4.metric("Time", ai["created_at"].strftime("%H:%M:%S") if ai["created_at"] else "N/A")
        with st.expander("Full AI Analysis", expanded=False):
            st.text(ai["ai_recommendation"] or "No recommendation")

    st.divider()

    # ── Quick Stats (24h) ──
    st.markdown("### 📊 Quick Stats (Last 24h)")

    rows = run_query(
        """
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE trade_action = 'BUY') AS buy_signals,
               COUNT(*) FILTER (WHERE trade_action = 'SELL') AS sell_signals,
               COUNT(*) FILTER (WHERE trade_action = 'WAIT') AS wait_signals,
               ROUND(AVG(bid)::numeric, 2) AS avg_bid,
               ROUND(AVG(ask)::numeric, 2) AS avg_ask
        FROM ai_analysis_log
        WHERE created_at >= NOW() - INTERVAL '24 hours';
        """
    )
    if rows and rows[0]:
        r = rows[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Analyses", r["total"])
        c2.metric("🟢 BUY Signals", r["buy_signals"])
        c3.metric("🔴 SELL Signals", r["sell_signals"])
        c4.metric("⏸️ WAIT", r["wait_signals"])

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

    # ── Signal Distribution (24h) ──
    if rows and rows[0] and rows[0]["total"] > 0:
        st.markdown("### 📡 Signal Distribution (24h)")
        r = rows[0]
        sig_col1, sig_col2 = st.columns(2)
        with sig_col1:
            fig_pie = px.pie(
                names=["BUY", "SELL", "WAIT"],
                values=[r["buy_signals"], r["sell_signals"], r["wait_signals"]],
                color_discrete_sequence=["#22c55e", "#ef4444", "#64748b"],
            )
            fig_pie.update_layout(
                template="plotly_dark", height=300,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.8)",
                font=dict(color="#94a3b8"),
                title="Signal Types",
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with sig_col2:
            # Price Chart (24h)
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
                    height=300, title="Price (24h)",
                    xaxis_title="Time", yaxis_title="Price (USD)",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,23,42,0.8)",
                    font=dict(color="#94a3b8"),
                )
                st.plotly_chart(fig, use_container_width=True)


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

        st.caption(f"Expectancy per trade: **${expectancy:+,.2f}**  |  Total Lots: **{float(s['total_lots']):.2f}**")
    else:
        st.info("No closed trades in this period")

    st.divider()

    # ----- BUY vs SELL Analysis -----
    st.markdown("### ⚖️ BUY vs SELL Performance")
    direction_stats = run_query(
        f"""
        SELECT
            action,
            COUNT(*) AS trades,
            COUNT(*) FILTER (WHERE profit > 0) AS wins,
            COUNT(*) FILTER (WHERE profit < 0) AS losses,
            COALESCE(SUM(profit), 0) AS total_pnl,
            COALESCE(AVG(profit), 0) AS avg_pnl
        FROM trades
        WHERE status = 'CLOSED' AND {date_filter}
        GROUP BY action;
        """
    )
    if direction_stats:
        df_dir = pd.DataFrame(direction_stats)
        dir_col1, dir_col2 = st.columns(2)
        with dir_col1:
            fig_dir_bar = go.Figure()
            for _, row in df_dir.iterrows():
                color = "#22c55e" if row["action"] == "BUY" else "#ef4444"
                fig_dir_bar.add_trace(go.Bar(
                    x=[row["action"]],
                    y=[row["trades"]],
                    name=row["action"],
                    marker_color=color,
                    text=[f"{int(row['trades'])} trades"],
                    textposition="outside",
                ))
            fig_dir_bar.update_layout(
                title="Trade Count by Direction",
                template="plotly_dark", height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.8)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_dir_bar, use_container_width=True)

        with dir_col2:
            fig_dir_pnl = go.Figure()
            for _, row in df_dir.iterrows():
                pnl = float(row["total_pnl"])
                color = "#22c55e" if pnl >= 0 else "#ef4444"
                fig_dir_pnl.add_trace(go.Bar(
                    x=[row["action"]],
                    y=[pnl],
                    name=row["action"],
                    marker_color=color,
                    text=[f"${pnl:+,.2f}"],
                    textposition="outside",
                ))
            fig_dir_pnl.update_layout(
                title="P/L by Direction",
                template="plotly_dark", height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.8)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_dir_pnl, use_container_width=True)

        # Direction summary table
        st.dataframe(
            df_dir,
            use_container_width=True,
            column_config={
                "action": "Direction",
                "trades": "# Trades",
                "wins": "Wins",
                "losses": "Losses",
                "total_pnl": st.column_config.NumberColumn("Total P/L", format="$%.2f"),
                "avg_pnl": st.column_config.NumberColumn("Avg P/L", format="$%.2f"),
            },
        )

    st.divider()

    # ----- Time-of-Day P/L Heatmap -----
    st.markdown("### 🕐 Performance by Hour (UTC)")
    hourly_perf = run_query(
        """
        SELECT
            EXTRACT(HOUR FROM closed_at)::int AS hour,
            COUNT(*) AS trades,
            COALESCE(SUM(profit), 0) AS total_pnl,
            COUNT(*) FILTER (WHERE profit > 0) AS wins,
            COUNT(*) FILTER (WHERE profit < 0) AS losses
        FROM trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY EXTRACT(HOUR FROM closed_at)
        ORDER BY hour;
        """
    )
    if hourly_perf:
        df_hourly = pd.DataFrame(hourly_perf)
        hour_col1, hour_col2 = st.columns(2)
        with hour_col1:
            colors_h = ["#22c55e" if v >= 0 else "#ef4444" for v in df_hourly["total_pnl"]]
            fig_h = go.Figure()
            fig_h.add_trace(go.Bar(
                x=df_hourly["hour"], y=df_hourly["total_pnl"],
                marker_color=colors_h,
                text=[f"${v:+,.1f}" for v in df_hourly["total_pnl"]],
                textposition="outside",
            ))
            fig_h.update_layout(
                title="P/L by Hour (UTC)", template="plotly_dark", height=300,
                xaxis=dict(dtick=1, title="Hour (UTC)"), yaxis_title="P/L ($)",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.8)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_h, use_container_width=True)

        with hour_col2:
            df_hourly["win_rate"] = df_hourly.apply(
                lambda r: (r["wins"] / r["trades"] * 100) if r["trades"] > 0 else 0, axis=1
            )
            fig_wr = go.Figure()
            fig_wr.add_trace(go.Bar(
                x=df_hourly["hour"], y=df_hourly["win_rate"],
                marker_color=["#22c55e" if v >= 50 else "#ef4444" for v in df_hourly["win_rate"]],
                text=[f"{v:.0f}%" for v in df_hourly["win_rate"]],
                textposition="outside",
            ))
            fig_wr.add_hline(y=50, line_dash="dash", line_color="#f59e0b", opacity=0.5)
            fig_wr.update_layout(
                title="Win Rate by Hour (UTC)", template="plotly_dark", height=300,
                xaxis=dict(dtick=1, title="Hour (UTC)"), yaxis_title="Win Rate %",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.8)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_wr, use_container_width=True)

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
# PAGE: AI MODELS
# ==========================================
elif page == "🤖 AI Models":
    st.markdown("## 🤖 AI Model Management")
    st.caption("Configure and swap AI models used by the trading bot. Changes take effect on the next analysis cycle.")

    # --- Check if table exists ---
    table_check = run_query(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'ai_model_config'
        ) AS exists;
        """
    )
    table_exists = table_check and table_check[0]["exists"]

    if not table_exists:
        st.error("Table `ai_model_config` not found. Run `db/migrate_add_ai_model_config.sql` first.")
        st.code(open("db/migrate_add_ai_model_config.sql").read() if os.path.exists("db/migrate_add_ai_model_config.sql") else "-- Migration file not found", language="sql")
        st.stop()

    # --- Current Active Models (by role) ---
    st.markdown("### ⚡ Active Models")

    # Check if model_role column exists
    role_col_check = run_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'ai_model_config' AND column_name = 'model_role'
        ) AS exists;
    """)
    has_role_col = role_col_check and role_col_check[0]["exists"]

    if has_role_col:
        active_models = run_query(
            "SELECT * FROM ai_model_config WHERE is_active = TRUE ORDER BY model_role, updated_at DESC;"
        )
    else:
        active_models = run_query(
            "SELECT * FROM ai_model_config WHERE is_active = TRUE ORDER BY updated_at DESC LIMIT 1;"
        )

    if active_models:
        for am in active_models:
            role_label = am.get("model_role", "main").upper() if has_role_col else "MAIN"
            role_emoji = "🧠" if role_label == "MAIN" else "⚡"
            am_col1, am_col2, am_col3, am_col4, am_col5 = st.columns(5)
            am_col1.metric("Role", f"{role_emoji} {role_label}")
            am_col2.metric("Provider", am["provider"].title())
            am_col3.metric("Model", am["display_name"] or am["model"])
            am_col4.metric("Max Tokens", am["max_tokens"])
            am_col5.metric("Temperature", f"{am['temperature']}")
            st.markdown(
                f"""<div class="card-panel">
                <h4>{role_emoji} {role_label} — {am['display_name'] or am['model']}</h4>
                <b>Model:</b> {am['model']}<br>
                <b>API URL:</b> {am['api_url']}<br>
            <b>API Key:</b> {'*' * 8 + am['api_key'][-4:] if len(am['api_key']) > 4 else '***'}<br>
            <b>Last Updated:</b> {am['updated_at'].strftime('%Y-%m-%d %H:%M') if am['updated_at'] else 'N/A'}
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.warning("No active model configured. The bot will fall back to environment variables.")

    st.divider()

    # --- All Models ---
    st.markdown("### 📋 All Configured Models")
    if has_role_col:
        all_models = run_query("SELECT * FROM ai_model_config ORDER BY model_role, is_active DESC, updated_at DESC;")
    else:
        all_models = run_query("SELECT * FROM ai_model_config ORDER BY is_active DESC, updated_at DESC;")

    if all_models:
        for model in all_models:
            with st.container():
                active_badge = "🟢 ACTIVE" if model["is_active"] else "⚪ Inactive"
                role_str = model.get("model_role", "main").upper() if has_role_col else ""
                role_badge = f" [{role_str}]" if role_str else ""
                display = model["display_name"] or model["model"]
                st.markdown(
                    f"""<div class="card-panel">
                    <h4>{display}{role_badge} <span style="font-size:0.8rem;">{active_badge}</span></h4>
                    <span class="text-muted">Provider: {model['provider']} | Model: {model['model']} |
                    Tokens: {model['max_tokens']} | Temp: {model['temperature']}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )

                btn_col1, btn_col2, btn_col3 = st.columns(3)

                with btn_col1:
                    if not model["is_active"]:
                        if st.button(f"✅ Activate", key=f"activate_{model['id']}"):
                            m_role = model.get("model_role", "main") if has_role_col else None
                            if has_role_col and m_role:
                                # Deactivate only models with the SAME role
                                run_command(
                                    "UPDATE ai_model_config SET is_active = FALSE, updated_at = NOW() WHERE model_role = %s;",
                                    (m_role,),
                                )
                            else:
                                run_command("UPDATE ai_model_config SET is_active = FALSE, updated_at = NOW();")
                            run_command(
                                "UPDATE ai_model_config SET is_active = TRUE, updated_at = NOW() WHERE id = %s;",
                                (model["id"],),
                            )
                            role_info = f" (role={m_role})" if m_role else ""
                            run_command(
                                "INSERT INTO bot_events (event_type, message) VALUES (%s, %s);",
                                ("CONFIG_CHANGE", f"AI model switched to {model['provider']}/{model['model']}{role_info}"),
                            )
                            st.success(f"Activated: {display}{role_info}")
                            st.rerun()

                with btn_col2:
                    if st.button(f"🧪 Test", key=f"test_{model['id']}"):
                        st.info(f"Testing connection to {model['provider']}...")
                        try:
                            headers = {
                                "Authorization": f"Bearer {model['api_key']}",
                                "Content-Type": "application/json",
                            }
                            payload = {
                                "model": model["model"],
                                "messages": [{"role": "user", "content": "Say OK"}],
                                "max_tokens": 10,
                                "temperature": 0.1,
                            }
                            resp = req_lib.post(
                                model["api_url"],
                                headers=headers,
                                json=payload,
                                timeout=15,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                                st.success(f"Connection OK! Response: {reply[:100]}")
                            else:
                                st.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                        except Exception as e:
                            st.error(f"Connection failed: {e}")

                with btn_col3:
                    if st.button(f"🗑️ Delete", key=f"delete_{model['id']}"):
                        if model["is_active"]:
                            st.error("Cannot delete the active model. Activate another model first.")
                        else:
                            run_command("DELETE FROM ai_model_config WHERE id = %s;", (model["id"],))
                            st.success(f"Deleted: {display}")
                            st.rerun()
    else:
        st.info("No models configured yet. Add one below.")

    st.divider()

    # --- Edit Existing Model ---
    st.markdown("### ✏️ Edit Model")
    if all_models:
        model_options = {f"{m['display_name'] or m['model']} ({m['provider']})": m for m in all_models}
        selected_name = st.selectbox("Select model to edit", list(model_options.keys()))
        sel = model_options[selected_name]

        with st.form("edit_model_form"):
            edit_display = st.text_input("Display Name", value=sel["display_name"] or "")
            edit_provider = st.selectbox(
                "Provider",
                ["openrouter", "nvidia"],
                index=1 if sel["provider"] == "nvidia" else 0,
            )
            edit_model = st.text_input("Model ID", value=sel["model"])
            edit_url = st.text_input("API URL", value=sel["api_url"])
            edit_key = st.text_input("API Key", value=sel["api_key"], type="password")
            edit_tokens = st.number_input("Max Tokens", 50, 4096, int(sel["max_tokens"]))
            edit_temp = st.number_input("Temperature", 0.0, 2.0, float(sel["temperature"]), step=0.05)
            if has_role_col:
                current_role = sel.get("model_role", "main") or "main"
                edit_role = st.selectbox(
                    "Model Role",
                    ["main", "forecast"],
                    index=0 if current_role == "main" else 1,
                    help="main = Full BUY/SELL/WAIT analysis | forecast = Quick HOLD/CLOSE position check"
                )
            else:
                edit_role = "main"
            edit_notes = st.text_area("Notes", value=sel.get("notes") or "")

            if st.form_submit_button("💾 Save Changes"):
                if has_role_col:
                    run_command(
                        """
                        UPDATE ai_model_config
                        SET display_name = %s, provider = %s, model = %s,
                            api_url = %s, api_key = %s, max_tokens = %s,
                            temperature = %s, model_role = %s, notes = %s, updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (edit_display, edit_provider, edit_model, edit_url, edit_key,
                         edit_tokens, edit_temp, edit_role, edit_notes, sel["id"]),
                    )
                else:
                    run_command(
                        """
                        UPDATE ai_model_config
                        SET display_name = %s, provider = %s, model = %s,
                            api_url = %s, api_key = %s, max_tokens = %s,
                            temperature = %s, notes = %s, updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (edit_display, edit_provider, edit_model, edit_url, edit_key,
                         edit_tokens, edit_temp, edit_notes, sel["id"]),
                    )
                st.success(f"Updated: {edit_display or edit_model}")
                st.rerun()

    st.divider()

    # --- Add New Model ---
    st.markdown("### ➕ Add New Model")
    with st.form("add_model_form"):
        new_display = st.text_input("Display Name", placeholder="e.g. DeepSeek V3.2 (Main Analysis)")
        new_provider = st.selectbox("Provider", ["openrouter", "nvidia"], key="new_provider")
        new_model = st.text_input("Model ID", placeholder="e.g. deepseek/deepseek-v3.2")
        new_url = st.text_input("API URL", placeholder="https://openrouter.ai/api/v1/chat/completions")
        new_key = st.text_input("API Key", type="password")
        new_tokens = st.number_input("Max Tokens", 50, 4096, 400, key="new_tokens")
        new_temp = st.number_input("Temperature", 0.0, 2.0, 0.10, step=0.05, key="new_temp")
        if has_role_col:
            new_role = st.selectbox(
                "Model Role",
                ["main", "forecast"],
                key="new_role",
                help="main = Full BUY/SELL/WAIT analysis | forecast = Quick HOLD/CLOSE position check"
            )
        else:
            new_role = "main"
        new_notes = st.text_area("Notes", key="new_notes")

        if st.form_submit_button("➕ Add Model"):
            if new_model and new_url and new_key:
                if has_role_col:
                    run_command(
                        """
                        INSERT INTO ai_model_config
                            (provider, model, api_key, api_url, is_active, display_name,
                             max_tokens, temperature, model_role, notes)
                        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, %s, %s);
                        """,
                        (new_provider, new_model, new_key, new_url,
                         new_display or new_model, new_tokens, new_temp, new_role, new_notes),
                    )
                else:
                    run_command(
                        """
                        INSERT INTO ai_model_config
                            (provider, model, api_key, api_url, is_active, display_name,
                             max_tokens, temperature, notes)
                        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, %s);
                        """,
                        (new_provider, new_model, new_key, new_url,
                         new_display or new_model, new_tokens, new_temp, new_notes),
                    )
                st.success(f"Added: {new_display or new_model} (role={new_role})")
                st.rerun()
            else:
                st.error("Model ID, API URL, and API Key are required.")

    st.divider()

    # --- Fallback Info ---
    st.markdown("### ℹ️ Fallback Configuration")
    st.markdown(
        """
        If no active model is found in the database, the bot falls back to environment variables:
        - `AI_PROVIDER` (nvidia/openrouter)
        - `NVIDIA_API_KEY`, `NVIDIA_URL`, `NVIDIA_MODEL`
        - `OPENROUTER_API_KEY`, `OPENROUTER_URL`, `MODEL`
        """
    )


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

    # Get current values (support new columns)
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

    # --- Friday Auto-Close Status ---
    st.markdown("### 🔒 Friday Auto-Close (Weekend Gap Protection)")
    fri_enabled = os.getenv("FRIDAY_AUTO_CLOSE", "true").lower() in ("true", "1", "yes")
    fri_close_min = int(os.getenv("FRIDAY_CLOSE_MINUTES_BEFORE", 30))
    fri_no_trade_min = int(os.getenv("FRIDAY_NO_NEW_TRADE_MINUTES", 60))

    fri_col1, fri_col2, fri_col3 = st.columns(3)
    with fri_col1:
        if fri_enabled:
            st.markdown("**Status:** ✅ ENABLED")
        else:
            st.markdown("**Status:** ❌ DISABLED")
    with fri_col2:
        st.metric("Close positions at", f"Fri {22 - fri_close_min // 60}:{fri_close_min % 60:02d} UTC")
    with fri_col3:
        st.metric("Block new trades at", f"Fri {22 - fri_no_trade_min // 60}:{fri_no_trade_min % 60:02d} UTC")

    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() == 4:  # Friday
        mins_to_close = (22 * 60) - (now_utc.hour * 60 + now_utc.minute)
        if mins_to_close > 0:
            st.info(f"⏰ Today is Friday — **{mins_to_close} minutes** until market close (22:00 UTC)")
            if mins_to_close <= fri_no_trade_min:
                st.warning("🔒 New trades are currently BLOCKED (Friday close window)")
            if mins_to_close <= fri_close_min:
                st.error("⚠️ Position close-out is ACTIVE — all positions being closed")
        else:
            st.success("Market is closed for the weekend")

    # Recent Friday close events
    fri_events = run_query(
        "SELECT created_at, message FROM bot_events WHERE event_type IN ('FRIDAY_CLOSE', 'FRIDAY_CLOSE_DONE') ORDER BY created_at DESC LIMIT 5;"
    )
    if fri_events:
        st.markdown("**Recent Friday Close Events:**")
        for ev in fri_events:
            st.text(f"  {ev['created_at']} — {ev['message']}")

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

# Show active AI models from DB or env fallback
_ai_table_exists = run_query(
    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'ai_model_config') AS e;"
)[0]["e"]

_main_model_str = ""
_forecast_model_str = ""

if _ai_table_exists:
    # Check if model_role column exists
    _has_role = run_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'ai_model_config' AND column_name = 'model_role'
        ) AS e;
    """)[0]["e"]

    if _has_role:
        _active_models = run_query(
            "SELECT provider, model, display_name, model_role FROM ai_model_config WHERE is_active = TRUE ORDER BY model_role;"
        )
        for _am in (_active_models or []):
            _label = _am["display_name"] or _am["model"]
            if _am.get("model_role") == "forecast":
                _forecast_model_str = f"<b class='gold-accent'>⚡ Forecast:</b> {_label}<br>"
            else:
                _main_model_str = f"<b class='gold-accent'>🧠 Main:</b> {_label}<br>"
    else:
        _active_ai = run_query(
            "SELECT provider, model, display_name FROM ai_model_config WHERE is_active = TRUE LIMIT 1;"
        )
        if _active_ai:
            _main_model_str = f"<b class='gold-accent'>🧠 Engine:</b> {_active_ai[0]['display_name'] or _active_ai[0]['model']}<br>"

if not _main_model_str:
    _ai_prov = os.getenv("AI_PROVIDER", "openrouter").lower()
    _ai_model = os.getenv("NVIDIA_MODEL", "N/A") if _ai_prov == "nvidia" else os.getenv("MODEL", "N/A")
    _main_model_str = f"<b class='gold-accent'>🧠 Engine:</b> {_ai_model} ({_ai_prov})<br>"

if not _forecast_model_str:
    _fc = os.getenv("FORECAST_MODEL")
    if _fc:
        _forecast_model_str = f"<b class='gold-accent'>⚡ Forecast:</b> {_fc}<br>"

st.sidebar.markdown(f"""
<div class="text-muted">
{_main_model_str}{_forecast_model_str}<b class="gold-accent">Symbol:</b> XAUUSD
</div>
""", unsafe_allow_html=True)
st.sidebar.caption(f"AI Gold Trader v2.1 Enterprise • {datetime.now().strftime('%Y-%m-%d %H:%M')}")
